"""
Production AI Agent — Part 6 Final Project.

Chạy:     uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2
Kiểm tra: python check_production_ready.py

Luồng của POST /ask:
  verify_api_key (401) → check_rate_limit (429) → check_budget (402) → gọi LLM → record_cost
"""
import json
import logging
import signal
import sys
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, estimate_tokens, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import r, redis_healthy
from utils.mock_llm import ask as llm_ask


# ─────────────────────────────────────────────────────────
# Structured logging (tiêu chí 10): mỗi dòng log của app = 1 JSON object hợp lệ
# ─────────────────────────────────────────────────────────
class JsonFormatter(logging.Formatter):
    """Gom mọi trường vào một dict rồi json.dumps cả dòng — không nhét chuỗi JSON vào trong chuỗi."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "lvl": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            entry.update(fields)
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(JsonFormatter())
# force=True: thay mọi cấu hình logging có sẵn. Nếu không, basicConfig sẽ bị bỏ qua khi root logger
# đã có handler (đúng lỗi đã gặp ở bản production của Part 1).
logging.basicConfig(level=settings.log_level, handlers=[_handler], force=True)
logger = logging.getLogger("agent")


def log_event(event: str, level: int = logging.INFO, **fields) -> None:
    logger.log(level, event, extra={"fields": fields})


# ─────────────────────────────────────────────────────────
# Lifecycle: startup / graceful shutdown (tiêu chí 11)
# ─────────────────────────────────────────────────────────
START_TIME = time.monotonic()
_state = {"ready": False}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    if not settings.agent_api_key:
        if settings.environment == "production":
            raise RuntimeError("AGENT_API_KEY must be set in production")
        log_event("config_warning", logging.WARNING,
                  detail="AGENT_API_KEY chưa đặt: mọi request /ask sẽ bị 401")
    redis_ok = await run_in_threadpool(redis_healthy)   # chỉ để ghi log, không chặn khởi động
    _state["ready"] = True
    log_event("startup", environment=settings.environment, port=settings.port, redis_ok=redis_ok,
              rate_limit_per_minute=settings.rate_limit_per_minute,
              daily_budget_usd=settings.daily_budget_usd, monthly_budget_usd=settings.monthly_budget_usd)

    yield

    # Shutdown: uvicorn chỉ chạy tới đây sau khi đã ngừng nhận request mới
    # và các request đang xử lý đã trả lời xong.
    _state["ready"] = False
    log_event("shutdown", uptime_seconds=round(time.monotonic() - START_TIME, 1))
    try:
        r.close()
    except Exception:
        pass


_previous_sigterm = None


def _on_sigterm(signum, frame):
    """Ghi log + đánh dấu not-ready, rồi trả quyền cho handler cũ (của uvicorn).

    Không gọi lại handler cũ thì uvicorn không bao giờ biết phải tắt.
    """
    _state["ready"] = False
    log_event("sigterm_received")
    if callable(_previous_sigterm):
        _previous_sigterm(signum, frame)
    elif _previous_sigterm == signal.SIG_DFL:
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        signal.raise_signal(signal.SIGTERM)


if threading.current_thread() is threading.main_thread():
    _previous_sigterm = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, _on_sigterm)


app = FastAPI(title="Production AI Agent", version="1.0.0", lifespan=lifespan)


# ─────────────────────────────────────────────────────────
# Middleware: log mỗi request bằng JSON + chặn lộ stack trace
# ─────────────────────────────────────────────────────────
@app.middleware("http")
async def request_log(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", "")[:64] or uuid.uuid4().hex[:16]
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        # Lỗi không lường trước: log đầy đủ (kèm stack trace) nhưng client chỉ nhận thông báo chung
        logger.exception("unhandled_error", extra={"fields": {"request_id": request_id,
                                                              "path": request.url.path}})
        response = JSONResponse(status_code=500,
                                content={"detail": "Internal server error", "request_id": request_id})
    response.headers["X-Request-ID"] = request_id
    log_event("request", method=request.method, path=request.url.path, status=response.status_code,
              ms=round((time.perf_counter() - started) * 1000, 1), request_id=request_id)
    return response


# ─────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────
class AskRequest(BaseModel):
    # Body sai kiểu, thiếu field, JSON hỏng hay câu hỏi quá dài → FastAPI tự trả 422 kèm lý do rõ ràng
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = Field(default=None, max_length=64)


@app.get("/")
def root():
    return {"app": "Production AI Agent", "environment": settings.environment,
            "endpoints": ["/health", "/ready", "POST /ask"]}


@app.get("/health")
def health():
    """Liveness (tiêu chí 4): process còn chạy là 200 — không phụ thuộc Redis."""
    return {"status": "ok", "uptime_seconds": round(time.monotonic() - START_TIME, 1),
            "environment": settings.environment}


@app.get("/ready")
def ready():
    """Readiness (tiêu chí 5): 200 khi đã khởi động xong, chưa bắt đầu tắt và Redis kết nối được."""
    if not _state["ready"]:
        raise HTTPException(status_code=503, detail="Not ready: starting up or shutting down")
    if not redis_healthy():
        raise HTTPException(status_code=503, detail="Not ready: Redis not reachable")
    return {"status": "ready"}


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    check_rate_limit(api_key)          # vượt RATE_LIMIT_PER_MINUTE → 429 (tiêu chí 7)
    check_budget()                     # hết budget → 402 (tiêu chí 8)

    started = time.perf_counter()
    try:
        answer = llm_ask(body.question)
    except Exception:
        logger.exception("llm_error")
        raise HTTPException(status_code=502, detail="LLM upstream error")

    input_tokens, output_tokens = estimate_tokens(body.question), estimate_tokens(answer)
    cost = record_cost(input_tokens, output_tokens)
    log_event("ask", user_id=body.user_id, question_length=len(body.question),
              input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=round(cost, 8),
              llm_ms=round((time.perf_counter() - started) * 1000, 1))
    return {
        "question": body.question,
        "answer": answer,
        "model": settings.llm_model,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens,
                  "cost_usd": round(cost, 8)},
    }
