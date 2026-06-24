class AppError(Exception):
    def __init__(
        self,
        detail: str,
        *,
        status_code: int = 400,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code
        self.headers = headers or {}

class AuthenticationError(AppError):
    def __init__(self, detail: str = "Authentication required.") -> None:
        super().__init__(
            detail,
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )

class AuthorizationError(AppError):
    def __init__(self, detail: str = "You are not allowed to perform this action.") -> None:
        super().__init__(detail, status_code=403)

class NotFoundError(AppError):
    def __init__(self, detail: str = "Resource not found.") -> None:
        super().__init__(detail, status_code=404)

class DependencyUnavailableError(AppError):
    def __init__(self, detail: str = "A required service is temporarily unavailable.") -> None:
        super().__init__(detail, status_code=503)

class RequestEntityTooLargeError(AppError):
    def __init__(self, detail: str = "Uploaded file exceeds the allowed size.") -> None:
        super().__init__(detail, status_code=413)

class RateLimitExceededError(AppError):
    def __init__(self, detail: str = "Rate limit exceeded.", retry_after_seconds: int = 60) -> None:
        super().__init__(
            detail,
            status_code=429,
            headers={"Retry-After": str(max(retry_after_seconds, 1))},
        )
