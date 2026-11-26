"""
Rate limiting (tiêu chí 7) — sliding window 60 giây bằng Redis sorted set.

Mỗi API key có một sorted set: member = 1 request, score = thời điểm (epoch giây).
Trong MỘT transaction (MULTI/EXEC) ta:
  1. ZREMRANGEBYSCORE — xoá request cũ hơn 60 giây
  2. ZADD            — thêm request hiện tại
  3. ZCARD           — đếm số request trong cửa sổ
  4. EXPIRE          — key tự hết hạn khi không còn dùng
Nếu đếm được > giới hạn: xoá lại request vừa thêm (không tính request bị từ chối) và trả 429.

Vì state nằm trong Redis nên mọi worker / instance dùng chung, và vẫn còn sau khi restart agent.
"""
import hashlib
import time
import uuid

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60


def _bucket(key: str) -> str:
    # Lưu hash của API key, không lưu key thật trong Redis
    return "ratelimit:" + hashlib.sha256(key.encode()).hexdigest()[:24]


def check_rate_limit(key: str) -> None:
    limit = settings.rate_limit_per_minute
    bucket = _bucket(key)
    now = time.time()
    member = f"{now:.6f}-{uuid.uuid4().hex[:8]}"
    try:
        pipe = r.pipeline(transaction=True)
        pipe.zremrangebyscore(bucket, 0, now - WINDOW_SECONDS)
        pipe.zadd(bucket, {member: now})
        pipe.zcard(bucket)
        pipe.expire(bucket, WINDOW_SECONDS)
        _, _, count, _ = pipe.execute()

        if count > limit:
            r.zrem(bucket, member)
            oldest = r.zrange(bucket, 0, 0, withscores=True)
            retry_after = int(oldest[0][1] + WINDOW_SECONDS - now) + 1 if oldest else WINDOW_SECONDS
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded: {limit} requests / {WINDOW_SECONDS}s",
                headers={"Retry-After": str(max(1, retry_after))},
            )
    except redis.RedisError:
        # Không đọc được state → không biết còn quota hay không → từ chối an toàn (503)
        raise HTTPException(status_code=503, detail="Rate limiter unavailable")
