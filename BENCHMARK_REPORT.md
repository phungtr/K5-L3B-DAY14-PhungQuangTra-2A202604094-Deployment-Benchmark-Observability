# Benchmark & Observability Report — Day 14

> Mọi con số lấy từ report JSON trong [`reports/`](reports/), CSV trong [`benchmark-results/`](benchmark-results/) và ảnh trong [`screenshots/`](screenshots/).

**Họ tên:** Phung Quang Tra
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
| Quality gate | FAIL (accuracy ≥ 80%) | PASS (≥ 80%, 0 regression so với v1) | PASS (≥ 100%, 0 regression so với v2) |

**Những câu v2 trả lời sai ban đầu và cách sửa:**

| ID | Keyword bị thiếu | Đã sửa gì |
|---|---|---|
| security-02 | token, hết hạn, chữ ký | Thêm vào `KNOWLEDGE_BASE` một tài liệu so sánh JWT với API key, từ khoá kích hoạt `["jwt", "json web token"]` |
| scaling-03 | cpu, memory, custom metrics | Thêm tài liệu về Kubernetes HPA, từ khoá kích hoạt `["hpa", "autoscal", "kubernetes"]` |

Hai tài liệu được thêm ở **cuối** `KNOWLEDGE_BASE` trong `develop/utils/mock_llm.py`, với từ khoá riêng. Nhờ vậy, khi các câu khác có số từ khoá khớp bằng nhau thì vẫn chọn tài liệu cũ như trước, và `--baseline reports/eval_v2.json` xác nhận **0 regression**. Bản sửa cũng được chép sang `production/utils/mock_llm.py` để stack Docker dùng cùng knowledge base. Không sửa `golden_dataset.jsonl`.

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

### 4.1 Screenshot

- [ ] Dashboard Grafana khi đang có tải (thấy rõ Golden Signals)
- [ ] Một trace chậm trong Jaeger (thấy span nào chiếm thời gian)
- [ ] Một trace lỗi trong Jaeger (có event `exception`)
- [ ] Trang Alerts của Prometheus với ít nhất 1 alert đang **firing**

### 4.2 Thí nghiệm "phá hệ thống"

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | | | |
| B | `MOCK_SLOW_RATE=0.3` | | | |
| C | `LLM_MODEL=mock-llm-large` | | | |
| D | `docker pause` 1 instance | | | |
| E | `AGENT_VERSION=v1` | | | |

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

...

### 4.3 Debug bằng trace

Chọn 1 trace chậm nhất bạn tìm được:

- `trace_id`: ...
- Tổng thời gian: ... ms
- Span chiếm nhiều thời gian nhất: ... (... ms, ...%)
- Dòng log tương ứng (grep theo `trace_id`):

```json

```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | | | | | |
| 3 | | | | | |

**Giải thích kết quả:** Scale có cải thiện p95 không? Nút thắt nằm ở đâu?

...

---

## 6. Kết luận

- 3 điều bạn học được về benchmark & observability:
  1. ...
  2. ...
  3. ...
- Nếu đưa agent này lên production thật, bạn sẽ thêm metric / alert nào nữa?

...

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
