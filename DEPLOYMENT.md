# Deployment Information

## Public URL

https://agent-production-72a08393.up.railway.app

## Platform

**Railway**: project `day14-agent`. Agent Part 6 được deploy từ thư mục `06-lab-complete/` bằng Railway CLI (`railway up`), build theo `Dockerfile` như cấu hình trong `06-lab-complete/railway.toml`.

| Service | Vai trò |
|---|---|
| `agent` | Agent Part 6 (FastAPI, uvicorn 2 worker), public qua URL ở trên |
| `Redis` | Redis của Railway, chỉ truy cập được qua mạng nội bộ `redis.railway.internal:6379` |

## Test Commands

Đặt `BASE` là URL public và `AGENT_API_KEY` là key đã đặt trên Railway. Key không được ghi trong repo; Lab Coach cần thì mình gửi riêng.

```bash
BASE=https://agent-production-72a08393.up.railway.app
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"     # 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"      # 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'   # 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'   # 200
```

Kết quả chạy ngày 2026-11-26:

```text
200
200
401
200
```

### Health Check

```bash
curl https://agent-production-72a08393.up.railway.app/health
# {"status":"ok","uptime_seconds":25.0,"environment":"production"}

curl https://agent-production-72a08393.up.railway.app/ready
# {"status":"ready"}          ← 200 nghĩa là agent đã kết nối được Redis trên Railway
```

### API Test (with authentication)

```bash
curl -X POST https://agent-production-72a08393.up.railway.app/ask \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"question": "What is deployment?"}'
# {"question":"What is deployment?","answer":"Deployment là quá trình đưa code từ máy bạn lên server để người khác dùng được.","model":"mock-llm","usage":{"input_tokens":4,"output_tokens":19,"cost_usd":1.2e-05}}
```

### Rate limit trên URL public (`RATE_LIMIT_PER_MINUTE=10`)

Gửi 12 request liên tiếp. 2 request kiểm tra ở trên nằm trong cùng phút nên cũng được tính, vì vậy chỉ còn 8 request trả 200:

```text
200 200 200 200 200 200 200 200 429 429 429 429

HTTP/1.1 429 Too Many Requests
retry-after: 38
{"detail":"Rate limit exceeded: 10 requests / 60s"}
```

### Script chấm với URL public

```text
$ python check_production_ready.py --static-only --public-url https://agent-production-72a08393.up.railway.app
✅ 12. Public URL ready (Railway / Render config)
     ✅ Public URL: GET https://agent-production-72a08393.up.railway.app/health → 200
```

## Environment Variables Set

Đặt cho service `agent` trên Railway bằng `railway variables --set`. Không có giá trị nào nằm trong code hay trong repo.

| Biến | Giá trị |
|---|---|
| `AGENT_API_KEY` | Chuỗi ngẫu nhiên 43 ký tự, sinh bằng `secrets.token_urlsafe(32)`; không ghi ở đây |
| `REDIS_URL` | `${{Redis.REDIS_URL}}`: biến tham chiếu của Railway, tự trỏ tới `redis.railway.internal:6379` |
| `ENVIRONMENT` | `production` |
| `RATE_LIMIT_PER_MINUTE` | `10` |
| `DAILY_BUDGET_USD` | `1.0` |
| `MONTHLY_BUDGET_USD` | `10.0` |
| `LOG_LEVEL` | `INFO` |
| `PORT` | Railway tự cấp; `CMD` trong Dockerfile nghe theo `${PORT:-8000}` |

## Các lệnh đã dùng để deploy

```bash
cd 06-lab-complete
railway login
railway init --name day14-agent
railway add --database redis
railway add --service agent
railway variables --service agent \
  --set "AGENT_API_KEY=<chuỗi ngẫu nhiên>" --set 'REDIS_URL=${{Redis.REDIS_URL}}' \
  --set ENVIRONMENT=production --set RATE_LIMIT_PER_MINUTE=10 \
  --set DAILY_BUDGET_USD=1.0 --set MONTHLY_BUDGET_USD=10.0 --set LOG_LEVEL=INFO
railway up --service agent --ci
railway domain --service agent
```

## Screenshots

- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)

## Ghi chú

Railway CLI 5.75 cảnh báo `railway.toml` (Config as Code) sẽ ngừng được hỗ trợ từ 2026-12-01, và khuyên chuyển sang `.railway/railway.ts`. Deployment hiện tại không bị ảnh hưởng. Nếu deploy lại sau ngày đó thì cần chạy `railway config migrate`.
