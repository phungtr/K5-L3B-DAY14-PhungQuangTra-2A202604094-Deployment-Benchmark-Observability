"""
Config — 12-Factor: mọi cấu hình đọc từ biến môi trường.

Mỗi giá trị có default hợp lý để chạy local; trên Railway / Render các biến này được đặt
trong dashboard của nền tảng. Không có secret nào nằm trong code: AGENT_API_KEY mặc định rỗng,
khi rỗng thì mọi request /ask đều bị từ chối (401).
"""
import os
from dataclasses import dataclass, field


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


@dataclass
class Settings:
    # Server
    port: int = field(default_factory=lambda: _int("PORT", 8000))
    environment: str = field(default_factory=lambda: os.getenv("ENVIRONMENT", "development"))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper())

    # Security
    agent_api_key: str = field(default_factory=lambda: os.getenv("AGENT_API_KEY", ""))

    # State (rate limit + cost guard) nằm trong Redis để mọi worker / instance dùng chung
    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379/0"))

    # Giới hạn
    rate_limit_per_minute: int = field(default_factory=lambda: _int("RATE_LIMIT_PER_MINUTE", 10))
    daily_budget_usd: float = field(default_factory=lambda: _float("DAILY_BUDGET_USD", 1.0))
    monthly_budget_usd: float = field(default_factory=lambda: _float("MONTHLY_BUDGET_USD", 10.0))

    # LLM (mock)
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "mock-llm"))


settings = Settings()
