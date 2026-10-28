"""Политика подписей кошелька. Чистые функции, без БД.

Источник правды задачника — явные поля реестра:
  initiator_roles  («Заводит»)     — 1–2 роли, начинают перевод;
  confirmer_roles  («Подписывает») — 1–2 роли, подписывают перевод инициатора;
  owner_can_alone  — владелец может отправить сам, без второй подписи.

Веса ролей и порог (`signer_weights`, `threshold`) — только проверка
согласованности: каждая пара «заводит i + подписывает s» (i ≠ s) обязана набирать
порог, а `owner_can_alone` требует вес владельца не ниже порога. У кошельков без
весов проверка пропускается. Те же правила повторены в static/stand/tasks.html.
"""
import json

OPERATOR, FINDIR, OWNER = 'operator', 'findir', 'teodor'
# Допустимые роли в полях политики и их порядок в интерфейсе.
POLICY_ROLES = (OPERATOR, FINDIR, OWNER)
MAX_POLICY_ROLES = 2

ROLE_DATIVE = {OPERATOR: 'операционисту', FINDIR: 'финансисту', OWNER: 'владельцу'}
ROLE_NAME = {OPERATOR: 'операционист', FINDIR: 'финансист', OWNER: 'владелец'}
ROLE_GENITIVE = {OPERATOR: 'операциониста', FINDIR: 'финансиста', OWNER: 'владельца'}


def parse_roles(raw):
    """JSON-строка или список → список ролей без дублей и мусора, в порядке записи."""
    if isinstance(raw, (str, bytes)):
        try:
            raw = json.loads(raw or '[]')
        except (TypeError, ValueError):
            return []
    if not isinstance(raw, list):
        return []
    out = []
    for role in raw:
        if role in POLICY_ROLES and role not in out:
            out.append(role)
    return out


def validate_roles(value, label):
    """Для API: (список, None) или (None, текст ошибки). 1–2 роли, без дублей."""
    if not isinstance(value, list) or not all(isinstance(r, str) for r in value):
        return None, f'«{label}»: передайте список ролей'
    if not 1 <= len(value) <= MAX_POLICY_ROLES:
        return None, f'«{label}»: выберите одну или две роли'
    if len(set(value)) != len(value):
        return None, f'«{label}»: роли не должны повторяться'
    if any(r not in POLICY_ROLES for r in value):
        return None, f'«{label}»: допустимы операционист, финансист, владелец'
    return list(value), None


def normalize_weights(raw):
    """JSON-строка или dict → {роль: int > 0}. Мусор и нулевые веса отбрасываются."""
    if isinstance(raw, (str, bytes)):
        try:
            raw = json.loads(raw or '{}')
        except (TypeError, ValueError):
            return {}
    if not isinstance(raw, dict):
        return {}
    return {str(role): weight for role, weight in raw.items()
            if isinstance(weight, int) and not isinstance(weight, bool) and weight > 0}


def can_complete(weights, threshold, roles):
    """Сумма весов РАЗНЫХ ролей из `roles` не меньше порога."""
    weights = normalize_weights(weights)
    if isinstance(threshold, bool) or not isinstance(threshold, int) or threshold <= 0:
        return False
    return sum(weights.get(role, 0) for role in set(roles or ())) >= threshold


def consistency_problems(initiator_roles, confirmer_roles, owner_can_alone, weights, threshold):
    """Рассогласование явной политики с весами. Пустой список — согласовано
    (или весов нет: проверка пропускается)."""
    weights = normalize_weights(weights)
    if not weights:
        return []
    problems = []
    for init in initiator_roles:
        for sign in confirmer_roles:
            if init != sign and not can_complete(weights, threshold, [init, sign]):
                problems.append(f'заводит {init} + подписывает {sign} не набирают порог {threshold}')
    if owner_can_alone and not can_complete(weights, threshold, [OWNER]):
        problems.append(f'владелец не набирает порог {threshold} один')
    return problems


def initial_role(initiator_roles):
    """Кому задача назначается сначала: первая роль из «Заводит»."""
    roles = parse_roles(initiator_roles)
    return roles[0] if roles else None


def initiate_targets(initiator_roles, owner_can_alone, current):
    """Кому менеджер может передать задачу завести перевод: роли из «Заводит»
    и владелец (если может отправить сам), кроме текущей."""
    roles = parse_roles(initiator_roles)
    if owner_can_alone and OWNER not in roles:
        roles.append(OWNER)
    return [role for role in POLICY_ROLES if role in roles and role != current]


def can_claim(owner_can_alone, current, role):
    """Взять перевод может текущая роль; владелец — всегда, если может сам."""
    return role == current or (role == OWNER and bool(owner_can_alone))


def default_sign_role(confirmer_roles, initiator_role):
    """По умолчанию подпись у первой роли из «Подписывает», которая не завела."""
    for role in parse_roles(confirmer_roles):
        if role != initiator_role:
            return role
    return None


def sign_targets(confirmer_roles, initiator_role, current):
    """Кому можно переназначить подпись: «Подписывает» без инициатора и текущей роли."""
    return [role for role in parse_roles(confirmer_roles)
            if role != initiator_role and role != current]


def policy_ready(initiator_roles, confirmer_roles):
    """Политика задана: есть и «Заводит», и «Подписывает»."""
    return bool(parse_roles(initiator_roles)) and bool(parse_roles(confirmer_roles))
