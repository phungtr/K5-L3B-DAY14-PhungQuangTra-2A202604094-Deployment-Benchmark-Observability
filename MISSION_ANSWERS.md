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

1. **Base image:** `python:3.11`. Đây là bản Python đầy đủ trên Debian, kèm compiler và nhiều công cụ, nên rất nặng.
2. **Working directory:** `/app`. Các lệnh `COPY`, `RUN`, `CMD` sau đó đều chạy trong thư mục này.
3. **Vì sao `COPY requirements.txt` trước khi copy code:** Docker cache theo từng layer. Chỉ cần `requirements.txt` không đổi thì layer `pip install` được dùng lại; sửa code chỉ làm build lại vài layer cuối, nên rất nhanh. Nếu `COPY . .` đứng trước, mỗi lần sửa một dòng code đều làm mất cache, phải cài lại toàn bộ thư viện.
4. **CMD khác ENTRYPOINT:** `CMD` là lệnh mặc định, bị thay thế khi chạy `docker run <image> <lệnh khác>`. `ENTRYPOINT` là chương trình cố định; tham số của `docker run` được nối thêm vào sau nó, muốn đổi phải dùng `--entrypoint`. Hay dùng kết hợp: `ENTRYPOINT ["uvicorn"]` cùng `CMD ["app:app", "--port", "8000"]`. Nên viết ở dạng exec (mảng JSON) để process là PID 1 và nhận được SIGTERM.

### Exercise 2.2: Build và chạy bản develop

Build từ gốc repo, vì Dockerfile `COPY` theo đường dẫn tính từ gốc. Bản develop nhận `question` qua query string.

```text
$ docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
build my-agent:develop OK (69s)
$ docker run --rm -d -p 8000:8000 --name agent-develop my-agent:develop
$ curl -X POST "http://localhost:8000/ask?question=What%20is%20Docker"
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
$ curl http://localhost:8000/health
{"status":"ok","uptime_seconds":0.7,"container":true}
$ docker ps
IMAGE              STATUS        PORTS
my-agent:develop   Up 1 second   0.0.0.0:8000->8000/tcp, [::]:8000->8000/tcp
```

### Exercise 2.3: Multi-stage build và kích thước image

- **Stage 1 (`builder`):** từ `python:3.11-slim`, cài thêm `gcc` và `libpq-dev` để build được thư viện cần compile, rồi `pip install --user` vào `/root/.local`. Stage này không được dùng để deploy.
- **Stage 2 (`runtime`):** bắt đầu lại từ một `python:3.11-slim` sạch, tạo user non-root `appuser`, chỉ copy `/root/.local` từ builder cùng `main.py` và `utils/`, thêm `HEALTHCHECK`, chạy uvicorn 2 worker.
- **Vì sao nhỏ hơn:** base `slim` không có compiler, tài liệu hay các gói hệ thống thừa. Compiler, cache của apt và pip chỉ nằm ở stage builder, không đi vào image cuối. Image cuối chỉ có Python runtime, thư viện và code.

```text
$ docker build -f 02-docker/production/Dockerfile -t my-agent:advanced .
build my-agent:advanced OK (99s)
$ docker images my-agent
IMAGE               ID             DISK USAGE   CONTENT SIZE   EXTRA
my-agent:advanced   f99da662cb99        240MB         57.4MB
my-agent:develop    27c3ea98d477       1.67GB          426MB
```

| Image | Disk usage (giải nén trên đĩa) | Content size (các layer nén, dung lượng phải tải) |
|---|---|---|
| `my-agent:develop` (single-stage, `python:3.11`) | 1.67 GB | 426 MB |
| `my-agent:advanced` (multi-stage, `python:3.11-slim`) | 240 MB | 57.4 MB |
| Chênh lệch | nhỏ hơn **85.6%** | nhỏ hơn **86.5%** |

Docker Engine 29 (containerd image store) in hai cột: `DISK USAGE` là dung lượng sau khi giải nén, `CONTENT SIZE` là tổng các layer nén. Cách tính: (1670 − 240) / 1670 = 85.6%; (426 − 57.4) / 426 = 86.5%.

### Exercise 2.4: Docker Compose stack

