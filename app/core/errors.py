"""公共错误只暴露稳定代码，不把数据库异常、文件路径或模型密钥返回前端。"""

from shared.errors import AppError as AppError


def not_found():
    return AppError("not_found", "资源不存在或不在当前项目内", 404)


def conflict(message="数据已发生变化，请刷新后重试"):
    return AppError("conflict", message, 409)
