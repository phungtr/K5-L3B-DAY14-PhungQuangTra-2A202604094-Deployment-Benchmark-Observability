# Day 14 Lab — Mission Answers

> Bài cá nhân · K5 · Day 14 — Deployment, Benchmark & Observability
> Môi trường chạy: Windows 11 + WSL2 (Ubuntu 24.04, Python 3.12.3) + Docker Desktop 4.55 (Engine 29.1.3)

---

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns trong `01-localhost-vs-production/develop/app.py`

| # | Anti-pattern | Dòng | Hậu quả |
|---|---|---|---|
| 1 | API key hardcode: `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"` | 17 | Push code lên GitHub là lộ key. Muốn đổi key phải sửa code rồi deploy lại |
| 2 | Mật khẩu database nằm trong code: `DATABASE_URL = "postgresql://admin:password123@..."` | 18 | Lộ thông tin đăng nhập DB; dev và production bị buộc dùng chung một chuỗi kết nối |
| 3 | Config cứng, không đọc từ môi trường: `DEBUG = True`, `MAX_TOKENS = 500` | 21–22 | Muốn đổi cấu hình giữa dev / staging / production phải sửa code |
| 4 | Dùng `print()` thay cho logging, và **in cả secret ra log**: `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` | 33–34, 38 | Log không có level, không có thời gian, khó lọc và tìm kiếm. Key lọt vào mọi hệ thống thu thập log |
| 5 | Không có health check endpoint | 42–43 | Platform không biết app còn sống hay đã treo để restart hoặc ngừng gửi traffic. Đã kiểm chứng ở Exercise 1.2: `GET /health` trả **404** |
| 6 | Port cố định `port=8000` | 52 | Railway / Render cấp cổng qua biến `PORT`; app nghe sai cổng thì health check của platform thất bại |
| 7 | Bind `host="localhost"` | 51 | Trong container, app chỉ nhận kết nối từ chính container đó; từ bên ngoài không gọi được |
| 8 | `reload=True` luôn bật | 53 | Reload là tính năng cho dev: theo dõi file, chạy thêm process giám sát, tốn tài nguyên và có thể restart app ngoài ý muốn |
| 9 | Không có xử lý khi tắt (không có `lifespan` / shutdown hook để dọn dẹp, đóng kết nối) | cả file | Khi deploy bản mới hoặc scale down, tài nguyên không được đóng gọn |
| 10 | Nhận `question` qua query string, không giới hạn độ dài | 30–31 | Câu hỏi của người dùng nằm trong URL nên lọt vào access log / proxy log; không giới hạn độ dài thì có thể gửi prompt rất dài, tốn tiền LLM |

### Exercise 1.2: Chạy bản develop

```text
$ cd 01-localhost-vs-production/develop
$ pip install -r requirements.txt
$ python app.py

# Terminal thứ hai:
$ curl -X POST "http://localhost:8000/ask?question=Hello"
{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}

$ curl -i http://localhost:8000/health
HTTP/1.1 404 Not Found
date: Thu, 26 Nov 2026 07:50:16 GMT
server: uvicorn
content-length: 22
content-type: application/json

{"detail":"Not Found"}
```

**Nhận xét:** app chạy và trả lời được, nhưng chưa sẵn sàng cho production: không có `/health` (404), mỗi request đều in API key ra log (dòng 34), chỉ nghe trên `localhost:8000`. Bản develop nhận `question` qua query string; gửi JSON sẽ bị 422.

### Exercise 1.3: So sánh develop và production

**Chạy bản production:**

```text
$ cd ../production
$ cp .env.example .env
$ pip install -r requirements.txt
$ python app.py

$ curl -w '\n' http://localhost:8000/health
{"status":"ok","uptime_seconds":23.8,"version":"1.0.0","environment":"development","timestamp":"2026-11-26T07:53:58.705994+00:00"}
$ curl -w '\n' http://localhost:8000/ready
{"ready":true}
$ curl -w '\n' -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question": "Hello"}'
{"question":"Hello","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.","model":"gpt-4o-mini"}
```

Log của server lúc đó:

```text
WARNING:root:OPENAI_API_KEY not set — using mock LLM
INFO:     Started server process [911]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     127.0.0.1:32946 - "GET /health HTTP/1.1" 200 OK
INFO:     127.0.0.1:32948 - "GET /ready HTTP/1.1" 200 OK
INFO:     127.0.0.1:32956 - "POST /ask HTTP/1.1" 200 OK
```