Chạy `docker compose -p k5-day14-docker up -d --build` trong `02-docker/production/`. `-p` để không trùng tên project với stack của Part 5 và Part 7. Trước đó cần `touch .env.local`.

```text
                    ┌──────────────── network "internal" (bridge) ────────────────┐
Client ──:80/:443──▶│ nginx ──proxy_pass agent:8000──▶ agent (FastAPI, 2 worker)    │
                    │  (rate limit 10 r/s,               │            │             │
                    │   security headers)  REDIS_URL redis:6379   QDRANT_URL qdrant:6333
                    │                                     ▼            ▼             │
                    │                                   redis        qdrant          │
                    │                              (volume redis_data) (volume qdrant_data)
                    └──────────────────────────────────────────────────────────────┘
```

- **Service được start:** `redis` và `qdrant` trước (có healthcheck). `agent` chỉ start khi cả hai đã healthy (`depends_on: condition: service_healthy`). `nginx` start sau `agent`.
- **Giao tiếp:** các service gọi nhau bằng tên service qua DNS của Docker trong network `internal`. Chỉ `nginx` mở cổng ra máy host (80, 443); `agent`, `redis`, `qdrant` không public.

```text
$ docker compose -p k5-day14-docker ps
SERVICE   IMAGE                   STATUS                                     PORTS
agent     k5-day14-docker-agent   Up Less than a second (health: starting)   8000/tcp
nginx     nginx:alpine            Up Less than a second                      0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
qdrant    qdrant/qdrant:v1.9.0    Up 11 seconds (healthy)                    6333-6334/tcp
redis     redis:7-alpine          Up 11 seconds (healthy)                    6379/tcp
$ curl http://localhost/health          # lần 1: 502 (agent chưa khởi động xong), curl tự thử lại:
{"status":"ok","uptime_seconds":0.8,"version":"2.0.0","timestamp":"2026-11-26T09:14:40.724436"}
$ curl http://localhost/ask -X POST -H "Content-Type: application/json" -d '{"question": "Explain microservices"}'
{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
$ curl -i http://localhost/health
HTTP/1.1 200 OK
Server: nginx
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
```

**Nhận xét:**
- Request đầu tiên bị **502** vì `nginx` chỉ `depends_on: agent` (chờ container start), không chờ agent healthy. Agent chưa nghe cổng 8000 thì Nginx không có upstream nào để gửi tới. Nên dùng `condition: service_healthy` cho cả `nginx`.
- Log của agent trong stack này cũng bị đúng lỗi "JSON lồng trong chuỗi" như ở Part 1: `{"time":"...","level":"INFO","msg":"{"event": "request", "q_len": 21}"}` không phải JSON hợp lệ.

---

## Part 3: Cloud Deployment

### Exercise 3.1 / 3.2: Deploy agent Part 6

- Nền tảng: **Railway**, project `day14-agent` gồm service `agent` (agent Part 6, build từ `06-lab-complete/Dockerfile`) và service `Redis`.
- URL public: https://agent-production-72a08393.up.railway.app
- 4 lệnh tự kiểm tra của CP6: `/health` **200**, `/ready` **200**, `/ask` không key **401**, `/ask` có key **200**. Trên URL public, rate limit trả 429 sau 10 request / phút. Chi tiết, biến môi trường và các lệnh deploy: [DEPLOYMENT.md](DEPLOYMENT.md).
- Ảnh: [dashboard](screenshots/dashboard.png) · [running](screenshots/running.png) · [test](screenshots/test.png)

### So sánh `railway.toml` và `render.yaml`

Hai file trong `06-lab-complete/` cùng deploy một agent, nhưng mô tả ở hai mức khác nhau:

