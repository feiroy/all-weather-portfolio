"""接口层的锁：必须在同一线程内可重入，且重计算不能持锁跑。

2026-11-12 的线上事故（服务整整卡死一小时）：
    `_portfolio()` 在 `with _LOCK:` 里面调 `strategy_weights()`，
    而它第一行 `_live()` 又要 `with _LOCK:` —— `threading.Lock` 不可重入，
    同一线程二次 acquire 永久阻塞，事件循环跟着挂死，**所有接口 25 秒超时无响应**。

原来的 278 条测试全绿也没拦住，因为业务逻辑全对，错的是加锁结构。
所以这里两条守护：① 锁必须是可重入的；② `_portfolio()` 在超时内必须返回。
"""
from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import api.server as S  # noqa: E402


class LockSafety(unittest.TestCase):
    def test_lock_is_reentrant(self):
        """同一线程连拿两次不能阻塞 —— 用普通 Lock 会永久挂住。"""
        done = threading.Event()

        def worker():
            with S._LOCK:
                with S._LOCK:
                    done.set()

        # 放子线程里试：真要是不可重入，阻塞的是那个 daemon 线程，不会把测试进程一起挂死
        threading.Thread(target=worker, daemon=True).start()
        self.assertTrue(done.wait(3),
                        "S._LOCK 在同一线程重入时阻塞了 —— 这会让整个服务卡死，"
                        "必须是 RLock，且不要在持锁时调用 _live()/strategy_weights()")

    def test_portfolio_does_not_deadlock(self):
        """走一遍真实路径：_portfolio() 会经 strategy_weights() 调到 _live()。"""
        if not S.AC.path_of("main").exists():
            self.skipTest("没有 main 账户，跳过（这条测试依赖仓库里的 data/accounts/main.json）")

        box = {}

        def worker():
            try:
                P, a = S._portfolio("main")
                box["ok"] = (len(P.plan["orders"]), a.get("strategy"))
            except BaseException as e:            # noqa: BLE001
                box["err"] = f"{type(e).__name__}: {e}"

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        t.join(30)
        self.assertFalse(t.is_alive(),
                         "_portfolio('main') 30 秒没返回 —— 又是持锁重入把事件循环堵死了")
        self.assertIn("ok", box, f"_portfolio 抛异常：{box.get('err')}")

    def test_live_cached_second_call_is_fast(self):
        """_live() 只该算一遍：第二次必须走缓存，否则每次切页都要重跑三策略全历史。"""
        if not S.AC.path_of("main").exists():
            self.skipTest("没有 main 账户")
        t0 = time.time()
        S._live()
        first = time.time() - t0
        t0 = time.time()
        S._live()
        second = time.time() - t0
        self.assertLess(second, 0.2, f"第二次 _live() 用了 {second:.2f}s（首次 {first:.2f}s），缓存没生效")


if __name__ == "__main__":
    unittest.main()
