"""Cross-cutting protections.

- Security headers on every response, including a Content Security Policy that allows only our
  own files plus what Google's sign-in button needs.
- Same-origin enforcement for state-changing requests, so another website cannot make a signed-in
  browser call our API (defence in depth on top of SameSite cookies).
- A small in-memory rate limiter for sign-in attempts, uploads, and paid explanation calls.

The rate limiter is per server instance. Cloud Run may run several, so treat limits as
approximate: enough to blunt brute force and runaway cost, not a hard quota.
"""
import os
import threading
import time
from collections import defaultdict, deque
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware

ENV = os.environ.get("TRUEACRE_ENV", "development")
IS_PRODUCTION = ENV == "production"

HSTS_MAX_AGE = 365 * 24 * 3600  # seconds browsers remember to use HTTPS only (one year, the common minimum)
GSI = "https://accounts.google.com"  # Google Identity Services: script, button iframe, and styles
CSP = "; ".join([
    "default-src 'self'",
    f"script-src 'self' {GSI}/gsi/client",
    f"frame-src {GSI}/gsi/",
    f"connect-src 'self' {GSI}/gsi/",
    f"style-src 'self' {GSI}/gsi/style",
    "img-src 'self' data: https://*.googleusercontent.com",  # Google profile pictures
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
])

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        headers = response.headers
        headers["Content-Security-Policy"] = CSP
        headers["X-Content-Type-Options"] = "nosniff"
        headers["X-Frame-Options"] = "DENY"
        headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if IS_PRODUCTION:
            headers["Strict-Transport-Security"] = f"max-age={HSTS_MAX_AGE}; includeSubDomains"
        return response


class SameOriginMiddleware(BaseHTTPMiddleware):
    """Reject state-changing API requests whose Origin does not match the Host we were called on."""

    async def dispatch(self, request, call_next):
        if request.method in UNSAFE_METHODS and request.url.path.startswith("/api/"):
            origin = request.headers.get("origin")
            site = request.headers.get("sec-fetch-site")
            if origin and urlsplit(origin).netloc != request.headers.get("host"):
                return _forbidden()
            if site and site not in ("same-origin", "none"):
                return _forbidden()
        return await call_next(request)


def _forbidden():
    from fastapi.responses import JSONResponse

    return JSONResponse({"detail": "cross-site request refused"}, status_code=403)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


class RateLimiter:
    """At most `limit` events per `window_seconds` per key. Raises 429 when exceeded."""

    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window = window_seconds
        self._events: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            events = self._events[key]
            while events and now - events[0] > self.window:
                events.popleft()
            if len(events) >= self.limit:
                retry = int(self.window - (now - events[0])) + 1
                raise HTTPException(status_code=429, detail="too many requests, slow down",
                                    headers={"Retry-After": str(retry)})
            events.append(now)