| Khía cạnh | `railway.toml` | `render.yaml` |
|---|---|---|
| Phạm vi | Chỉ cấu hình build và deploy của **một service**. Project, Redis và biến môi trường tạo bằng CLI hoặc dashboard | Blueprint mô tả **cả hạ tầng**: web service, Key Value (Redis), biến môi trường và liên kết giữa chúng |
| Build | `builder = "DOCKERFILE"`, `dockerfilePath` | `runtime: docker`, `dockerfilePath`, `dockerContext` (tính từ gốc repo vì file nằm trong thư mục con) |
| Health check | `healthcheckPath = "/health"`, `healthcheckTimeout` | `healthCheckPath: /health` |
| Restart | `restartPolicyType = "ON_FAILURE"`, tối đa 3 lần | Render tự restart, file không cấu hình |
| Redis | Không khai báo trong file: tạo bằng `railway add --database redis`, nối vào agent bằng biến tham chiếu `${{Redis.REDIS_URL}}` | Khai báo service `type: keyvalue`, nối vào agent bằng `fromService` với `property: connectionString` |
| Secret | Không có trong file, đặt bằng `railway variables` | `sync: false` (nhập ở dashboard khi tạo Blueprint) hoặc `generateValue: true` |
| Cách deploy | `railway up` upload thư mục ở máy, không cần GitHub | Render đọc Blueprint từ repo GitHub và tự deploy lại khi push |

**Vì sao khác:** Railway thiên về CLI và dashboard. Hạ tầng (service, database, biến) nằm trong project trên Railway, còn file chỉ quyết định cách build và chạy service. Render theo hướng Infrastructure as Code: commit một file là dựng lại được cả stack, nên Redis và secret cũng phải khai báo trong file. Railway CLI 5.75 còn cảnh báo `railway.toml` sẽ ngừng hỗ trợ từ 2026-12-01 để chuyển sang `.railway/railway.ts`, tức Railway cũng đang đi theo hướng IaC. File mẫu ở `03-cloud-deployment/` dùng `builder = "NIXPACKS"` kèm `startCommand`. Bản của mình dùng `DOCKERFILE` vì `CMD` trong Dockerfile đã nghe theo `${PORT:-8000}`, nên agent chạy giống hệt nhau ở local, trong Docker và trên Railway.

### Exercise 3.3: Pipeline CI/CD trên Cloud Run

`cloudbuild.yaml` mô tả pipeline 4 bước chạy trên Cloud Build mỗi khi push lên `main`; mỗi bước có `waitFor` bước trước, nên test fail là dừng luôn, không build hay deploy:

1. **`test`:** cài requirements và chạy `pytest` trong image `python:3.11-slim`.
2. **`build`:** build Docker image, gắn 2 tag `$COMMIT_SHA` và `latest`, dùng `--cache-from latest` để tận dụng layer cache.
3. **`push`:** đẩy cả 2 tag lên Container Registry.
4. **`deploy`:** `gcloud run deploy` đúng image theo commit SHA lên Cloud Run (region `asia-southeast1`, public, 1–10 instance, 512Mi / 1 CPU). Secret lấy từ Secret Manager bằng `--set-secrets`.

`service.yaml` là định nghĩa Knative của service (IaC): `minScale 1` để tránh cold start, `maxScale 10`, mỗi instance tối đa 80 request đồng thời, liveness probe `/health`, startup probe `/ready`, secret qua `secretKeyRef` thay vì ghi thẳng giá trị.

---

## Part 4: API Security

### Exercise 4.1: API key authentication

- **Kiểm tra ở đâu:** dependency `verify_api_key` (`04-api-gateway/develop/app.py` dòng 39–54). Nó đọc header `X-API-Key` qua `APIKeyHeader(auto_error=False)` và được gắn vào `/ask` bằng `Depends(verify_api_key)` (dòng 70). Key đúng lấy từ biến môi trường `AGENT_API_KEY` (dòng 35).
- **Sai key:** thiếu header thì trả **401**, có header nhưng sai thì trả **403** `Invalid API key.`. Bản Part 6 của mình trả 401 cho cả hai trường hợp, theo yêu cầu của bài.
- **Rotate key:** key được đọc từ biến môi trường lúc khởi động, nên chỉ cần đặt giá trị mới trên nền tảng rồi restart hoặc redeploy, không phải sửa code. Muốn không bị gián đoạn thì cho app chấp nhận cả key cũ lẫn key mới trong một thời gian (ví dụ biến `AGENT_API_KEYS` chứa danh sách), báo client đổi sang key mới, rồi gỡ key cũ.

Chạy `AGENT_API_KEY=secret-key-123 python app.py` trong `04-api-gateway/develop/`:

