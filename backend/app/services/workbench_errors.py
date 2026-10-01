"""工作台业务异常：路由层统一翻译成 HTTP 状态码。"""
from __future__ import annotations


class WorkbenchError(Exception):
    """工作台通用异常：detail 直接作为响应说明。"""

    status_code = 400


class WorkbenchDenied(WorkbenchError):
    """越权请求：没有会话、会话失效、跨面访问或只读面提交，一律拒绝。"""

    status_code = 403


class WorkbenchNotFound(WorkbenchError):
    """授权面、调查点、报告等对象不存在。"""

    status_code = 404


class WorkbenchConflict(WorkbenchError):
    """并发改面冲突、阶段顺序错误、重复发起等。"""

    status_code = 409
