"""Синтетические проверки очереди: без Playwright и сетевых запросов."""
import asyncio
import threading
import time

from calculator import _PlaywrightQueue


def test_full_queue_rejects_without_starting_work():
    q = _PlaywrightQueue(max_pending=1)
    started = threading.Event()
    release = threading.Event()
    calls = []

    async def busy():
        started.set()
        await asyncio.to_thread(release.wait)
        return {'rate': 1}

    async def queued():
        calls.append('queued')
        return {'rate': 2}

    first = threading.Thread(target=lambda: q.submit(busy, timeout=2))
    first.start()
    assert started.wait(1)
    second = threading.Thread(target=lambda: q.submit(queued, timeout=0.1))
    second.start()
    deadline = time.monotonic() + 0.5
    while q.queue.qsize() != 1 and time.monotonic() < deadline:
        time.sleep(0.001)
    assert q.queue.qsize() == 1
    assert q.submit(queued, timeout=0.1) == {'error': 'queue_full'}
    second.join(1)
    release.set()
    first.join(2)
    q.queue.join()
    assert calls == []


def test_expired_queue_item_is_never_started():
    q = _PlaywrightQueue(max_pending=1)
    started = threading.Event()
    release = threading.Event()
    calls = []

    async def busy():
        started.set()
        await asyncio.to_thread(release.wait)
        return {'rate': 1}

    async def expired():
        calls.append('expired')
        return {'rate': 2}

    first = threading.Thread(target=lambda: q.submit(busy, timeout=2))
    first.start()
    assert started.wait(1)
    assert q.submit(expired, timeout=0.02) == {'error': 'queue_timeout'}
    release.set()
    first.join(2)
    q.queue.join()
    assert calls == []
