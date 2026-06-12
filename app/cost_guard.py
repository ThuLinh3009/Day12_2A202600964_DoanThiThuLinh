"""
Cost Guard — Budget protection for LLM API calls.

Tracks token usage and estimated cost per day (global) and per month (per user).
Primary storage: Redis. Fallback: in-memory (resets on restart).

Pricing reference (gpt-4o-mini):
  Input:  $0.00015 / 1K tokens
  Output: $0.0006  / 1K tokens
"""
import time
import logging
from fastapi import HTTPException

logger = logging.getLogger(__name__)

# In-memory fallback state
_daily: dict[str, float] = {}   # date -> cost
_monthly: dict[str, float] = {} # "user:YYYY-MM" -> cost


def _get_redis():
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


def estimate_cost(input_tokens: int, output_tokens: int) -> float:
    """Estimate USD cost for a given token count (gpt-4o-mini rates)."""
    return (input_tokens / 1000) * 0.00015 + (output_tokens / 1000) * 0.0006


def check_daily_budget(cost: float) -> None:
    """
    Check global daily budget before making an LLM call.
    Raises HTTP 503 if daily budget would be exceeded.
    """
    from app.config import settings

    today = time.strftime("%Y-%m-%d")
    r = _get_redis()

    if r:
        spent = float(r.get(f"cost:daily:{today}") or 0)
    else:
        spent = _daily.get(today, 0.0)

    if spent + cost > settings.daily_budget_usd:
        raise HTTPException(
            status_code=503,
            detail=f"Daily budget of ${settings.daily_budget_usd:.2f} exhausted. Try tomorrow.",
        )


def record_cost(input_tokens: int, output_tokens: int, user_id: str = "global") -> float:
    """
    Record actual cost after a successful LLM call.
    Returns cost incurred.
    """
    cost = estimate_cost(input_tokens, output_tokens)
    today = time.strftime("%Y-%m-%d")
    month = time.strftime("%Y-%m")
    r = _get_redis()

    if r:
        pipe = r.pipeline()
        daily_key = f"cost:daily:{today}"
        user_key = f"cost:user:{user_id}:{month}"
        pipe.incrbyfloat(daily_key, cost)
        pipe.expire(daily_key, 2 * 86400)  # keep 2 days
        pipe.incrbyfloat(user_key, cost)
        pipe.expire(user_key, 35 * 86400)  # keep ~35 days
        pipe.execute()
    else:
        _daily[today] = _daily.get(today, 0.0) + cost
        mk = f"{user_id}:{month}"
        _monthly[mk] = _monthly.get(mk, 0.0) + cost

    return cost


def check_user_monthly_budget(user_id: str, cost: float, monthly_limit: float = 10.0) -> None:
    """
    Check per-user monthly budget ($10/month by default).
    Raises HTTP 402 if limit would be exceeded.
    """
    month = time.strftime("%Y-%m")
    r = _get_redis()

    if r:
        spent = float(r.get(f"cost:user:{user_id}:{month}") or 0)
    else:
        spent = _monthly.get(f"{user_id}:{month}", 0.0)

    if spent + cost > monthly_limit:
        raise HTTPException(
            status_code=402,
            detail=f"Monthly budget of ${monthly_limit:.2f} per user exceeded.",
        )


def get_daily_usage() -> dict:
    """Return today's cost summary."""
    today = time.strftime("%Y-%m-%d")
    r = _get_redis()
    from app.config import settings

    if r:
        spent = float(r.get(f"cost:daily:{today}") or 0)
    else:
        spent = _daily.get(today, 0.0)

    return {
        "date": today,
        "spent_usd": round(spent, 6),
        "budget_usd": settings.daily_budget_usd,
        "used_pct": round(spent / settings.daily_budget_usd * 100, 1),
    }