**Thử tắt bằng SIGTERM** (tín hiệu mà Docker / Railway / Render gửi khi tắt container). `timeout` gửi SIGTERM sau 6 giây:

```text
$ PORT=8011 timeout --preserve-status -s TERM 6 python app.py &
$ curl -w '\n' -X POST http://localhost:8011/ask -H 'Content-Type: application/json' -d '{"question":"Hello"}'
{"question":"Hello","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.","model":"gpt-4o-mini"}

# log server
INFO:     127.0.0.1:56984 - "POST /ask HTTP/1.1" 200 OK
INFO:     Shutting down
INFO:     Waiting for application shutdown.
INFO:     Application shutdown complete.
INFO:     Finished server process [1076]

exit code sau SIGTERM: 0
```

**Bảng so sánh:**

| Feature | Develop | Production | Tại sao quan trọng? |
|---|---|---|---|
| Config | Hardcode trong code (dòng 17–22) | `config.py` đọc mọi giá trị bằng `os.getenv(...)` có giá trị mặc định (config.py dòng 17–35); `.env.example` làm mẫu | Cùng một bản build chạy được ở dev / staging / production, chỉ cần đổi biến môi trường. Đổi cấu hình không phải sửa code. Secret không nằm trong git |
| Secrets | Key và mật khẩu DB nằm trong code, key còn bị in ra log | Đọc từ biến môi trường. Thiếu `AGENT_API_KEY` khi `ENVIRONMENT=production` thì dừng ngay lúc khởi động (config.py dòng 42–43). Log không chứa secret | Repo public bị bot quét lấy key chỉ trong vài phút. Log được gửi tới nhiều hệ thống và nhiều người đọc được |
| Host / Port | `localhost:8000` cố định | `HOST=0.0.0.0`, `PORT` lấy từ môi trường (config.py dòng 17–18, app.py dòng 196–197) | Container phải bind `0.0.0.0` mới nhận được traffic từ bên ngoài. Cloud cấp `PORT` động cho từng service |
| Health check | Không có: `GET /health` trả **404** | `/health` (liveness) và `/ready` (readiness) (app.py dòng 135–161). Đã gọi được: 200 và `{"ready":true}`. `/ready` ở bản này chỉ dựa vào cờ `is_ready`: bật ở dòng 58 khi khởi động xong, tắt ở dòng 64 khi bắt đầu tắt | Platform dựa vào `/health` để restart app bị treo. Load balancer dựa vào `/ready` để chỉ gửi traffic tới instance đã sẵn sàng: đang khởi động hoặc đang tắt thì tạm không nhận |
| Logging | `print()`, không có level, in cả secret | Dự định: log JSON qua `logging` (app.py dòng 28–31, 111–122), chỉ ghi độ dài câu hỏi, không ghi secret. **Thực tế có 2 lỗi** (xem ghi chú bên dưới): khi chạy không thấy dòng log nào của app, và kể cả khi in ra được thì dòng log cũng **không phải JSON hợp lệ** | Log có cấu trúc thì máy parse, lọc, đếm được (Loki, Datadog...). Phải chạy thử và parse thử log, không chỉ đọc code |
| Shutdown | Không có xử lý khi tắt | Hai cơ chế riêng. (1) `lifespan` (dòng 39–67): phần sau `yield` (dòng 63–67) chạy khi uvicorn tắt, đặt `is_ready = False` rồi dọn dẹp. (2) Handler SIGTERM `handle_sigterm` (dòng 180–189): chỉ ghi log (log này cũng bị mất do lỗi logging), **không** tự tắt app. Việc tắt an toàn do uvicorn làm: trong lúc chạy, uvicorn thay handler này bằng handler của nó, tắt xong mới gọi lại handler cũ. Kết quả thử: có handler thì **exit code 0**; bỏ handler thì vẫn tắt êm nhưng **exit code 143** (test C) | Khi deploy bản mới hoặc scale down, platform gửi SIGTERM. Tắt an toàn giúp request đang xử lý được trả lời xong và kết nối được đóng gọn. Exit code khác 0 khiến platform và hệ thống giám sát hiểu là app thoát do lỗi (phần `docker stop` của script chấm Part 6 yêu cầu exit code 0: `check_production_ready.py` dòng 824) |
| Reload | `reload=True` luôn bật | Chỉ bật khi `DEBUG=true` (app.py dòng 198) | Reload chỉ dành cho lúc code; trong production nó tốn thêm process và có thể restart app ngoài ý muốn |
| Input | `question` qua query string, không kiểm tra | Nhận JSON body (dòng 103–108): thiếu hoặc rỗng `question` thì trả **422** rõ ràng. Nhưng JSON hỏng thì trả **500** Internal Server Error, vì lỗi của `await request.json()` (dòng 104) không được bắt; client chỉ thấy `Internal Server Error`, không lộ stack trace. Và vẫn chưa giới hạn độ dài: câu hỏi 10.000 ký tự vẫn trả 200 (test A) | Input sai là lỗi của client, phải trả mã 4xx rõ ràng; trả 500 làm hệ thống báo lỗi server giả và che mất lỗi thật. Giới hạn độ dài để chặn prompt quá dài làm tốn tiền LLM. Câu hỏi không lọt vào URL và access log |

