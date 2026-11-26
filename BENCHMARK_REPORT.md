# Benchmark & Observability Report — Day 14

> Mọi con số lấy từ report JSON trong [`reports/`](reports/), CSV trong [`benchmark-results/`](benchmark-results/) và ảnh trong [`screenshots/`](screenshots/).

**Họ tên:** Phùng Quang Trà
**Ngày chạy:** 2026-11-26
**Môi trường:** Laptop AMD Ryzen 7 8745H (8 nhân / 16 luồng), RAM 20 GB. Windows 11 + WSL2 Ubuntu 24.04 (Python 3.12.3). Docker Desktop 4.55 (Engine 29.1.3, cấp cho Docker 16 CPU / 9.6 GB). Ở phần develop, agent chạy 1 process uvicorn, còn `load_test.py` chạy trên cùng máy.

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | Mock LLM mất 120–180 ms cộng khoảng 20 ms retrieval, nên p95 lúc bình thường khoảng 220–300 ms (bảng 2.1). 500 ms chừa biên cho jitter mà người dùng chat vẫn thấy nhanh; trùng ngưỡng mặc định của `load_test.py`. Alert `AgentHighLatencyP95` (p95 > 1 s trong 2 phút) là mức báo động khi đã vi phạm nặng |
| Error rate `/ask` | < 2 % | Upstream mock lỗi sẵn khoảng 1% (`MOCK_ERROR_RATE=0.01`), nên 1% là nhiễu bình thường; 2% đủ chặt để bắt sự cố thật. Alert `AgentHighErrorRate` báo động (critical) ở 5% |
| Accuracy trên golden dataset | ≥ 85 % và không regression | Ngưỡng quality gate trong CI ([`.github/workflows/eval.yml`](.github/workflows/eval.yml)). Bản hiện tại đạt 100% (23/23) |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2)

Mỗi mức gửi 300 request, `MOCK_SLOW_RATE=0.03` và `MOCK_ERROR_RATE=0.01` (mặc định). File: `reports/load_v2_c{1,10,50,100}.json`.

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4.26 | 190.5 | 221.2 | 1688.4 | 0.00% | ✅ PASS |
| 10 | 43.77 | 191.2 | 224.1 | 1676.0 | 0.33% | ✅ PASS |
| 50 | 104.22 | 203.1 | 299.1 | 1693.8 | 1.33% | ✅ PASS |
| 100 | 58.31 | 433.0 | 3066.1 | 3341.9 | 0.00% | ❌ FAIL (p95) |

**Nhận xét:** RPS tăng gần tuyến tính từ concurrency 1 lên 10 (4.26 → 43.77, gấp khoảng 10 lần). Mỗi request chủ yếu là *chờ* LLM (`asyncio.sleep` khoảng 190 ms), nên event loop xử lý được nhiều request song song. Tính theo Little's law: RPS ≈ concurrency / latency = 10 / 0.22 s ≈ 45, khớp số đo.

Từ 50 trở lên thì không còn tuyến tính. Theo lý thuyết, concurrency 50 phải được khoảng 230 RPS, thực tế chỉ 104. Agent develop chỉ có **1 process uvicorn (1 event loop, dùng 1 core)**, mỗi request phải parse JSON, ghi log JSON và cập nhật metrics; `load_test.py` lại chạy trên cùng máy, nên CPU thành nút thắt và p95 tăng từ 224 lên 299 ms. Ở concurrency 100 agent quá tải: request xếp hàng chờ event loop, p50 lên 433 ms, p95 lên 3066 ms, và RPS còn **giảm** xuống 58 vì thời gian chờ trong hàng tăng nhanh hơn số request được xử lý. Một instance này chỉ giữ được SLO tới khoảng 50 request đồng thời; muốn hơn phải scale ngang (xem mục 5).

Ở mọi mức, p99 đều khoảng 1.7 s. Đó là 3% request chậm do `MOCK_SLOW_RATE=0.03`, không phải do tải.

### 2.2 Tail latency

Cùng 300 request, concurrency 20; agent v2 được khởi động lại với từng giá trị `MOCK_SLOW_RATE`. File: `reports/load_v2_slow_{0,0.03,0.1}.json`.

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 194.7 | 227.8 | 251.9 |
| 0.03 (mặc định) | 227.0 | 238.3 | 1682.9 |
| 0.1 | 355.0 | 1691.1 | 1716.8 |

