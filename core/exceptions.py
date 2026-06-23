import logging
from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("cafe_backend")


class InternalError(Exception):
    def __init__(self, original: Exception, context: str = ""):
        self.original = original
        self.context = context
        super().__init__(str(original))


async def internal_error_handler(request: Request, exc: InternalError) -> JSONResponse:
    msg = f"{exc.context}: {exc.original}" if exc.context else str(exc.original)
    logger.error(f"[InternalError] {request.method} {request.url.path} - {msg}")
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
