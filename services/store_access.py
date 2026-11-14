"""Bound Store connections across the host's short-lived timer loops."""

from __future__ import annotations

import asyncio
import threading

from plugin.sdk.plugin import Err, SdkError

from . import locks


class StoreAccess:
    WAIT_SEC = 15.0

    def __init__(self, logger=lambda: None):
        self.lock = threading.Lock()
        self.logger = logger

    async def call(self, store, operation, *args):
        if not await locks.acquire(self.lock, self.WAIT_SEC):
            return Err(SdkError("backup_busy"))
        cancelled = None

        async def finish(awaitable):
            nonlocal cancelled
            task = asyncio.ensure_future(awaitable)
            while True:
                try:
                    return await asyncio.shield(task)
                except asyncio.CancelledError as exc:
                    if task.cancelled():
                        raise
                    cancelled = exc

        try:
            try:
                result = await finish(getattr(store, operation)(*args))
            finally:
                # SDK close() closes every registered connection. Serialize all
                # public operations so cleanup cannot interrupt another writer.
                close = getattr(store, "close", None)
                if callable(close):
                    try:
                        closed = await finish(close())
                        if isinstance(closed, Err):
                            self._warn_close()
                    except Exception:
                        self._warn_close()
            if cancelled is not None:
                raise cancelled
            return result
        finally:
            self.lock.release()

    def _warn_close(self):
        logger = self.logger()
        if logger is not None:
            logger.warning("store connection cleanup failed; retrying after the next operation")