**Nhận xét:** p99 nhạy nhất với request chậm. Chỉ cần 3% request chậm thêm 1.5 s là p99 nhảy từ 252 lên 1683 ms (gấp 6.7 lần), trong khi avg chỉ tăng 32 ms (195 → 227) và p95 gần như không đổi (228 → 238). Lý do: 3% < 5%, nên ngưỡng p95 chưa chạm tới nhóm request chậm. Khi 10% request chậm (> 5%), p95 cũng lên 1691 ms, còn avg mới 355 ms.

Average che giấu nhóm người dùng bị chậm. Avg 355 ms trông vẫn "ổn", nhưng thật ra cứ 10 người thì 1 người phải chờ khoảng 1.7 s. SLO đặt theo p95 / p99 để cam kết trải nghiệm cho 95% / 99% người dùng và bắt được tail latency mà average không thấy.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

File: `reports/eval_v1.json`, `reports/eval_v2.json`, `reports/eval_v2_fixed.json`.

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.35% (1/23) | 91.3% (21/23) | 100% (23/23) |
| Avg tokens / câu | 57.0 | 109.3 | 115.8 |
| Tổng cost (USD) | 0.000403 | 0.000764 | 0.000809 |
| Cost / câu đúng (USD) | 0.00040335 | 0.00003639 | 0.00003518 |
| Quality gate theo ngưỡng CI (accuracy ≥ 85%, không regression) | FAIL (4.35% < 85%) | PASS (91.3%, 0 regression so với v1) | PASS (100%, 0 regression so với v2) |

Ngưỡng 85% là ngưỡng của SLO (mục 1) và của job CI `eval.yml`. Lúc chạy, v1 và v2 dùng ngưỡng mặc định 80% của `run_eval.py` (trường `quality_gate.min_accuracy` trong JSON), còn bản sau khi sửa KB dùng `--min-accuracy 1.0` (lệnh bên dưới). Xét theo 85% thì kết quả PASS / FAIL của cả ba bản không đổi.

**Những câu v2 trả lời sai ban đầu và cách sửa:**

| ID | Keyword bị thiếu | Đã sửa gì |
|---|---|---|
| security-02 | token, hết hạn, chữ ký | Thêm vào `KNOWLEDGE_BASE` một tài liệu so sánh JWT với API key, từ khoá kích hoạt `["jwt", "json web token"]` |
| scaling-03 | cpu, memory, custom metrics | Thêm tài liệu về Kubernetes HPA, từ khoá kích hoạt `["hpa", "autoscal", "kubernetes"]` |

Hai tài liệu được thêm ở **cuối** `KNOWLEDGE_BASE` trong `develop/utils/mock_llm.py`, với từ khoá riêng. Nhờ vậy, khi các câu khác có số từ khoá khớp bằng nhau thì vẫn chọn tài liệu cũ như trước, và `--baseline reports/eval_v2.json` xác nhận **0 regression**. Bản sửa cũng được chép sang `production/utils/mock_llm.py` để stack Docker dùng cùng knowledge base. Không sửa `golden_dataset.jsonl`.

**Hạn chế:** hai tài liệu được viết dựa đúng vào 2 câu v2 trả lời sai trong golden dataset, nên 100% (23/23) là điểm trên chính bộ câu đã dùng để sửa. Kết quả này dễ bị overfit: nó chưa chứng minh agent trả lời tốt hơn với câu hỏi mới về JWT hay HPA. Muốn đánh giá công bằng thì cần một tập câu hỏi riêng (held-out) không dùng khi sửa KB, hoặc thêm câu mới vào golden dataset rồi chạy lại.

```text
$ python eval/run_eval.py --url http://localhost:8002 --min-accuracy 1.0 --baseline reports/eval_v2.json --out reports/eval_v2_fixed.json
  Accuracy      : 100.0%  (23/23)
  ✨ Câu được cải thiện : 2
  ⚠️  Câu bị regression : 0
  Quality gate (accuracy ≥ 100%, không regression): ✅ PASS
```

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**
- **Chi phí:** v2 tốn khoảng 1.9 lần token mỗi câu (109.3 so với 57.0) và tổng cost cũng gấp khoảng 1.9 lần (0.000764 so với 0.000403 USD), vì prompt có thêm tài liệu được retrieve.
- **Latency:** p95 của eval tăng 20.7 ms (190.8 → 211.5 ms) do thêm bước retrieval khoảng 20 ms và prompt dài hơn.
- **Chất lượng:** accuracy tăng từ 4.35% lên 91.3%, nên **cost cho mỗi câu đúng rẻ hơn khoảng 11 lần** (0.00040335 → 0.00003639 USD).