```text
$ curl -i http://localhost:8000/ask -X POST -H "Content-Type: application/json" -d '{"question": "Hello"}'    # không có key
HTTP/1.1 401 Unauthorized
content-type: application/json

{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

$ curl -i ... -H "X-API-Key: wrong-key"
HTTP/1.1 403 Forbidden
content-type: application/json

{"detail":"Invalid API key."}

$ curl -i ... -H "X-API-Key: secret-key-123"
HTTP/1.1 200 OK
content-type: application/json

{"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
```

### Exercise 4.2: JWT authentication

**Luồng JWT** (`04-api-gateway/production/auth.py`):
1. `POST /auth/token` với username và password.
2. Server ký token HS256 bằng `JWT_SECRET`. Payload gồm `sub` (user), `role`, `iat`, `exp` (hết hạn sau 60 phút).
3. Client gửi `Authorization: Bearer <token>` ở mỗi request.
4. `verify_token` kiểm tra chữ ký và `exp` rồi lấy ra user và role, không cần tra database.
5. Token sai trả 403, token hết hạn trả 401 `Token expired`.

Chạy `python app.py` trong `04-api-gateway/production/` (venv riêng vì bản này cần `pydantic>=2.11`):

```text
$ curl -X POST http://localhost:8000/auth/token -d '{"username": "student", "password": "demo123"}'
{"access_token": "eyJhbGciOi...(đã che)", "token_type": "bearer", "expires_in_minutes": 60, "hint": "Include in header: Authorization: Bearer ey...(đã che)"}
# payload của token (phần giữa, chỉ là base64, ai cũng đọc được; không chứa bí mật):
{"sub":"student","role":"user","iat":1795684420,"exp":1795688020}

$ curl -i ... /auth/token sai mật khẩu
HTTP/1.1 401 Unauthorized
{"detail":"Invalid credentials"}

$ curl -i ... /ask không có token
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer
{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

$ curl -i ... /ask -H "Authorization: Bearer invalid.token.value"
HTTP/1.1 403 Forbidden
{"detail":"Invalid token."}

$ curl -i ... /ask -H "Authorization: Bearer $TOKEN" -d '{"question": "Explain JWT"}'
HTTP/1.1 200 OK
{"question":"Explain JWT","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.","usage":{"requests_remaining":9,"budget_remaining_usd":1.9e-05}}
```

Trường `budget_remaining_usd` trong response thật ra trả về số tiền **đã dùng** (`usage.total_cost_usd` ở `app.py` dòng 160), chứ không phải số còn lại. Đây là lỗi đặt tên trong code mẫu.

### Exercise 4.3: Rate limiting

- **Thuật toán:** sliding window theo từng user (`rate_limiter.py`). Mỗi user có một `deque` lưu thời điểm các request; mỗi lần gọi thì xoá các mốc cũ hơn 60 giây rồi đếm. Docstring gọi là "Sliding Window Counter", nhưng vì lưu từng timestamp nên đúng hơn là *sliding window log*.
- **Giới hạn:** user thường 10 request / phút, admin 100 request / phút (dòng 86–87).
- **Bypass cho admin:** `app.py` chọn limiter theo role (`rate_limiter_admin if role == "admin" else rate_limiter_user`). Tài khoản `teacher` có role admin nên dùng limiter 100 request / phút.
- **Hạn chế:** state nằm trong RAM của process, nên mỗi instance hoặc worker đếm riêng và restart là mất. Vì vậy bản Part 6 dùng Redis sorted set.

```text
$ for i in {1..20}; do curl ... /ask -H "Authorization: Bearer $TOKEN" -d "{\"question\": \"Test $i\"}"; done
Test 1: HTTP 200 ... "requests_remaining":8 ...
...
Test 9: HTTP 200 ...
Test 10: HTTP 429 {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
...
Test 20: HTTP 429 {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}

$ curl -i ... (request bị chặn)
HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795684482
retry-after: 59
{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}

# admin (teacher), 12 request liên tiếp:
teacher: 200 200 200 200 200 200 200 200 200 200 200 200
```

Request "Explain JWT" ở 4.2 đã dùng 1 lượt, nên trong vòng lặp chỉ còn 9 request trả 200; request thứ 10 trong cùng phút bị 429.

### Exercise 4.4: Cost guard