**Ghi chú về Logging — lỗi tìm ra khi chạy thử:** bản production định ghi log JSON, nhưng khi chạy chỉ thấy `WARNING:root:OPENAI_API_KEY not set — using mock LLM` và log của uvicorn, không có dòng `{"event": ...}` nào. Nguyên nhân:

1. `app.py` dòng 24 import `config` **trước** khi gọi `logging.basicConfig` ở dòng 28.
2. Trong lúc import, `config.py` dòng 45 gọi `logging.warning(...)` vì thiếu `OPENAI_API_KEY`. Python liền tự cấu hình logging mặc định (chính là dòng `WARNING:root:...`).
3. Đến dòng 28, `basicConfig` không làm gì nữa, vì nó chỉ có tác dụng khi logging chưa được cấu hình. Level vẫn là WARNING nên mọi `logger.info(...)` bị bỏ qua mà không báo lỗi.

Cách sửa: `logging.basicConfig(..., force=True)`, hoặc cấu hình logging trước khi import `config`. Đã tái hiện lỗi bằng một script nhỏ cùng thứ tự gọi: dòng INFO không được in, level của root logger vẫn là `WARNING`.

**Lỗi thứ hai — dòng log không phải JSON hợp lệ:** format ở dòng 30 là `{"time":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}`, còn message lại là chuỗi `json.dumps(...)` (dòng 49–55, 111–115, 119–122). Chuỗi JSON bị nhét vào giữa hai dấu nháy mà không escape, nên dòng log thành `"msg":"{"event": ...}"` và parser báo lỗi (test D bên dưới). Cách đúng: gom mọi trường vào một dict rồi `json.dumps` cả dòng, ví dụ tự viết một `logging.Formatter`.

**Ghi chú về `.env`:** lệnh `cp .env.example .env` không có tác dụng với bản này, vì code không gọi `load_dotenv()`; mọi giá trị đều lấy từ mặc định trong `config.py`. "Đọc từ biến môi trường" khác với "đọc file `.env`": muốn dùng file `.env` phải nạp nó vào môi trường trước (ví dụ `env_file` trong Docker Compose, hoặc `set -a; source .env; set +a`).

**Kiểm tra thêm** (chạy bản production ở cổng 8012 và 8013):

- Test A: gửi `{}`, gửi JSON hỏng `{"question": `, gửi câu hỏi dài 10.000 ký tự.
- Test B: `ENVIRONMENT=production python app.py` mà không đặt `AGENT_API_KEY`.
- Test C: chép `app.py`, `config.py`, `utils/` ra một thư mục tạm, comment dòng 189 (`signal.signal(signal.SIGTERM, handle_sigterm)`), chạy `PORT=8013 timeout --preserve-status -s TERM 6 python app.py` rồi gửi 1 request. Code mẫu trong repo không bị sửa.
- Test D: dựng một dòng log bằng đúng format ở dòng 30, với message là `json.dumps(...)`, rồi thử `json.loads` dòng đó.

