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
    result, proc = run_script(_fake_get_server_script() + '''
        import stand_egress
        stand_egress.install()
        status_code, data, err = stand_egress.read_get('eth_tx_receipt', {
            'chainid': '56', 'module': 'proxy', 'action': 'eth_getTransactionReceipt',
            'txhash': '0x' + 'a' * 64}, _base_url=_base)
        OUT({'err': err, 'hits': len(FakeChain.hits)})
    ''', extra_env={'STAND_ETHERSCAN_API_KEY': 'fake-key'})
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
    ''', extra_env={'STAND_ETHERSCAN_API_KEY': 'fake-key'})
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
    result, proc = run_script(_fake_get_server_script() + '''
        import stand_egress
        stand_egress.install()
        status_code, data, err = stand_egress.read_get('eth_tx_receipt', {
            'chainid': '1', 'module': 'proxy', 'action': 'eth_getTransactionReceipt',
            'txhash': '0x' + 'a' * 64}, _base_url=_base)
        OUT({'err': err, 'hits': len(FakeChain.hits)})
    ''', extra_env={'STAND_ETHERSCAN_API_KEY': None})
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
    ''', extra_env={'STAND_ETHERSCAN_API_KEY': 'stand-eth-key'})
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
        import stand_egress
        stand_egress.install()
        stand_egress.allow_test_target('127.0.0.1', 1)  # регистрируем адрес, но там никто не слушает
        status_code, data, err = stand_egress.read_get(
            'prod_incomes', {'all': 1}, _base_url='http://127.0.0.1:1')
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


def test_read_body_read_timeout_and_protocol_error_are_stable_codes():
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
    assert result == {'read_timeout': 'read_timeout', 'read_error': 'read_error'}


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
