"""Проверка переводов общей доски по сети, без отправки денег."""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from collections import defaultdict, deque
import os
import re
from urllib.parse import urlparse, parse_qs

import requests


TRON_USDT = 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t'
ETH_USDT = '0xdac17f958d2ee523a2206206994597c13d831ec7'
ETH_TRANSFER_TOPIC = ('0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef')
DEFAULT_WALLETS = {
    # Legacy id kept for saved deals (including 1478/1479): it still means this address.
    'vitaly': 'TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ',
    'grusha': 'TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ',
    'andrey': 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn',
    'teodor': 'TVmgzMQ2zwV2DVPscBf98WRRdhrcpf5x5p',
    'teodor-erc': '0x68aEA0F5386a57b48953F6fFF2f22D29D00D9ba9',
}
LEGACY_GRUSHA_ADDRESS = 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn'
TRONSCAN_USER_AGENT = 'Mozilla/5.0 (Apple) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
SERVER_FIELDS = ('status', 'verifiedAmount', 'verifiedAt', 'from', 'to',
                 'lastCheckedAt', 'checkError', 'demoOutcome', 'demo', 'timestampMs')
# Инвойс и тариф фиксируются с s11; сумму клиента операционист ещё может
# исправить на s11 до первого выпуска документов.
FREEHOLD_LOCKED_STEPS = {'s11', 's11b', 's12', 's14', 's14m', 's15', 's18', 's18w',
                         's22', 's23', 's24', 's25', 's26', 's27', 'done'}


def _amount(value):
    # None — «сумма не задана»: её берём из сети, а не считаем нулём
    if value is None:
        return None
    try:
        number = Decimal(str(value or '0').replace(' ', '').replace('\u00a0', '').replace(',', '.'))
        return number if number.is_finite() and number >= 0 else None
    except (InvalidOperation, ValueError):
        return None


def normalize_network(value):
    value = str(value or '').strip().lower().replace('-', '')
    return value if value in ('trc20', 'erc20') else None


def normalize_ref(ref, network):
    """Хеш или ссылка на обозреватель; demo ref намеренно не похож на хеш."""
    raw = str(ref or '').strip()
    if raw.startswith('demo:'):
        return raw
    if raw.startswith(('http://', 'https://')):
        url = urlparse(raw)
        if network == 'trc20' and url.hostname not in ('tronscan.org', 'www.tronscan.org'):
            return None
        if network == 'erc20' and url.hostname not in ('etherscan.io', 'www.etherscan.io'):
            return None
        raw = (parse_qs(url.query).get('hash') or [None])[0] or url.path.rstrip('/').split('/')[-1]
        if url.fragment and 'transaction/' in url.fragment:
            raw = url.fragment.split('transaction/')[-1].split('/')[0]
    if network == 'trc20':
        return raw.removeprefix('0x').lower() if re.fullmatch(r'(?:0x)?[0-9a-fA-F]{64}', raw) else None
    if network == 'erc20':
        if re.fullmatch(r'[0-9a-fA-F]{64}', raw):
            raw = '0x' + raw
        return raw.lower() if re.fullmatch(r'0x[0-9a-fA-F]{64}', raw) else None
    return None


def valid_address(value, network):
    value = str(value or '').strip()
    if network == 'trc20':
        return bool(re.fullmatch(r'T[1-9A-HJ-NP-Za-km-z]{33}', value))
    if network == 'erc20':
        return bool(re.fullmatch(r'0x[0-9a-fA-F]{40}', value))
    return False


def stand_wallet_address(state, wallet_id):
    """Resolve a stand wallet without rewriting persisted wallet IDs or custom addresses."""
    wallet = next((w for w in state.get('wallets', []) if w.get('id') == wallet_id), None)
    address = (wallet or {}).get('addr')
    # Only the exact old built-in mapping is stale; user-edited addresses retain precedence.
    if wallet_id == 'grusha' and address == LEGACY_GRUSHA_ADDRESS:
        return DEFAULT_WALLETS['grusha']
    if wallet_id == 'andrey' and address == 'адрес уточнить':
        return DEFAULT_WALLETS['andrey']
    return address or DEFAULT_WALLETS.get(wallet_id)


