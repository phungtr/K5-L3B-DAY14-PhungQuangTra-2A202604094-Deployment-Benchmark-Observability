"""
API Key authentication (tiêu chí 6).

- Client gửi header  X-API-Key: <key>
- Key phải trùng biến môi trường AGENT_API_KEY
- Thiếu hoặc sai key → HTTP 401

APIKeyHeader(auto_error=False): khi thiếu header FastAPI không tự trả 403/422,
mà trả None để ta tự quyết định trả 401.
"""
import hmac

from fastapi import HTTPException, Security
from fastapi.security.api_key import APIKeyHeader

from app.config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(api_key: str | None = Security(api_key_header)) -> str:
    """Dependency cho FastAPI — dùng trong /ask: Depends(verify_api_key)."""
    expected = settings.agent_api_key
    # compare_digest so sánh thời gian hằng → không lộ key qua timing attack.
    # expected rỗng (chưa cấu hình key) → từ chối tất cả.
    if not api_key or not expected or not hmac.compare_digest(api_key.encode(), expected.encode()):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return api_key
