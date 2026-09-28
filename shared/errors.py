"""跨模块可展示错误；message 不得含密钥、文件路径或供应商原始响应。"""


class AppError(Exception):
    def __init__(self, code: str, message: str, status: int = 422, details=None):
        super().__init__(message)
        self.code, self.message, self.status, self.details = code, message, status, details
