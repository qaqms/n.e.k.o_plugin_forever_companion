"""Exercise connection lifetimes with real SQLite and short-lived host loops."""

import asyncio
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from forever_companion.services.store_access import StoreAccess


class SqliteStore:
    def __init__(self, path, tm):
        self.path, self.tm = path, tm
        self.local = threading.local()
        self.connections = set()

    def connection(self):
        connection = getattr(self.local, "connection", None)
        if connection not in self.connections:
            connection = sqlite3.connect(self.path, check_same_thread=False)
            connection.execute("CREATE TABLE IF NOT EXISTS items (key TEXT PRIMARY KEY, value TEXT)")
            self.connections.add(connection)
            self.local.connection = connection
        return connection

    async def set(self, key, value):
        def write():
            connection = self.connection()
            connection.execute("INSERT OR REPLACE INTO items VALUES (?, ?)", (key, json.dumps(value)))
            connection.commit()
            return self.tm.Ok(None)
        return await asyncio.to_thread(write)

    async def get(self, key):
        def read():
            row = self.connection().execute("SELECT value FROM items WHERE key = ?", (key,)).fetchone()
            return self.tm.Ok(json.loads(row[0]) if row else None)
        return await asyncio.to_thread(read)

    async def keys(self, prefix):
        def read():
            keys = [row[0] for row in self.connection().execute("SELECT key FROM items")]
            return self.tm.Ok(sorted(key for key in keys if key.startswith(prefix)))
        return await asyncio.to_thread(read)

    async def close(self):
        def close():
            for connection in self.connections:
                connection.close()
            self.connections.clear()
            return self.tm.Ok(None)
        return await asyncio.to_thread(close)


def test_short_lived_loops_release_connections_and_keep_data(tmp_path, tm):
    store = SqliteStore(tmp_path / "store.db", tm)
    access = StoreAccess()
    for index in range(25):
        asyncio.run(access.call(store, "set", f"key{index}", {"value": index}))
        assert not store.connections
    assert asyncio.run(access.call(store, "get", "key24")).value == {"value": 24}
    assert len(asyncio.run(access.call(store, "keys", "key")).value) == 25
    assert not store.connections


def test_parallel_host_threads_do_not_close_each_others_connections(tmp_path, tm):
    store = SqliteStore(tmp_path / "store.db", tm)
    access = StoreAccess()

    def write(index):
        return asyncio.run(access.call(store, "set", f"key{index}", index))

    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(write, range(30)))
    assert all(isinstance(result, tm.Ok) for result in results)
    assert len(asyncio.run(access.call(store, "keys", "")).value) == 30
    assert not store.connections


def test_cancellation_waits_for_the_write_and_cleanup(tm):
    access = StoreAccess()

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []

        class Store:
            async def set(self, *_):
                entered.set()
                await release.wait()
                calls.append("written")
                return tm.Ok(None)

            async def close(self):
                calls.append("closed")
                return tm.Ok(None)

        task = asyncio.create_task(access.call(Store(), "set", "key", 1))
        await entered.wait()
        task.cancel()
        await asyncio.sleep(0)
        assert access.lock.locked() and not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert calls == ["written", "closed"]
        assert not access.lock.locked()

    asyncio.run(scenario())


def test_cleanup_failure_does_not_hide_committed_write(tm):
    messages = []
    logger = type("Logger", (), {"warning": lambda _, message: messages.append(message)})()
    access = StoreAccess(logger=lambda: logger)

    class Store:
        async def set(self, *_):
            return tm.Ok("committed")

        async def close(self):
            raise RuntimeError("private details")

    assert asyncio.run(access.call(Store(), "set", "key", 1)).value == "committed"
    assert len(messages) == 1 and "private details" not in messages[0]
    assert not access.lock.locked()