**Cách làm** (code thật ở `06-lab-complete/app/cost_guard.py`, đã qua script chấm Part 6):
1. **Trước khi gọi LLM**, `check_budget()` đọc tổng chi phí trong ngày và trong tháng từ Redis (`cost:daily:YYYY-MM-DD`, `cost:monthly:YYYY-MM`). Đạt `DAILY_BUDGET_USD` hoặc `MONTHLY_BUDGET_USD` thì trả **402 Payment Required**, nên không tốn thêm tiền gọi LLM.
2. **Sau khi gọi LLM**, `record_cost()` tính cost = input_tokens × giá input + output_tokens × giá output, rồi cộng vào cả hai key bằng `INCRBYFLOAT` trong một transaction.
3. Key ngày có TTL 2 ngày, key tháng có TTL 32 ngày, nên tự reset sang ngày hoặc tháng mới mà không cần cron.
4. State nằm trong Redis nên mọi worker và instance dùng chung, restart không mất. Redis lỗi thì trả 503 (từ chối an toàn), không cho gọi LLM khi không biết còn budget hay không.

Theo đề Exercise 4.4 (mỗi user $10 / tháng), viết lại theo từng user như sau:

```python
def check_budget(user_id: str, estimated_cost: float) -> bool:
    key = f"budget:{user_id}:{datetime.now(timezone.utc):%Y-%m}"   # key mới mỗi tháng → tự reset
    current = float(r.get(key) or 0)
    if current + estimated_cost > 10:                               # $10 / tháng / user
        return False
    pipe = r.pipeline()
    pipe.incrbyfloat(key, estimated_cost)
    pipe.expire(key, 32 * 24 * 3600)
    pipe.execute()
    return True
```

Đoạn này có race condition: hai request đồng thời cùng đọc `current` cũ thì có thể vượt budget một chút. Muốn chặt hơn thì `INCRBYFLOAT` trước rồi kiểm tra, vượt thì trừ lại, hoặc dùng một Lua script.

So với bản mẫu `04-api-gateway/production/cost_guard.py`: bản mẫu lưu trong RAM, mỗi user $1 / ngày (trả 402), tổng toàn hệ thống $10 / ngày (trả 503). Sau 10 request, `/me/usage` của `student` cho thấy `"requests":10, "cost_usd":0.000196`.

**Vì sao cần cả rate limit lẫn cost guard:** rate limit bảo vệ *tốc độ* (số request / phút, chống spam và chia công bằng). Cost guard bảo vệ *tiền*: vài request với prompt rất dài vẫn có thể tốn nhiều tiền dù không hề vượt rate limit.

---

## Part 5: Scaling & Reliability

### Exercise 5.1–5.5

#### 5.1 Health check: liveness và readiness

- **`/health` (liveness):** hỏi "process còn sống không?". Lỗi thì platform **restart** container. Không được phụ thuộc vào database hay Redis; nếu phụ thuộc, Redis chết sẽ làm mọi instance bị restart liên tục mà vẫn không khỏi.
- **`/ready` (readiness):** hỏi "đã nhận traffic được chưa?". Lỗi thì load balancer **ngừng gửi traffic** tới instance đó nhưng không restart. Dùng khi đang khởi động, đang tắt, hoặc mất kết nối tới thứ app phụ thuộc.

```text
$ curl http://localhost:8000/health      # 05-scaling-reliability/develop
{"status":"ok","uptime_seconds":0.5,"version":"1.0.0","environment":"development","timestamp":"2026-11-26T09:13:57.374344+00:00","checks":{"memory":{"status":"ok","used_percent":11.2}}}
$ curl http://localhost:8000/ready
{"ready":true,"in_flight_requests":1}
```

#### 5.2 Graceful shutdown

Gửi `POST /ask?question=Long task` rồi 0.05 giây sau gửi SIGTERM cho process:

```text
$ kill -TERM 3841   (gửi lúc request 'Long task' đang chạy)
request đang chạy → 200 {"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
exit code của process: 0
--- log ---
INFO:     Shutting down
INFO:     127.0.0.1:42486 - "POST /ask?question=Long%20task HTTP/1.1" 200 OK
INFO:     Waiting for application shutdown.
2026-11-26 16:14:00,507 INFO 🔄 Graceful shutdown initiated...
2026-11-26 16:14:00,507 INFO ✅ Shutdown complete
INFO:     Application shutdown complete.
INFO:     Finished server process [3841]
2026-11-26 16:14:00,508 INFO Received signal 15 — uvicorn will handle graceful shutdown
```