So theo "cost / câu" thì v1 rẻ hơn, nhưng gần như mọi câu v1 đều sai, tức là trả tiền cho câu trả lời vô dụng. "Cost / câu đúng" mới so công bằng hai phiên bản. Sau khi sửa KB, token mỗi câu tăng nhẹ (115.8), nhưng cost / câu đúng còn giảm thêm (0.00003518).

**Quality gate trong CI:** [`.github/workflows/eval.yml`](.github/workflows/eval.yml) chạy trên mỗi pull request. Job khởi động agent v2 (`MOCK_ERROR_RATE=0`) rồi chạy `python eval/run_eval.py --min-accuracy 0.85`. `run_eval.py` trả **exit code 1** khi accuracy dưới ngưỡng hoặc có regression, khiến step đó fail và cả job fail. Khi nhánh `main` bật *Require status checks to pass before merging* (Settings → Branches), PR có eval fail sẽ không merge được.

---

## 4. Observability stack (production)

Stack chạy bằng `docker compose -p k5-day14-observability up -d --build` trong `06-lab-complete/benchmark-observability/production/`. Ảnh được chụp trực tiếp từ các trang Grafana, Jaeger, Prometheus đang chạy trên máy (Edge chạy ngầm qua Playwright).

Có hai trục trặc khi dựng stack, đã sửa:
- **Agent restart liên tục** với lỗi `ModuleNotFoundError: No module named 'uvicorn'`. Nguyên nhân: Dockerfile cài thư viện bằng `pip install --user` rồi copy sang `/home/agent/.local`, nhưng user `agent` có home là `/app`. Sửa bằng `ENV PYTHONUSERBASE=/home/agent/.local`. Trong lúc lỗi, mọi request qua Nginx đều trả 502.
- **`docker compose run locust` âm thầm đưa số agent về mặc định** `replicas: 2`, vì nó bật lại các service mà Locust phụ thuộc (`depends_on`). Lần đo "1 instance" đầu tiên thật ra có 2 instance (thấy rõ trên panel *Requests/s theo instance*). Các lần đo trong báo cáo đều chạy với `--no-deps`, và số instance được kiểm tra cả trước lẫn sau khi chạy.

Unit test alert rules: `promtool test rules /p/alert_rules_test.yml` → `SUCCESS`.

### 4.1 Screenshot

- [x] [Dashboard Grafana khi đang có tải](screenshots/grafana-dashboard.png): 3 instance, Locust 100 user. Traffic 61.8 req/s, Error rate 0.97%, p95 294.12 ms, in-flight 17, Instances up 3. Panel *Requests/s theo instance* thấy rõ lúc 1 instance chịu khoảng 60 req/s, rồi chuyển sang 3 instance.
  - Panel *Tokens/s* vẽ dạng **stack** (`"stacking": {"mode": "normal"}` trong `grafana/dashboards/agent-overview.json`): đường vàng `output` được vẽ chồng lên `input`, nên đỉnh của nó (khoảng 7.3K) là **tổng** 4794 + 2527 = 7321 tokens/s, không phải riêng output. Số của từng loại xem câu 3 của Exercise 7.4 bên dưới.
  - Panel *Cost burn rate* lên khoảng $6/giờ, vượt vạch đỏ $2/giờ, nên `LLMCostBurnRateHigh` cũng **firing** trong lần chạy 100 user này. `/api/v1/alerts` lúc 09:40:10Z (tải đã giảm) vẫn cho thấy alert này firing, `activeAt` 09:28:02Z, giá trị $2.26/giờ. Ngưỡng cố định $2/giờ không phân biệt được traffic tăng hợp lệ với việc mỗi request đắt lên (thí nghiệm C). Nên alert thêm theo cost / request, hoặc theo % budget ngày.
