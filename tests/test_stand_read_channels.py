"""Доказательство контролируемых каналов чтения стенда (T9): read_get(op, params).

Как и в test_stand_egress.py — каждый сценарий в свежем subprocess с боеподобным
env: внутри обычного pytest-процесса conftest.py уже глушит сеть, и патчи
модуля выглядели бы работающими даже без реального guard'а.
"""
import json
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

BASE_ENV = {
    'SECRET_KEY': 'test-secret-only',
    'STAND_PASSWORD': 'test-secret-only',
    'PYTHON_DOTENV_DISABLED': '1',
    'LOCAL_NO_AUTH': '0',
    'BITRIX_WEBHOOK': 'https://bitrix.invalid/rest/fake/',
    'TELEGRAM_BOT_TOKEN': '111:fake-prod-token',
    'REF_LOGIN_BOT_TOKEN': '222:fake-ref-token',
    'GOOGLE_SA_JSON': '',
    'DOVERKA_API_KEY': 'fake-doverka-key',
    'CRM_WEBHOOK_URL': 'https://webhook.invalid/deal-completed',
    'WL_BOT_URL': 'https://wl-bot.invalid',
    'WL_BOT_API_KEY': 'fake-wl-key',
    'METRIKA_TOKEN': 'fake-metrika-token',
    'STAND_TG_CHAT': '-1009999999',
    'STAND_TG_TOKEN': '333:fake-stand-token',
    'STAND_DOCPARSE_KEY': 'fake-docparse-key',
    'STAND_PROD_RO_KEY': 'fake-prod-ro-key',
    'OPENROUTER_API_KEY': 'fake-openrouter-key',
    'HTTPS_PROXY': 'http://proxy.invalid:3128',
    'STAND_TRANSFER_POLL_ENABLED': '0',
    'REESTR_SYNC_ENABLED': '0',
    'PAYMENT_POLL_ENABLED': '0',
    'PAYIN_ADDR_BACKFILL': '0',
    'TRONSCAN_WARM_ENABLED': '0',
    'KYC_RETENTION_ENABLED': '0',
}


def run_script(body, stand_mode='1', extra_env=None, timeout=30):
    env = dict(BASE_ENV)
    if stand_mode is not None:
        env['STAND_MODE'] = stand_mode
    if extra_env:
        for key, value in extra_env.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
    preamble = textwrap.dedent(f'''
        import sys, os, json, tempfile
        sys.path.insert(0, {str(ROOT)!r})
        _workdir = tempfile.mkdtemp(prefix='stand-read-test-')
        os.environ.setdefault('DATABASE_URL', 'sqlite:///' + _workdir + '/test.db')
        def OUT(d):
            print(json.dumps(d, default=str))
    ''')
    script = preamble + '\n' + textwrap.dedent(body)
    proc = subprocess.run([sys.executable, '-c', script], env=env,
                          capture_output=True, text=True, timeout=timeout, cwd=str(ROOT))
    last_line = ''
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line:
            last_line = line
    assert last_line, (
        f'subprocess не напечатал результат.\\nSTDOUT:\\n{proc.stdout}\\nSTDERR:\\n{proc.stderr}')
    try:
        return json.loads(last_line), proc
    except json.JSONDecodeError:
        raise AssertionError(f'последняя строка stdout не JSON: {last_line!r}\\nSTDERR:\\n{proc.stderr}')


def _fake_get_server_script():
    """Фейковый HTTP-сервер, отвечающий на любой GET и запоминающий путь,
    query, метод и заголовки каждого запроса — для сверки, что канал шлёт
    ровно то, что разрешено контрактом."""
    return '''
        import threading, http.server, json as _json
        from urllib.parse import urlsplit, parse_qs

        class FakeChain(http.server.BaseHTTPRequestHandler):
            hits = []
            next_status = 200
            next_body = b'{}'
            next_headers = {}

            def _record(self):
                parts = urlsplit(self.path)
                FakeChain.hits.append({
                    'method': self.command, 'path': parts.path,
                    'query': parse_qs(parts.query),
                    'headers': {k: v for k, v in self.headers.items()},
                })

            def do_GET(self):
                self._record()
                self.send_response(FakeChain.next_status)
                for k, v in FakeChain.next_headers.items():
                    self.send_header(k, v)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(FakeChain.next_body)

            def do_POST(self):
                self._record()
                self.send_response(200); self.end_headers()

            def log_message(self, *a):
                pass

        _srv = http.server.HTTPServer(('127.0.0.1', 0), FakeChain)
        _port = _srv.server_port
        threading.Thread(target=_srv.serve_forever, daemon=True).start()
        _base = f'http://127.0.0.1:{_port}'
        import stand_egress
        stand_egress.install()
        stand_egress.allow_test_target('127.0.0.1', _port)
    '''