```text
===== TEST A: input sai (cổng 8012) =====
>>> A1. body {} (thiếu question)
HTTP/1.1 422 Unprocessable Entity
date: Thu, 26 Nov 2026 08:21:46 GMT
server: uvicorn
content-length: 39
content-type: application/json

{"detail":"question field is required"}
>>> A2. JSON hỏng: {"question": 
HTTP/1.1 500 Internal Server Error
date: Thu, 26 Nov 2026 08:21:46 GMT
server: uvicorn
content-length: 21
content-type: text/plain; charset=utf-8

Internal Server Error
>>> A3. câu hỏi dài 10000 ký tự -> mã HTTP:
200
--- log server lúc nhận JSON hỏng ---
INFO:     127.0.0.1:60542 - "POST /ask HTTP/1.1" 422 Unprocessable Entity
INFO:     127.0.0.1:60552 - "POST /ask HTTP/1.1" 500 Internal Server Error
ERROR:    Exception in ASGI application
    raise JSONDecodeError("Expecting value", s, err.value) from None
json.decoder.JSONDecodeError: Expecting value: line 1 column 14 (char 13)
INFO:     127.0.0.1:60554 - "POST /ask HTTP/1.1" 200 OK

===== TEST B: ENVIRONMENT=production, không đặt AGENT_API_KEY =====
exit code: 1
ValueError: AGENT_API_KEY must be set in production!

===== TEST C: SIGTERM khi bỏ handler (bản sao, cổng 8013) =====
189:# DA BO HANDLER: signal.signal(signal.SIGTERM, handle_sigterm)
POST /ask -> 200
exit code sau SIGTERM (không có handler): 143
INFO:     Shutting down
INFO:     Waiting for application shutdown.
INFO:     Application shutdown complete.
INFO:     Finished server process [1594]

===== TEST D: dòng log theo format của app.py có phải JSON hợp lệ? =====
{"time":"2026-11-26 15:22:03,565","level":"INFO","msg":"{"event": "agent_request", "question_length": 5, "client_ip": "127.0.0.1"}"}
=> KHÔNG phải JSON hợp lệ: Expecting ',' delimiter: line 1 column 59 (char 58)
```

Nhận xét:

- **Test A:** thiếu field thì trả 422 đúng, nhưng JSON hỏng lại trả 500. Stack trace chỉ nằm trong log server, client không thấy.
- **Test B:** thiếu `AGENT_API_KEY` ở production thì app dừng ngay lúc khởi động (exit code 1). Đây là kiểu "fail fast": lỗi cấu hình lộ ra lúc deploy, không đợi tới lúc có người gọi API.
- **Test C:** so với lần thử có handler ở trên (exit code 0), thấy rõ việc tắt an toàn là do uvicorn, còn handler chỉ quyết định exit code cuối cùng. Uvicorn tắt xong thì gửi lại SIGTERM cho chính process; không có handler thì tín hiệu đó kết thúc process, ra 143 = 128 + 15 (15 là số của SIGTERM). Chạy lại lần nữa vẫn ra: không có handler 143, có handler 0. Phiên bản dùng khi thử: uvicorn 0.30.0 (`pip show uvicorn`); đoạn code gửi lại tín hiệu nằm ở `uvicorn/server.py` dòng 318–328.
- **Script chấm Part 6** kiểm tra tắt an toàn ở 2 chỗ. Mục 2 (Runtime) chỉ yêu cầu process tự thoát trong 20 giây và request đang chạy vẫn trả 200; exit code chỉ được in ra, không bắt buộc là 0 (`check_production_ready.py` dòng 756). Phần Docker yêu cầu `docker stop` cho exit code 0 và xong trong dưới 10 giây (dòng 824).

### Tự kiểm tra (CP1): một anti-pattern đã được bản production sửa

- **Port cố định:** develop `app.py` dòng 52 `port=8000` → production `config.py` dòng 18 `port: int = field(default_factory=lambda: int(os.getenv("PORT", "8000")))`, được dùng ở production `app.py` dòng 197 `port=settings.port`.
- **Health check:** develop không có (`GET /health` → 404) → production `app.py` dòng 135–149 `@app.get("/health")`.

---

## Part 2: Docker

### Exercise 2.1: Câu hỏi về `02-docker/develop/Dockerfile`

1. Base image:
2. Working directory:
3. Tại sao `COPY requirements.txt` trước `COPY` code:
4. CMD khác ENTRYPOINT thế nào:

### Exercise 2.2: Build và chạy bản develop

_(dán lệnh build, lệnh chạy container và kết quả gọi `/ask`, `/health`)_

### Exercise 2.3: Multi-stage build và kích thước image

- Stage 1 làm gì:
- Stage 2 làm gì:
- Tại sao image nhỏ hơn:

| Image | Kích thước (đo bằng `docker images`) |
|---|---|
| `my-agent:develop` | ___ MB |
| `my-agent:advanced` | ___ MB |
| Chênh lệch | ___ % |

### Exercise 2.4: Docker Compose stack

