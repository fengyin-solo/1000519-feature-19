"""地图禁入面联动工作台：只读访问面、现场记录授权、跨面脱敏、地图版本联动。

设计要点（对应业务约定）：
- 圈定调查区域生成「只读访问面」，现场记录只在面内可读，跨面引用图件只给脱敏摘要，
  其余越权请求一律拒绝（403）。
- 全局维护一个单调递增的 map_version；授权面一变化（登记/改面/关入口/回收/定稿联动）
  就升版，灾害点图、调查台账、报告章节都按同一版本载入工作台。
- 撤销访问分两步：先关闭图面入口（旧会话立刻不能提交），再回收现场字段。
- 并发改面走 base_version 乐观锁 + 审签人 + change_token 幂等：以最新审签版本为准，
  只保留一个有效版本；未成功的改面不改状态，旧会话权限不受影响，断线可带原 token 重试。
- 存量环境调查点在初始化与显式回填时，按调查区域/几何归属回填到对应访问面。

全部状态保存在内存里（与 app.store 一致的演示口径），用一把可重入锁保护所有写操作。
"""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

from app.geometry import as_point, point_in_polygon, polygon_area
from app.store import store

ENV_MODULE = "environmental"

SURFACE_ACTIVE = "有效"
SURFACE_ENTRY_CLOSED = "入口已关闭"
SURFACE_REVOKED = "已撤销"

# 跨面引用时必须遮蔽的敏感字段；其余为可公开的脱敏摘要字段。
SENSITIVE_FIGURE_KEYS = ["原始图件", "坐标底图", "涉密备注", "数据源路径"]
PUBLIC_FIGURE_KEYS = ["图件编号", "图件名称", "调查区域", "比例尺", "内容摘要"]


