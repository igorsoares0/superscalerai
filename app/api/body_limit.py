"""Cap request bodies before anything buffers them.

FastAPI resolves an `UploadFile` parameter by parsing the whole multipart body
first, so an endpoint can only measure an upload *after* Starlette has spooled
it to a temp file (everything above ~1 MB) and started handing it back as
bytes. A multi-gigabyte POST would fill the disk and then the heap of a box
we're sizing at 8 GB. This runs on the raw ASGI stream, ahead of all of that.
"""

from fastapi import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import settings

# Multipart framing (boundaries, headers) around a max_upload_mb file is a few
# hundred bytes; this is room to spare, so the endpoint stays the place where
# the documented file limit is enforced and worded.
FRAMING_SLACK = 64 * 1024


def max_body_bytes() -> int:
    return settings.max_upload_mb * 1024 * 1024 + FRAMING_SLACK


class BodySizeLimitMiddleware:
    """Reject any request whose body exceeds the cap.

    Trusts Content-Length when it's there — the usual case, and the only way
    to refuse *before* reading anything — and counts bytes as they arrive when
    it isn't: chunked requests declare no length, and a hostile client can
    simply lie about it.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        limit = max_body_bytes()
        declared = _declared_length(scope)
        if declared is not None and declared > limit:
            response = JSONResponse({"detail": "request body too large"}, status_code=413)
            return await response(scope, receive, send)

        received = 0

        async def counting_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    # FastAPI re-raises HTTPException from body parsing
                    # untouched, so this lands as a 413 and not a generic 400.
                    raise HTTPException(413, "request body too large")
            return message

        await self.app(scope, counting_receive, send)


def _declared_length(scope: Scope) -> int | None:
    for name, value in scope.get("headers", []):
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None  # malformed: let the byte counter handle it
    return None
