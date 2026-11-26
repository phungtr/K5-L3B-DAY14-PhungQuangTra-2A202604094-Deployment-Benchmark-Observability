"""
Kết nối Redis dùng chung cho rate limiter và cost guard.

- redis.from_url() chỉ tạo connection pool, KHÔNG kết nối ngay lúc import,
  nên app vẫn khởi động được khi Redis chưa sẵn sàng (/health vẫn 200).
- Timeout ngắn để /ready trả 503 nhanh khi Redis chết, thay vì treo request.
"""
import redis

from app.config import settings

r = redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=2,
    socket_timeout=2,
)


def redis_healthy() -> bool:
    """Dùng cho GET /ready: ping được Redis → True, lỗi kết nối / timeout → False."""
    try:
        return bool(r.ping())
    except redis.RedisError:
        return False
