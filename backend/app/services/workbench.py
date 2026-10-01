"""地图禁入面联动工作台业务规则。

授权面（只读访问面）、工作台会话、版本审签、撤销回收、跨面脱敏、报告快照、
并发改面与存量回填全部收在这里；路由层只做参数搬运。
"""
from __future__ import annotations

import secrets
import threading
from copy import deepcopy
from datetime import datetime
from typing import Any

from app.services.workbench_errors import (
    WorkbenchConflict,
    WorkbenchDenied,
    WorkbenchNotFound,
)
from app.store import store

MODULE = "environmental"
FIGURE_MODULE = "mapping"

# 现场记录的敏感字段：面内全量可见，跨面/回收后不可见
FIELD_KEYS = ["调查编号", "调查区域", "灾害类型"]
SENSITIVE_KEYS = ["危害等级", "影响范围", "调查日期", "调查人员", "调查状态"]
# 回收现场字段后留下的占位
RECLAIMED_MARK = "▇▇ 已随授权撤销回收"

# 同一调查区域只允许一个有效授权面
FACE_OVERLAP_MESSAGE = "调查区域「{area}」已存在有效授权面，请在原授权面上改面审签"
SESSION_GONE_MESSAGE = "会话不存在或已失效，请重新进入工作台"
READ_ONLY_MESSAGE = "该授权面为只读访问面，仅可查看现场记录，禁止提交"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _mask(value: Any) -> str:
    """跨面脱敏：保留首个字符，其余打码。"""
    text = str(value or "").strip()
    if not text:
        return "—"
    return text[0] + "**" if len(text) > 1 else text


def _sample_group(name: Any) -> str:
    """提取样例分组尾号（如「环境地质样例1」→「样例1」），用于把存量图件挂到授权面上。"""
    text = str(name or "")
    marker = "样例"
    if marker in text:
        return marker + text.rsplit(marker, 1)[1]
    return text


