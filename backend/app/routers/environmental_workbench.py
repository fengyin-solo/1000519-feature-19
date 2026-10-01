"""地图禁入面联动工作台接口。

授权面圈定/改面审签、只读工作台会话、面内现场记录与图件、历史报告快照、
两段式撤销都挂在 /api/environmental/workbench 下。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

from app.services.workbench import workbench_service

router = APIRouter(prefix="/api/environmental/workbench", tags=["环境地质-禁入面工作台"])


class FaceCreatePayload(BaseModel):
    name: str = Field(description="授权面名称")
    areas: list[str] = Field(default_factory=list, description="圈定的调查区域列表")
    operator: str = Field(default="值班管理员")
    bounds: dict[str, Any] | None = None
    change_id: str | None = Field(default=None, description="断线重放用幂等键")


class ChangePreparePayload(BaseModel):
    """改面草稿：只需提交新的调查区域，不改动授权面名称。"""

    areas: list[str] = Field(default_factory=list, description="圈定后的调查区域列表")
    operator: str = Field(default="值班管理员")
    bounds: dict[str, Any] | None = None
    change_id: str | None = Field(default=None, description="断线重放用幂等键")


class SignPayload(BaseModel):
    operator: str = Field(default="值班管理员")
    draft_no: int | None = Field(default=None, description="待审签的改面草稿号；缺省取最新一份")
    change_id: str | None = None


class SessionOpenPayload(BaseModel):
    operator: str = Field(default="调查人员")
    change_id: str | None = None


class RevokePayload(BaseModel):
    revoke_id: str | None = Field(default=None, description="断线重放用幂等键")


class SubmitPayload(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)


def _token(x_session_token: str | None) -> str | None:
    return x_session_token


@router.get("/faces")
def list_faces() -> dict[str, Any]:
    """查看全部授权面及其有效版本、撤销阶段。"""
    return {"items": workbench_service.list_faces()}


@router.post("/faces")
def create_face(payload: FaceCreatePayload) -> dict[str, Any]:
    """圈定调查区域生成只读访问面，存量环境调查点按调查区域回填归属。"""
    return workbench_service.create_face(
        name=payload.name,
        areas=payload.areas,
        operator=payload.operator,
        bounds=payload.bounds,
        change_id=payload.change_id,
    )


@router.post("/faces/{face_id}/changes/prepare")
def prepare_change(face_id: int, payload: ChangePreparePayload) -> dict[str, Any]:
    """提交改面草稿（新调查区域），尚未覆盖现版本。"""
    return workbench_service.prepare_change(
        face_id,
        areas=payload.areas,
        operator=payload.operator,
        bounds=payload.bounds,
        change_id=payload.change_id,
    )


@router.post("/faces/{face_id}/changes/sign")
def sign_change(face_id: int, payload: SignPayload) -> dict[str, Any]:
    """审签改面：以最新审签版本为准，只保留一个有效版本；成功后地图三件套同步新版本。"""
    return workbench_service.sign_change(
        face_id,
        operator=payload.operator,
        draft_no=payload.draft_no,
        change_id=payload.change_id,
    )


@router.post("/faces/{face_id}/sessions")
def open_session(face_id: int, payload: SessionOpenPayload) -> dict[str, Any]:
    """人员进入某授权面工作台，领取只读会话令牌。"""
    return workbench_service.open_session(
        face_id, operator=payload.operator, change_id=payload.change_id
    )


@router.get("/faces/{face_id}/sessions/me")
def session_status(
    face_id: int, x_session_token: str | None = Header(default=None)
) -> dict[str, Any]:
    """旧会话返回工作台时核对版本与有效性。"""
    return workbench_service.session_status(face_id, _token(x_session_token))


@router.get("/faces/{face_id}/map")
def get_map(
    face_id: int, x_session_token: str | None = Header(default=None)
) -> dict[str, Any]:
    """灾害点图、调查台账、报告章节同步重载到同一地图版本；跨面图件只给脱敏摘要。"""
    return workbench_service.map_bundle(face_id, _token(x_session_token))


@router.get("/faces/{face_id}/records/{record_id}")
def get_record(
    face_id: int, record_id: int, x_session_token: str | None = Header(default=None)
) -> dict[str, Any]:
    """查看单条现场记录；跨面只给脱敏摘要，撤销后字段回收。"""
    return workbench_service.get_record(face_id, _token(x_session_token), record_id)


@router.post("/faces/{face_id}/records")
def submit_record(
    face_id: int,
    payload: SubmitPayload,
    x_session_token: str | None = Header(default=None),
) -> dict[str, Any]:
    """只读面提交入口：一律拒绝（含撤销后的旧会话）。"""
    return workbench_service.submit_record(face_id, _token(x_session_token), payload.values)


@router.post("/faces/{face_id}/reports")
def generate_report(
    face_id: int, x_session_token: str | None = Header(default=None)
) -> dict[str, Any]:
    """生成报告：固化当前地图版本与可见性快照，历史报告维持该快照不变。"""
    return workbench_service.generate_report(face_id, _token(x_session_token))


@router.get("/faces/{face_id}/reports")
def list_reports(
    face_id: int, x_session_token: str | None = Header(default=None)
) -> dict[str, Any]:
    """列出该面历史报告及其可见性快照（撤销后仍可按快照查看）。"""
    return workbench_service.list_reports(face_id, _token(x_session_token))


@router.get("/faces/{face_id}/reports/{report_id}")
def get_report(
    face_id: int, report_id: int, x_session_token: str | None = Header(default=None)
) -> dict[str, Any]:
    """读取历史报告快照，内容停留在生成时的地图版本与字段可见性。"""
    return workbench_service.get_report(face_id, _token(x_session_token), report_id)


@router.post("/faces/{face_id}/revoke/begin")
def begin_revoke(face_id: int, payload: RevokePayload) -> dict[str, Any]:
    """撤销第一步：先关闭图面入口，旧会话不得再提交。"""
    return workbench_service.begin_revoke(face_id, revoke_id=payload.revoke_id)


@router.post("/faces/{face_id}/revoke/complete")
def complete_revoke(face_id: int, payload: RevokePayload) -> dict[str, Any]:
    """撤销第二步：再回收现场字段并作废旧会话。"""
    return workbench_service.complete_revoke(face_id, revoke_id=payload.revoke_id)
