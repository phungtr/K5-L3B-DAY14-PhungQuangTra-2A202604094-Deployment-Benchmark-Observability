# ============================================================
# Production Dockerfile — multi-stage (tiêu chí 1)
#   Stage 1 (builder): tạo virtualenv và cài dependencies
#   Stage 2 (runtime): chỉ copy virtualenv + code, chạy bằng user non-root
# Build từ thư mục 06-lab-complete:  docker build -t day14-agent .
# ============================================================

# ---------- Stage 1: builder ----------
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build
# Copy requirements trước code → layer cài dependencies được cache khi chỉ sửa code
COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install -r requirements.txt

# ---------- Stage 2: runtime ----------
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PORT=8000

# User không có quyền root
RUN groupadd --system app && useradd --system --gid app --no-create-home app

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY app/ ./app/
COPY utils/ ./utils/

USER app
EXPOSE 8000

# Docker tự đánh dấu container unhealthy nếu /health không trả lời
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT', '8000'), timeout=3)" || exit 1

# `exec` thay sh bằng uvicorn → uvicorn là PID 1, nhận trực tiếp SIGTERM khi `docker stop`.
# Nghe theo biến PORT do Railway / Render cấp, mặc định 8000.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2"]