class WorkbenchError(Exception):
    """工作台业务异常：携带 HTTP 状态码，路由层据此返回。"""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class WorkbenchService:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.map_version = 1

        self.surfaces: list[dict[str, Any]] = []
        self.figures: list[dict[str, Any]] = []
        self.field_notes: dict[int, dict[str, Any]] = {}
        self.sessions: dict[str, dict[str, Any]] = {}
        self.chapters: list[dict[str, Any]] = []
        self.change_tokens: dict[str, dict[str, Any]] = {}

        self._surface_seq = 0
        self._chapter_seq = 0
        self._seeded = False
        self.backfill_stats: dict[str, Any] = {"total": 0, "inside": 0, "outside": 0}

    # ------------------------------------------------------------------
    # 初始化与存量回填
    # ------------------------------------------------------------------
    def bootstrap(self) -> None:
        """幂等初始化：预置三个只读访问面、跨面图件与现场字段，再回填存量点。"""
        with self._lock:
            if self._seeded:
                return
            presets = [
                ("东区", [[120, 120], [700, 100], [720, 430], [140, 450]]),
                ("西区", [[80, 520], [470, 500], [450, 880], [100, 900]]),
                ("南区", [[540, 600], [900, 580], [920, 940], [560, 960]]),
            ]
            for region, polygon in presets:
                self._surface_seq += 1
                self.surfaces.append({
                    "id": self._surface_seq,
                    "调查区域": region,
                    "polygon": polygon,
                    "状态": SURFACE_ACTIVE,
                    "版本": 1,
                    "审签人": "初始圈定",
                    "地图版本": self.map_version,
                    "创建时间": _now(),
                    "关闭时间": None,
                    "回收时间": None,
                })

            self.figures = [
                {
                    "id": 1, "图件编号": "MAP-E-01", "图件名称": "东区滑坡灾害点图",
                    "调查区域": "东区", "比例尺": "1:2000",
                    "内容摘要": "东区前缘两处滑坡边界与监测点分布。",
                    "原始图件": "gis://secure/east/slope.raw", "坐标底图": "CGCS2000-东区机密底图",
                    "涉密备注": "含未公开钻孔与居民地坐标", "数据源路径": "s3://secret/east/hazard.dwg",
                },
                {
                    "id": 2, "图件编号": "MAP-W-01", "图件名称": "西沟泥石流域图",
                    "调查区域": "西区", "比例尺": "1:5000",
                    "内容摘要": "西沟泥石流物源区、流通区与堆积扇范围。",
                    "原始图件": "gis://secure/west/debris.raw", "坐标底图": "CGCS2000-西区机密底图",
                    "涉密备注": "沟道断面为内部测量成果", "数据源路径": "s3://secret/west/debris.dwg",
                },
                {
                    "id": 3, "图件编号": "MAP-S-01", "图件名称": "南塬地裂缝分布图",
                    "调查区域": "南区", "比例尺": "1:2000",
                    "内容摘要": "南塬台地三条地裂缝走向与影响带。",
                    "原始图件": "gis://secure/south/fissure.raw", "坐标底图": "CGCS2000-南区机密底图",
                    "涉密备注": "含拟迁改管线坐标", "数据源路径": "s3://secret/south/fissure.dwg",
                },
            ]

            seed_notes = {
                1: ("东区前缘坡体后缘见张拉裂缝，雨季有扩展迹象。", "取样 E-S01 粉质黏土，含水率偏高。", "建议布设位移监测并雨季避让。"),
                3: ("西沟沟口松散堆积物厚，具备泥石流物源条件。", "取样 W-S03 砾石土，颗粒级配不良。", "建议降险加固并设置拦挡。"),
                5: ("南塬台地发现三条近平行地裂缝，最长约 120m。", "待取样。", "建议圈定影响带并限制耕作扰动。"),
            }
            for point_id, (desc, sample, advice) in seed_notes.items():
                self.field_notes[point_id] = {
                    "现场描述": desc, "取样记录": sample, "处置建议": advice,
                    "更新人": "现场组", "更新时间": _now(), "已回收": False,
                }

            self._seeded = True
            self.backfill_owned_points()

    def backfill_owned_points(self) -> dict[str, Any]:
        """按调查区域与几何归属，把存量环境调查点回填到对应只读访问面。

        可重复执行：每次都依据当前有效访问面重算「归属区域 / 面内」，幂等无副作用。
        尚未圈定访问面的区域（如未划界缓冲带）归属为空、面内为否。
        """
        with self._lock:
            active = [s for s in self.surfaces if s["状态"] == SURFACE_ACTIVE]
            inside = 0
            for row in store.rows(ENV_MODULE):
                point = as_point((row.get("坐标X"), row.get("坐标Y")))
                owner = None
                if point is not None:
                    for surface in active:
                        if point_in_polygon(point[0], point[1], surface["polygon"]):
                            owner = surface["调查区域"]
                            break
                declared = str(row.get("调查区域") or "").strip()
                row["归属区域"] = owner
                # 声明区域与几何归属一致才算正确落面，便于发现跨界的存量脏数据。
                row["面内"] = owner is not None and owner == declared
                if row["面内"]:
                    inside += 1
            rows = store.rows(ENV_MODULE)
            self.backfill_stats = {
                "total": len(rows),
                "inside": inside,
                "outside": len(rows) - inside,
            }
            return dict(self.backfill_stats)

    # ------------------------------------------------------------------
    # 授权判定
    # ------------------------------------------------------------------
    def _active_surface(self, region: str) -> dict[str, Any] | None:
        for surface in self.surfaces:
            if surface["调查区域"] == region and surface["状态"] == SURFACE_ACTIVE:
                return surface
        return None

    def _allowed_regions(self, session: dict[str, Any]) -> set[str]:
        if session["scope"] == "full":
            return {s["调查区域"] for s in self.surfaces if s["状态"] == SURFACE_ACTIVE}
        return {session["scope"]}

    def _owner_region(self, row: dict[str, Any]) -> str | None:
        point = as_point((row.get("坐标X"), row.get("坐标Y")))
        if point is None:
            return None
        for surface in self.surfaces:
            if surface["状态"] == SURFACE_ACTIVE and point_in_polygon(point[0], point[1], surface["polygon"]):
                return surface["调查区域"]
        return None

    def _assert_point_in_scope(self, session: dict[str, Any], point_id: int) -> dict[str, Any]:
        row = store.find(ENV_MODULE, point_id)
        if row is None:
            raise WorkbenchError(404, f"环境调查点 {point_id} 不存在或已归档")
        owner = self._owner_region(row)
        if owner is None or owner not in self._allowed_regions(session):
            # 面外 / 跨面取数：不在授权访问面内，一律拒绝。
            raise WorkbenchError(403, "越权请求已拒绝：该调查点不在当前授权访问面内")
        return row

    def _assert_can_submit(self, session: dict[str, Any], region: str | None = None) -> None:
        if session.get("closed"):
            raise WorkbenchError(403, "会话已随访问撤销关闭，旧会话不得继续提交，请重新申请访问面")
        if session["map_version"] != self.map_version:
            raise WorkbenchError(409, "地图版本已变更，请先重新载入工作台到最新版本再提交")
        if session["scope"] != "full":
            surface = self._active_surface(session["scope"])
            if surface is None:
                status = self._surface_status(session["scope"])
                hint = "访问面入口已关闭" if status == SURFACE_ENTRY_CLOSED else "访问面已撤销"
                raise WorkbenchError(403, f"{hint}，当前会话不得继续提交")
        elif region is not None and self._active_surface(region) is None:
            raise WorkbenchError(403, "目标区域访问面入口已关闭，越权请求已拒绝")

    def _surface_status(self, region: str) -> str | None:
        for surface in self.surfaces:
            if surface["调查区域"] == region:
                return surface["状态"]
        return None

    def _bump_version(self) -> int:
        self.map_version += 1
        return self.map_version

    # ------------------------------------------------------------------
    # 访问面：登记 / 并发改面 / 撤销两段式
    # ------------------------------------------------------------------
    def create_surface(self, region: str, polygon: list[list[float]], approver: str) -> dict[str, Any]:
        region = str(region or "").strip()
        if not region:
            raise WorkbenchError(400, "调查区域不能为空")
        if polygon_area(polygon) <= 0:
            raise WorkbenchError(400, "访问面顶点无法围成有效区域，请重新圈定")
        with self._lock:
            existing = next((s for s in self.surfaces if s["调查区域"] == region
                             and s["状态"] != SURFACE_REVOKED), None)
            if existing is not None:
                raise WorkbenchError(409, f"区域「{region}」已存在有效访问面，只保留一个有效版本，请走改面审签")
            self._surface_seq += 1
            version = self._bump_version()
            surface = {
                "id": self._surface_seq,
                "调查区域": region,
                "polygon": polygon,
                "状态": SURFACE_ACTIVE,
                "版本": 1,
                "审签人": approver or "未署名",
                "地图版本": version,
                "创建时间": _now(),
                "关闭时间": None,
                "回收时间": None,
            }
            self.surfaces.append(surface)
            self.backfill_owned_points()
            return {"surface": surface, "map_version": version}

    def revise_surface(
        self,
        surface_id: int,
        polygon: list[list[float]],
        approver: str,
        base_version: int,
        change_token: str,
    ) -> dict[str, Any]:
        change_token = str(change_token or "").strip()
        if not change_token:
            raise WorkbenchError(400, "并发改面必须携带 change_token，便于断线重连续传")
        if polygon_area(polygon) <= 0:
            raise WorkbenchError(400, "访问面顶点无法围成有效区域，请重新圈定")
        with self._lock:
            # 幂等：同一个改面令牌断线重连重试，直接回放首次结果，不重复升版/改面。
            if change_token in self.change_tokens:
                replay = self.change_tokens[change_token]
                if replay["surface_id"] != surface_id:
                    raise WorkbenchError(409, "change_token 已用于其他访问面，拒绝串用")
                return {"surface": replay["surface"], "map_version": replay["map_version"], "replayed": True}

            surface = next((s for s in self.surfaces if s["id"] == surface_id), None)
            if surface is None:
                raise WorkbenchError(404, f"访问面 {surface_id} 不存在")
            if surface["状态"] != SURFACE_ACTIVE:
                raise WorkbenchError(409, "访问面入口已关闭或已撤销，不能改面，请重新申请")
            # 乐观锁：以最新审签版本为准。基线落后说明期间有人改过面，本次改面整体失败，
            # 不改动任何状态（旧会话权限因此保持不变），让调用方拉最新版本后再试。
            if int(base_version) != self.map_version:
                raise WorkbenchError(
                    409,
                    f"检测到并发改面：基线版本 {base_version} 已过期，最新审签版本为 {self.map_version}，"
                    "本次改面已回滚未生效，请按最新版本重绘",
                )

            new_version = self._bump_version()
            surface["polygon"] = polygon
            surface["版本"] = int(surface["版本"]) + 1
            surface["审签人"] = approver or "未署名"
            surface["地图版本"] = new_version
            self.change_tokens[change_token] = {
                "surface_id": surface_id, "surface": surface, "map_version": new_version,
            }
            self.backfill_owned_points()
            return {"surface": surface, "map_version": new_version, "replayed": False}

    def close_surface_entry(self, surface_id: int) -> dict[str, Any]:
        """撤销第一段：关闭图面入口。升版后旧会话版本落后、入口判定失败，立即不能提交。"""
        with self._lock:
            surface = next((s for s in self.surfaces if s["id"] == surface_id), None)
            if surface is None:
                raise WorkbenchError(404, f"访问面 {surface_id} 不存在")
            if surface["状态"] == SURFACE_REVOKED:
                raise WorkbenchError(409, "访问面已撤销回收，无需重复关闭")
            if surface["状态"] == SURFACE_ENTRY_CLOSED:
                return {"surface": surface, "map_version": self.map_version, "replayed": True}
            surface["状态"] = SURFACE_ENTRY_CLOSED
            surface["关闭时间"] = _now()
            version = self._bump_version()
            # 绑定该区域的旧会话立刻置为不可提交（全区会话在提交时按区域动态拦截）。
            for session in self.sessions.values():
                if session["scope"] == surface["调查区域"]:
                    session["entry_open"] = False
                    session["reject_reason"] = "访问面入口已关闭，旧会话不得继续提交"
            return {"surface": surface, "map_version": version}

    def reclaim_surface_fields(self, surface_id: int) -> dict[str, Any]:
        """撤销第二段：回收现场字段。必须先关闭入口，杜绝边回收边提交。"""
        with self._lock:
            surface = next((s for s in self.surfaces if s["id"] == surface_id), None)
            if surface is None:
                raise WorkbenchError(404, f"访问面 {surface_id} 不存在")
            if surface["状态"] == SURFACE_ACTIVE:
                raise WorkbenchError(409, "撤销须先关闭图面入口，再回收现场字段，当前入口仍开放")
            if surface["状态"] == SURFACE_REVOKED:
                return {"surface": surface, "map_version": self.map_version, "replayed": True, "reclaimed": 0}

            region = surface["调查区域"]
            reclaimed = 0
            for row in store.rows(ENV_MODULE):
                point = as_point((row.get("坐标X"), row.get("坐标Y")))
                if point is not None and point_in_polygon(point[0], point[1], surface["polygon"]):
                    note = self.field_notes.get(int(row["id"]))
                    if note and not note.get("已回收"):
                        # 现场字段按既定顺序清空，只保留回收标记，保持台账骨架可追溯。
                        note["现场描述"] = ""
                        note["取样记录"] = ""
                        note["处置建议"] = ""
                        note["更新人"] = "系统回收"
                        note["更新时间"] = _now()
                        note["已回收"] = True
                        reclaimed += 1
            surface["状态"] = SURFACE_REVOKED
            surface["回收时间"] = _now()
            version = self._bump_version()
            for session in self.sessions.values():
                if session["scope"] == region:
                    session["closed"] = True
                    session["entry_open"] = False
                    session["reject_reason"] = "访问已撤销，现场字段已回收，旧会话关闭"
            self.backfill_owned_points()
            return {"surface": surface, "map_version": version, "reclaimed": reclaimed}

    # ------------------------------------------------------------------
    # 会话与工作台载入
    # ------------------------------------------------------------------
    def open_session(self, operator: str, scope: str) -> dict[str, Any]:
        operator = str(operator or "").strip() or "未署名人员"
        with self._lock:
            if scope != "full":
                if self._active_surface(scope) is None:
                    raise WorkbenchError(403, f"区域「{scope}」没有有效访问面，无法进入工作台")
            session_id = f"s-{len(self.sessions) + 1}-{self.map_version}"
            session = {
                "id": session_id,
                "operator": operator,
                "scope": scope,
                "map_version": self.map_version,
                "entry_open": True,
                "closed": False,
                "reject_reason": None,
                "opened_at": _now(),
                "last_reload": _now(),
            }
            self.sessions[session_id] = session
            return dict(session)

    def _session_or_404(self, session_id: str) -> dict[str, Any]:
        session = self.sessions.get(session_id)
        if session is None:
            raise WorkbenchError(404, "会话不存在或已过期，请重新进入工作台")
        return session

    def reload_session(self, session_id: str) -> dict[str, Any]:
        """断线返回 / 授权面变化后重新载入：同步到最新地图版本并重算入口状态。"""
        with self._lock:
            session = self._session_or_404(session_id)
            session["map_version"] = self.map_version
            session["last_reload"] = _now()
            if session["scope"] != "full":
                surface = self._active_surface(session["scope"])
                if surface is None:
                    status = self._surface_status(session["scope"])
                    session["entry_open"] = False
                    session["reject_reason"] = (
                        "访问面入口已关闭，请等待现场字段回收完成"
                        if status == SURFACE_ENTRY_CLOSED
                        else "访问已撤销，旧会话已关闭，不得继续提交"
                    )
                    if status == SURFACE_REVOKED:
                        session["closed"] = True
                else:
                    session["entry_open"] = not session.get("closed", False)
                    session["reject_reason"] = None
            return self.bundle(session_id)

    def _ledger_rows(self, regions: set[str]) -> list[dict[str, Any]]:
        items = []
        for row in store.rows(ENV_MODULE):
            owner = self._owner_region(row)
            if owner is not None and owner in regions:
                items.append({
                    "id": row["id"],
                    "调查编号": row.get("调查编号"),
                    "调查区域": owner,
                    "灾害类型": row.get("灾害类型"),
                    "危害等级": row.get("危害等级"),
                    "影响范围": row.get("影响范围"),
                    "调查状态": row.get("调查状态"),
                    "面内": True,
                })
        return items

    def _hazard_points(self, regions: set[str]) -> list[dict[str, Any]]:
        points = []
        for row in store.rows(ENV_MODULE):
            owner = self._owner_region(row)
            point = as_point((row.get("坐标X"), row.get("坐标Y")))
            accessible = owner is not None and owner in regions
            points.append({
                "id": row["id"],
                "调查编号": row.get("调查编号"),
                "灾害类型": row.get("灾害类型"),
                "x": point[0] if point else None,
                "y": point[1] if point else None,
                "归属区域": owner,
                "面内可见": accessible,
            })
        return points

    def bundle(self, session_id: str) -> dict[str, Any]:
        """工作台一次性载入同一地图版本下的灾害点图、调查台账与报告章节。"""
        with self._lock:
            session = self._session_or_404(session_id)
            regions = self._allowed_regions(session)
            surfaces = [
                {k: surface[k] for k in ("id", "调查区域", "polygon", "状态", "版本", "审签人", "地图版本")}
                for surface in self.surfaces
                if surface["调查区域"] in regions or session["scope"] == "full"
            ]
            return {
                "map_version": self.map_version,
                "session": dict(session),
                "surfaces": surfaces,
                "hazard_map": {
                    "version": self.map_version,
                    "points": self._hazard_points(regions),
                },
                "ledger": {
                    "version": self.map_version,
                    "items": self._ledger_rows(regions),
                    "total": len(self._ledger_rows(regions)),
                },
                "chapters": self._chapter_views(session),
            }

    # ------------------------------------------------------------------
    # 现场记录（面内只读 / 提交）
    # ------------------------------------------------------------------
    def get_field_note(self, session_id: str, point_id: int) -> dict[str, Any]:
        with self._lock:
            session = self._session_or_404(session_id)
            self._assert_point_in_scope(session, point_id)  # 面外取字段一律 403
            note = self.field_notes.get(point_id)
            if note is None:
                return {"point_id": point_id, "现场描述": None, "取样记录": None, "处置建议": None, "空记录": True}
            return {"point_id": point_id, **dict(note)}

    def submit_field_note(
        self, session_id: str, point_id: int, values: dict[str, Any], client_version: int
    ) -> dict[str, Any]:
        with self._lock:
            session = self._session_or_404(session_id)
            row = self._assert_point_in_scope(session, point_id)
            if int(client_version) != self.map_version:
                # 用客户端提交时认定的版本兜底，防止绕过 reload 用陈旧会话写入。
                raise WorkbenchError(409, "地图版本已变更，请重新载入工作台后再提交")
            self._assert_can_submit(session, self._owner_region(row))
            note = self.field_notes.setdefault(point_id, {"已回收": False})
            if note.get("已回收"):
                raise WorkbenchError(409, "现场字段已被回收，不能再提交")
            for key in ("现场描述", "取样记录", "处置建议"):
                if values.get(key) is not None:
                    note[key] = str(values.get(key))
            note["更新人"] = session["operator"]
            note["更新时间"] = _now()
            note["已回收"] = False
            return {"point_id": point_id, "note": dict(note), "map_version": self.map_version}

    # ------------------------------------------------------------------
    # 跨面引用图件：脱敏摘要 / 越权拒绝
    # ------------------------------------------------------------------
    def _figure_or_404(self, figure_id: int) -> dict[str, Any]:
        figure = next((f for f in self.figures if f["id"] == figure_id), None)
        if figure is None:
            raise WorkbenchError(404, f"图件 {figure_id} 不存在")
        return figure

    def reference_figure(self, session_id: str, figure_id: int, detail: bool) -> dict[str, Any]:
        with self._lock:
            session = self._session_or_404(session_id)
            figure = self._figure_or_404(figure_id)
            within = figure["调查区域"] in self._allowed_regions(session)
            if not within:
                if detail:
                    # 跨面还要取全量明细：越权，一律拒绝，不返回任何敏感字段。
                    raise WorkbenchError(403, "越权请求已拒绝：跨面引用图件不提供全量明细，仅可查看脱敏摘要")
                masked = {key: figure.get(key) for key in PUBLIC_FIGURE_KEYS}
                masked["id"] = figure["id"]
                masked["脱敏"] = True
                masked["提示"] = "跨面引用，仅显示脱敏摘要，原始图件与坐标底图已遮蔽"
                return masked
            # 面内引用可看全量。
            if detail:
                return {"脱敏": False, **dict(figure)}
            return {"脱敏": False, **{key: figure.get(key) for key in PUBLIC_FIGURE_KEYS + ["id"]}}

    # ------------------------------------------------------------------
    # 报告章节与可见性快照
    # ------------------------------------------------------------------
    def _visible_point_summaries(self, region: str) -> list[dict[str, Any]]:
        summaries = []
        for row in store.rows(ENV_MODULE):
            owner = self._owner_region(row)
            if owner == region:
                summaries.append({
                    "id": row["id"],
                    "调查编号": row.get("调查编号"),
                    "灾害类型": row.get("灾害类型"),
                    "危害等级": row.get("危害等级"),
                })
        return summaries

    def create_chapter(self, region: str) -> dict[str, Any]:
        region = str(region or "").strip()
        with self._lock:
            if self._surface_status(region) is None:
                raise WorkbenchError(404, f"区域「{region}」尚未圈定访问面，无法生成报告章节")
            existing = next((c for c in self.chapters if c["调查区域"] == region
                             and c["状态"] == "草稿"), None)
            if existing is not None:
                return existing
            self._chapter_seq += 1
            chapter = {
                "id": self._chapter_seq,
                "章节编号": f"CH-{self._chapter_seq:03d}",
                "调查区域": region,
                "状态": "草稿",
                "地图版本": self.map_version,
                "创建时间": _now(),
                "定稿时间": None,
                "可见性快照": None,
            }
            self.chapters.append(chapter)
            return chapter

    def freeze_chapter(self, chapter_id: int, client_version: int) -> dict[str, Any]:
        """定稿：固化当时的可见性快照。历史报告此后不随授权面变化而改变可见性。"""
        with self._lock:
            chapter = next((c for c in self.chapters if c["id"] == chapter_id), None)
            if chapter is None:
                raise WorkbenchError(404, f"报告章节 {chapter_id} 不存在")
            if chapter["状态"] == "已定稿":
                return chapter
            if int(client_version) != self.map_version:
                raise WorkbenchError(409, "地图版本已变更，请按最新版本重载章节后再定稿")
            chapter["状态"] = "已定稿"
            chapter["地图版本"] = self.map_version
            chapter["定稿时间"] = _now()
            chapter["可见性快照"] = {
                "地图版本": self.map_version,
                "可见调查点": self._visible_point_summaries(chapter["调查区域"]),
            }
            return chapter

    def _chapter_views(self, session: dict[str, Any]) -> list[dict[str, Any]]:
        regions = self._allowed_regions(session)
        views = []
        for chapter in self.chapters:
            if chapter["调查区域"] not in regions:
                continue
            view = {k: chapter.get(k) for k in ("id", "章节编号", "调查区域", "状态", "地图版本", "定稿时间")}
            if chapter["状态"] == "已定稿":
                # 历史报告维持定稿时的可见性快照，不再受当前授权面影响。
                view["可见调查点"] = chapter["可见性快照"]["可见调查点"]
                view["快照版本"] = chapter["可见性快照"]["地图版本"]
            else:
                # 草稿章节随当前地图版本实时联动。
                view["地图版本"] = self.map_version
                view["可见调查点"] = self._visible_point_summaries(chapter["调查区域"])
                view["快照版本"] = None
            views.append(view)
        return views

    # ------------------------------------------------------------------
    # 管理端总览
    # ------------------------------------------------------------------
    def overview(self) -> dict[str, Any]:
        with self._lock:
            return {
                "map_version": self.map_version,
                "backfill": self.backfill_stats,
                "surfaces": [
                    {k: s.get(k) for k in ("id", "调查区域", "polygon", "状态", "版本", "审签人", "地图版本", "关闭时间", "回收时间")}
                    for s in self.surfaces
                ],
                "figures": [
                    {k: f.get(k) for k in ("id", "图件编号", "图件名称", "调查区域", "比例尺", "内容摘要")}
                    for f in self.figures
                ],
                "points": self._hazard_points({s["调查区域"] for s in self.surfaces}),
                "chapters": [
                    {k: c.get(k) for k in ("id", "章节编号", "调查区域", "状态", "地图版本")}
                    for c in self.chapters
                ],
                "open_sessions": [
                    {"id": s["id"], "operator": s["operator"], "scope": s["scope"],
                     "map_version": s["map_version"], "entry_open": s["entry_open"], "closed": s["closed"]}
                    for s in self.sessions.values()
                ],
            }


workbench = WorkbenchService()