_(sơ đồ các service, service nào được start, giao tiếp với nhau thế nào, kết quả test qua Nginx)_

---

## Part 3: Cloud Deployment

### Exercise 3.1 / 3.2: Deploy agent Part 6

- Nền tảng:
- URL public:
- Ảnh: [dashboard](screenshots/dashboard.png) · [running](screenshots/running.png) · [test](screenshots/test.png)

### So sánh `railway.toml` và `render.yaml`

_(khác nhau chỗ nào, vì sao)_

### Exercise 3.3: Pipeline CI/CD trên Cloud Run

_(3–5 dòng mô tả các bước trong `cloudbuild.yaml` và `service.yaml`)_

---

## Part 4: API Security

### Exercise 4.1: API key authentication

_(API key được kiểm tra ở đâu, sai key thì sao, rotate key thế nào; output `curl -i` 401 và 200)_

### Exercise 4.2: JWT authentication

_(luồng JWT; output lấy token — che token trước khi dán)_

### Exercise 4.3: Rate limiting

_(thuật toán, giới hạn bao nhiêu request/phút, cách bypass cho admin; output `curl -i` có 429)_

### Exercise 4.4: Cost guard

_(giải thích cách làm)_

---

## Part 5: Scaling & Reliability

### Exercise 5.1–5.5

_(liveness vs readiness, graceful shutdown, stateless; kết quả `docker compose -p k5-day14-scaling up -d --build --scale agent=3` và `python test_stateless.py`)_

---

## Part 6: Final Project — output `check_production_ready.py`

Chạy đầy đủ (có Docker) trong WSL2 Ubuntu, tại thư mục `06-lab-complete/`:

