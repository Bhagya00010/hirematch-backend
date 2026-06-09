from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from fastapi import HTTPException, Request, status


@dataclass
class RateLimitRecord:
    remaining: int
    reset_at: float


class RateLimiter:
    """FastAPI dependency that rate-limits requests by client identity.

    Usage:
        @router.post("/login")
        def login(..., _: None = Depends(RateLimiter(limit=5, window_seconds=60))):
            ...
    """

    def __init__(
        self,
        limit: int = 60,
        window_seconds: int = 60,
        key_prefix: str = "rl",
        identifier: Callable[[Request], str] | None = None,
    ):
        self.limit = limit
        self.window_seconds = window_seconds
        self.key_prefix = key_prefix
        self.identifier = identifier
        self._store: dict[str, RateLimitRecord] = {}

    def _get_client_ip(self, request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()

        client = request.client
        return client.host if client is not None else "unknown"

    def _get_identity(self, request: Request) -> str:
        if self.identifier is not None:
            return self.identifier(request)
        return self._get_client_ip(request)

    def _get_key(self, request: Request) -> str:
        return f"{self.key_prefix}:{self._get_identity(request)}:{request.url.path}"

    async def __call__(self, request: Request) -> None:
        key = self._get_key(request)
        now = time.time()
        record = self._store.get(key)

        if record is None or record.reset_at <= now:
            self._store.pop(key, None)

            record = RateLimitRecord(
                remaining=self.limit,
                reset_at=now + self.window_seconds,
            )
        if record.remaining <= 0:
            retry_after = int(max(record.reset_at - now, 0))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests, please try again later.",
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(self.limit),
                    "X-RateLimit-Remaining": "0",
                },
            )

        record.remaining -= 1
        self._store[key] = record

      # Auth APIs
register_rate_limiter = RateLimiter(limit=5, window_seconds=60)
login_rate_limiter = RateLimiter(limit=5, window_seconds=60)
refresh_rate_limiter = RateLimiter(limit=10, window_seconds=60)
forgot_password_rate_limiter = RateLimiter(limit=3, window_seconds=300)
reset_password_rate_limiter = RateLimiter(limit=3, window_seconds=300)

# Generic API limiters
read_rate_limiter = RateLimiter(limit=100, window_seconds=60)
write_rate_limiter = RateLimiter(limit=30, window_seconds=60)
heavy_rate_limiter = RateLimiter(limit=10, window_seconds=60)