"""worker.py: суточное расписание 09:00 Asia/Bangkok + обработка запросов менеджера
на внеплановый сбор (несколько подряд схлопываются в один collect_once)."""
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'BankRates'))
import worker as w  # noqa: E402 — BankRates/worker.py сам импортирует rate_fetchers без пакета


def test_next_daily_run_same_day_before_nine():
    after = datetime(2026, 10, 28, 1, 0, tzinfo=timezone.utc)  # 08:00 BKK
    nxt = w._next_daily_run(after)
    assert nxt.astimezone(ZoneInfo('Asia/Bangkok')).strftime('%Y-%m-%d %H:%M') == '2026-10-28 09:00'


def test_next_daily_run_after_nine_rolls_to_tomorrow():
    after = datetime(2026, 10, 28, 3, 0, tzinfo=timezone.utc)  # 10:00 BKK
    nxt = w._next_daily_run(after)
    assert nxt.astimezone(ZoneInfo('Asia/Bangkok')).strftime('%Y-%m-%d %H:%M') == '2026-10-29 09:00'


def test_tick_runs_on_schedule_without_pending(monkeypatch):
    calls = []
    monkeypatch.setattr(w, '_pending_refresh_requests', lambda conn: [])
    monkeypatch.setattr(w, '_complete_refresh_requests', lambda conn, ids, result: calls.append(('complete', ids)))
    monkeypatch.setattr(w, 'collect_once', lambda conn, key: calls.append(('collect',)) or {'SCB': 'ok'})
    now = datetime(2026, 10, 28, 3, 0, tzinfo=timezone.utc)
    result = w._tick(conn=object(), bangkok_bank_api_key='', next_daily_at=now, now=now)
    assert calls == [('collect',)]
    assert result > now


def test_tick_collapses_multiple_pending_requests(monkeypatch):
    calls = []
    monkeypatch.setattr(w, '_pending_refresh_requests', lambda conn: [1, 2, 3])
    monkeypatch.setattr(w, '_complete_refresh_requests', lambda conn, ids, result: calls.append(ids))
    monkeypatch.setattr(w, 'collect_once', lambda conn, key: calls.append('collect') or {'SCB': 'ok'})
    far_future = datetime(2099, 1, 1, tzinfo=timezone.utc)
    result = w._tick(conn=object(), bangkok_bank_api_key='', next_daily_at=far_future,
                      now=datetime.now(timezone.utc))
    assert calls == ['collect', [1, 2, 3]]
    assert result == far_future  # расписание не трогали — сбор был вызван запросом, не планом


def test_tick_noop_without_pending_or_schedule(monkeypatch):
    calls = []
    monkeypatch.setattr(w, '_pending_refresh_requests', lambda conn: [])
    monkeypatch.setattr(w, 'collect_once', lambda conn, key: calls.append('collect'))
    far_future = datetime(2099, 1, 1, tzinfo=timezone.utc)
    w._tick(conn=object(), bangkok_bank_api_key='', next_daily_at=far_future, now=datetime.now(timezone.utc))
    assert calls == []


class _FakeCursor:
    def execute(self, *a, **k):
        pass

    def fetchone(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeConn:
    def cursor(self):
        return _FakeCursor()

    def commit(self):
        pass


def test_collect_once_skips_disabled_bank_without_network(monkeypatch):
    # SCB режет запросы с серверных IP Railway (Imperva) — BANK_RATES_DISABLED
    # должен пропускать его ДО обращения к сети, чтобы не сыпать 403 в лог.
    monkeypatch.setattr(w, 'BANK_RATES_DISABLED', {'SCB'})

    def boom():
        raise AssertionError('fetch_scb не должен вызываться для отключённого банка')

    ok = w.rf.SourceValue(value=w.Decimal('33.5'), source_timestamp='2026-10-28 09:00:00')
    monkeypatch.setattr(w.rf, 'fetch_scb', boom)
    monkeypatch.setattr(w.rf, 'fetch_kasikorn', lambda: ok)
    monkeypatch.setattr(w.rf, 'fetch_bangkok_bank', lambda key: ok)
    monkeypatch.setattr(w.rf, 'validate_source_timestamp', lambda *a, **k: None)

    results = w.collect_once(_FakeConn(), bangkok_bank_api_key='key')
    assert results['SCB'] == 'disabled'
    assert results['Kasikornbank'] == 'ok'
    assert results['Bangkok Bank'] == 'ok'
