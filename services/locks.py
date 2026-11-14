"""在 async 路径里等一把跨线程锁。

插件同时跑在三条线程上：宿主命令循环（入口/工具/面板轮询）、tide_tick、diary_write_tick
——宿主给每个定时器开一条线程、每趟 asyncio.run 一个新循环。asyncio.Lock 绑定单个循环，
不能跨线程共享，只能用 threading.Lock；而在 async 路径里阻塞等锁会卡死所在循环（持锁方
可能正在连发几次 4 秒超时的宿主 HTTP）。这里短轮询并让出循环，超时返回 False 由调用方降级。
"""

from __future__ import annotations

import asyncio
import threading
import time

_POLL_SEC = 0.02


async def acquire(lock: threading.Lock, timeout: float) -> bool:
    """在 timeout 秒内拿到锁返回 True（调用方负责 release），拿不到返回 False。"""
    if lock.acquire(blocking=False):
        return True
    deadline = time.monotonic() + max(0.0, timeout)
    while time.monotonic() < deadline:
        await asyncio.sleep(_POLL_SEC)
        if lock.acquire(blocking=False):
            return True
    return False


async def finish(awaitable):
    """Keep an in-flight persistence operation alive until its outcome is known."""
    task = asyncio.ensure_future(awaitable)
    cancelled = None
    while True:
        try:
            result = await asyncio.shield(task)
            break
        except asyncio.CancelledError as exc:
            if task.cancelled():
                raise
            cancelled = exc
    if cancelled is not None:
        raise cancelled
    return result