- [x] [Một trace chậm trong Jaeger](screenshots/jaeger-slow-trace.png): span `chat mock-llm-small` chiếm 1.7 s trong tổng 2.1 s.
- [x] [Một trace lỗi trong Jaeger](screenshots/jaeger-error-trace.png): `POST /ask` trả 503, span LLM có `error.type = upstream_unavailable` và event `exception` ("Upstream LLM error: 503 Service Unavailable (mock)").
- [x] [Trang Alerts của Prometheus](screenshots/prometheus-alert-firing.png): nhóm `agent-slo` hiện **FIRING (2)**, gồm `AgentHighErrorRate` và `AgentHighLatencyP95`. Ảnh chụp lúc 09:47:56Z (16:47:56 giờ máy), khoảng 3 phút 54 giây sau T0 của thí nghiệm A + B (mục 4.2) và trước khi bắt đầu C. `AgentHighErrorRate` có *Active Since* 3m 26s, giá trị 0.224 (error rate 22.4%). Nhóm `agent-cost` lúc này INACTIVE.

**Trả lời Exercise 7.4.** Số liệu lấy từ Prometheus lúc 16:36:05, cùng thời điểm chụp ảnh Grafana (3 instance, 100 user):

1. **p95 = 294 ms, avg = 232 ms** (p99 = 1819 ms). p95 và avg chỉ cách nhau 62 ms, vì hơn 95% request là request "bình thường" (LLM khoảng 200 ms). Khoảng cách thật sự nằm ở p99 (1.8 s): 3% request bị chậm thêm 1.5 s (`MOCK_SLOW_RATE=0.03`) chỉ lộ ra ở p99. Avg tăng rất ít nên che mất nhóm người dùng bị chậm.
2. **Requests/s theo instance: 20.60 / 20.71 / 20.74.** Tải chia gần như đều: Nginx dùng round-robin trên `server agent:8000 resolve`, và DNS của Docker trả về IP của cả 3 container.
3. **Input 4794 tokens/s, gấp khoảng 1.9 lần output 2527 tokens/s.** Prompt gửi vào LLM gồm system prompt, tài liệu retrieve được (RAG) và câu hỏi, khoảng 81–95 token. Câu trả lời chỉ khoảng 46–55 token. RAG làm prompt dài thêm nên input luôn lớn hơn output.
4. **`curl http://localhost:8080/metrics` trả 404**, do `nginx.conf` có `location = /metrics { return 404; }`. Metrics chỉ dành cho Prometheus, vốn scrape thẳng `agent:8000` trong mạng nội bộ. Public `/metrics` sẽ lộ thông tin hệ thống (route, lưu lượng, version, cost) cho bất kỳ ai, và người ngoài có thể scrape liên tục làm tốn tài nguyên.

### 4.2 Thí nghiệm "phá hệ thống"

