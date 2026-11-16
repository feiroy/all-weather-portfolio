#!/usr/bin/env bash
# 安装提交前自检钩子。
#
#   bash scripts/install-hooks.sh
#
# 做三件事：
#   1. 生成 .githooks/：pre-commit = 跑 scripts/check.sh；其余钩子 = 转发给公司的 ~/.git-hooks
#   2. 把本仓库的 core.hooksPath 指到 .githooks（只影响这个仓库，不动全局配置）
#   3. 打印装了什么、怎么跳过
#
# 为什么不用 .git/hooks：本机 core.hooksPath 已被公司设成 ~/.git-hooks（root 所有），
# 那个 pre-commit 只是「转发到 .git/hooks/pre-commit」的空壳，实测在本机沙箱里并不会
# 真的把 .git/hooks 里的钩子拉起来（写探针验证过：提交照样过、日志没写）。指到 .githooks 才可靠。
#
# 卸载：git config --local --unset core.hooksPath && rm -rf .githooks
set -euo pipefail
cd "$(dirname "$0")/.." || exit 1

HOOKS=.githooks
UPSTREAM="${AW_UPSTREAM_HOOKS:-$HOME/.git-hooks}"

mkdir -p "$HOOKS"
cp scripts/git-hooks/pre-commit "$HOOKS/pre-commit"
cp scripts/git-hooks/_chain "$HOOKS/_chain"
chmod +x "$HOOKS/pre-commit" "$HOOKS/_chain"

# 公司钩子逐个建转发（pre-commit 除外：我们自己接管了）
chained=()
if [ -d "$UPSTREAM" ]; then
  for f in "$UPSTREAM"/*; do
    [ -f "$f" ] || continue
    name=$(basename "$f")
    [ "$name" = "pre-commit" ] && continue
    ln -sf _chain "$HOOKS/$name"
    chained+=("$name")
  done
fi

git config --local core.hooksPath "$HOOKS"

echo "已安装：$HOOKS/pre-commit（每次 git commit 先跑 scripts/check.sh）"
if [ ${#chained[@]} -gt 0 ]; then
  echo "已转发公司钩子：${chained[*]}"
else
  echo "没找到 $UPSTREAM，只装了 pre-commit"
fi
echo "跳过：AW_SKIP_CHECK=1 git commit -m \"...\""
