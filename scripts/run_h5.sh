#!/bin/bash
# H5 版：构建前端 + 启动接口服务。浏览器打开 http://127.0.0.1:8600
#
# 手机同一 Wi-Fi 用：HOST=0.0.0.0 scripts/run_h5.sh，再用 http://<电脑局域网 IP>:8600 打开
#   开到局域网时建议设访问密码（不设则谁打开都能看、能记账）：
#     export AW_PASSWORD_SHA256=$(printf '你的密码' | shasum -a 256 | cut -d' ' -f1)
#     HOST=0.0.0.0 scripts/run_h5.sh
#   设了以后接口都要先登录（页面会自动跳到登录页），登录有效期 180 天。
set -e
cd "$(dirname "$0")/.."
if [ ! -d web/node_modules ]; then (cd web && npm install); fi
(cd web && npm run build)
exec ./myenv/bin/python -m uvicorn api.server:app --host "${HOST:-127.0.0.1}" --port "${PORT:-8600}"