Thứ tự log cho thấy uvicorn ngừng nhận request mới ("Shutting down"), chờ request đang chạy trả 200, rồi mới chạy phần shutdown của `lifespan` và thoát với code 0. Dòng "Received signal 15" của handler tự viết xuất hiện **cuối cùng**, vì uvicorn chỉ gọi lại handler cũ sau khi đã tắt xong (đúng như đã phân tích ở Part 1).

#### 5.3 Stateless design

Bản `production/app.py` lưu lịch sử hội thoại trong Redis (`session:{id}`, TTL 1 giờ, giữ 20 tin nhắn gần nhất), không lưu trong RAM. Nếu dùng dict trong RAM thì mỗi instance (và mỗi worker) có một bản riêng: request sau của cùng user rơi vào instance khác sẽ không thấy lịch sử, và restart là mất hết.

Có một điểm yếu: nếu lúc import không ping được Redis, app **lặng lẽ** chuyển sang lưu trong RAM (dòng 35–45), tức là trở thành stateful mà không ai biết. An toàn hơn là cho `/ready` trả 503 khi mất Redis, giống bản Part 6.

#### 5.4 Load balancing: 3 instance sau Nginx

`docker compose -p k5-day14-scaling up -d --build --scale agent=3` trong `05-scaling-reliability/production/` (cổng 8080, endpoint `POST /chat`):

```text
NAME                       IMAGE                    STATUS                    PORTS
k5-day14-scaling-agent-1   k5-day14-scaling-agent   Up 19 seconds (healthy)   8000/tcp
k5-day14-scaling-agent-2   k5-day14-scaling-agent   Up 19 seconds (healthy)   8000/tcp
k5-day14-scaling-agent-3   k5-day14-scaling-agent   Up 19 seconds (healthy)   8000/tcp
k5-day14-scaling-nginx-1   nginx:alpine             Up 18 seconds             0.0.0.0:8080->80/tcp
k5-day14-scaling-redis-1   redis:7-alpine           Up 30 seconds (healthy)   6379/tcp

$ for i in {1..10}; do curl http://localhost:8080/chat -X POST -d "{\"question\": \"Request $i\"}"; done
Request 1 → served_by=instance-86644e  X-Served-By=172.20.0.5:8000
Request 2 → served_by=instance-bc24b4  X-Served-By=172.20.0.4:8000
Request 3 → served_by=instance-4b90dc  X-Served-By=172.20.0.3:8000
Request 4 → served_by=instance-86644e  X-Served-By=172.20.0.5:8000
...
Request 10 → served_by=instance-86644e  X-Served-By=172.20.0.5:8000

$ docker compose -p k5-day14-scaling logs agent | grep "POST /chat"   (đếm theo instance)
      7 agent-1
      6 agent-2
      7 agent-3
```

Nginx chia request lần lượt (round-robin) cho 3 instance. DNS của Docker trả về IP của cả 3 container cho tên `agent`.

**Lần chạy đầu bị 502 ở mọi request:** request được gửi ngay khi 3 agent còn `health: starting`. Nginx kết nối thất bại nên tạm đánh dấu các upstream là lỗi (mặc định `max_fails=1`, `fail_timeout=10s`), và trả 502 cho tới khi hết thời gian đó. Lần chạy lại chờ `/chat` trả 200 trước rồi mới đo. Bài học: load balancer chỉ nên gửi traffic khi instance đã ready.

#### 5.5 Test stateless

```text
$ python test_stateless.py
Session ID: fb6142fe-4e02-489d-9fa8-11b947f59830
Request 1: [instance-bc24b4]   Q: What is Docker?
Request 2: [instance-4b90dc]   Q: Why do we need containers?
Request 3: [instance-86644e]   Q: What is Kubernetes?
Request 4: [instance-bc24b4]   Q: How does load balancing work?
Request 5: [instance-4b90dc]   Q: What is Redis used for?
Instances used: {'instance-86644e', 'instance-4b90dc', 'instance-bc24b4'}
✅ All requests served despite different instances!
--- Conversation History ---
Total messages: 10
✅ Session history preserved across all instances via Redis!
```

