"""
Production AI Agent — Day 12 × Day 09 Integration

Day 09: Multi-Agent Shopping Assistant (LangGraph + ChromaDB + real LLM)
Day 12: Production deployment (auth, rate limit, cost guard, health, graceful shutdown)

Flow:  POST /ask  →  verify_api_key  →  rate_limit  →  ShoppingAssistant.ask()  →  response
"""
import time
import signal
import logging
import json
import asyncio
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, HTTPException, Depends, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

from app.config import settings
from app.auth import verify_api_key
from app.rate_limiter import check_rate_limit
from app.cost_guard import check_daily_budget, record_cost, get_daily_usage

# ─────────────────────────────────────────────────────────
# Logging — JSON structured
# ─────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format='{"ts":"%(asctime)s","lvl":"%(levelname)s","msg":"%(message)s"}',
)
logger = logging.getLogger(__name__)

START_TIME = time.time()
_is_ready = False
_request_count = 0
_error_count = 0
_assistant = None          # ShoppingAssistant singleton
_executor = ThreadPoolExecutor(max_workers=4)   # for sync LangGraph calls

# ─────────────────────────────────────────────────────────
# Lifespan — init shopping assistant once at startup
# ─────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _assistant, _is_ready

    logger.info(json.dumps({
        "event": "startup",
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model,
    }))

    try:
        import sys, os
        src_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
        if src_path not in sys.path:
            sys.path.insert(0, src_path)

        from shopping_entry import load_assistant
        ShoppingAssistant, ShoppingSettings = load_assistant()

        shopping_settings = ShoppingSettings.load()
        _assistant = ShoppingAssistant(shopping_settings)
        logger.info(json.dumps({"event": "shopping_assistant_ready"}))
    except Exception as e:
        logger.error(json.dumps({"event": "startup_error", "error": str(e)}))
        _assistant = None

    _is_ready = True
    logger.info(json.dumps({"event": "ready"}))

    yield

    _is_ready = False
    _executor.shutdown(wait=False)
    logger.info(json.dumps({"event": "shutdown"}))

# ─────────────────────────────────────────────────────────
# App
# ─────────────────────────────────────────────────────────
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)

@app.middleware("http")
async def request_middleware(request: Request, call_next):
    global _request_count, _error_count
    start = time.time()
    _request_count += 1
    try:
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        if "server" in response.headers:
            del response.headers["server"]
        duration = round((time.time() - start) * 1000, 1)
        logger.info(json.dumps({
            "event": "request",
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "ms": duration,
        }))
        return response
    except Exception:
        _error_count += 1
        raise

# ─────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────
class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000,
                          description="Câu hỏi cho Shopping Assistant")
    user_id: str = Field(default="anonymous", max_length=64,
                         description="User ID để track per-user budget")


class AskResponse(BaseModel):
    question: str
    answer: str
    route: dict
    model: str
    cost_usd: float
    timestamp: str


# ─────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────

@app.get("/", tags=["Info"])
def root():
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "agent": "Day 09 Multi-Agent Shopping Assistant",
        "llm": f"{settings.llm_provider}/{settings.llm_model}",
        "endpoints": {
            "ask": "POST /ask  (requires X-API-Key)",
            "health": "GET  /health",
            "ready": "GET  /ready",
            "metrics": "GET  /metrics  (requires X-API-Key)",
        },
    }


@app.post("/ask", response_model=AskResponse, tags=["Agent"])
async def ask_agent(
    body: AskRequest,
    request: Request,
    _key: str = Depends(verify_api_key),
):
    """
    Gửi câu hỏi cho Shopping Assistant.

    Agent sẽ tự động route qua:
    - **Policy Worker**: tra cứu chính sách (RAG + ChromaDB)
    - **Data Worker**: tra cứu đơn hàng / khách hàng / voucher
    - **Response Worker**: tổng hợp câu trả lời cuối cùng

    **Authentication:** `X-API-Key: <your-key>`
    """
    if _assistant is None:
        raise HTTPException(status_code=503, detail="Shopping assistant not initialized. Check LLM API key.")

    # Rate limit keyed by first 8 chars of API key
    check_rate_limit(_key[:8])

    # Budget pre-check (rough estimate: 500 tokens ~ $0.001 for GPT-4o-mini)
    estimated_cost = 0.001
    check_daily_budget(estimated_cost)

    logger.info(json.dumps({
        "event": "agent_call",
        "user_id": body.user_id,
        "q_len": len(body.question),
        "client": str(request.client.host) if request.client else "unknown",
    }))

    # LangGraph is synchronous — run in thread pool to avoid blocking event loop
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            _executor,
            lambda: _assistant.ask(body.question)
        )
    except Exception as e:
        logger.error(json.dumps({"event": "agent_error", "error": str(e)}))
        raise HTTPException(status_code=500, detail=f"Agent error: {str(e)}")

    # Record actual cost
    cost = record_cost(input_tokens=len(body.question.split()) * 2,
                       output_tokens=len(result.get("final_answer", "").split()) * 2,
                       user_id=body.user_id)

    return AskResponse(
        question=body.question,
        answer=result.get("final_answer", ""),
        route=result.get("route", {}),
        model=settings.llm_model,
        cost_usd=round(cost, 6),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@app.get("/health", tags=["Operations"])
def health():
    """Liveness probe — container restart if this fails."""
    return {
        "status": "ok",
        "version": settings.app_version,
        "environment": settings.environment,
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "total_requests": _request_count,
        "checks": {
            "llm_provider": settings.llm_provider,
            "llm_model": settings.llm_model,
            "shopping_assistant": "ready" if _assistant is not None else "not_initialized",
            "redis": "connected" if settings.redis_url else "disabled",
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/ready", tags=["Operations"])
def ready():
    """Readiness probe — load balancer stops routing here if not ready."""
    if not _is_ready:
        raise HTTPException(status_code=503, detail="Service not ready yet")
    return {"ready": True}


@app.get("/metrics", tags=["Operations"])
def metrics(_key: str = Depends(verify_api_key)):
    """Basic operational metrics (protected)."""
    usage = get_daily_usage()
    return {
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "total_requests": _request_count,
        "error_count": _error_count,
        "daily_cost": usage,
        "rate_limit_per_minute": settings.rate_limit_per_minute,
        "agent_status": "ready" if _assistant is not None else "not_initialized",
    }


# ─────────────────────────────────────────────────────────
# Graceful Shutdown
# ─────────────────────────────────────────────────────────
def _handle_signal(signum, _frame):
    logger.info(json.dumps({"event": "SIGTERM_received", "signum": signum}))

signal.signal(signal.SIGTERM, _handle_signal)


if __name__ == "__main__":
    logger.info(f"Starting {settings.app_name} on {settings.host}:{settings.port}")
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        timeout_graceful_shutdown=30,
    )
