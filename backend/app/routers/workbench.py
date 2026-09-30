"""地图禁入面联动工作台接口。

路由层只做参数装配与异常翻译，业务规则全部在 WorkbenchService。
所有越权返回 403，并发版本冲突返回 409，参数缺失返回 400。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.workbench import WorkbenchError, workbench

router = APIRouter(prefix="/api/workbench", tags=["地图禁入面工作台"])

workbench.bootstrap()


def _guard(call):
    """统一把 WorkbenchError 翻译成 HTTP 响应，端点只关心正常返回。"""
    try:
        return call()
    except WorkbenchError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


# ----------------------------------------------------------------------
# 请求体模型
# ----------------------------------------------------------------------
class SurfacePayload(BaseModel):
    region: str = Field(default="", description="调查区域名称")
    polygon: list[list[float]] = Field(default_factory=list, description="按顺序排列的顶点")
    approver: str = Field(default="", description="审签人")


class ReviseSurfacePayload(BaseModel):
    polygon: list[list[float]] = Field(default_factory=list)
    approver: str = ""
    base_version: int = Field(..., description="客户端认定的地图基线版本")
    change_token: str = Field(..., description="改面令牌，断线重连原样重传")


class SessionPayload(BaseModel):
    operator: str = ""
    scope: str = Field(..., description="full 或单个调查区域名")


class FieldNotePayload(BaseModel):
    values: dict[str, str] = Field(default_factory=dict)
    map_version: int


class FigurePayload(BaseModel):
    detail: bool = Field(default=False, description="跨面取全量明细会被 403 拒绝")


class FreezePayload(BaseModel):
    map_version: int


# ----------------------------------------------------------------------
# 管理端
# ----------------------------------------------------------------------
@router.get("/overview")
def overview() -> dict:
    """管理端总览：访问面、灾害点、图件、会话与存量回填情况。"""
    return workbench.overview()


@router.post("/backfill")
def backfill() -> dict:
    """存量环境调查点按调查区域 / 几何归属回填，幂等可重复执行。"""
    stats = workbench.backfill_owned_points()
    return {"ok": True, "message": "存量环境调查点已按调查区域回填归属", "backfill": stats}


@router.post("/surfaces")
def create_surface(payload: SurfacePayload) -> dict:
    result = _guard(lambda: workbench.create_surface(payload.region, payload.polygon, payload.approver))
    return {"ok": True, "message": f"已为「{payload.region}」生成只读访问面", **result}


@router.put("/surfaces/{surface_id}")
def revise_surface(surface_id: int, payload: ReviseSurfacePayload) -> dict:
    result = _guard(lambda: workbench.revise_surface(
        surface_id, payload.polygon, payload.approver,
        payload.base_version, payload.change_token,
    ))
    action = "断线重连已复用既有审签结果" if result.get("replayed") else "改面已按最新审签版本生效"
    return {"ok": True, "message": action, **result}


@router.post("/surfaces/{surface_id}/close-entry")
def close_entry(surface_id: int) -> dict:
    result = _guard(lambda: workbench.close_surface_entry(surface_id))
    return {"ok": True, "message": "图面入口已关闭，旧会话返回后不得继续提交", **result}


@router.post("/surfaces/{surface_id}/reclaim-fields")
def reclaim_fields(surface_id: int) -> dict:
    result = _guard(lambda: workbench.reclaim_surface_fields(surface_id))
    return {"ok": True, "message": f"现场字段已回收 {result['reclaimed']} 条，访问面撤销完成", **result}


# ----------------------------------------------------------------------
# 现场会话
# ----------------------------------------------------------------------
@router.post("/sessions")
def open_session(payload: SessionPayload) -> dict:
    session = _guard(lambda: workbench.open_session(payload.operator, payload.scope))
    return {"ok": True, "message": "已进入只读访问工作台", "session": session}


@router.get("/sessions/{session_id}/bundle")
def get_bundle(session_id: str) -> dict:
    return _guard(lambda: workbench.bundle(session_id))


@router.post("/sessions/{session_id}/reload")
def reload_session(session_id: str) -> dict:
    return _guard(lambda: workbench.reload_session(session_id))


@router.get("/sessions/{session_id}/points/{point_id}/field")
def get_field_note(session_id: str, point_id: int) -> dict:
    return _guard(lambda: workbench.get_field_note(session_id, point_id))


@router.post("/sessions/{session_id}/points/{point_id}/field")
def submit_field_note(session_id: str, point_id: int, payload: FieldNotePayload) -> dict:
    result = _guard(lambda: workbench.submit_field_note(
        session_id, point_id, payload.values, payload.map_version,
    ))
    return {"ok": True, "message": "现场记录已提交到当前地图版本", **result}


@router.post("/sessions/{session_id}/figures/{figure_id}/reference")
def reference_figure(session_id: str, figure_id: int, payload: FigurePayload) -> dict:
    return _guard(lambda: workbench.reference_figure(session_id, figure_id, payload.detail))


# ----------------------------------------------------------------------
# 报告章节
# ----------------------------------------------------------------------
@router.post("/chapters")
def create_chapter(payload: SurfacePayload) -> dict:
    chapter = _guard(lambda: workbench.create_chapter(payload.region))
    return {"ok": True, "message": "报告章节草稿已生成，将随地图版本联动重载", "chapter": chapter}


@router.post("/chapters/{chapter_id}/freeze")
def freeze_chapter(chapter_id: int, payload: FreezePayload) -> dict:
    chapter = _guard(lambda: workbench.freeze_chapter(chapter_id, payload.map_version))
    return {"ok": True, "message": "章节已定稿，可见性快照已固化，历史报告维持原可见性", "chapter": chapter}
