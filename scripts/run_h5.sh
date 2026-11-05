#!/bin/bash
# H5 原型：构建前端（有改动时）+ 启动接口服务。浏览器打开 http://127.0.0.1:8600
# 手机同一 Wi-Fi 试用：HOST=0.0.0.0 scripts/run_h5.sh，再用 http://<电脑局域网 IP>:8600 打开
#   注意：原型接口没有密码，局域网里谁打开都能看、能记账，只在家里网络临时用
set -e
cd "$(dirname "$0")/.."
if [ ! -d web/node_modules ]; then (cd web && npm install); fi
(cd web && npm run build)
exec ./myenv/bin/python -m uvicorn api.server:app --host "${HOST:-127.0.0.1}" --port "${PORT:-8600}"