Locust chạy 30 user suốt các thí nghiệm. Cấu hình đổi qua file `.env` rồi `docker compose up -d` (chỉ agent bị tạo lại). Thời gian tính từ lúc `up -d` xong (T0); trạng thái alert lấy từ `/api/v1/alerts`, mỗi 5 giây một lần. Thứ tự chạy: E trước khi hệ thống còn sạch, rồi A + B cùng lúc (T0 09:44:02Z), rồi C (T0 09:48:16Z) và D (pause lúc 09:48:50Z).

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` (critical) | Pending sau 29 s (error rate 5.9%), **firing sau 90 s** (18.8%); `for: 1m` | *Error rate* chuyển đỏ; *LLM calls theo kết quả* có đường `error` tăng; trace lỗi xuất hiện trong Jaeger |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` (warning) | Pending sau 19 s (p95 1.52 s), **firing sau 140 s** (p95 1.895 s); `for: 2m` | *Latency /ask*: p95 và p99 vọt lên khoảng 1.9 s, trong khi avg chỉ 573 ms |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` (warning) | Pending sau 16 s, **firing sau 145 s** ($14.4/giờ); `for: 2m` | *Cost burn rate* vượt vạch đỏ $2/giờ, lên $15.2/giờ (v1 chỉ $0.61/giờ); p95 tăng lên 695 ms (model lớn chậm hơn 2.5 lần) |
| D | `docker pause` agent 172.20.0.8 | `AgentInstanceDown` (critical) | Pending sau khoảng 7 s, **firing sau khoảng 41 s**; `for: 30s` | *Instances up* giảm từ 3 xuống 2; *Requests/s theo instance* mất 1 đường. Error rate của agent vẫn **xanh (0.8%)** dù Nginx trả **30 lỗi 504** (09:48:58 → 09:50:40) |
| E | `AGENT_VERSION=v1` | **Không có** (theo dõi 150 s; chỉ `AgentInstanceDown` pending vài giây lúc tạo lại container, không firing) | — | *Retrieval hit ratio* mất dữ liệu (v1 không retrieve); *Tokens/s* giảm (input 668/s, output 362/s); cost $0.61/giờ; bảng *Phiên bản đang chạy* đổi sang v1. Error 0.59%, p95 200 ms, mọi chỉ số đều "xanh" |

**Thí nghiệm D:** dùng `docker pause` chứ không dùng `docker stop`, vì container bị pause vẫn còn trong DNS nên Prometheus thấy target `up == 0`. Container bị stop thì biến mất khỏi DNS, Prometheus coi như target không còn tồn tại nên không có alert.

Lỗi 504 xảy ra ở Nginx: request treo quá `proxy_read_timeout 10s` mà chưa bao giờ được agent xử lý xong, nên metric của agent không đếm. Trong 15 phút đó, `http_requests_total` của agent chỉ có status 200 (9229) và 503 (786), không có 504 nào. Metric chỉ phản ánh những gì chính service đó nhìn thấy, nên cần thêm giám sát ở tầng load balancer (tỉ lệ 5xx của Nginx) hoặc synthetic check từ bên ngoài.

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

Lỗi chất lượng không làm metric hạ tầng đỏ: v1 vẫn nhanh, vẫn ít lỗi, thậm chí còn rẻ hơn, nhưng accuracy chỉ còn 4.35% so với 91.3% của v2 (mục 3). Cách phát hiện:
1. **Chặn từ trước khi deploy:** chạy eval trên golden dataset trong CI (`run_eval.py --min-accuracy 0.85 --baseline ...`). Bản v1 sẽ fail quality gate và không được merge hay deploy.
2. **Giám sát chất lượng khi đang chạy:** lấy mẫu một phần traffic thật để chấm điểm (LLM-as-judge hoặc so với đáp án), theo dõi tỉ lệ người dùng đánh giá 👍/👎, và tỉ lệ câu trả lời "chung chung" (fallback).
3. **Alert trên metric đại diện cho chất lượng:** ví dụ retrieval hit ratio dưới 80% trong 10 phút, hoặc số token output trung bình giảm đột ngột. Ở thí nghiệm E, hit ratio mất hẳn dữ liệu, đây là tín hiệu rõ nhất trên dashboard.
4. **Canary deploy:** bản mới chỉ nhận một phần nhỏ traffic, so chỉ số chất lượng giữa hai bản rồi mới tăng dần, và theo dõi `agent_info` để biết lúc nào version đổi.

### 4.3 Debug bằng trace

Chọn 1 trace chậm nhất bạn tìm được:

- `trace_id`: `2ca5170d62256876bcfb6bb1a2ad92bb` (lúc 16:32:32, trong lần đo 1 instance)
- Tổng thời gian: **2098.4 ms** (`POST /ask`)
- Span chiếm nhiều thời gian nhất: **`chat mock-llm-small`** (**1692.4 ms, 80.7%**), tức là LLM chậm chứ không phải code của agent. Các span còn lại: `agent.run` 1795.7 ms, `agent.retrieve_context` 103.1 ms (4.9%). Khoảng 300 ms trước khi `agent.run` bắt đầu là thời gian request phải xếp hàng, vì lúc đó chỉ có 1 instance và nó bị giới hạn 0.5 CPU.
- Tìm bằng Jaeger API v3 (`/api/v3/traces`, operation `POST /ask`, `duration_min=1s`, lấy trace dài nhất), rồi mở trang `/trace/<id>` (ảnh `jaeger-slow-trace.png`).
- Dòng log tương ứng (`docker compose -p k5-day14-observability logs --no-log-prefix agent | grep 2ca5170d62256876bcfb6bb1a2ad92bb`):

```json
{"ts": "2026-11-26T09:32:34.814869+00:00", "level": "INFO", "service": "observable-agent", "instance": "b713334834d4", "event": "llm_call", "trace_id": "2ca5170d62256876bcfb6bb1a2ad92bb", "span_id": "ee8203f430292cc6", "request_id": "f5fbe50c91fe", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 95, "output_tokens": 55, "cost_usd": 4.7e-05, "llm_ms": 1692.5}
{"ts": "2026-11-26T09:32:34.815704+00:00", "level": "INFO", "service": "observable-agent", "instance": "b713334834d4", "event": "http_request", "trace_id": "2ca5170d62256876bcfb6bb1a2ad92bb", "span_id": "ee8203f430292cc6", "request_id": "f5fbe50c91fe", "method": "POST", "route": "/ask", "status": 200, "ms": 2097.1}
```

`llm_ms` = 1692.5 trong log khớp với span LLM 1692.4 ms trong Jaeger, và `ms` = 2097.1 khớp với tổng 2098.4 ms của trace.

**Trace lỗi** (`jaeger-error-trace.png`): `trace_id` `2fe94c9d9a66a61777e78bc80cc0efb3`, tổng 110.4 ms. Span `chat mock-llm-small` (88.8 ms) có status ERROR, `error.type = upstream_unavailable` và event `exception` (`utils.mock_llm.LLMError`: "Upstream LLM error: 503 Service Unavailable (mock)"). Log tương ứng:

```json
{"ts": "2026-11-26T09:36:27.661329+00:00", "level": "INFO", "service": "observable-agent", "instance": "9d0a8e146f87", "event": "llm_error", "trace_id": "2fe94c9d9a66a61777e78bc80cc0efb3", "span_id": "3c71db2ea21ff108", "request_id": "866d6d2bc634", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
{"ts": "2026-11-26T09:36:27.661800+00:00", "level": "INFO", "service": "observable-agent", "instance": "9d0a8e146f87", "event": "http_request", "trace_id": "2fe94c9d9a66a61777e78bc80cc0efb3", "span_id": "3c71db2ea21ff108", "request_id": "866d6d2bc634", "method": "POST", "route": "/ask", "status": 503, "ms": 109.5}
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

Mỗi lần chạy: `docker compose -p k5-day14-observability run --rm --no-deps locust -f /mnt/locust/locustfile.py --host http://nginx --headless -u 100 -r 10 -t 2m --csv /mnt/results/scale_N`. Số trong bảng lấy từ dòng `Aggregated` của `benchmark-results/scale_{1,3}_stats.csv`.

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 65.50 | 190 | 350 | 1700 | 70 / 7752 (0.90%) |
| 3 | 65.58 | 190 | 240 | 1700 | 65 / 7767 (0.84%) |

Riêng dòng `POST /ask`: p95 giảm từ 360 xuống 250 ms, p99 vẫn 1700 ms ở cả hai lần.

**Giải thích kết quả:**
- **RPS gần như không đổi (65.5).** Locust mô phỏng người dùng thật: 100 user, mỗi user nghỉ 0.5–2 giây giữa hai lần hỏi. Throughput vì vậy bị giới hạn bởi chính số user, không phải bởi server. Theo Little's law: 100 / (1.25 s nghỉ + 0.23 s chờ) ≈ 67 req/s. Muốn đo được sức chứa thật thì phải tăng số user.
- **p95 có cải thiện: từ 350 xuống 240 ms.** Với 1 instance (giới hạn 0.5 CPU), agent nhận khoảng 60 req/s, gần mức bão hoà. Lúc tải lên đỉnh, request phải xếp hàng chờ event loop; trace chậm ở mục 4.3 có khoảng 300 ms chờ trước khi `agent.run` bắt đầu. Với 3 instance, mỗi instance chỉ nhận khoảng 20 req/s, hết xếp hàng, nên latency trở về mức nền của LLM.
- **p99 không đổi (1700 ms), và đây là nút thắt chính.** Tail latency đến từ LLM upstream (3% request bị chậm thêm 1.5 s), không phải từ agent. Panel *LLM latency p95* giữ quanh 195–199 ms ở cả hai lần. Scale agent không làm LLM nhanh hơn; muốn giảm p99 phải xử lý ở tầng gọi LLM, ví dụ đặt timeout và retry, hedged request, cache câu trả lời, hoặc dùng model hay provider nhanh hơn.
- **Tỉ lệ lỗi khoảng 0.9% ở cả hai lần**, đều là lỗi 503 giả lập của mock LLM (`MOCK_ERROR_RATE=0.01`), không phải do tải.

---

## 6. Kết luận

- 3 điều bạn học được về benchmark & observability:
  1. **Average che giấu tail latency.** Chỉ 3% request chậm đã làm p99 tăng 6.7 lần, trong khi avg chỉ tăng 32 ms (mục 2.2). Vì vậy SLO và alert latency phải đặt theo p95 / p99.
  2. **Mỗi lớp giám sát chỉ thấy phần của nó.** Agent không đếm được 30 lỗi 504 xảy ra ở Nginx (thí nghiệm D). Bản v1 trả lời sai gần hết mà không alert hạ tầng nào kêu (thí nghiệm E). Cần kết hợp metric của app, metric của load balancer, synthetic check và eval chất lượng.
  3. **Phải kiểm tra lại cách đo trước khi tin số đo.** `docker compose run` âm thầm đổi số instance, và một lỗi Dockerfile làm mọi request trả 502. Nếu không nhìn panel *Instances up* và target của Prometheus thì đã có hai bảng benchmark sai. Alert cũng có độ trễ do `for:` (từ 41 giây tới 2.5 phút), nên cần tính tới khi đặt kỳ vọng thời gian phát hiện sự cố.
- Nếu đưa agent này lên production thật, bạn sẽ thêm metric / alert nào nữa?
  - **Tầng load balancer:** tỉ lệ 5xx và 504 của Nginx, upstream response time; thêm blackbox / synthetic probe gọi `/health` và một câu `/ask` mẫu từ bên ngoài.
  - **Chất lượng:** điểm eval trên traffic được lấy mẫu; alert khi retrieval hit ratio dưới 80% trong 10 phút; tỉ lệ 👎 từ người dùng; tỉ lệ câu trả lời fallback.
  - **Độ bão hoà:** in-flight request theo từng instance, độ trễ của event loop (thời gian chờ trước `agent.run`), CPU và RAM của container (cAdvisor); alert khi in-flight cao kéo dài để biết lúc nào cần scale.
  - **Chi phí:** phần trăm budget ngày đã dùng (alert ở 80%), cost cho mỗi request theo từng version; số lỗi 429 từ phía LLM provider.
  - **SLO:** chuyển sang alert theo *burn rate* của error budget, nhìn cả cửa sổ ngắn lẫn dài, thay cho ngưỡng cố định, để vừa báo nhanh vừa ít báo động giả.

---

## Phụ lục — Exercise 7.1: đọc metrics

Gửi 1 câu hỏi tới agent v2 rồi `curl http://localhost:8002/metrics` (đã lọc bớt dòng):

```text
http_requests_total{method="POST",route="/ask",status="200"} 1.0
agent_in_flight_requests 0.0
llm_request_duration_seconds_bucket{le="0.2",model="mock-llm-small"} 1.0
llm_request_duration_seconds_count{model="mock-llm-small"} 1.0
llm_request_duration_seconds_sum{model="mock-llm-small"} 0.165241873343536
llm_tokens_total{model="mock-llm-small",type="input"} 91.0
llm_tokens_total{model="mock-llm-small",type="output"} 55.0
agent_question_length_chars_count 1.0
agent_question_length_chars_sum 40.0
```

1. **Counter:** `http_requests_total`, `llm_tokens_total` (chỉ tăng). **Gauge:** `agent_in_flight_requests` (lên xuống theo số request đang xử lý). **Histogram:** `llm_request_duration_seconds` (các series `_bucket`, `_count`, `_sum`; p95 tính bằng `histogram_quantile`).
2. **Nếu dùng URL thật làm label `route`:** mỗi URL lạ mà bot quét (`/wp-admin`, `/.env`, `/a1b2c3`...) sẽ tạo một time series mới cho mọi metric có label đó, nhân thêm với các label khác (method, status). Số series tăng không giới hạn (cardinality bùng nổ), Prometheus tốn RAM và chậm dần tới mức sập. Dùng route template, và gán `unmatched` cho URL không khớp route nào, thì số series luôn cố định.
3. **Metric mới:** `agent_question_length_chars` là Histogram với bucket `(20, 50, 100, 200, 500, 1000, 2000)`, gọi `observe(len(question))` trong `ask()`. Dùng bucket chứ không dùng label `length=...`, vì độ dài có vô số giá trị. Câu hỏi ví dụ dài 40 ký tự nên `_sum` = 40.