def test_read_get_still_sends_identity_on_wire():
    result, proc = run_script(_fake_get_server_script() + '''
        status, data, err = stand_egress.read_get('market_rapira', {}, _base_url=_base)
        OUT({'status': status, 'err': err,
             'accept_encoding': FakeChain.hits[-1]['headers'].get('Accept-Encoding')})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result == {'status': 200, 'err': None, 'accept_encoding': 'identity'}


# ───────────────────────── (A) op/param — закрытый список ──────────────────

def test_unknown_op_rejected_before_any_network():
    result, proc = run_script('''
        import stand_egress
        stand_egress.install()
        status_code, data, err = stand_egress.read_get('tron_delete_all', {'hash': 'a' * 64})
        OUT({'status_code': status_code, 'data': data, 'err': err})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result == {'status_code': None, 'data': None, 'err': 'unknown_op'}


def test_unknown_param_rejected_before_network_hits_no_server():
    result, proc = run_script(_fake_get_server_script() + '''
        import stand_egress
        stand_egress.install()
        status_code, data, err = stand_egress.read_get(
            'tron_tx_info', {'hash': 'a' * 64, 'evil': 'DROP TABLE'}, _base_url=_base)
        OUT({'err': err, 'hits': len(FakeChain.hits)})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result == {'err': 'unknown_param', 'hits': 0}


def test_missing_required_param_rejected_before_network():
    result, proc = run_script(_fake_get_server_script() + '''
        import stand_egress
        stand_egress.install()
        status_code, data, err = stand_egress.read_get('tron_tx_info', {}, _base_url=_base)
        OUT({'err': err, 'hits': len(FakeChain.hits)})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result == {'err': 'missing_param', 'hits': 0}


def test_invalid_value_rejected_client_note_not_hash_format():
    """Имя клиента/заметка не проходит как hash — форма значения, не только имя параметра."""
    result, proc = run_script(_fake_get_server_script() + '''
        import stand_egress
        stand_egress.install()
        status_code, data, err = stand_egress.read_get(
            'tron_tx_info', {'hash': 'Иван Иванов, назначение застройщику'}, _base_url=_base)
        OUT({'err': err, 'hits': len(FakeChain.hits)})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result == {'err': 'invalid_param', 'hits': 0}


def test_multi_value_param_rejected():
    result, proc = run_script(_fake_get_server_script() + '''
        import stand_egress
        stand_egress.install()
        status_code, data, err = stand_egress.read_get(
            'tron_tx_info', {'hash': ['a' * 64, 'b' * 64]}, _base_url=_base)
        OUT({'err': err, 'hits': len(FakeChain.hits)})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result == {'err': 'invalid_param', 'hits': 0}


def test_eth_chainid_only_mainnet_allowed():
    # eth_* на стенде теперь блокируются на уровне канала до всякой валидации
    # параметров (решение Карима — см. секцию ниже) — сам валидатор всё ещё
    # часть спецификации op (на случай возврата ERC-20), проверяем его вне
    # STAND_MODE, где канал ещё доходит до этой стадии.
    result, proc = run_script(_fake_get_server_script() + '''
        import stand_egress
        stand_egress.install()
        status_code, data, err = stand_egress.read_get('eth_tx_receipt', {
            'chainid': '56', 'module': 'proxy', 'action': 'eth_getTransactionReceipt',
            'txhash': '0x' + 'a' * 64}, _base_url=_base)
        OUT({'err': err, 'hits': len(FakeChain.hits)})
    ''', stand_mode='0', extra_env={'STAND_ETHERSCAN_API_KEY': 'fake-key'})
    assert proc.returncode == 0, proc.stderr
    assert result == {'err': 'invalid_param', 'hits': 0}


def test_eth_block_tag_must_be_hex():
    result, proc = run_script(_fake_get_server_script() + '''
        import stand_egress
        stand_egress.install()
        status_code, data, err = stand_egress.read_get('eth_block_by_number', {
            'chainid': '1', 'module': 'proxy', 'action': 'eth_getBlockByNumber',
            'tag': 'latest; DROP TABLE', 'boolean': 'false'}, _base_url=_base)
        OUT({'err': err, 'hits': len(FakeChain.hits)})
    ''', stand_mode='0', extra_env={'STAND_ETHERSCAN_API_KEY': 'fake-key'})
    assert proc.returncode == 0, proc.stderr
    assert result == {'err': 'invalid_param', 'hits': 0}


def test_bitazza_instrument_and_depth_fixed():
    result, proc = run_script(_fake_get_server_script() + '''
        import stand_egress
        stand_egress.install()
        _, _, err_inst = stand_egress.read_get(
            'market_bitazza', {'OMSId': 1, 'InstrumentId': 999, 'Depth': 400}, _base_url=_base)
        _, _, err_depth = stand_egress.read_get(
            'market_bitazza', {'OMSId': 1, 'InstrumentId': 5, 'Depth': 100000}, _base_url=_base)
        OUT({'err_inst': err_inst, 'err_depth': err_depth, 'hits': len(FakeChain.hits)})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result == {'err_inst': 'invalid_param', 'err_depth': 'invalid_param', 'hits': 0}


def test_prod_incomes_only_all_flag_allowed():
    result, proc = run_script(_fake_get_server_script() + '''
        import stand_egress
        stand_egress.install()
        _, _, err = stand_egress.read_get(
            'prod_incomes', {'dsn': 'postgres://leak'}, _base_url=_base)
        OUT({'err': err, 'hits': len(FakeChain.hits)})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result == {'err': 'unknown_param', 'hits': 0}


# ─────────────────── (B)/(C) URL, заголовки, ключ строит канал ─────────────

def test_tron_tx_info_reaches_fake_server_get_only_no_extra_headers():
    result, proc = run_script(_fake_get_server_script() + '''
        import stand_egress
        stand_egress.install()
        status_code, data, err = stand_egress.read_get('tron_tx_info', {'hash': 'a' * 64}, _base_url=_base)
        hit = FakeChain.hits[0]
        OUT({'status_code': status_code, 'err': err, 'hits': len(FakeChain.hits),
             'method': hit['method'], 'path': hit['path'], 'query': hit['query'],
             'has_cookie': 'Cookie' in hit['headers'], 'has_referer': 'Referer' in hit['headers'],
             'has_origin': 'Origin' in hit['headers'], 'has_pro_key': 'TRON-PRO-API-KEY' in hit['headers']})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['status_code'] == 200 and result['err'] is None and result['hits'] == 1
    assert result['method'] == 'GET'
    assert result['path'] == '/api/transaction-info'
    assert result['query'] == {'hash': ['a' * 64]}
    assert result['has_cookie'] is False and result['has_referer'] is False and result['has_origin'] is False
    assert result['has_pro_key'] is False, 'без TRONSCAN_API_KEY заголовок ключа не добавляется'


def test_tron_tx_info_adds_key_header_when_configured():
    result, proc = run_script(_fake_get_server_script() + '''
        import stand_egress
        stand_egress.install()
        stand_egress.read_get('tron_tx_info', {'hash': 'a' * 64}, _base_url=_base)
        hit = FakeChain.hits[0]
        OUT({'pro_key': hit['headers'].get('TRON-PRO-API-KEY')})
    ''', extra_env={'TRONSCAN_API_KEY': 'stand-tron-key'})
    assert proc.returncode == 0, proc.stderr
    assert result['pro_key'] == 'stand-tron-key'


def test_eth_receipt_without_stand_key_never_touches_network():
    # Вне STAND_MODE (см. секцию ниже про блок на уровне канала) — no_key
    # по-прежнему валидная причина отказа до сети сама по себе.
    result, proc = run_script(_fake_get_server_script() + '''
        import stand_egress
        stand_egress.install()
        status_code, data, err = stand_egress.read_get('eth_tx_receipt', {
            'chainid': '1', 'module': 'proxy', 'action': 'eth_getTransactionReceipt',
            'txhash': '0x' + 'a' * 64}, _base_url=_base)
        OUT({'err': err, 'hits': len(FakeChain.hits)})
    ''', stand_mode='0', extra_env={'STAND_ETHERSCAN_API_KEY': None})
    assert proc.returncode == 0, proc.stderr
    assert result == {'err': 'no_key', 'hits': 0}


def test_eth_receipt_key_goes_only_as_apikey_query_param():
    result, proc = run_script(_fake_get_server_script() + '''
        import stand_egress
        stand_egress.install()
        stand_egress.read_get('eth_tx_receipt', {
            'chainid': '1', 'module': 'proxy', 'action': 'eth_getTransactionReceipt',
            'txhash': '0x' + 'a' * 64}, _base_url=_base)
        hit = FakeChain.hits[0]
        OUT({'apikey': hit['query'].get('apikey'), 'has_auth_header': 'Authorization' in hit['headers']})
    ''', stand_mode='0', extra_env={'STAND_ETHERSCAN_API_KEY': 'stand-eth-key'})
    assert proc.returncode == 0, proc.stderr
    assert result['apikey'] == ['stand-eth-key']
    assert result['has_auth_header'] is False


def test_prod_incomes_uses_x_api_key_header_and_stand_ro_key():
    result, proc = run_script(_fake_get_server_script() + '''
        import stand_egress
        stand_egress.install()
        status_code, data, err = stand_egress.read_get('prod_incomes', {'all': 1}, _base_url=_base)
        hit = FakeChain.hits[0]
        OUT({'err': err, 'path': hit['path'], 'query': hit['query'],
             'api_key': hit['headers'].get('X-Api-Key')})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['err'] is None
    assert result['path'] == '/api/sber-incomes'
    assert result['query'] == {'all': ['1']}
    assert result['api_key'] == 'fake-prod-ro-key'  # STAND_PROD_RO_KEY из BASE_ENV


def test_prod_incomes_key_never_appears_in_chain_or_market_channel():
    """Ключ STAND_PROD_RO_KEY не должен утечь в другой канал ни в заголовках,
    ни в query — даже если оба канала дергаются подряд в одном потоке."""
    result, proc = run_script(_fake_get_server_script() + '''
        import stand_egress
        stand_egress.install()
        stand_egress.read_get('prod_incomes', {'all': 1}, _base_url=_base)
        stand_egress.read_get('tron_tx_info', {'hash': 'a' * 64}, _base_url=_base)
        chain_hit = FakeChain.hits[1]
        OUT({'chain_headers': list(chain_hit['headers'].keys()),
             'leak_in_header': any('fake-prod-ro-key' in v for v in chain_hit['headers'].values()),
             'leak_in_query': any('fake-prod-ro-key' in str(v) for v in chain_hit['query'].values())})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['leak_in_header'] is False
    assert result['leak_in_query'] is False


def test_prod_incomes_key_not_in_status_or_stdout():
    result, proc = run_script(_fake_get_server_script() + '''
        import stand_egress
        stand_egress.install()
        stand_egress.read_get('prod_incomes', {'all': 1}, _base_url=_base)
        st = stand_egress.status()
        OUT({'status_dump': json.dumps(st, default=str)})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert 'fake-prod-ro-key' not in result['status_dump']
    assert 'fake-prod-ro-key' not in proc.stdout
    assert 'fake-prod-ro-key' not in proc.stderr


# ───────────────────────── (D) редиректы/ошибки/размер ─────────────────────

def test_redirect_not_followed():
    result, proc = run_script(_fake_get_server_script() + '''
        import stand_egress
        stand_egress.install()
        FakeChain.next_status = 307
        FakeChain.next_headers = {'Location': 'https://attacker-exfil.invalid/steal'}
        status_code, data, err = stand_egress.read_get('tron_tx_info', {'hash': 'a' * 64}, _base_url=_base)
        OUT({'status_code': status_code, 'err': err, 'hits': len(FakeChain.hits)})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result == {'status_code': 307, 'err': 'redirect_blocked', 'hits': 1}


def test_invalid_json_response_returns_stable_error():
    result, proc = run_script(_fake_get_server_script() + '''
        import stand_egress
        stand_egress.install()
        FakeChain.next_body = b'<html>not json</html>'
        status_code, data, err = stand_egress.read_get('market_rapira', {}, _base_url=_base)
        OUT({'status_code': status_code, 'data': data, 'err': err})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result == {'status_code': 200, 'data': None, 'err': 'invalid_json'}


def test_response_too_large_rejected():
    result, proc = run_script(_fake_get_server_script() + '''
        import stand_egress
        stand_egress.install()
        big = b'[' + b'1,' * (3 * 1024 * 1024) + b'1]'
        FakeChain.next_body = big
        status_code, data, err = stand_egress.read_get('market_rapira', {}, _base_url=_base)
        OUT({'err': err, 'data': data})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result == {'err': 'response_too_large', 'data': None}


def test_timeout_is_stable_error_without_url_or_key_leak():
    result, proc = run_script('''
        import os
        import stand_egress
        stand_egress.install()
        port = int(os.environ['CALCCRM_FENCE_PORT_START']) + 63
        stand_egress.allow_test_target('127.0.0.1', port)  # свой порт, но никто не слушает
        status_code, data, err = stand_egress.read_get(
            'prod_incomes', {'all': 1}, _base_url=f'http://127.0.0.1:{port}')
        OUT({'status_code': status_code, 'data': data, 'err': err})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['status_code'] is None and result['data'] is None
    assert result['err'] in ('network_error', 'timeout')
    assert 'fake-prod-ro-key' not in proc.stdout and 'fake-prod-ro-key' not in proc.stderr


def test_set_cookie_not_applied_across_calls():
    result, proc = run_script(_fake_get_server_script() + '''
        import stand_egress
        stand_egress.install()
        FakeChain.next_headers = {'Set-Cookie': 'session=stolen; Path=/'}
        stand_egress.read_get('market_rapira', {}, _base_url=_base)
        FakeChain.next_headers = {}
        stand_egress.read_get('market_rapira', {}, _base_url=_base)
        second_hit = FakeChain.hits[1]
        OUT({'sent_cookie_on_second_call': 'Cookie' in second_hit['headers']})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['sent_cookie_on_second_call'] is False


# ───────────────────────── (E) разрешение только на время вызова ───────────

def test_read_ctx_cleared_after_call_in_same_thread():
    result, proc = run_script(_fake_get_server_script() + '''
        import stand_egress
        stand_egress.install()
        stand_egress.read_get('tron_tx_info', {'hash': 'a' * 64}, _base_url=_base)
        OUT({'active_after': getattr(stand_egress._read_ctx, 'active', False),
             'pairs_after': list(getattr(stand_egress._read_ctx, 'allowed_pairs', set()))})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['active_after'] is False
    assert result['pairs_after'] == []


def test_neighbor_thread_does_not_inherit_read_permission():
    """thread-local: разрешение канала выставлено (белым ящиком, без гонки по
    времени) в одном потоке — сосед в другом потоке его не видит, свой поток
    видит по-прежнему."""
    result, proc = run_script('''
        import threading
        import stand_egress
        stand_egress.install()

        stand_egress._read_ctx.active = True
        stand_egress._read_ctx.host = 'apilist.tronscanapi.com'

        neighbor = {}
        def probe():
            neighbor['allowed'] = stand_egress._hostname_allowed('apilist.tronscanapi.com', 443)
        t = threading.Thread(target=probe)
        t.start(); t.join()

        main_allowed = stand_egress._hostname_allowed('apilist.tronscanapi.com', 443)
        OUT({'neighbor_allowed': neighbor['allowed'], 'main_allowed': main_allowed})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['neighbor_allowed'] is False
    assert result['main_allowed'] is True


# ───────────────────── (F) запрещённые синки во время чтения ───────────────

def test_forbidden_sinks_get_zero_hits_during_allowed_read():
    result, proc = run_script(_fake_get_server_script() + '''
        import stand_egress
        stand_egress.install()

        blocked = {'bitrix': False, 'tg_group': False}
        import requests
        try:
            requests.get('https://bitrix.invalid/rest/fake/crm.deal.list', timeout=1)
        except requests.exceptions.ConnectionError:
            blocked['bitrix'] = True

        res = stand_egress.tg_call('sendMessage', {'chat_id': -1009999999, 'text': 'leak'})
        blocked['tg_group'] = res.get('error') in ('denied', 'no_token') or not res.get('ok')

        status_code, data, err = stand_egress.read_get('tron_tx_info', {'hash': 'a' * 64}, _base_url=_base)
        OUT({'blocked': blocked, 'read_ok': err is None, 'chain_hits': len(FakeChain.hits)})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['blocked']['bitrix'] is True
    assert result['blocked']['tg_group'] is True
    assert result['read_ok'] is True
    assert result['chain_hits'] == 1


def test_global_allowlist_not_widened_by_installing_read_channels():
    """Установка guard'а и вызов read_get не открывают произвольный хост —
    неразрешённый внешний хост всё ещё блокируется по имени до DNS."""
    result, proc = run_script('''
        import stand_egress
        stand_egress.install()
        stand_egress.read_get('unknown_op_noop', {})  # заведомо неизвестный op, до сети
        import requests
        blocked = False
        try:
            requests.get('https://random-external-host.invalid/', timeout=1)
        except requests.exceptions.ConnectionError:
            blocked = True
        OUT({'blocked': blocked})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['blocked'] is True


def test_stand_mode_0_read_get_not_gated_by_guard_prod_unaffected():
    """Негативный контроль: вне STAND_MODE install() — no-op, read_get работает
    как обычный HTTP-вызов к _base_url — T9 не меняет поведение прода."""
    result, proc = run_script(_fake_get_server_script() + '''
        import stand_egress
        installed = stand_egress.install()
        status_code, data, err = stand_egress.read_get('tron_tx_info', {'hash': 'a' * 64}, _base_url=_base)
        OUT({'installed': installed, 'status_code': status_code, 'err': err})
    ''', stand_mode='0')
    assert proc.returncode == 0, proc.stderr
    assert result['installed'] is False
    assert result['status_code'] == 200 and result['err'] is None


# ───────────────── (G) неверные ответы сети не подтверждают перевод ────────

def test_verify_transfer_mismatch_on_wrong_receiver_via_channel():
    result, proc = run_script(_fake_get_server_script() + '''
        import stand_egress
        stand_egress.install()
        import stand_transfers as st

        def fake_read_get(op, params=None, _base_url=None):
            assert op == 'tron_tx_info'
            return 200, {
                'hash': 'a' * 64, 'confirmed': True, 'contractRet': 'SUCCESS', 'revert': False,
                'timestamp': 1700000000000,
                'trc20TransferInfo': [{
                    'contract_address': st.TRON_USDT,
                    'from_address': 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn',
                    'to_address': 'TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ',  # не тот получатель
                    'type': 'Transfer', 'status': 0,
                    'amount_str': '100000000', 'decimals': 6,
                }],
            }, None
        stand_egress.read_get = fake_read_get

        r = st.verify_transfer('a' * 64, 'trc20', 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn',
                               'TVmgzMQ2zwV2DVPscBf98WRRdhrcpf5x5p', 100)
        OUT({'status': r['status']})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['status'] == 'mismatch'


def test_verify_transfer_failed_on_reverted_tx_via_channel():
    result, proc = run_script('''
        import stand_egress
        stand_egress.install()
        import stand_transfers as st

        def fake_read_get(op, params=None, _base_url=None):
            return 200, {'hash': 'a' * 64, 'revert': True, 'contractRet': 'REVERT'}, None
        stand_egress.read_get = fake_read_get

        r = st.verify_transfer('a' * 64, 'trc20', 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn',
                               'TVmgzMQ2zwV2DVPscBf98WRRdhrcpf5x5p', 100)
        OUT({'status': r['status']})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['status'] == 'failed'


def test_verify_transfer_confirmed_only_on_full_match_via_channel():
    result, proc = run_script('''
        import stand_egress
        stand_egress.install()
        import stand_transfers as st

        def fake_read_get(op, params=None, _base_url=None):
            return 200, {
                'hash': 'a' * 64, 'confirmed': True, 'contractRet': 'SUCCESS', 'revert': False,
                'timestamp': 1700000000000,
                'trc20TransferInfo': [{
                    'contract_address': st.TRON_USDT,
                    'from_address': 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn',
                    'to_address': 'TVmgzMQ2zwV2DVPscBf98WRRdhrcpf5x5p',
                    'type': 'Transfer', 'status': 0,
                    'amount_str': '100000000', 'decimals': 6,
                }],
            }, None
        stand_egress.read_get = fake_read_get

        r = st.verify_transfer('a' * 64, 'trc20', 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn',
                               'TVmgzMQ2zwV2DVPscBf98WRRdhrcpf5x5p', 100)
        OUT({'status': r['status'], 'amount': r.get('verifiedAmount')})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['status'] == 'confirmed'
    assert result['amount'] == 100.0


def test_calculator_rates_never_fabricates_on_channel_error():
    result, proc = run_script('''
        import stand_egress
        stand_egress.install()
        import asyncio
        from calculator import ExchangeRateProvider

        stand_egress.read_get = lambda op, params=None, _base_url=None: (None, None, 'network_error')
        rates = asyncio.run(ExchangeRateProvider.get_all_rates())
        OUT(rates)
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result == {'usdt_thb': None, 'rub_usdt': None}


def test_calculator_rates_uses_channel_values_when_available():
    result, proc = run_script('''
        import stand_egress
        stand_egress.install()
        import asyncio
        from calculator import ExchangeRateProvider

        def fake_read_get(op, params=None, _base_url=None):
            if op == 'market_binance_th_ticker':
                return 200, {'symbol': 'USDTTHB', 'price': '32.5'}, None
            if op == 'market_binance_ticker':
                raise AssertionError('Global — только фоллбэк, TH уже ответил')
            if op == 'market_rapira':
                return 200, {'data': [{'symbol': 'USDT/RUB', 'askPrice': '81.0'}]}, None
            raise AssertionError(op)
        stand_egress.read_get = fake_read_get

        rates = asyncio.run(ExchangeRateProvider.get_all_rates())
        OUT(rates)
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['usdt_thb'] == 32.5
    assert result['rub_usdt'] == 81.0 * 1.0  # RAPIRA_MARKUP=1.0, наценка прода отдельно


# ───────────── QA-раунд (соведущий gpt-6-sol, thr_bhbwaywxwr) по 6b5e190 ────

def test_calculator_rates_falls_back_to_binance_global_when_th_fails():
    result, proc = run_script('''
        import stand_egress
        stand_egress.install()
        import asyncio
        from calculator import ExchangeRateProvider

        def fake_read_get(op, params=None, _base_url=None):
            if op == 'market_binance_th_ticker':
                return None, None, 'network_error'  # TH недоступен
            if op == 'market_binance_ticker':
                return 200, {'symbol': 'USDTTHB', 'price': '33.1'}, None
            if op == 'market_rapira':
                return 200, {'data': [{'symbol': 'USDT/RUB', 'askPrice': '82.0'}]}, None
            raise AssertionError(op)
        stand_egress.read_get = fake_read_get

        rates = asyncio.run(ExchangeRateProvider.get_all_rates())
        OUT(rates)
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['usdt_thb'] == 33.1


def test_calculator_rates_rejects_nan_and_infinity_price():
    result, proc = run_script('''
        import stand_egress
        stand_egress.install()
        import asyncio
        from calculator import ExchangeRateProvider

        out = {}
        for label, price in [('nan', 'NaN'), ('inf', 'Infinity'), ('neg', '-5'), ('zero', '0')]:
            def fake_read_get(op, params=None, _base_url=None, _price=price):
                # TH и Global оба «отвечают» тем же мусором — фоллбэк на
                # Global не спасает, итог должен остаться None.
                if op in ('market_binance_th_ticker', 'market_binance_ticker'):
                    return 200, {'symbol': 'USDTTHB', 'price': _price}, None
                if op == 'market_rapira':
                    return 200, {'data': []}, None
                raise AssertionError(op)
            stand_egress.read_get = fake_read_get
            out[label] = asyncio.run(ExchangeRateProvider.get_all_rates())['usdt_thb']
        OUT(out)
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result == {'nan': None, 'inf': None, 'neg': None, 'zero': None}


def test_calculator_rates_rejects_nan_and_infinity_rapira_ask():
    result, proc = run_script('''
        import stand_egress
        stand_egress.install()
        import asyncio
        from calculator import ExchangeRateProvider

        def fake_read_get(op, params=None, _base_url=None):
            if op == 'market_binance_th_ticker':
                return 200, {'symbol': 'USDTTHB', 'price': '32.0'}, None
            if op == 'market_rapira':
                return 200, {'data': [{'symbol': 'USDT/RUB', 'askPrice': 'Infinity'}]}, None
            raise AssertionError(op)
        stand_egress.read_get = fake_read_get

        rates = asyncio.run(ExchangeRateProvider.get_all_rates())
        OUT(rates)
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['rub_usdt'] is None


# ── B: _base_url — только зарегистрированный loopback, иначе invalid_base_url

def test_base_url_bypass_attempts_all_rejected_before_network():
    result, proc = run_script(_fake_get_server_script() + '''
        candidates = [
            'https://api.binance.com.evil',
            'https://api.binance.com@evil',
            'https://api.binance.com//evil',
            'https://api.binance.com/../evil',
            'https://api.binance.com/%2f',
            'https://api.binance.com\\\\evil',
            'https://api.binance.com.',
            'https://127.0.0.1',              # без порта (allow_test_target требует точный порт)
            'https://[::1]',
            'https://169.254.169.254:{0}'.format(_port),  # link-local, не loopback
            f'http://127.0.0.1:{_port + 1}',   # другой порт — не зарегистрирован
        ]
        out = []
        for v in candidates:
            _, _, err = stand_egress.read_get('market_rapira', {}, _base_url=v)
            out.append([v, err])
        OUT({'cases': out, 'hits': len(FakeChain.hits)})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['hits'] == 0, 'ни один обход не должен был дойти до фейкового сервера'
    for value, err in result['cases']:
        assert err == 'invalid_base_url', f'{value} должен быть отклонён, получили {err}'


def test_base_url_registered_loopback_target_is_allowed():
    result, proc = run_script(_fake_get_server_script() + '''
        _, _, err = stand_egress.read_get('market_rapira', {}, _base_url=_base)
        OUT({'err': err, 'hits': len(FakeChain.hits)})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result == {'err': None, 'hits': 1}


def test_base_url_with_own_path_rejected_not_silently_stripped():
    """_base_url обязан указывать голый host:port — путь в спецификации
    op'а, а не в _base_url. Лишний путь в тестовом override отклоняется до
    сети, а не молча отбрасывается (fail-closed, не «угадать намерение»)."""
    result, proc = run_script(_fake_get_server_script() + '''
        _, _, err = stand_egress.read_get('market_rapira', {}, _base_url=_base + '/smuggled/path')
        OUT({'err': err, 'hits': len(FakeChain.hits)})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result == {'err': 'invalid_base_url', 'hits': 0}


# ── D2: стабильные коды по статусу, без выдумывания курса на 429/5xx

def test_http_429_and_5xx_map_to_stable_error_codes():
    result, proc = run_script(_fake_get_server_script() + '''
        FakeChain.next_status = 429
        _, _, err_429 = stand_egress.read_get('market_rapira', {}, _base_url=_base)
        FakeChain.next_status = 500
        _, _, err_500 = stand_egress.read_get('market_rapira', {}, _base_url=_base)
        FakeChain.next_status = 404
        _, _, err_404 = stand_egress.read_get('market_rapira', {}, _base_url=_base)
        OUT({'err_429': err_429, 'err_500': err_500, 'err_404': err_404})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result == {'err_429': 'http_429', 'err_500': 'http_5xx', 'err_404': 'http_4xx'}


def test_read_body_without_real_socket_is_stable_read_error_not_raise():
    """QA-раунд 5: тело читается своим циклом с сырого сокета ответа, не через
    resp.raw.read() — фейковый Session.get без настоящего сокета (какой бы ни
    была причина: таймаут, обрыв протокола, что угодно) не может быть прочитан
    вообще и отклоняется сразу как read_error, а не гадает по типу исключения
    фейкового .raw.read(), которое теперь и не вызывается."""
    result, proc = run_script('''
        import urllib3
        from unittest.mock import patch
        import stand_egress

        class RaisingRaw:
            def __init__(self, exc):
                self._exc = exc
            def read(self, *a, **k):
                raise self._exc

        class FakeResp:
            def __init__(self, exc):
                self.status_code = 200
                self.raw = RaisingRaw(exc)
            def close(self):
                pass

        out = {}
        with patch('requests.Session.get', return_value=FakeResp(urllib3.exceptions.ReadTimeoutError(None, None, 'timeout'))):
            _, _, out['read_timeout'] = stand_egress.read_get('market_rapira', {})
        with patch('requests.Session.get', return_value=FakeResp(urllib3.exceptions.ProtocolError('broken'))):
            _, _, out['read_error'] = stand_egress.read_get('market_rapira', {})
        OUT(out)
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result == {'read_timeout': 'read_error', 'read_error': 'read_error'}


# ── E2: guard-разрешение — только на время своего connect(), не всей операции

def test_direct_socket_during_faked_session_get_is_blocked():
    """Session.get полностью подменена (как это делает тест соведущего) — наш
    собственный connect() ни разу не вызывается, поэтому окно разрешения не
    открывается вовсе, и прямой сокет в тот же host:443 в том же потоке
    блокируется — не «разрешение на весь вызов», а «разрешение на свой connect»."""
    result, proc = run_script('''
        import socket
        from unittest.mock import patch
        import stand_egress
        stand_egress.install()

        sent = []
        def lower(self, address):
            sent.append(address)
        with patch.object(stand_egress, '_orig_connect', lower):
            def fake_get(self, url, **kw):
                s = socket.socket()
                try:
                    s.connect(('api.rapira.net', 443))
                except Exception:
                    pass
                finally:
                    s.close()
                class Raw:
                    def read(self, *a, **k):
                        return b'{}'
                class Resp:
                    status_code = 200
                    raw = Raw()
                    def close(self):
                        pass
                return Resp()
            with patch('requests.Session.get', fake_get):
                stand_egress.read_get('market_rapira', {})
        OUT({'reached_lower_connect': sent})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['reached_lower_connect'] == []


def test_own_channel_connect_still_reaches_fake_server():
    """Контрольная проверка к E2: когда read_get реально сам открывает
    соединение (не подменённый Session.get), фейковый сервер получает запрос —
    сужение окна разрешения не сломало обычную работу канала."""
    result, proc = run_script(_fake_get_server_script() + '''
        _, _, err = stand_egress.read_get('market_rapira', {}, _base_url=_base)
        OUT({'err': err, 'hits': len(FakeChain.hits)})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result == {'err': None, 'hits': 1}


# ── I: прямые вызовы TronScan/Etherscan в CRM (app.py) — только через read_get

def test_app_tron_tx_info_uses_channel_not_direct_get_on_stand():
    result, proc = run_script('''
        from unittest.mock import patch
        import stand_egress
        stand_egress.install()
        import app

        calls = []
        def fake_direct_get(*a, **k):
            calls.append([a, k])
            class R:
                status_code = 200
                def json(self):
                    return {'trc20TransferInfo': []}
            return R()

        def fake_read_get(op, params=None, _base_url=None):
            assert op == 'tron_tx_info'
            assert params == {'hash': 'a' * 64}
            return 200, {'trc20TransferInfo': []}, None
        with patch('requests.get', side_effect=fake_direct_get), \
             patch.object(stand_egress, 'read_get', fake_read_get):
            result = app._tron_tx_info('a' * 64)
        OUT({'direct_get_calls': len(calls), 'result': result})
    ''', extra_env={'SECRET_KEY': 'test-secret', 'STAND_PASSWORD': 'test-password',
                     'LOCAL_NO_AUTH': '0'})
    assert proc.returncode == 0, proc.stderr
    assert result['direct_get_calls'] == 0
    assert result['result'] == {'amount_usdt': None, 'total_out_usdt': None,
                                 'extra_out_usdt': 0, 'from_address': None,
                                 'to_address': None, 'transfer_count': 0} or result['result'] == {}


def test_app_etherscan_tx_info_uses_channel_not_direct_get_on_stand():
    result, proc = run_script('''
        from unittest.mock import patch
        import stand_egress
        stand_egress.install()
        import app

        calls = []
        def fake_direct_get(*a, **k):
            calls.append([a, k])
            raise AssertionError('прямой requests.get не должен вызываться на стенде')

        def fake_read_get(op, params=None, _base_url=None):
            assert op == 'eth_tx_receipt'
            assert 'apikey' not in (params or {})
            return 200, {'result': None}, None
        with patch('requests.get', side_effect=fake_direct_get), \
             patch.object(stand_egress, 'read_get', fake_read_get):
            result = app._etherscan_tx_info('0x' + 'a' * 64)
        OUT({'direct_get_calls': len(calls), 'result': result})
    ''', extra_env={'SECRET_KEY': 'test-secret', 'STAND_PASSWORD': 'test-password',
                     'LOCAL_NO_AUTH': '0', 'STAND_ETHERSCAN_API_KEY': 'stand-eth-key'})
    assert proc.returncode == 0, proc.stderr
    assert result['direct_get_calls'] == 0
    assert result['result'] == {}


def test_app_etherscan_tx_info_without_stand_key_returns_empty_no_channel_call():
    result, proc = run_script('''
        from unittest.mock import patch
        import stand_egress
        stand_egress.install()
        import app

        def fake_read_get(*a, **k):
            raise AssertionError('без STAND_ETHERSCAN_API_KEY канал не должен вызываться')
        with patch.object(stand_egress, 'read_get', fake_read_get):
            result = app._etherscan_tx_info('0x' + 'a' * 64)
        OUT({'result': result})
    ''', extra_env={'SECRET_KEY': 'test-secret', 'STAND_PASSWORD': 'test-password',
                     'LOCAL_NO_AUTH': '0', 'STAND_ETHERSCAN_API_KEY': None})
    assert proc.returncode == 0, proc.stderr
    assert result['result'] == {}


# ───────── QA-раунд 2 (лидер): /api/wallets, сверка кошельков — новые op ────

_VALID_TRON_ADDR = 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn'  # grusha, из DEFAULT_WALLETS


def test_tron_account_balance_valid_address_reaches_fake_server():
    result, proc = run_script(_fake_get_server_script() + f'''
        status_code, data, err = stand_egress.read_get(
            'tron_account_balance', {{'address': {_VALID_TRON_ADDR!r}}}, _base_url=_base)
        OUT({{'err': err, 'path': FakeChain.hits[0]['path'] if FakeChain.hits else None,
             'query': FakeChain.hits[0]['query'] if FakeChain.hits else None}})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['err'] is None
    assert result['path'] == '/api/account'
    assert result['query'] == {'address': [_VALID_TRON_ADDR]}


def test_tron_account_balance_rejects_bad_checksum_before_network():
    result, proc = run_script(_fake_get_server_script() + '''
        # Последний символ испорчен — длина и алфавит верные, но контрольная сумма нет.
        bad = 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqX'
        _, _, err = stand_egress.read_get('tron_account_balance', {'address': bad}, _base_url=_base)
        OUT({'err': err, 'hits': len(FakeChain.hits)})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result == {'err': 'invalid_param', 'hits': 0}


def test_tron_account_balance_rejects_non_address_garbage():
    result, proc = run_script(_fake_get_server_script() + '''
        out = []
        for garbage in ['not-an-address', 'Иван Иванов', '0x' + 'a' * 40, 'T' + 'x' * 33, '']:
            _, _, err = stand_egress.read_get('tron_account_balance', {'address': garbage}, _base_url=_base)
            out.append(err)
        OUT({'errs': out, 'hits': len(FakeChain.hits)})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result == {'errs': ['invalid_param'] * 5, 'hits': 0}


def test_tron_account_tokens_same_address_validation_and_path():
    result, proc = run_script(_fake_get_server_script() + f'''
        _, _, err = stand_egress.read_get('tron_account_tokens', {{'address': {_VALID_TRON_ADDR!r}}}, _base_url=_base)
        OUT({{'err': err, 'path': FakeChain.hits[0]['path'] if FakeChain.hits else None}})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result == {'err': None, 'path': '/api/account/tokens'}


def test_tron_trc20_transfers_requires_fixed_usdt_contract():
    result, proc = run_script(_fake_get_server_script() + f'''
        _, _, err_wrong = stand_egress.read_get('tron_trc20_transfers', {{
            'relatedAddress': {_VALID_TRON_ADDR!r}, 'contract_address': 'TSomeOtherContract1111111111111111',
            'limit': 50, 'start': 0}}, _base_url=_base)
        _, _, err_ok = stand_egress.read_get('tron_trc20_transfers', {{
            'relatedAddress': {_VALID_TRON_ADDR!r}, 'contract_address': 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t',
            'limit': 50, 'start': 0}}, _base_url=_base)
        OUT({{'err_wrong': err_wrong, 'err_ok': err_ok, 'hits': len(FakeChain.hits)}})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result == {'err_wrong': 'invalid_param', 'err_ok': None, 'hits': 1}


def test_tron_trc20_transfers_limit_and_start_bounded():
    result, proc = run_script(_fake_get_server_script() + f'''
        base_params = {{'relatedAddress': {_VALID_TRON_ADDR!r},
                        'contract_address': 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t'}}
        out = {{}}
        for label, extra in [
            ('limit_zero', {{'limit': 0, 'start': 0}}),
            ('limit_too_big', {{'limit': 51, 'start': 0}}),
            ('start_negative', {{'limit': 50, 'start': -1}}),
            ('start_too_big', {{'limit': 50, 'start': 100000}}),
            ('ok', {{'limit': 50, 'start': 50}}),
        ]:
            _, _, err = stand_egress.read_get('tron_trc20_transfers', {{**base_params, **extra}}, _base_url=_base)
            out[label] = err
        OUT({{'errs': out, 'hits': len(FakeChain.hits)}})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['errs'] == {'limit_zero': 'invalid_param', 'limit_too_big': 'invalid_param',
                              'start_negative': 'invalid_param', 'start_too_big': 'invalid_param',
                              'ok': None}
    assert result['hits'] == 1


# ── runtime: при STAND_MODE ни один прямой requests.get к TronScan/Etherscan
# из CRM-функций app.py не выполняется — read_get вызывается вместо него.

def test_app_wallet_functions_never_call_requests_get_directly_on_stand():
    result, proc = run_script('''
        from unittest.mock import patch
        import stand_egress
        stand_egress.install()
        import app

        direct_calls = []
        def fake_direct_get(*a, **k):
            direct_calls.append(a[0] if a else k.get('url'))
            raise AssertionError('прямой requests.get не должен вызываться на стенде')

        def fake_read_get(op, params=None, _base_url=None):
            if op in ('tron_account_balance', 'tron_account_tokens'):
                return 200, {'address': 'x', 'balance': 1000000, 'trc20token_balances': []}, None
            if op == 'tron_trc20_transfers':
                return 200, {'token_transfers': []}, None
            if op == 'tron_tx_info':
                return 200, {'trc20TransferInfo': []}, None
            raise AssertionError(f'unexpected op {op}')

        addr = 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn'
        with patch('requests.get', side_effect=fake_direct_get), \\
             patch.object(stand_egress, 'read_get', fake_read_get):
            balances = app._tron_balances(addr)
            transfers = app._tron_usdt_transfers(addr)
            tx_amount = app._tron_tx_usdt_amount('a' * 64)
            to_addr = app._tron_tx_to_address('a' * 64)

        OUT({'direct_calls': direct_calls, 'balances': balances, 'transfers': transfers,
             'tx_amount': tx_amount, 'to_addr': to_addr})
    ''', extra_env={'SECRET_KEY': 'test-secret', 'STAND_PASSWORD': 'test-password',
                     'LOCAL_NO_AUTH': '0', 'PYTEST_CURRENT_TEST': None})
    assert proc.returncode == 0, proc.stderr
    assert result['direct_calls'] == []
    assert result['balances'] == [0.0, 1.0]
    assert result['transfers'] == []


def test_app_wallets_routes_never_call_requests_get_directly_on_stand():
    result, proc = run_script('''
        from unittest.mock import patch
        import stand_egress
        stand_egress.install()
        import app
        app.app.config['TESTING'] = True
        app.limiter.enabled = False
        client = app.app.test_client()

        db = app.get_session()
        try:
            admin = app.AdminUser(username='adm-wallets-test', role='admin', password_hash=b'x')
            db.add(admin); db.commit(); admin_id = admin.id
        finally:
            db.close()
        with client.session_transaction() as sess:
            sess['user_id'] = admin_id

        direct_calls = []
        def fake_direct_get(*a, **k):
            direct_calls.append(a[0] if a else k.get('url'))
            raise AssertionError('прямой requests.get не должен вызываться на стенде')

        def fake_read_get(op, params=None, _base_url=None):
            if op in ('tron_account_balance', 'tron_account_tokens'):
                return 200, {'address': 'x', 'balance': 2000000, 'trc20token_balances': []}, None
            raise AssertionError(f'unexpected op {op}')

        with patch('requests.get', side_effect=fake_direct_get), \\
             patch.object(stand_egress, 'read_get', fake_read_get):
            r1 = client.get('/api/wallets')
            r2 = client.post('/api/wallets', json={'address': 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn'})

        OUT({'direct_calls': direct_calls, 'get_status': r1.status_code, 'post_status': r2.status_code})
    ''', extra_env={'SECRET_KEY': 'test-secret', 'STAND_PASSWORD': 'test-password',
                     'LOCAL_NO_AUTH': '0'})
    assert proc.returncode == 0, proc.stderr
    assert result['direct_calls'] == []
    assert result['get_status'] == 200
    assert result['post_status'] == 200


def test_grep_no_unguarded_direct_tronscan_etherscan_calls_in_app_py():
    """Статическая проверка: каждый оставшийся requests.get(...) к TronScan/
    Etherscan в app.py стоит в ветке else после `if STAND_MODE:` (либо внутри
    _stand_get/_stand_tronscan_get самого канала) — grep, а не полный AST,
    но с окном контекста, которого достаточно для этого файла."""
    import re
    from pathlib import Path
    text = (ROOT / 'app.py').read_text()
    lines = text.split('\n')
    offenders = []
    for i, line in enumerate(lines):
        if 'requests.get(' in line and ('tronscanapi.com' in line or 'etherscan.io' in line):
            window = '\n'.join(lines[max(0, i - 14):i])
            if 'STAND_MODE' not in window:
                offenders.append((i + 1, line.strip()))
        elif re.search(r"requests\.get\(\s*(url|balance_url|alt_url)\s*,", line):
            # непрямая ссылка через переменную — ищем присвоение той же
            # переменной строкой с tronscan/etherscan в ближайших строках выше
            var = re.search(r"requests\.get\(\s*(\w+)\s*,", line).group(1)
            window = '\n'.join(lines[max(0, i - 10):i])
            if (f'{var} =' in window and ('tronscanapi.com' in window or 'etherscan.io' in window)
                    and 'STAND_MODE' not in window):
                offenders.append((i + 1, line.strip()))
    assert offenders == [], f'найдены необёрнутые прямые вызовы: {offenders}'


# ─────────── QA-раунд 3 (лидер): TH-парсер, дедлайн тела, все 3xx ──────────

def test_calculator_th_nested_shape_parsed_same_as_prod_no_fallback_needed():
    """TH отдаёт вложенную форму {code:0,data:[{symbol,price}]} — тот же
    разбор, что и прод-путь (ExchangeRateProvider._parse_binance_price),
    не флэт data.get('price'). Успешный TH не должен звать Global-фоллбэк."""
    result, proc = run_script('''
        import stand_egress
        stand_egress.install()
        import asyncio
        from calculator import ExchangeRateProvider

        calls = []
        def fake_read_get(op, params=None, _base_url=None):
            calls.append(op)
            if op == 'market_binance_th_ticker':
                return 200, {'code': 0, 'data': [{'symbol': 'USDTTHB', 'price': '35.5'}]}, None
            if op == 'market_binance_ticker':
                raise AssertionError('TH уже дал валидный курс — Global не нужен')
            if op == 'market_rapira':
                return 200, {'data': []}, None
            raise AssertionError(op)
        stand_egress.read_get = fake_read_get

        rates = asyncio.run(ExchangeRateProvider.get_all_rates())
        OUT({'usdt_thb': rates['usdt_thb'], 'ops': calls})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['usdt_thb'] == 35.5
    assert result['ops'] == ['market_binance_th_ticker', 'market_rapira']


def test_calculator_parse_binance_price_shared_by_prod_and_stand():
    """_parse_binance_price — одна функция на форму TH (nested) и Global (flat)."""
    result, proc = run_script('''
        from calculator import ExchangeRateProvider as P
        OUT({
            'th_nested': P._parse_binance_price({'code': 0, 'data': [{'symbol': 'USDTTHB', 'price': '32.1'}]}, 'USDTTHB'),
            'th_nested_dict': P._parse_binance_price({'code': 0, 'data': {'symbol': 'USDTTHB', 'price': '32.2'}}, 'USDTTHB'),
            'global_flat': P._parse_binance_price({'price': '32.3'}, 'USDTTHB'),
            'wrong_symbol': P._parse_binance_price({'code': 0, 'data': [{'symbol': 'BTCUSDT', 'price': '1'}]}, 'USDTTHB'),
            'garbage': P._parse_binance_price('not a dict', 'USDTTHB'),
            'empty': P._parse_binance_price({}, 'USDTTHB'),
        })
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result == {'th_nested': 32.1, 'th_nested_dict': 32.2, 'global_flat': 32.3,
                      'wrong_symbol': None, 'garbage': None, 'empty': None}


def _slow_drip_server_script(deadline=None):
    return f'''
        import http.server, threading, time as _time
        class SlowHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = b'{{"x":1}}'
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                for b in body:
                    try:
                        self.wfile.write(bytes([b])); self.wfile.flush()
                    except Exception:
                        return
                    _time.sleep(.08)
            def log_message(self, *a):
                pass
        _srv = http.server.HTTPServer(('127.0.0.1', 0), SlowHandler)
        _port = _srv.server_port
        threading.Thread(target=_srv.serve_forever, daemon=True).start()
        import stand_egress
        stand_egress.install()
        stand_egress.allow_test_target('127.0.0.1', _port)
        {"stand_egress._READ_TOTAL_DEADLINE = " + str(deadline) if deadline else ""}
    '''


def test_slow_drip_body_aborts_at_deadline_not_at_full_transfer_time():
    """7 байт по одному каждые 0.08с (≈0.56с всего) с дедлайном 0.25с — общий
    дедлайн должен сработать заметно раньше полной передачи, а не только на
    таймауте одной операции requests (который каждый отдельный recv не ловит,
    раз новые байты приходят быстрее per-op таймаута)."""
    result, proc = run_script(_slow_drip_server_script(deadline=0.25) + '''
        import time
        start = time.monotonic()
        status_code, data, err = stand_egress.read_get(
            'market_rapira', {}, _base_url=f'http://127.0.0.1:{_port}')
        OUT({'elapsed': round(time.monotonic() - start, 2), 'err': err, 'data': data})
    ''', timeout=15)
    assert proc.returncode == 0, proc.stderr
    assert result['err'] == 'read_timeout'
    assert result['data'] is None
    assert result['elapsed'] < 0.4, f"должен был прерваться у дедлайна 0.25с, а не ждать все 0.56с: {result['elapsed']}"


def test_slow_drip_body_completes_when_deadline_is_generous():
    """Контрольная проверка: тот же медленный сервер, но с щедрым дедлайном —
    сужение окна на watchdog-поток не сломало обычное успешное чтение."""
    result, proc = run_script(_slow_drip_server_script(deadline=5.0) + '''
        status_code, data, err = stand_egress.read_get(
            'market_rapira', {}, _base_url=f'http://127.0.0.1:{_port}')
        OUT({'status_code': status_code, 'data': data, 'err': err})
    ''', timeout=15)
    assert proc.returncode == 0, proc.stderr
    assert result == {'status_code': 200, 'data': {'x': 1}, 'err': None}


def test_all_3xx_including_uncommon_codes_are_redirect_blocked():
    result, proc = run_script(_fake_get_server_script() + '''
        out = {}
        for status in range(300, 309):
            FakeChain.next_status = status
            _, _, err = stand_egress.read_get('market_rapira', {}, _base_url=_base)
            out[status] = err
        OUT(out)
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result == {str(s): 'redirect_blocked' for s in range(300, 309)}


# ─────── QA-раунд 4 (лидер): TH/Global разбор по источнику, поток-демон ────

def test_parse_binance_price_global_source_rejects_nested_shape_like_main():
    """Global — строго плоский {price}, как в main: TH-образный вложенный
    ответ на Global-эндпоинте не должен молча распознаваться (там его в
    реальности не бывает, а если и придёт — это не тот формат)."""
    result, proc = run_script('''
        from calculator import ExchangeRateProvider as P
        OUT({
            'global_flat': P._parse_binance_price({'price': '35.4'}, 'USDTTHB', source='global'),
            'global_nested_rejected': P._parse_binance_price(
                {'code': 0, 'data': [{'symbol': 'USDTTHB', 'price': '35.4'}]}, 'USDTTHB', source='global'),
            'global_garbage': P._parse_binance_price({'price': 'bad'}, 'USDTTHB', source='global'),
            'global_missing_price': P._parse_binance_price({}, 'USDTTHB', source='global'),
        })
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result == {'global_flat': 35.4, 'global_nested_rejected': None,
                      'global_garbage': None, 'global_missing_price': None}


def test_calculator_stand_mode_global_fallback_uses_strict_flat_parser():
    """В STAND_MODE market_binance_ticker (фоллбэк) тоже должен идти через
    source='global' — TH-образный мусор на этом канале не подтверждает курс."""
    result, proc = run_script('''
        import stand_egress
        stand_egress.install()
        import asyncio
        from calculator import ExchangeRateProvider

        def fake_read_get(op, params=None, _base_url=None):
            if op == 'market_binance_th_ticker':
                return None, None, 'network_error'
            if op == 'market_binance_ticker':
                # TH-образный ответ там, где его быть не должно — не курс.
                return 200, {'code': 0, 'data': [{'symbol': 'USDTTHB', 'price': '35.4'}]}, None
            if op == 'market_rapira':
                return 200, {'data': []}, None
            raise AssertionError(op)
        stand_egress.read_get = fake_read_get

        rates = asyncio.run(ExchangeRateProvider.get_all_rates())
        OUT(rates)
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['usdt_thb'] is None


def test_read_body_without_reachable_socket_rejected_immediately_no_thread():
    """QA-раунд 5: чтение тела больше не заводит отдельный поток вообще — если
    у ответа нет достижимого сырого сокета (совсем фейковый нижний транспорт,
    как в тесте/баге стороннего кода), read_get отказывает СРАЗУ как
    read_error, не пытаясь читать вслепую и не оставляя после себя ни одного
    живого потока чтения."""
    result, proc = run_script('''
        import threading, time
        from unittest.mock import patch
        import stand_egress
        stand_egress.install()
        stand_egress._READ_TOTAL_DEADLINE = .15

        class Raw:
            def read(self, *a, **kw):
                time.sleep(3)
                return b'{}'
        class Resp:
            status_code = 200
            raw = Raw()
            def close(self):
                pass

        before = {t.name for t in threading.enumerate()}
        start = time.monotonic()
        with patch('requests.Session.get', return_value=Resp()):
            result = stand_egress.read_get('market_rapira', {})
        elapsed = time.monotonic() - start
        after = {t.name for t in threading.enumerate()} - before
        OUT({'result': result, 'elapsed': round(elapsed, 2), 'new_threads': sorted(after)})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['result'] == [None, None, 'read_error']
    assert result['elapsed'] < 0.5, 'не должен ждать вообще — сокет недостижим сразу'
    assert result['new_threads'] == []


def test_slow_real_socket_deadline_leaves_no_live_threads_after_return():
    """Тот же дедлайн на реальном (не фейковом) медленном сокете — теперь
    через settimeout в цикле чтения чанками, без watchdog-потока вовсе."""
    result, proc = run_script(_slow_drip_server_script(deadline=0.2) + '''
        import threading, time
        before = {t.name for t in threading.enumerate()}
        start = time.monotonic()
        result = stand_egress.read_get('market_rapira', {}, _base_url=f'http://127.0.0.1:{_port}')
        elapsed = time.monotonic() - start
        time.sleep(0.5)  # если бы поток всё же завёлся и завис — успел бы остаться живым
        after = {t.name for t in threading.enumerate()} - before
        OUT({'result': result, 'elapsed': round(elapsed, 2), 'new_threads': sorted(after)})
    ''', timeout=15)
    assert proc.returncode == 0, proc.stderr
    assert result['result'] == [None, None, 'read_timeout']
    assert result['elapsed'] < 0.4
    assert result['new_threads'] == []


def test_read_ctx_inactive_during_body_read_phase_of_slow_drip():
    """E2 после перехода на свой цикл чтения (без resp.raw.read()): разрешение
    guard'а действует только внутри своего connect(), поэтому во время ВСЕЙ
    фазы чтения тела (в том числе долгой, медленной) _read_ctx неактивен —
    соседний прямой коннект в том же потоке в это время в принципе не может
    быть спутан с разрешённым, читать нечего дополнительно ловить."""
    result, proc = run_script(_slow_drip_server_script(deadline=0.2) + '''
        import threading, time
        seen_during_read = []
        stop = threading.Event()
        def poll():
            while not stop.is_set():
                seen_during_read.append(getattr(stand_egress._read_ctx, 'active', False))
                time.sleep(0.01)
        t = threading.Thread(target=poll, daemon=True)
        t.start()
        start = time.monotonic()
        result = stand_egress.read_get('market_rapira', {}, _base_url=f'http://127.0.0.1:{_port}')
        elapsed = time.monotonic() - start
        stop.set(); t.join(timeout=1)
        OUT({'result': result, 'elapsed': round(elapsed, 2),
             'active_seen_during_read': any(seen_during_read)})
    ''', timeout=15)
    assert proc.returncode == 0, proc.stderr
    assert result['elapsed'] < 0.4
    assert result['active_seen_during_read'] is False


# ───── ERC receipt через контролируемый канал чтения ───

def test_verify_transfer_erc20_uses_read_channel_on_stand():
    result, proc = run_script('''
        import stand_egress
        stand_egress.install()
        import stand_transfers as st

        calls = []
        def fake_read_get(op, params=None, _base_url=None):
            calls.append(op)
            return 200, {'result': None}, None
        stand_egress.read_get = fake_read_get

        r = st.verify_transfer('0x' + 'a' * 64, 'erc20',
                               '0x' + 'c' * 40, '0x' + 'b' * 40, 100)
        OUT({'status': r['status'], 'calls': calls})
    ''', extra_env={'STAND_ETHERSCAN_API_KEY': 'stand-fake-key'})
    assert proc.returncode == 0, proc.stderr
    assert result == {'status': 'pending', 'calls': ['eth_tx_receipt']}


def test_verify_transfer_trc20_unaffected_by_erc20_disable():
    result, proc = run_script('''
        import stand_egress
        stand_egress.install()
        import stand_transfers as st

        def fake_read_get(op, params=None, _base_url=None):
            assert op == 'tron_tx_info'
            return 200, {}, None
        stand_egress.read_get = fake_read_get

        r = st.verify_transfer('a' * 64, 'trc20',
                               'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn',
                               'TVmgzMQ2zwV2DVPscBf98WRRdhrcpf5x5p', 100)
        OUT({'status': r['status']})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['status'] == 'pending'


def test_app_etherscan_tx_info_disabled_on_stand_even_with_key():
    result, proc = run_script('''
        from unittest.mock import patch
        import stand_egress
        stand_egress.install()
        import app

        def fail_if_called(*a, **k):
            raise AssertionError('read_get/requests.get не должны вызываться для ERC-20 на стенде')
        with patch('requests.get', side_effect=fail_if_called), \\
             patch.object(stand_egress, 'read_get', fail_if_called):
            result = app._etherscan_tx_info('0x' + 'a' * 64)
        OUT({'result': result})
    ''', extra_env={'SECRET_KEY': 'test-secret', 'STAND_PASSWORD': 'test-password',
                     'LOCAL_NO_AUTH': '0', 'STAND_ETHERSCAN_API_KEY': 'stand-fake-key'})
    assert proc.returncode == 0, proc.stderr
    assert result['result'] == {}


def test_app_tx_lookup_route_erc20_disabled_on_stand():
    result, proc = run_script('''
        from unittest.mock import patch
        import stand_egress
        stand_egress.install()
        import app
        app.app.config['TESTING'] = True
        app.limiter.enabled = False
        client = app.app.test_client()

        db = app.get_session()
        try:
            admin = app.AdminUser(username='adm-erc-test', role='admin', password_hash=b'x')
            db.add(admin); db.commit(); admin_id = admin.id
        finally:
            db.close()
        with client.session_transaction() as sess:
            sess['user_id'] = admin_id

        def fail_if_called(*a, **k):
            raise AssertionError('сеть не должна вызываться')
        with patch('requests.get', side_effect=fail_if_called), \\
             patch.object(stand_egress, 'read_get', fail_if_called):
            r = client.get('/api/tx/lookup?hash=' + '0x' + 'a' * 64 + '&network=erc20')
        OUT({'status': r.status_code, 'body': r.get_json()})
    ''', extra_env={'SECRET_KEY': 'test-secret', 'STAND_PASSWORD': 'test-password',
                     'LOCAL_NO_AUTH': '0', 'STAND_ETHERSCAN_API_KEY': 'stand-fake-key'})
    assert proc.returncode == 0, proc.stderr
    assert result['status'] == 503
    assert 'ERC-20' in result['body']['error']


# ── QA: непрерывный приток байтов не должен маскировать проверку дедлайна ───

def test_continuous_drip_still_respects_deadline_not_full_body():
    """200 байт по 1 каждые 20мс (~4с всего) с дедлайном 0.3с — операция
    обязана завершиться заметно раньше полной передачи, около самого
    дедлайна (не позже 0.5с): read1() возвращает частичные куски по мере
    поступления, поэтому дедлайн проверяется на каждой итерации цикла, а не
    только после того, как придёт вся заявленная Content-Length."""
    result, proc = run_script('''
        import http.server, threading, time as _time
        class DripHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = b'x' * 200
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                for b in body:
                    try:
                        self.wfile.write(bytes([b])); self.wfile.flush()
                    except Exception:
                        return
                    _time.sleep(.02)
            def log_message(self, *a):
                pass
        _srv = http.server.HTTPServer(('127.0.0.1', 0), DripHandler)
        _port = _srv.server_port
        threading.Thread(target=_srv.serve_forever, daemon=True).start()
        import time
        import stand_egress
        stand_egress.install()
        stand_egress.allow_test_target('127.0.0.1', _port)
        stand_egress._READ_TOTAL_DEADLINE = 0.3

        start = time.monotonic()
        result = stand_egress.read_get('market_rapira', {}, _base_url=f'http://127.0.0.1:{_port}')
        elapsed = time.monotonic() - start
        OUT({'result': result, 'elapsed': round(elapsed, 2)})
    ''', timeout=15)
    assert proc.returncode == 0, proc.stderr
    assert result['result'] == [None, None, 'read_timeout']
    assert result['elapsed'] <= 0.5, f"должен завершиться у дедлайна, не ждать полную передачу (~4с): {result['elapsed']}"


# ── Канал допускает только фиксированные eth_* read ops ──

def test_read_get_allows_eth_read_ops_on_stand():
    result, proc = run_script(_fake_get_server_script() + '''
        _, _, err_receipt = stand_egress.read_get('eth_tx_receipt', {
            'chainid': '1', 'module': 'proxy', 'action': 'eth_getTransactionReceipt',
            'txhash': '0x' + 'a' * 64}, _base_url=_base)
        _, _, err_block = stand_egress.read_get('eth_block_by_number', {
            'chainid': '1', 'module': 'proxy', 'action': 'eth_getBlockByNumber',
            'tag': '0x1', 'boolean': 'false'}, _base_url=_base)
        OUT({'err_receipt': err_receipt, 'err_block': err_block, 'hits': len(FakeChain.hits)})
    ''', extra_env={'STAND_ETHERSCAN_API_KEY': 'stand-fake-key'})
    assert proc.returncode == 0, proc.stderr
    assert result == {'err_receipt': None, 'err_block': None, 'hits': 2}


def test_read_get_eth_ops_work_normally_outside_stand_mode():
    """Прод read_get не использует, но канал сам по себе не должен менять
    поведение вне STAND_MODE — negative control."""
    result, proc = run_script(_fake_get_server_script() + '''
        _, _, err = stand_egress.read_get('eth_tx_receipt', {
            'chainid': '1', 'module': 'proxy', 'action': 'eth_getTransactionReceipt',
            'txhash': '0x' + 'a' * 64}, _base_url=_base)
        OUT({'err': err, 'hits': len(FakeChain.hits)})
    ''', stand_mode='0', extra_env={'STAND_ETHERSCAN_API_KEY': 'stand-fake-key'})
    assert proc.returncode == 0, proc.stderr
    assert result['err'] is None
    assert result['hits'] == 1


# ───── QA инцидент: Transfer-Encoding: chunked (Rapira/TronScan HTTP/1.1) ───
# read1() читал сырой BufferedReader сокета в обход HTTP-декодера фрейминга —
# разметка чанков (hex-длина\r\n…данные…\r\n) попадала в тело как мусор, и
# json.loads падал с invalid_json/read_error. Чтение переведено на
# resp.raw._fp.read1() — сам http.client.HTTPResponse, который framing
# декодирует и для chunked, и для Content-Length.

def _chunked_server_script():
    return '''
        import http.server, threading, socket

        class ChunkedHandler(http.server.BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            next_chunks = [b'{"a":1,', b'"b":2,', b'"c":3}']
            drop_mid_chunk = False

            def do_GET(self):
                self.send_response(200)
                self.send_header('Transfer-Encoding', 'chunked')
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                if ChunkedHandler.drop_mid_chunk:
                    # Заявляем большой чанк, шлём часть данных и рвём соединение —
                    # клиент должен увидеть оборванный chunked-поток, не подмену JSON.
                    self.wfile.write(b'64\\r\\n{"partial":')
                    self.wfile.flush()
                    self.close_connection = True
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    return
                for c in ChunkedHandler.next_chunks:
                    self.wfile.write(('%x\\r\\n' % len(c)).encode() + c + b'\\r\\n')
                    self.wfile.flush()
                self.wfile.write(b'0\\r\\n\\r\\n')

            def log_message(self, *a):
                pass

        _srv = http.server.HTTPServer(('127.0.0.1', 0), ChunkedHandler)
        _port = _srv.server_port
        threading.Thread(target=_srv.serve_forever, daemon=True).start()
        _base = f'http://127.0.0.1:{_port}'
        import stand_egress
        stand_egress.install()
        stand_egress.allow_test_target('127.0.0.1', _port)
    '''


def test_chunked_response_decoded_correctly_not_treated_as_raw_bytes():
    result, proc = run_script(_chunked_server_script() + '''
        status_code, data, err = stand_egress.read_get('market_rapira', {}, _base_url=_base)
        OUT({'status_code': status_code, 'data': data, 'err': err})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result == {'status_code': 200, 'data': {'a': 1, 'b': 2, 'c': 3}, 'err': None}


def test_chunked_response_with_many_small_chunks():
    result, proc = run_script(_chunked_server_script() + '''
        ChunkedHandler.next_chunks = [b'{"', b'x', b'"', b':', b'[', b'1', b',', b'2', b',', b'3', b']', b'}']
        status_code, data, err = stand_egress.read_get('market_rapira', {}, _base_url=_base)
        OUT({'status_code': status_code, 'data': data, 'err': err})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result == {'status_code': 200, 'data': {'x': [1, 2, 3]}, 'err': None}


def test_chunked_slow_drip_respects_deadline():
    """Медленный дрип ЧАНКАМИ (не байтами через Content-Length, а полноценным
    chunked framing) — 10 чанков по 20мс с дедлайном 0.15с обязаны прерваться
    заметно раньше полной передачи (~0.2с), не позже 0.4с."""
    result, proc = run_script('''
        import http.server, threading, time

        class SlowChunked(http.server.BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            def do_GET(self):
                self.send_response(200)
                self.send_header('Transfer-Encoding', 'chunked')
                self.end_headers()
                for i in range(10):
                    c = b'{"i":%d}' % i
                    try:
                        self.wfile.write(('%x\\r\\n' % len(c)).encode() + c + b'\\r\\n')
                        self.wfile.flush()
                    except Exception:
                        return
                    time.sleep(.02)
                try:
                    self.wfile.write(b'0\\r\\n\\r\\n')
                except Exception:
                    pass
            def log_message(self, *a):
                pass

        _srv = http.server.HTTPServer(('127.0.0.1', 0), SlowChunked)
        _port = _srv.server_port
        threading.Thread(target=_srv.serve_forever, daemon=True).start()
        import stand_egress
        stand_egress.install()
        stand_egress.allow_test_target('127.0.0.1', _port)
        stand_egress._READ_TOTAL_DEADLINE = 0.15

        start = time.monotonic()
        result = stand_egress.read_get('market_rapira', {}, _base_url=f'http://127.0.0.1:{_port}')
        elapsed = time.monotonic() - start
        OUT({'result': result, 'elapsed': round(elapsed, 2)})
    ''', timeout=15)
    assert proc.returncode == 0, proc.stderr
    assert result['result'] == [None, None, 'read_timeout']
    assert result['elapsed'] <= 0.4


def test_chunked_dropped_mid_chunk_is_read_error():
    result, proc = run_script(_chunked_server_script() + '''
        ChunkedHandler.drop_mid_chunk = True
        status_code, data, err = stand_egress.read_get('market_rapira', {}, _base_url=_base)
        OUT({'status_code': status_code, 'data': data, 'err': err})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['data'] is None
    assert result['err'] == 'read_error'


# ── ручная проверка живой сети (см. отчёт) выполнена отдельно интерактивно ──