def expected_addresses(state, deal):
    conv = next((c for c in state.get('convs', []) if c.get('id') == deal.get('cnvId')), None)
    wallet_id = (conv or {}).get('walletId') or deal.get('walletId')
    sender = stand_wallet_address(state, wallet_id)
    return sender, (deal.get('transfer') or {}).get('addr')


def send_fingerprint(state, deal, send):
    network = normalize_network(send.get('net') or (deal.get('transfer') or {}).get('net') or 'TRC-20')
    ref = normalize_ref(send.get('ref') or send.get('hash'), network)
    explicit_hash = normalize_ref(send.get('hash'), network) if send.get('hash') else None
    if explicit_hash and ref != explicit_hash:
        ref = None
    sender, receiver = expected_addresses(state, deal)
    amount = _amount(send.get('amount'))
    canonical_amount = format(amount.normalize(), 'f') if amount is not None else None
    sender = str(sender or '').lower() if network == 'erc20' else str(sender or '')
    receiver = str(receiver or '').lower() if network == 'erc20' else str(receiver or '')
    return (ref, network, canonical_amount, sender, receiver)


def preserve_server_fields(old_state, new_state):
    """Не принимать подтверждение перевода из браузерного PUT."""
    # Сберовская выписка принадлежит серверу. Люди могут привязать приход,
    # включить его в пачку или исключить, но не поменять исходные деньги.
    old_incomes = {i.get('id'): i for i in old_state.get('incomes', [])
                   if isinstance(i, dict) and i.get('source') == 'sber'}
    received = {i.get('id'): i for i in new_state.get('incomes', [])
                if isinstance(i, dict)}
    protected = ('id', 'source', 'uuid', 'date', 'arrivedAt', 'payer', 'rub',
                 'grossRub', 'feeRub',
                 'kind', 'acc', 'accSource', 'purpose', 'docNumber', 'demo')
    for income_id, previous in old_incomes.items():
        incoming = received.get(income_id)
        if incoming is None:
            # Отсутствие записи в PUT — устаревший снимок клиента, а не команда
            # снять человеческую привязку. Возвращаем всю запись из доски.
            incoming = previous.copy()
            new_state.setdefault('incomes', []).append(incoming)
        for field in protected:
            if field in previous:
                incoming[field] = previous[field]
            else:
                incoming.pop(field, None)
    # Прислать новый «серверный» приход из браузера тоже нельзя.
    new_state['incomes'] = [i for i in new_state.get('incomes', [])
                            if not (isinstance(i, dict) and i.get('source') == 'sber'
                                    and i.get('id') not in old_incomes)]
    old_deals = {d.get('id'): d for d in old_state.get('deals', [])}
    old_convs = {c.get('id'): c for c in old_state.get('convs', [])}
    for conv in new_state.get('convs', []):
        previous = old_convs.get(conv.get('id')) or {}
        trusted = defaultdict(deque)
        for tx in previous.get('txs', []) or []:
            trusted[(tx.get('hash'), normalize_network(tx.get('net')))].append(tx)
        members = [d for d in new_state.get('deals', [])
                   if d.get('id') in {s.get('dealId') for s in conv.get('sources', []) or []}]
        all_demo = bool(members) and all(d.get('demoTransfers') for d in members)
        incoming = []
        for tx in conv.get('txs', []) or []:
            key = (tx.get('hash'), normalize_network(tx.get('net')))
            if trusted[key]:
                incoming.append(trusted[key].popleft())
            elif (all_demo and re.fullmatch(r'demo:incoming:[0-9]+:[A-Za-z0-9_-]+',
                                            str(tx.get('hash') or ''))
                  and tx.get('demo') is True and tx.get('status') == 'confirmed'
                  and _amount(tx.get('amount')) is not None):
                incoming.append(tx)
        conv['txs'] = incoming
    for deal in new_state.get('deals', []):
        transfer = deal.get('transfer') or {}
        previous = old_deals.get(deal.get('id')) or {}
        # Preserve a signature on stale snapshots. A changed signature is kept
        # only after app._stand_guard_transition validated it against a live
        # StandChannel row and the server HMAC.
        if (previous.get('bitrixCloseProof') and not deal.get('bitrixCloseProof')
                and deal.get('source') == previous.get('source')
                and deal.get('sourceRef') == previous.get('sourceRef')):
            deal['bitrixCloseProof'] = previous['bitrixCloseProof']
        if previous.get('bitrixSync'):
            deal['bitrixSync'] = previous['bitrixSync']
        else:
            deal.pop('bitrixSync', None)
        old_conv = old_convs.get(previous.get('cnvId')) or {}
        if (previous.get('transfer') or {}).get('sends') or old_conv.get('txs'):
            deal['demoTransfers'] = bool(previous.get('demoTransfers'))
        # Денежную основу инвойса фиксируем с s11. План клиента допускает
        # последнюю правку на s11 до появления документов или прихода.
        if previous.get('kind') == 'Фрихолд' and previous.get('step') in FREEHOLD_LOCKED_STEPS:
            fields = ['invoiceUsd', 'ippsTariff', 'invoiceCurrency', 'invoiceThb']
            if (previous.get('step') != 's11' or previous.get('docPack')
                    or previous.get('docVersion') or previous.get('payinHashes')):
                fields.append('amountUsdt')
            for field in fields:
                if field in previous:
                    deal[field] = previous[field]
                else:
                    deal.pop(field, None)
        # Only the row-locked acknowledgement endpoint may create/change this.
        # A changed financial fingerprint leaves the old ack in history but it
        # no longer authorizes progression.
        deal.pop('freeholdLossAck', None)
        if previous.get('freeholdLossAck'):
            deal['freeholdLossAck'] = previous['freeholdLossAck']
        for protected in ('serverSettled', 'serverTransferComplete'):
            deal.pop(protected, None)
            if previous.get(protected):
                deal[protected] = True
        # Отметку «проверено в сети» на хеше прихода ставит только сервер
        old_payin = {h.get('hash'): h for h in previous.get('payinHashes') or [] if h.get('verified')}
        for h in deal.get('payinHashes') or []:
            if not isinstance(h, dict):
                continue
            trusted = old_payin.get(h.get('hash'))
            fields = ('verified', 'verifiedAt', 'timestampMs', 'otherSender',
                      'network', 'net') + (
                () if str(h.get('hash') or '').startswith('demo:') else ('from', 'to'))
            for field in fields:
                h.pop(field, None)
            if trusted:
                h.update({f: trusted[f] for f in fields + ('amount',) if f in trusted})
        payout = deal.get('payout')
        if isinstance(payout, dict):
            payout.pop('reimbursement', None)
            old_reimbursement = (previous.get('payout') or {}).get('reimbursement')
            if old_reimbursement:
                payout['reimbursement'] = old_reimbursement
        if previous.get('serverTransferComplete'):
            payout = deal.setdefault('payout', {})
            old_payout = previous.get('payout') or {}
            for field in ('hashes', 'hash', 'usdt'):
                if field in old_payout:
                    payout[field] = old_payout[field]
            deal['mfPayout'] = previous.get('mfPayout') or []
            deal.setdefault('pay', {})['outHash'] = (previous.get('pay') or {}).get('outHash')
        old_sends = (previous.get('transfer') or {}).get('sends') or []
        old_by_key = defaultdict(deque)
        for old_send in old_sends:
            old_by_key[send_fingerprint(old_state, previous, old_send)].append(old_send)
        for send in transfer.get('sends') or []:
            key = send_fingerprint(new_state, deal, send)
            trusted = old_by_key[key].popleft() if key[0] and old_by_key[key] else None
            for field in SERVER_FIELDS:
                send.pop(field, None)
            if trusted:
                send.update({field: trusted[field] for field in SERVER_FIELDS if field in trusted})
            else:
                send['status'] = 'pending'
        if previous and previous.get('postConv') in ('coins', 'ipps_swift'):
            # Перевести задачу дальше подписей (Coins/IPPS) может только серверная проверка.
            if not previous.get('serverTransferComplete') and deal.get('step') in ('s25', 's26', 's27', 'done') and previous.get('step') in ('s23', 's24'):
                deal['step'] = previous['step']
                deal['closed'] = False
            if not previous.get('closed') and (deal.get('closed') or deal.get('step') == 'done') and not (
                    previous.get('serverTransferComplete')
                    and (deal.get('pay') or {}).get('invoicePaid')
                    and (deal.get('docs') or {}).get('receipt')
                    and deal.get('sentToClient')):
                deal['closed'] = False
                deal['step'] = previous.get('step') or 's27'
        # Серверная запись возмещения и закрытия не может появиться через общий PUT.
        if previous and previous.get('serverSettled'):
            for field in ('serverSettled', 'closed', 'closeReason', 'closedAt', 'step', 'payout'):
                if field in previous:
                    deal[field] = previous[field]
    return new_state


