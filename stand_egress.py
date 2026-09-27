"""Заглушка T5, заменяется модулем T1."""

_policy = lambda channel, recipient, operation: operation in ('getMe', 'getWebhookInfo', 'getUpdates')


def set_policy(policy):
    """Зарегистрировать политику получателей."""
    global _policy
    _policy = policy


def can_send(channel, recipient, operation):
    """Проверить решение политики."""
    return bool(_policy(channel, recipient, operation))


def tg_call(method, payload):
    """Заглушка T5, заменяется модулем T1; сеть здесь всегда выключена."""
    if not can_send('telegram', (payload or {}).get('chat_id'), method):
        return {'ok': False, 'error': 'policy_denied'}
    return {'ok': False, 'error': 't1_not_installed'}