```text
$ python check_production_ready.py
...
================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

Một số dòng chi tiết trong cùng lần chạy:

```text
✅ Docker: build image thành công — 72s
✅ Docker: image < 500 MB — 63 MB
✅ Khi chạy: vượt giới hạn → 429 — 429 sau 5 request thành công (RATE_LIMIT_PER_MINUTE=5)
✅ Khi chạy: state nằm trong Redis — restart agent vẫn bị 429
✅ Khi chạy: Redis mất kết nối → /ready 503 (còn /health vẫn 200)
✅ Khi chạy: hết budget → 402 — 402 ở request thứ 1
✅ Khi chạy: mọi dòng log của app là JSON hợp lệ — 17 dòng JSON
✅ Khi chạy: SIGTERM lúc đang có request → request vẫn 200, process tự thoát — exit code 0
✅ Docker: `docker stop` tắt êm (exit code 0, < 10s) — exit code 0, 0.9s
```

**Cách làm từng phần** (code trong `06-lab-complete/`):

| Phần | File | Cách làm |
|---|---|---|
| Config | `app/config.py` | Mọi giá trị đọc bằng `os.getenv` có giá trị mặc định. `AGENT_API_KEY` mặc định rỗng, khi rỗng thì mọi request `/ask` đều bị từ chối |
| API key | `app/auth.py` | `APIKeyHeader(auto_error=False)` để tự trả 401 (không phải 403 hay 422); so sánh key bằng `hmac.compare_digest` |
| Rate limit | `app/rate_limiter.py` | Sliding window 60 giây bằng Redis sorted set, chạy trong một transaction: ZREMRANGEBYSCORE → ZADD → ZCARD → EXPIRE. Vượt giới hạn thì xoá request vừa thêm, trả 429 kèm `Retry-After`. Key trong Redis là hash của API key |
| Cost guard | `app/cost_guard.py` | Cộng dồn chi phí (ước lượng khoảng 4 ký tự / token) vào Redis theo ngày và theo tháng bằng `INCRBYFLOAT`. Đạt `DAILY_BUDGET_USD` hoặc `MONTHLY_BUDGET_USD` thì trả 402 |
| Redis | `app/redis_client.py` | `redis.from_url` không kết nối lúc import nên app vẫn khởi động khi Redis chết; timeout 2 giây để `/ready` trả 503 nhanh |
| Health / Ready | `app/main.py` | `/health` không phụ thuộc Redis. `/ready` trả 503 khi chưa khởi động xong, đang tắt, hoặc ping Redis lỗi |
| Logging | `app/main.py` | `JsonFormatter` gom các trường vào một dict rồi `json.dumps` cả dòng; `basicConfig(force=True)` để tránh đúng lỗi đã gặp ở Part 1 |
| Tắt an toàn | `app/main.py` | `lifespan` dọn dẹp sau `yield`. Handler SIGTERM chỉ ghi log rồi gọi lại handler cũ của uvicorn |
| Docker | `Dockerfile` | 2 stage: builder tạo venv `/opt/venv`; runtime `python:3.11-slim` chỉ copy venv và code, chạy bằng user `app`, có `HEALTHCHECK`, `CMD` là `exec uvicorn ... --port ${PORT:-8000} --workers 2` để uvicorn là PID 1 |

**Vì sao "402 ở request thứ 1":** cost guard tính tổng chi phí của cả agent trong ngày. Các lần chạy trước trong cùng bài kiểm tra (budget 1000 USD) đã ghi chi phí vào cùng Redis, nên khi budget hạ xuống 0.000001 USD thì tổng đã vượt ngay từ request đầu tiên.

---

## AI log

| Lần | Phần | Tôi hỏi AI gì | AI trả lời / đã làm gì | Tôi tự sửa và tự kiểm tra thế nào |
|---|---|---|---|---|
| 1 | Tổng quan | Đọc đề, liệt kê việc cần làm để hoàn thành lab | Claude Code (Claude Opus 5.5) tóm tắt rubric, checkpoint, file phải nộp và các lỗi bị trừ điểm | Đối chiếu với `RUBRIC.md`, `CHECKPOINTS.md`, `SUBMISSION.md` |
| 2 | Môi trường | Cài môi trường chạy lab trên Windows | Hướng dẫn cài WSL2 Ubuntu 24.04 và venv Python; tạo user Linux; tìm ra lỗi Docker WSL integration (thiếu `backend.sock` sau khi `wsl --terminate`) và cách khởi động lại | Tự chạy lệnh kiểm tra: `os.name` in `posix`, `docker run --rm hello-world` chạy được |
| 3 | Part 1 | Nhờ tắt server và viết mục Part 1 | AI gửi SIGTERM tắt server, chạy thêm một lần thử SIGTERM ở cổng 8011 để lấy log và exit code, tìm ra lỗi thứ tự logging trong `production/app.py`, viết nháp Part 1 từ output tôi đã chạy | Tự chạy các lệnh curl của 1.2 và 1.3. Đọc lại bản nháp, đối chiếu từng số dòng với code: khớp hết |
| 4 | Part 1 | Đưa danh sách góp ý cho bản nháp: sửa hàng Input (JSON hỏng trả 500, chưa giới hạn độ dài), hàng Health check (bỏ vế DB ở `/ready`), hàng Shutdown (tách `lifespan` và handler SIGTERM); thêm ý log không phải JSON hợp lệ; chạy test 422/500, `ENVIRONMENT=production` và SIGTERM khi bỏ handler | AI chạy 4 test (A–D) trên máy tôi; test bỏ handler chạy trên bản sao trong thư mục tạm, không sửa code mẫu. AI sửa 3 hàng của bảng 1.3 và ghi chú logging theo góp ý, dán output test vào bài | Xem dòng 5 |
| 5 | Part 1 | Nhờ AI làm 3 việc kiểm tra: chạy lại test A2 và C rồi so với bài; xem `check_production_ready.py` có thật sự kiểm tra exit code 0 không; chạy `pip show uvicorn` để ghi version | AI chạy lại: A2 vẫn trả 500; C ra 143 khi không có handler và 0 khi có handler, khớp với bài. AI đọc script: mục 2 Runtime không bắt buộc exit code 0 (dòng 756), phần Docker thì bắt buộc (dòng 824), nên sửa lại câu trong hàng Shutdown. `pip show uvicorn` cho 0.30.0, đã ghi vào nhận xét test C | _(Tự mở script ở dòng 756 và 824, thấy Runtime chỉ cần process tự thoát, còn Docker đòi exit code 0.)_ |
| 6 | Part 6 | Nhờ AI làm hoàn chỉnh bài lab, bắt đầu từ Part 6 | AI viết code cho 12 file của `06-lab-complete/` (6 file trong `app/`, `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.env.example`, `railway.toml`, `render.yaml`); cài thư viện và `redis-server` trong WSL; chạy `check_production_ready.py` bản đầy đủ: PASS 12/12, 43/43 checks | _(TODO: đọc hiểu từng file trong `06-lab-complete/app/` vì Lab Coach có thể hỏi bất kỳ dòng nào; tự chạy lại `python check_production_ready.py`)_ |
