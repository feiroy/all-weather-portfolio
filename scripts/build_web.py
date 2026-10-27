"""打包线上版网页到 deploy_web_pub/（只放运行需要的文件，不上传 myenv、测试、报告）。

用法：
    ./myenv/bin/python scripts/build_web.py              # 沿用已有访问密码
    ./myenv/bin/python scripts/build_web.py --password   # 生成新的随机访问密码（旧的手机书签失效）

产物 deploy_web_pub/：
    allweather/  streamlit_app/        代码
    data/                              行情、估值、净值明细、模拟账户（本机快照）
    data/fund_nav/                     自选基金净值缓存 + 全市场申购状态（本机 rebal/nav 的拷贝）
    output/nv_curves.csv               回测净值（回测表现页用）
    .streamlit/config.toml             主题
    .streamlit/secrets.toml            访问密码哈希（不进 git）
    requirements.txt  start.sh         线上安装与启动

线上环境说明（用**个人 WorkBuddy 账号**发布，手机外网可访问）：
    - 「更新数据」在线上照常可用，数据写在线上沙箱里，重新发布会被本机快照覆盖；
    - 线上录入的持仓成交不会同步回本机，真实记账以本机为准，线上主要用来看；
    - 线上沙箱拉估值可能失败（akshare 接口变更 / 无外网），valuation.py 已做兜底：
      源不可用时沿用本地数据，不弹红字。行情（data/*.csv）照常可拉。
    - 目录固定为 deploy_web_pub/，不要改目录名，否则会变成另一个应用、网址也会变。
"""
from __future__ import annotations

import argparse
import hashlib
import secrets
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "deploy_web_pub"
REBAL_NAV = Path.home() / "WorkBuddy" / "2026-10-23-10-28-09" / "rebal" / "nav"
SECRET = OUT / ".streamlit" / "secrets.toml"
PW_NOTE = ROOT / ".workbuddy" / "web_password.txt"     # 明文密码只留本机（.workbuddy 不上传、不进 git）

REQUIREMENTS = """\
streamlit>=1.66
pandas>=2.2
numpy>=1.26
altair>=5
scipy>=1.11
matplotlib>=3.7
openpyxl>=3.1
requests>=2.31
akshare>=1.17
"""

START = """\
#!/bin/sh
# 线上启动：监听平台注入的 $PORT，绑定 0.0.0.0（平台反向代理要求）
exec python -m streamlit run streamlit_app/app.py \\
  --server.port "${PORT:-8501}" --server.address 0.0.0.0 --server.headless true \\
  --server.enableCORS false --server.enableXsrfProtection false \\
  --browser.gatherUsageStats false --client.toolbarMode minimal
"""


def _copy_tree(src: Path, dst: Path, patterns=("*",)):
    for pat in patterns:
        for f in src.rglob(pat):
            if f.is_file() and "__pycache__" not in f.parts and not f.name.endswith(".pyc"):
                t = dst / f.relative_to(src)
                t.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, t)


def build(new_password: bool) -> str | None:
    old_secret = SECRET.read_text(encoding="utf-8") if SECRET.exists() else None
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()

    _copy_tree(ROOT / "allweather", OUT / "allweather", ("*.py",))
    _copy_tree(ROOT / "streamlit_app", OUT / "streamlit_app", ("*.py", "*.json"))
    _copy_tree(ROOT / "data", OUT / "data")
    (OUT / "output").mkdir()
    shutil.copy2(ROOT / "output" / "nv_curves.csv", OUT / "output" / "nv_curves.csv")
    if REBAL_NAV.exists():
        _copy_tree(REBAL_NAV, OUT / "data" / "fund_nav", ("*.csv",))
        if (REBAL_NAV.parent / "purchase_all.csv").exists():
            shutil.copy2(REBAL_NAV.parent / "purchase_all.csv", OUT / "data" / "fund_nav" / "purchase_all.csv")
    (OUT / ".streamlit").mkdir()
    shutil.copy2(ROOT / ".streamlit" / "config.toml", OUT / ".streamlit" / "config.toml")
    (OUT / "requirements.txt").write_text(REQUIREMENTS, encoding="utf-8")
    (OUT / "start.sh").write_text(START, encoding="utf-8")
    (OUT / "start.sh").chmod(0o755)

    password = None
    if new_password or not old_secret:
        password = secrets.token_urlsafe(9)          # 12 位随机密码
        digest = hashlib.sha256(password.encode()).hexdigest()
        SECRET.write_text(f'password_sha256 = "{digest}"\n', encoding="utf-8")
        PW_NOTE.parent.mkdir(parents=True, exist_ok=True)
        PW_NOTE.write_text(password + "\n", encoding="utf-8")
    else:
        SECRET.write_text(old_secret, encoding="utf-8")

    size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file()) / 1e6
    n = sum(1 for f in OUT.rglob("*") if f.is_file())
    print(f"已打包到 {OUT}：{n} 个文件，{size:.1f} MB")
    return password


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--password", action="store_true", help="生成新的随机访问密码")
    pw = build(ap.parse_args().password)
    if pw:
        print(f"新访问密码：{pw}（已保存到 {PW_NOTE}）")