**Giải thích:** 5 câu của cùng một session đi qua cả 3 instance, nhưng lịch sử vẫn đủ 10 tin nhắn (5 câu hỏi và 5 câu trả lời), vì mọi instance đọc và ghi cùng một key trong Redis.

**Thử thêm: tắt hẳn 1 instance giữa cuộc hội thoại.** Script mặc định không tắt instance nào, nên mình tự làm thêm:

```text
(Turn 1, Turn 2 trong một session mới)
$ docker stop k5-day14-scaling-agent-1
Turn 4 served_by instance-86644e        ← response cho câu "Turn 3"
Turn 5 served_by instance-bc24b4        ← response cho câu "Turn 4"
history count = 8 ['Turn 1', 'Turn 2', 'Turn 3', 'Turn 4']
```

Instance bị tắt không làm mất hội thoại: các lượt sau do 2 instance còn lại xử lý, và lịch sử vẫn đủ 4 lượt (8 tin nhắn). Trường `turn` trong response của app đếm lệch 1 (nó đếm sau khi đã thêm câu hỏi hiện tại), nên mình dùng `history` để kiểm tra.

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
| 7 | Part 3 | Nhờ AI deploy agent Part 6 lên Railway | AI cài Railway CLI, tạo project `day14-agent` + Redis + service `agent`, đặt biến môi trường (key sinh ngẫu nhiên, không in ra), `railway up`, tạo domain, chạy 4 lệnh tự kiểm tra (200/200/401/200) và thử rate limit trên URL public; viết `DEPLOYMENT.md` và mục Part 3 | Tự đăng nhập Railway (`railway login`). _(TODO: tự chạy 4 lệnh ở `DEPLOYMENT.md`, chụp 3 ảnh deploy)_ |
| 8 | Part 7 (Bước 1) | Nhờ AI làm Part 7 phần chạy local | AI thêm metric `agent_question_length_chars` (7.1); chạy load test 4 mức concurrency và 3 mức `MOCK_SLOW_RATE`; eval v1, v2; thêm 2 tài liệu (JWT, HPA) vào `KNOWLEDGE_BASE` để v2 đạt 23/23, không regression; viết job CI `.github/workflows/eval.yml`; viết mục 1–3 của `BENCHMARK_REPORT.md` từ file JSON | _(TODO: tự chạy lại eval cuối, đối chiếu số trong `BENCHMARK_REPORT.md` với file JSON)_ |
| 9 | Part 2, 4, 5 | Nhờ AI chạy các bài tập Part 2, 4, 5 và viết câu trả lời | AI build 2 image, đo kích thước, chạy stack Compose Part 2; chạy bản develop và production của Part 4 (API key, JWT, rate limit; che token khi in); chạy Part 5 (health/ready, SIGTERM, 3 instance + `test_stateless.py`, tắt 1 instance); tìm nguyên nhân lỗi 502 ở lần chạy đầu; viết các mục Part 2, 4, 5 từ output thật | _(TODO: tự chạy lại ít nhất 1 lệnh mỗi Part, đọc hiểu câu trả lời)_ |
| 10 | Part 7 (Bước 2) | Nhờ AI làm stack observability và chụp ảnh Part 7 | AI dựng stack Prometheus/Grafana/Jaeger/Locust; sửa lỗi `PYTHONUSERBASE` trong `production/Dockerfile` (agent restart liên tục); phát hiện `docker compose run` làm đổi số instance nên đo lại 1 và 3 instance với `--no-deps`; tìm trace chậm và trace lỗi qua Jaeger API, đối chiếu với log theo `trace_id`; chạy thí nghiệm A–E, đo thời gian tới lúc alert firing; chụp 4 ảnh bằng Edge chạy ngầm (Playwright); viết mục 4–6 của `BENCHMARK_REPORT.md` | _(TODO: tự mở 4 ảnh trong `screenshots/`, đối chiếu số trong mục 4–5 với ảnh và file CSV)_ |
