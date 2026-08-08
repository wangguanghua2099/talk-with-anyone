class AppError(Exception):
    """业务错误：携带 HTTP 状态码与稳定错误码。

    响应格式统一为 {"error_code": ..., "message": ..., "error": ...}，
    其中 error 字段为向后兼容保留。
    """

    def __init__(self, error_code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.status_code = status_code