class WorkbenchService:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._faces: list[dict[str, Any]] = []
        self._sessions: list[dict[str, Any]] = []
        self._reports: list[dict[str, Any]] = []
        # change_id / revoke_id -> 已成功的响应副本，支撑断线重放
        self._idem: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------ 内部工具

    def _find_face_row(self, face_id: int) -> dict[str, Any]:
        for face in self._faces:
            if int(face["id"]) == face_id:
                return face
        raise WorkbenchNotFound(f"授权面 {face_id} 不存在或已归档")

    def _find_session(self, token: str | None) -> dict[str, Any]:
        if not token:
            raise WorkbenchDenied(SESSION_GONE_MESSAGE)
        for session in self._sessions:
            if session["token"] == token:
                return session
        raise WorkbenchDenied(SESSION_GONE_MESSAGE)

    def _require_face_session(self, face_id: int, token: str | None) -> dict[str, Any]:
        session = self._find_session(token)
        if int(session["face_id"]) != face_id:
            raise WorkbenchDenied("工作台会话与授权面不匹配，禁止跨面访问")
        return session

    def _idem_get(self, scope: str, key: str | None) -> dict[str, Any] | None:
        if not key:
            return None
        return self._idem.get(f"{scope}:{key}")

    def _idem_put(self, scope: str, key: str | None, payload: dict[str, Any]) -> None:
        if key:
            self._idem[f"{scope}:{key}"] = deepcopy(payload)

    def _area_rows(self, areas: list[str]) -> list[dict[str, Any]]:
        """授权面覆盖到的存量环境调查点（按调查区域判定）。"""
        area_set = set(areas)
        return [
            row
            for row in store.rows(MODULE)
            if str(row.get("调查区域", "")).strip() in area_set
        ]

    def _face_rows(self, face: dict[str, Any]) -> list[dict[str, Any]]:
        """当前归属在该授权面上的现场记录。"""
        return [
            row
            for row in store.rows(MODULE)
            if row.get("_face_id") == face["id"]
        ]

    def _visible_record(self, row: dict[str, Any], *, full: bool) -> dict[str, Any]:
        """面内全量字段；字段被回收后只留编号与回收占位。"""
        record = {"id": row["id"]}
        for key in FIELD_KEYS:
            record[key] = row.get(key)
        if not full:
            for key in SENSITIVE_KEYS:
                record[key] = RECLAIMED_MARK
            record["现场字段状态"] = "已回收"
            return record
        for key in SENSITIVE_KEYS:
            record[key] = row.get(key)
        record["现场字段状态"] = "面内可见"
        return record

    def _cross_figures(self, face: dict[str, Any]) -> list[dict[str, Any]]:
        """跨面引用图件：只给脱敏摘要，不给原文。"""
        result: list[dict[str, Any]] = []
        for figure in store.rows(FIGURE_MODULE):
            owner = figure.get("_face_id")
            if owner is None or owner == face["id"]:
                continue
            owner_face = next((item for item in self._faces if item["id"] == owner), None)
            result.append(
                {
                    "图幅编号": figure.get("图幅编号"),
                    "图幅名称": _mask(figure.get("图幅名称")),
                    "比例尺": _mask(figure.get("比例尺")),
                    "归属面": owner_face["name"] if owner_face else f"授权面{owner}",
                    "摘要": "跨面引用图件，仅显示脱敏摘要，原文需对面授权",
                }
            )
        return result

    def _own_figures(self, face: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {key: figure.get(key) for key in ("图幅编号", "图幅名称", "比例尺", "填图面积", "填图状态")}
            for figure in store.rows(FIGURE_MODULE)
            if figure.get("_face_id") == face["id"]
        ]

    def _chapters(self, face: dict[str, Any]) -> list[dict[str, Any]]:
        """报告章节：按灾害类型汇总面内调查点，章节随同一地图版本生成。"""
        rows = self._face_rows(face)
        grouped: dict[str, list[str]] = {}
        for row in rows:
            grouped.setdefault(str(row.get("灾害类型") or "未分类"), []).append(
                str(row.get("调查编号"))
            )
        return [
            {
                "章节": f"{kind}灾害点",
                "点位数量": len(codes),
                "调查点": codes,
                "地图版本": face["map_version"],
            }
            for kind, codes in sorted(grouped.items())
        ]

    def _hazard_layer(self, face: dict[str, Any], *, full: bool) -> dict[str, Any]:
        return {
            "图层": "灾害点图",
            "地图版本": face["map_version"],
            "点位": [self._visible_record(row, full=full) for row in self._face_rows(face)],
        }

    def _ledger(self, face: dict[str, Any], *, full: bool) -> dict[str, Any]:
        return {
            "台账": "环境调查台账",
            "地图版本": face["map_version"],
            "记录": [self._visible_record(row, full=full) for row in self._face_rows(face)],
        }

    # ------------------------------------------------------------------ 授权面管理

    def list_faces(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self._face_brief(face) for face in self._faces]

    def _face_brief(self, face: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": face["id"],
            "name": face["name"],
            "调查区域": list(face["areas"]),
            "有效版本": face["signed_version"],
            "地图版本": face["map_version"],
            "审签人": face["signed_by"],
            "审签时间": face["signed_at"],
            "图面入口": "开放" if face["entry_open"] else "关闭",
            "现场字段": "已回收" if face["fields_reclaimed"] else "在授",
            "状态": self._face_status(face),
            "历史版本": list(face["history"]),
            "待审签草稿数": sum(1 for item in face.get("drafts", []) if not item.get("作废")),
        }

    def _face_status(self, face: dict[str, Any]) -> str:
        if face["fields_reclaimed"]:
            return "已撤销"
        if not face["entry_open"]:
            return "撤销中·入口已关闭"
        if any(not item.get("作废") for item in face.get("drafts", [])):
            return "改面草稿待审签"
        return "生效中"

    def create_face(
        self,
        *,
        name: str,
        areas: list[str],
        operator: str,
        bounds: dict[str, Any] | None = None,
        change_id: str | None = None,
    ) -> dict[str, Any]:
        name = name.strip()
        areas = [item.strip() for item in areas if item.strip()]
        if not name or not areas:
            raise WorkbenchConflict("授权面名称与调查区域均不能为空")
        with self._lock:
            cached = self._idem_get("create-face", change_id)
            if cached is not None:
                return cached
            for face in self._faces:
                if face["fields_reclaimed"]:
                    continue
                overlap = sorted(set(face["areas"]) & set(areas))
                if overlap:
                    raise WorkbenchConflict(FACE_OVERLAP_MESSAGE.format(area="、".join(overlap)))

            face_id = max((int(item["id"]) for item in self._faces), default=0) + 1
            version = 1
            map_version = f"MAP-V{version}"
            face = {
                "id": face_id,
                "name": name,
                "areas": areas,
                "bounds": bounds or {},
                "signed_version": version,
                "map_version": map_version,
                "signed_by": operator,
                "signed_at": _now(),
                "entry_open": True,
                "fields_reclaimed": False,
                "history": [
                    {"版本": version, "地图版本": map_version, "审签人": operator, "时间": _now()}
                ],
                "drafts": [],
                "draft_seq": 0,
            }
            self._faces.append(face)
            # 存量环境调查点按调查区域回填归属；同步把同区域图件挂到本面
            backfilled = self._backfill_points(face)
            self._claim_figures(face)
            payload = self._face_brief(face)
            payload["回填调查点"] = backfilled
            self._idem_put("create-face", change_id, payload)
            return deepcopy(payload)

    def _backfill_points(self, face: dict[str, Any]) -> list[str]:
        """把面覆盖到、且尚无有效归属的存量调查点回填到该授权面。"""
        codes: list[str] = []
        for row in self._area_rows(face["areas"]):
            if row.get("_face_id") in (None, face["id"]):
                row["_face_id"] = face["id"]
                row["_face_version"] = face["map_version"]
                codes.append(str(row.get("调查编号")))
        return codes

    def _claim_figures(self, face: dict[str, Any]) -> None:
        """同调查区域分组的存量图件挂到本面，作为面内图件；其余授权面引用时即跨面。"""
        groups = {_sample_group(area) for area in face["areas"]}
        for figure in store.rows(FIGURE_MODULE):
            if figure.get("_face_id") is not None:
                continue
            if _sample_group(figure.get("图幅名称")) in groups:
                figure["_face_id"] = face["id"]

    # ------------------------------------------------------------------ 改面审签

    def prepare_change(
        self,
        face_id: int,
        *,
        areas: list[str],
        operator: str,
        bounds: dict[str, Any] | None = None,
        change_id: str | None = None,
    ) -> dict[str, Any]:
        """并发改面：每个圈面请求各自保存一份草稿，并记录所依据的最新审签版本。"""
        areas = [item.strip() for item in areas if item.strip()]
        if not areas:
            raise WorkbenchConflict("改面后的调查区域不能为空")
        with self._lock:
            cached = self._idem_get(f"prepare-change:{face_id}", change_id)
            if cached is not None:
                return cached
            face = self._find_face_row(face_id)
            self._require_mutable(face)
            for other in self._faces:
                if other["id"] == face_id or other["fields_reclaimed"]:
                    continue
                overlap = sorted(set(other["areas"]) & set(areas))
                if overlap:
                    raise WorkbenchConflict(FACE_OVERLAP_MESSAGE.format(area="、".join(overlap)))
            face["draft_seq"] += 1
            draft = {
                "草稿号": face["draft_seq"],
                "areas": areas,
                "bounds": bounds or face["bounds"],
                "base_version": face["signed_version"],
                "operator": operator,
            }
            face["drafts"].append(draft)
            payload = self._face_brief(face)
            payload["草稿"] = deepcopy(draft)
            payload["待审签草稿数"] = len(face["drafts"])
            self._idem_put(f"prepare-change:{face_id}", change_id, payload)
            return deepcopy(payload)

    def _require_mutable(self, face: dict[str, Any]) -> None:
        if face["fields_reclaimed"]:
            raise WorkbenchConflict("授权面已撤销，不能再改面")
        if not face["entry_open"]:
            raise WorkbenchConflict("授权面正处于撤销流程，图面入口已关闭")

    def sign_change(
        self,
        face_id: int,
        *,
        operator: str,
        draft_no: int | None = None,
        change_id: str | None = None,
    ) -> dict[str, Any]:
        """审签某份改面草稿：以最新审签版本为准，只保留一个有效版本。

        草稿基线落后于最新审签版本时，说明并发期间已有更新版本落地，旧草稿驳回。
        """
        with self._lock:
            cached = self._idem_get(f"sign-change:{face_id}", change_id)
            if cached is not None:
                return cached
            face = self._find_face_row(face_id)
            self._require_mutable(face)
            drafts = face.get("drafts", [])
            pending = [item for item in drafts if not item.get("作废")]
            if not drafts:
                raise WorkbenchConflict("没有待审签的改面草稿，请先圈定新调查区域")
            if draft_no is None:
                draft = pending[-1] if pending else None
                if draft is None:
                    raise WorkbenchConflict("待审签草稿均已随更新版本作废，请按最新版本重绘")
            else:
                draft = next((item for item in drafts if item["草稿号"] == draft_no), None)
                if draft is None:
                    raise WorkbenchNotFound(f"改面草稿 {draft_no} 不存在")
                if draft.get("作废"):
                    raise WorkbenchConflict(
                        f"草稿{draft_no}基于 V{draft['base_version']}，授权面已有更新的审签版本 "
                        f"V{face['signed_version']}，请按最新版本重绘"
                    )
            # 并发改面：基线版本必须等于最新审签版本，否则按最新版本为准驳回旧改动
            if draft["base_version"] != face["signed_version"]:
                draft["作废"] = True
                raise WorkbenchConflict(
                    f"授权面已存在更新的审签版本 V{face['signed_version']}，"
                    f"本次基于 V{draft['base_version']} 的改面被驳回，请按最新版本重绘"
                )

            new_areas = draft["areas"]
            new_bounds = draft["bounds"]
            # 再次做跨面占用校验，防止草稿期间别的面扩了过来
            for other in self._faces:
                if other["id"] == face_id or other["fields_reclaimed"]:
                    continue
                overlap = sorted(set(other["areas"]) & set(new_areas))
                if overlap:
                    raise WorkbenchConflict(FACE_OVERLAP_MESSAGE.format(area="、".join(overlap)))

            # 校验全部通过后才落库：未成功不动旧版本，旧会话权限自然保持
            new_version = face["signed_version"] + 1
            map_version = f"MAP-V{new_version}"
            face["areas"] = new_areas
            face["bounds"] = new_bounds
            face["signed_version"] = new_version
            face["map_version"] = map_version
            face["signed_by"] = operator
            face["signed_at"] = _now()
            face["history"].append(
                {"版本": new_version, "地图版本": map_version, "审签人": operator, "时间": _now()}
            )
            # 新版本生效后，其余并发草稿因基线落后自动作废；只保留这一个有效版本
            for item in face["drafts"]:
                if item is not draft:
                    item["作废"] = True

            # 新面覆盖范围内的存量点回填归属；掉出新面的点解除归属
            self._reconcile_points(face)
            self._claim_figures(face)
            # 在线旧会话统一挂到最新审签版本：返回工作台即按新版本重载
            for session in self._sessions:
                if session["face_id"] == face_id and session["active"]:
                    session["face_version"] = new_version
                    session["map_version"] = map_version
            payload = self._face_brief(face)
            self._idem_put(f"sign-change:{face_id}", change_id, payload)
            return deepcopy(payload)

    def _reconcile_points(self, face: dict[str, Any]) -> None:
        in_areas = set(face["areas"])
        for row in store.rows(MODULE):
            belongs = str(row.get("调查区域", "")).strip() in in_areas
            if belongs and row.get("_face_id") is None:
                row["_face_id"] = face["id"]
                row["_face_version"] = face["map_version"]
            elif not belongs and row.get("_face_id") == face["id"]:
                row.pop("_face_id", None)
                row.pop("_face_version", None)

    # ------------------------------------------------------------------ 工作台会话

    def open_session(self, face_id: int, *, operator: str, change_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            cached = self._idem_get(f"open-session:{face_id}", change_id)
            if cached is not None:
                return cached
            face = self._find_face_row(face_id)
            if face["fields_reclaimed"]:
                raise WorkbenchDenied("授权面已撤销，不能再进入工作台")
            token = secrets.token_hex(8)
            session = {
                "token": token,
                "face_id": face_id,
                "operator": operator.strip() or "调查人员",
                "face_version": face["signed_version"],
                "map_version": face["map_version"],
                "active": True,
                "entry_open": True,
                "opened_at": _now(),
            }
            self._sessions.append(session)
            payload = self._session_view(face, session)
            self._idem_put(f"open-session:{face_id}", change_id, payload)
            return deepcopy(payload)

    def _session_view(self, face: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
        return {
            "session_token": session["token"],
            "授权面": face["name"],
            "face_id": face["id"],
            "访问性质": "只读访问面",
            "有效版本": session["face_version"],
            "最新审签版本": face["signed_version"],
            "地图版本": session["map_version"],
            "会话有效": session["active"],
            "图面入口": "开放" if face["entry_open"] else "关闭",
            "提示": (
                "授权面已更新，请按最新地图版本重载"
                if session["face_version"] != face["signed_version"]
                else "仅可在面内查看现场记录，禁止提交"
            ),
        }

    def session_status(self, face_id: int, token: str | None) -> dict[str, Any]:
        with self._lock:
            session = self._find_session(token)
            if int(session["face_id"]) != face_id:
                raise WorkbenchDenied("工作台会话与授权面不匹配，禁止跨面访问")
            face = self._find_face_row(face_id)
            view = self._session_view(face, session)
            # 旧会话返回工作台探活：撤销后令牌本身仍可识别，但明确告知会话已失效
            if not session["active"] or face["fields_reclaimed"]:
                view["会话有效"] = False
                view["提示"] = "授权已撤销，会话已失效，请重新申请授权面"
            return view

    def submit_record(
        self, face_id: int, token: str | None, values: dict[str, Any]
    ) -> dict[str, Any]:
        """工作台只读：任何提交一律拒绝；撤销后的旧会话同样拒绝。"""
        with self._lock:
            session = self._require_face_session(face_id, token)
            face = self._find_face_row(face_id)
            if not session["active"] or face["fields_reclaimed"]:
                raise WorkbenchDenied("访问已撤销，旧会话不得继续提交，请重新申请授权面")
            if not face["entry_open"]:
                raise WorkbenchDenied("图面入口已关闭，旧会话返回工作台后不得继续提交")
            raise WorkbenchDenied(READ_ONLY_MESSAGE)

    # ------------------------------------------------------------------ 面内读取

    def _require_readable(self, face: dict[str, Any], session: dict[str, Any]) -> None:
        if not session["active"] or face["fields_reclaimed"]:
            raise WorkbenchDenied("访问已撤销，工作台内容不可再查看")
        if not face["entry_open"]:
            raise WorkbenchDenied("图面入口已关闭，正在回收现场字段，请稍候")

    def map_bundle(self, face_id: int, token: str | None) -> dict[str, Any]:
        """工作台主读取口：灾害点图、调查台账、报告章节同步到同一地图版本。"""
        with self._lock:
            session = self._require_face_session(face_id, token)
            face = self._find_face_row(face_id)
            self._require_readable(face, session)
            session["face_version"] = face["signed_version"]
            session["map_version"] = face["map_version"]
            return {
                "授权面": face["name"],
                "调查区域": list(face["areas"]),
                "地图版本": face["map_version"],
                "审签版本": face["signed_version"],
                "灾害点图": self._hazard_layer(face, full=True),
                "调查台账": self._ledger(face, full=True),
                "报告章节": self._chapters(face),
                "面内图件": self._own_figures(face),
                "跨面引用图件": self._cross_figures(face),
            }

    def get_record(self, face_id: int, token: str | None, record_id: int) -> dict[str, Any]:
        with self._lock:
            session = self._require_face_session(face_id, token)
            face = self._find_face_row(face_id)
            row = store.find(MODULE, record_id)
            if row is None:
                raise WorkbenchNotFound(f"环境调查点 {record_id} 不存在或已归档")
            if row.get("_face_id") != face_id:
                # 跨面看点：拒绝原文，仅给脱敏摘要
                return {
                    "id": record_id,
                    "调查编号": row.get("调查编号"),
                    "灾害类型": _mask(row.get("灾害类型")),
                    "摘要": "该现场记录不在当前授权面内，仅显示脱敏摘要",
                }
            if not session["active"] or face["fields_reclaimed"]:
                return self._visible_record(row, full=False)
            if not face["entry_open"]:
                # 入口已关但字段尚未回收：仍可读字段，顺序上先关门再回收
                return self._visible_record(row, full=True)
            return self._visible_record(row, full=True)

    # ------------------------------------------------------------------ 报告快照

    def generate_report(self, face_id: int, token: str | None) -> dict[str, Any]:
        with self._lock:
            session = self._require_face_session(face_id, token)
            face = self._find_face_row(face_id)
            self._require_readable(face, session)
            session["face_version"] = face["signed_version"]
            session["map_version"] = face["map_version"]
            report_id = max((int(item["id"]) for item in self._reports), default=0) + 1
            # 可见性快照：把当时面内字段与地图版本固化，后续改面/撤销不影响历史报告
            snapshot = {
                "id": report_id,
                "face_id": face_id,
                "授权面": face["name"],
                "地图版本": face["map_version"],
                "审签版本": face["signed_version"],
                "生成时间": _now(),
                "灾害点图": deepcopy(self._hazard_layer(face, full=True)),
                "调查台账": deepcopy(self._ledger(face, full=True)),
                "报告章节": deepcopy(self._chapters(face)),
                "可见性快照": {
                    "现场记录": "面内全量可见",
                    "跨面图件": "仅脱敏摘要",
                    "快照版本": face["map_version"],
                },
            }
            self._reports.append(snapshot)
            return deepcopy(snapshot)

    def list_reports(self, face_id: int, token: str | None) -> dict[str, Any]:
        with self._lock:
            self._require_face_session(face_id, token)
            self._find_face_row(face_id)
            items = [
                {
                    "id": report["id"],
                    "授权面": report["授权面"],
                    "地图版本": report["地图版本"],
                    "审签版本": report["审签版本"],
                    "生成时间": report["生成时间"],
                    "可见性快照": report["可见性快照"],
                }
                for report in self._reports
                if report["face_id"] == face_id
            ]
            return {"face_id": face_id, "历史报告": items}

    def get_report(self, face_id: int, token: str | None, report_id: int) -> dict[str, Any]:
        with self._lock:
            self._require_face_session(face_id, token)
            for report in self._reports:
                if report["id"] == report_id and report["face_id"] == face_id:
                    return deepcopy(report)
            raise WorkbenchNotFound(f"报告 {report_id} 不在授权面 {face_id} 的历史快照中")

    # ------------------------------------------------------------------ 撤销（两段式）

    def begin_revoke(self, face_id: int, *, revoke_id: str | None = None) -> dict[str, Any]:
        """撤销第一步：先关闭图面入口，现场字段暂不回收。"""
        with self._lock:
            cached = self._idem_get(f"revoke-begin:{face_id}", revoke_id)
            if cached is not None:
                return cached
            face = self._find_face_row(face_id)
            if face["fields_reclaimed"]:
                raise WorkbenchConflict("授权面已撤销完成，请勿重复操作")
            face["entry_open"] = False
            for session in self._sessions:
                if session["face_id"] == face_id and session["active"]:
                    session["entry_open"] = False
            payload = self._face_brief(face)
            payload["撤销阶段"] = "图面入口已关闭，现场字段待回收"
            self._idem_put(f"revoke-begin:{face_id}", revoke_id, payload)
            return deepcopy(payload)

    def complete_revoke(self, face_id: int, *, revoke_id: str | None = None) -> dict[str, Any]:
        """撤销第二步：回收现场字段并作废全部旧会话。"""
        with self._lock:
            cached = self._idem_get(f"revoke-complete:{face_id}", revoke_id)
            if cached is not None:
                return cached
            face = self._find_face_row(face_id)
            if face["fields_reclaimed"]:
                raise WorkbenchConflict("授权面已撤销完成，请勿重复操作")
            if face["entry_open"]:
                raise WorkbenchConflict("需先关闭图面入口，再回收现场字段，不得跳步")
            for row in self._face_rows(face):
                for key in SENSITIVE_KEYS:
                    row[key] = RECLAIMED_MARK
                row["_fields_reclaimed"] = True
            face["fields_reclaimed"] = True
            face["entry_open"] = False
            for session in self._sessions:
                if session["face_id"] == face_id and session["active"]:
                    session["active"] = False
                    session["entry_open"] = False
            payload = self._face_brief(face)
            payload["撤销阶段"] = "现场字段已回收，旧会话全部失效"
            self._idem_put(f"revoke-complete:{face_id}", revoke_id, payload)
            return deepcopy(payload)


workbench_service = WorkbenchService()