def _result(status, **kwargs):
    return {'status': status, 'verifiedAt': datetime.now(timezone.utc).isoformat()
            if status == 'confirmed' else None, **kwargs}


class _ChannelError(Exception):
    """Ошибка контролируемого канала чтения стенда (stand_egress.read_get)."""


class _StandChannelResponse:
    """Приводит (status_code, json, error) от read_get к форме, которую ждёт
    остальной код verify_transfer (response.status_code / response.json())."""
    __slots__ = ('status_code', '_data')

    def __init__(self, status_code, data):
        self.status_code = status_code
        self._data = data

    def json(self):
        return self._data


_STAND_CHANNEL_ERRORS = {
    'no_key': 'Сеть недоступна: нет ключа',
    'timeout': 'Сеть не ответила: таймаут',
    'read_timeout': 'Сеть не ответила: таймаут при чтении ответа',
    'read_error': 'Сеть не ответила: обрыв при чтении ответа',
    'tls_error': 'Сеть не ответила: TLS',
    'network_error': 'Сеть не ответила',
    'redirect_blocked': 'Сеть отдала редирект — отклонено',
    'response_too_large': 'Ответ сети слишком большой',
    'invalid_json': 'Сеть отдала не JSON',
    'http_429': 'TronScan/Etherscan HTTP 429 — лимит запросов',
    'http_5xx': 'TronScan/Etherscan HTTP 5xx',
    'http_4xx': 'TronScan/Etherscan HTTP 4xx',
}


