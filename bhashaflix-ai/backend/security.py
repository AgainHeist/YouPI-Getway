"""Access control, rate limiting and safe path handling."""
from __future__ import annotations

import hmac
import time
import threading
from collections import deque
from pathlib import Path

from fastapi import HTTPException, Request

from .config import settings
from .models import error_payload
from .services import repo


def _unauthorized(detail: str = "A valid access token is required.") -> HTTPException:
    return HTTPException(status_code=401, detail=error_payload("UNAUTHORIZED", detail))


def provided_token(request: Request) -> str:
    header = request.headers.get("x-api-token") or ""
    if header:
        return header
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.query_params.get("token") or ""


def require_token(request: Request) -> None:
    """Enforce the shared token when the operator configured one."""
    if not settings.auth_required:
        return
    token = provided_token(request)
    if not token or not hmac.compare_digest(token, settings.api_token):
        raise _unauthorized()


def optional_token_ok(request: Request) -> bool:
    if not settings.auth_required:
        return True
    token = provided_token(request)
    return bool(token) and hmac.compare_digest(token, settings.api_token)


def client_ip(request: Request) -> str:
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class RateLimiter:
    """Sliding-window limiter keyed by client IP (per process)."""

    def __init__(self, limit: int, window: float = 60.0):
        self.limit = limit
        self.window = window
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            bucket = self._hits.setdefault(key, deque())
            while bucket and now - bucket[0] > self.window:
                bucket.popleft()
            if len(bucket) >= self.limit:
                return False
            bucket.append(now)
            return True


limiter = RateLimiter(settings.rate_limit_per_min)


def guard_job_path(job_id: str, *parts: str) -> Path:
    """Resolve a file inside a job directory, refusing traversal."""
    try:
        base = repo.job_dir(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=error_payload("JOB_NOT_FOUND", "Invalid project id.")) from exc
    resolved = base.joinpath(*parts).resolve()
    if base.resolve() not in resolved.parents and resolved != base.resolve():
        raise HTTPException(status_code=400, detail=error_payload("JOB_NOT_FOUND", "Invalid file path."))
    return resolved


def ensure_job(job_id: str) -> dict:
    job = repo.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=error_payload("JOB_NOT_FOUND"))
    return job
