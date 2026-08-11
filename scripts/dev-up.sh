#!/bin/bash
# 是真是假 · 本地开发环境一键启动
# 用法：bash scripts/dev-up.sh   （或双击 dev-up.command）
# 启动后端(8000) + 前端(5173)，进程脱离终端常驻；日志在 backend/var/logs/ 和 frontend/vite.log
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# 已在跑就不重复起
if lsof -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "[skip] 后端已在 8000 端口运行"
else
  cd "$ROOT/backend" || exit 1
  nohup .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 \
    >> var/logs/server.out 2>&1 &
  echo "[ok] 后端已启动 (pid $!)"
fi

if lsof -iTCP:5173 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "[skip] 前端已在 5173 端口运行"
else
  cd "$ROOT/frontend" || exit 1
  nohup npm run dev \
    >> vite.log 2>&1 &
  echo "[ok] 前端已启动 (pid $!)"
fi

# 就绪检查（最多等 15 秒）
for i in $(seq 1 15); do
  BACK=$(curl -s -o /dev/null -w "%{http_code}" --max-time 2 http://127.0.0.1:8000/api/v1/health)
  FRONT=$(curl -s -o /dev/null -w "%{http_code}" --max-time 2 http://localhost:5173/)
  if [ "$BACK" = "200" ] && [ "$FRONT" = "200" ]; then
    echo "[ready] 打开 http://localhost:5173 即可使用"
    exit 0
  fi
  sleep 1
done
echo "[warn] 服务未在 15 秒内就绪，请把 backend/var/logs/server.out 和 frontend/vite.log 发给我排查"
exit 1