def _stand_get(url, params=None, headers=None, timeout=None):
    """На стенде подменяет requests.get в verify_transfer: маршрутизирует
    вызов через stand_egress.read_get по известному URL. Заголовки и ключ
    (TRON-PRO-API-KEY / apikey) строит сам канал — 'apikey' из params сюда
    не передаём, иначе read_get отказал бы как неизвестный параметр."""
    import stand_egress

    params = params or {}
    if url == 'https://apilist.tronscanapi.com/api/transaction-info':
        op, op_params = 'tron_tx_info', {'hash': params.get('hash')}
    elif url == 'https://api.etherscan.io/v2/api' and params.get('action') == 'eth_getTransactionReceipt':
        op, op_params = 'eth_tx_receipt', {k: v for k, v in params.items() if k != 'apikey'}
    elif url == 'https://api.etherscan.io/v2/api' and params.get('action') == 'eth_getBlockByNumber':
        op, op_params = 'eth_block_by_number', {k: v for k, v in params.items() if k != 'apikey'}
    else:
        raise _ChannelError('Канал не настроен')
    status_code, data, err = stand_egress.read_get(op, op_params)
    if err == 'http_4xx' and op == 'tron_tx_info' and status_code == 404:
        # TronScan отдаёт 404 на ещё не проиндексированный хеш — как раньше
        # при прямом requests.get, это «пока нет данных», не ошибка канала.
        return _StandChannelResponse(status_code, {})
    if err:
        raise _ChannelError(_STAND_CHANNEL_ERRORS.get(err, 'Сеть недоступна'))
    return _StandChannelResponse(status_code, data)


