"""Keep whole entry invocations outside a backup/restore, across host loops."""

from __future__ import annotations

import asyncio
import inspect
import threading
import time
from contextvars import ContextVar
from functools import wraps

from plugin.sdk.plugin import Err, SdkError

from ..core.backup import BackupError

_CURRENT = ContextVar("forever_companion_data_operation", default=None)

# 定时器每 2/10 秒一趟，碰上独占操作直接跳过这趟即可，不排队
_NO_WAIT = frozenset({"tick", "diary_write_tick"})
_EXCLUSIVE = frozenset({"startup", "reset_all", "_debug_diary_fill"})


class DataGate:
    """整段入口调用的闸：备份/恢复/重置独占，其余（面板轮询、定时器、普通入口）共享。

    三条线程会同时进门（宿主命令循环、tide_tick、diary_write_tick，各自一个事件循环），
    所以计数用 threading.Lock 保护、等待用短轮询让出循环。独占方排队期间不再放新的共享方
    进门（写者优先）：否则 5 秒一次的面板轮询和 2/10 秒的定时器首尾相接，独占方永远等不到
    空档——过去的做法是独占方见人就退，一次 256 MB 导入要分约 683 块，几乎必然中途失败。
    """

    EXCLUSIVE_WAIT_SEC = 20.0  # 等在飞的共享方（定时器里可能正跑一次模型调用）收尾
    SHARED_WAIT_SEC = 2.0  # 等一块备份分片写完；面板 ui.context 只有约 5 秒预算
    _POLL_SEC = 0.05

    def __init__(self):
        self.lock = threading.Lock()
        self.active = 0
        self.exclusive = False
        self.waiting = 0  # 排队中的独占方
        self.blocked = False

    def enter(self, exclusive=False):
        """立刻试一次，不等待。"""
        with self.lock:
            if self.exclusive or (not exclusive and (self.blocked or self.waiting)):
                return False
            if exclusive:
                if self.active:
                    return False
                self.exclusive = True
            else:
                self.active += 1
            return True

    async def acquire(self, exclusive=False, timeout=0.0):
        """在 timeout 秒内进门返回 True，否则 False（调用方回 backup_busy）。"""
        if self.enter(exclusive):
            return True
        if timeout <= 0:
            return False
        if exclusive:
            with self.lock:
                self.waiting += 1
        try:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                await asyncio.sleep(self._POLL_SEC)
                if self.blocked and not exclusive:
                    return False
                if self._enter_queued(exclusive):
                    return True
            return False
        finally:
            if exclusive:
                with self.lock:
                    self.waiting -= 1

    def _enter_queued(self, exclusive):
        # 排队中的独占方自己也计在 waiting 里，不能被写者优先挡住
        if not exclusive:
            return self.enter(False)
        with self.lock:
            if self.exclusive or self.active:
                return False
            self.exclusive = True
            return True

    def leave(self, exclusive=False):
        with self.lock:
            if exclusive:
                self.exclusive = False
            else:
                self.active -= 1


def _wrap(function, name):
    @wraps(function)
    async def guarded(self, *args, **kwargs):
        if _CURRENT.get() is self:
            return await function(self, *args, **kwargs)
        gate = self._data_gate
        startup = name == "startup"
        exclusive = name in _EXCLUSIVE
        if name == "shutdown":
            # 还主动搭话开关与数据闸无关：备份/恢复进行中、启动卡在恢复阻塞里也得先还
            await self._begin_shutdown()
        if gate.blocked and not startup:
            if name == "dashboard" and not gate.exclusive:
                return {"backup_recovery_required": True, "status": {"enabled": False}}
            return Err(SdkError("backup_recovery_required"))
        if name in _NO_WAIT:
            wait = 0.0
        elif name == "shutdown":
            wait = 0.2  # 宿主只给插件进程约 1 秒退出
        else:
            wait = gate.EXCLUSIVE_WAIT_SEC if exclusive else gate.SHARED_WAIT_SEC
        if not await gate.acquire(exclusive=exclusive, timeout=wait):
            if name == "dashboard" and not gate.blocked:
                # 面板轮询拿到 Err 会被宿主包成 {"value": ...} 当状态下发：给个标记，面板沿用上一帧
                return {"backup_busy": True}
            return Err(SdkError("backup_recovery_required" if gate.blocked else "backup_busy"))
        token = _CURRENT.set(self)
        try:
            if startup:
                await self._backup_recover()
            return await function(self, *args, **kwargs)
        except BackupError as exc:
            return Err(SdkError(exc.code))
        finally:
            _CURRENT.reset(token)
            gate.leave(exclusive=exclusive)
    return guarded


def guard_data_operations(cls):
    # SDK discovery reads the class, so preserve signatures and all decorator
    # metadata with wraps. Also cover dynamically registered debug handlers.
    for name, member in inspect.getmembers(cls, inspect.iscoroutinefunction):
        if name == "data_backup" or not member.__module__.startswith(cls.__module__):
            continue
        if name.startswith("_") and not name.startswith("_debug_"):
            continue
        setattr(cls, name, _wrap(member, name))
    return cls
