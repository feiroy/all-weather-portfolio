#!/bin/bash
# H5 版：构建前端 + 启动接口服务。浏览器打开 http://127.0.0.1:8600
#
# 手机同一 Wi-Fi 用：HOST=0.0.0.0 scripts/run_h5.sh，再用 http://<电脑局域网 IP>:8600 打开
#   开到局域网时建议设访问密码（不设则谁打开都能看、能记账）：
#     export AW_PASSWORD_SHA256=$(printf '你的密码' | shasum -a 256 | cut -d' ' -f1)
#     HOST=0.0.0.0 scripts/run_h5.sh
#   设了以后接口都要先登录（页面会自动跳到登录页），登录有效期 180 天。
#
# Python 解释器：$AW_PYTHON → 仓库内 ./myenv → 当前 $VIRTUAL_ENV → python3 → python，取第一个装了依赖的。
set -e
cd "$(dirname "$0")/.."

PY=""
for cand in "${AW_PYTHON:-}" ./myenv/bin/python "${VIRTUAL_ENV:+$VIRTUAL_ENV/bin/python}" python3 python; do
  [ -n "$cand" ] || continue
  if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import starlette, uvicorn' 2>/dev/null; then
    PY="$cand"; break
  fi
done
if [ -z "$PY" ]; then
  echo "找不到装了 starlette/uvicorn 的 Python。" >&2
  echo "  先 pip install -r requirements.txt，或指定解释器：AW_PYTHON=/path/to/python scripts/run_h5.sh" >&2
  exit 1
fi
echo "使用 Python: $PY"

# ---- 前端构建 ----
# npm 不一定在 PATH 里（本机只有 WorkBuddy 自带的 node），按常见位置找一遍。
find_npm() {
  if command -v npm >/dev/null 2>&1; then command -v npm; return 0; fi
  for d in "$HOME"/.workbuddy/binaries/node/versions/*/bin \
           /opt/homebrew/bin /usr/local/bin \
           "$HOME"/.nvm/versions/node/*/bin \
           "$HOME"/.volta/bin; do
    [ -x "$d/npm" ] && { echo "$d/npm"; return 0; }
  done
  return 1
}

if [ "${SKIP_BUILD:-0}" = "1" ]; then
  echo "跳过前端构建（SKIP_BUILD=1），直接用现有 web/dist"
else
  NPM="$(find_npm || true)"
  if [ -n "$NPM" ]; then
    export PATH="$(dirname "$NPM"):$PATH"
    echo "使用 npm: $NPM"
    if [ ! -d web/node_modules ]; then (cd web && "$NPM" install); fi
    (cd web && "$NPM" run build)
  elif [ -f web/dist/index.html ]; then
    echo "找不到 npm，跳过前端构建，直接用已有 web/dist" >&2
    echo "  （前端源码有改动才需要构建：装 Node，或把 node 的 bin 目录加进 PATH）" >&2
  else
    echo "找不到 npm，且 web/dist 不存在 —— 无法构建前端。" >&2
    echo "  装 Node（brew install node）或把已有 node 的 bin 目录加进 PATH 后重试。" >&2
    exit 1
  fi
fi

exec "$PY" -m uvicorn api.server:app --host "${HOST:-127.0.0.1}" --port "${PORT:-8600}"