def verify_transfer(ref, network, sender, receiver, amount, *, demo=False,
                    demo_outcome=None, get=requests.get, etherscan_key=None,
                    tronscan_key=None):
    """Сверить перевод по сети. Деньги эта функция не отправляет."""
    stand_mode = os.environ.get('STAND_MODE') == '1'
    network = normalize_network(network)
    tx_hash = normalize_ref(ref, network)
    required = _amount(amount)
    if not network or (amount is not None and (required is None or required <= 0)):
        return _result('mismatch', checkError='Некорректная сеть или сумма')
    if amount is not None and sender is None:
        return _result('mismatch', checkError='Не задан кошелёк отправителя')
    if ((sender is not None and not valid_address(sender, network))
            or not valid_address(receiver, network)):
        return _result('mismatch', checkError='Адрес отправителя или получателя не определён')
    if demo:
        if not re.fullmatch(r'demo:[0-9]+:[A-Za-z0-9_-]+', tx_hash or ''):
            return _result('mismatch', checkError='Для demo нужен demo:<dealId>:<nonce>')
        if demo_outcome == 'confirmed':
            if required is None:
                return _result('mismatch', checkError='Demo требует сумму')
            return _result('confirmed', verifiedAmount=float(required), **{'from': sender, 'to': receiver}, demo=True)
        return _result(demo_outcome if demo_outcome in ('failed', 'pending') else 'pending', demo=True)
    if not tx_hash or tx_hash.startswith('demo:'):
        return _result('mismatch', checkError='Некорректный хеш перевода')
    if stand_mode:
        # На стенде ходим в сеть только через контролируемый канал чтения T9
        # (stand_egress.read_get) — сокет-guard блокирует прямой requests.get.
        get = _stand_get
        tronscan_key = tronscan_key or os.environ.get('TRONSCAN_API_KEY')
        if network == 'erc20':
            etherscan_key = os.environ.get('STAND_ETHERSCAN_API_KEY')
    try:
        if network == 'trc20':
            headers = {'User-Agent': TRONSCAN_USER_AGENT}
            api_key = tronscan_key or os.environ.get('TRONSCAN_API_KEY')
            if api_key:
                headers['TRON-PRO-API-KEY'] = api_key
            response = get('https://apilist.tronscanapi.com/api/transaction-info',
                           params={'hash': tx_hash}, headers=headers, timeout=8)
            if response.status_code in (404, 200):
                data = response.json() or {}
                if not data or not data.get('hash'):
                    return _result('pending')
                if normalize_ref(data.get('hash'), network) != tx_hash:
                    return _result('mismatch', checkError='TronScan ответил другим хешем')
            else:
                return _result('error', checkError=f'TronScan HTTP {response.status_code}')
            if data.get('revert') is True or data.get('contractRet') not in (None, 'SUCCESS'):
                return _result('failed', checkError='Транзакция завершилась с ошибкой')
            if data.get('confirmed') is not True or data.get('contractRet') != 'SUCCESS' or data.get('revert') is not False:
                return _result('pending')
            timestamp_ms = int(data.get('timestamp') or 0)
            transfers = data.get('trc20TransferInfo') or []
            if isinstance(transfers, dict):
                transfers = [transfers]
            matches = [t for t in transfers
                       if t.get('contract_address') == TRON_USDT
                       and (sender is None or t.get('from_address') == sender)
                       and t.get('to_address') == receiver
                       and t.get('type', 'Transfer') == 'Transfer' and t.get('status', 0) == 0]
            actual = sum((_amount(t.get('amount_str')) or Decimal(0)) /
                         (Decimal(10) ** int(t.get('decimals') or 6)) for t in matches)
        else:
            if not etherscan_key:
                return _result('error', checkError='Etherscan API не настроен')
            response = get('https://api.etherscan.io/v2/api', params={
                'chainid': '1', 'module': 'proxy', 'action': 'eth_getTransactionReceipt',
                'txhash': tx_hash, 'apikey': etherscan_key}, timeout=8)
            if response.status_code != 200:
                return _result('error', checkError=f'Etherscan HTTP {response.status_code}')
            receipt = (response.json() or {}).get('result')
            if not receipt:
                return _result('pending')
            if str(receipt.get('transactionHash') or '').lower() != tx_hash:
                return _result('mismatch', checkError='Etherscan ответил другим хешем')
            if stand_mode and receipt.get('status') is None:
                return _result('pending')
            if str(receipt.get('status')).lower() not in ('0x1', '1'):
                return _result('failed', checkError='Ethereum receipt failed')
            if not receipt.get('blockNumber'):
                return _result('pending')
            block_response = get('https://api.etherscan.io/v2/api', params={
                'chainid': '1', 'module': 'proxy', 'action': 'eth_getBlockByNumber',
                'tag': receipt['blockNumber'], 'boolean': 'false', 'apikey': etherscan_key},
                timeout=8)
            if block_response.status_code != 200:
                return _result('error', checkError=f'Etherscan block HTTP {block_response.status_code}')
            block = (block_response.json() or {}).get('result') or {}
            if stand_mode and block.get('number') and str(block['number']).lower() != str(receipt['blockNumber']).lower():
                return _result('mismatch', checkError='Etherscan ответил другим блоком')
            if stand_mode and block.get('hash') and receipt.get('blockHash') and str(block['hash']).lower() != str(receipt['blockHash']).lower():
                return _result('mismatch', checkError='Etherscan ответил другим блоком')
            if not block.get('timestamp'):
                return _result('error', checkError='Etherscan не отдал время блока')
            timestamp_ms = int(str(block['timestamp']), 16) * 1000
            matches = []
            for log in receipt.get('logs') or []:
                topics = log.get('topics') or []
                if (str(log.get('address') or '').lower() == ETH_USDT
                    and len(topics) >= 3 and str(topics[0]).lower() == ETH_TRANSFER_TOPIC
                    and (not stand_mode or (log.get('removed') is not True and len(topics) == 3
                        and re.fullmatch(r'0x[0-9a-fA-F]{64}', str(topics[1]))
                        and re.fullmatch(r'0x[0-9a-fA-F]{64}', str(topics[2]))))
                    and (sender is None or '0x' + str(topics[1])[-40:].lower() == sender.lower())
                    and '0x' + str(topics[2])[-40:].lower() == receiver.lower()):
                    matches.append(log)
            actual = sum(Decimal(int(str(t.get('data') or '0x0'), 16)) / Decimal(1_000_000)
                         for t in matches)
    except (requests.RequestException, ValueError, TypeError, InvalidOperation, _ChannelError) as exc:
        return _result('error', checkError=str(exc)[:160])
    actual_from = sender or (matches[0].get('from_address') if network == 'trc20' and matches else None)
    if network == 'erc20' and sender is None and matches:
        actual_from = '0x' + str(matches[0]['topics'][1])[-40:].lower()
    if not matches or actual <= 0 or (required is not None and abs(actual - required) > Decimal('0.01')):
        return _result('mismatch', verifiedAmount=float(actual), **{'from': sender, 'to': receiver},
                       checkError='Токен, адреса или сумма не совпали')
    return _result('confirmed', verifiedAmount=float(actual), timestampMs=timestamp_ms,
                   **{'from': actual_from, 'to': receiver})
