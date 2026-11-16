#!/usr/bin/env bash
# 开发结束必跑：单元测试 + 数据/口径自检。
#
#   ./myenv/bin/python scripts/check.sh     # 也可以 bash scripts/check.sh
#
# 任何一项红都返回 1。不要用「环境问题」「不影响」绕过 —— 先看堆栈、先试着修。
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

PY=./myenv/bin/python
[ -x "$PY" ] || PY=python3
fail=0

echo "== 单元测试"
if ! "$PY" -m pytest tests -q; then
  fail=1
  echo "!! 单测没全过"
fi

echo
echo "== 数据与口径自检"
if ! "$PY" scripts/doctor.py; then
  fail=1
  echo "!! 自检有红项（先试 scripts/doctor.py --fix）"
fi

echo
if [ "$fail" -eq 0 ]; then
  echo "全部通过"
else
  echo "有失败项，看上面的输出"
fi
exit "$fail"
