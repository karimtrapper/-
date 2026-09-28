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
        status_code, data, err = stand_egress.read_get(
            'prod_incomes', {'all': 1}, _base_url='http://127.0.0.1:1')  # порт без слушателя
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
            if op == 'market_binance_ticker':
                return 200, {'symbol': 'USDTTHB', 'price': '32.5'}, None
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
