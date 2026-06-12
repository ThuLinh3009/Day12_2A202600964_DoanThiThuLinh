"""
Rate Limiter — Sliding window algorithm.

Primary: Redis-backed (survives restarts, works across multiple instances).
Fallback: In-memory deque (single-instance only, used when Redis unavailable).
"""
import time
import logging
from collections import defaultdict, deque
from fastapi import HTTPException

logger = logging.getLogger(__name__)

# In-memory fallback (used when Redis is not available)
_memory_windows: dict[str, deque] = defaultdict(deque)


def _get_redis():
    """Return Redis client or None if unavailable."""
    from app.config import settings

    if not settings.redis_url:
        return None
    try:
        import redis
        r = redis.from_url(settings.redis_url, socket_connect_timeout=1)
        r.ping()
        return r
    except Exception:
        return None


def check_rate_limit(key: str, limit: int | None = None) -> None:
    """
    Sliding window rate limit check.

    key   — unique identifier (e.g. first 8 chars of API key)
    limit — max requests per 60 seconds; defaults to settings.rate_limit_per_minute
    """
    from app.config import settings

    max_requests = limit or settings.rate_limit_per_minute
    window_seconds = 60
    now = time.time()

    redis_client = _get_redis()

    if redis_client:
        _redis_rate_limit(redis_client, key, max_requests, window_seconds, now)
    else:
        _memory_rate_limit(key, max_requests, window_seconds, now)


def _redis_rate_limit(r, key: str, limit: int, window: int, now: float) -> None:
    """Sliding window via Redis sorted set."""
    redis_key = f"rl:{key}"
    pipe = r.pipeline()
    try:
        # Remove entries older than window
        pipe.zremrangebyscore(redis_key, 0, now - window)
        # Count remaining
        pipe.zcard(redis_key)
        # Add current timestamp
        pipe.zadd(redis_key, {str(now): now})
        # Auto-expire the key after window duration
        pipe.expire(redis_key, window + 1)
        results = pipe.execute()
        count = results[1]  # zcard result (before adding new)
        if count >= limit:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded: {limit} req/{window}s. Try again later.",
                headers={"Retry-After": str(window)},
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Redis rate limit error, falling back to memory: {e}")
        _memory_rate_limit(key, limit, window, now)


def _memory_rate_limit(key: str, limit: int, window: int, now: float) -> None:
    """Sliding window via in-memory deque (single-instance fallback)."""
    window_deque = _memory_windows[key]
    while window_deque and window_deque[0] < now - window:
        window_deque.popleft()
    if len(window_deque) >= limit:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: {limit} req/{window}s. Try again later.",
            headers={"Retry-After": str(window)},
        )
    window_deque.append(now)
