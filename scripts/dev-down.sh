#!/bin/bash
# 是真是假 · 停止本地开发环境
kill $(lsof -tiTCP:8000 -sTCP:LISTEN) 2>/dev/null && echo "[ok] 后端已停止"
kill $(lsof -tiTCP:5173 -sTCP:LISTEN) 2>/dev/null && echo "[ok] 前端已停止"
exit 0
