# -*- coding: utf-8 -*-
"""Реестр компаний-агентов, от имени которых выпускаются документы.

Документы (договор, допсоглашение / Приложения 1–2, счёт) выпускает та компания,
на чьи реквизиты платит клиент. Всё, что у компаний отличается, лежит здесь, в
одном месте: docgen, стенд и раздел «Документы» CRM ничего не знают про
конкретные компании.

Добавить новую компанию:
  1. запись в `AGENTS` (поля — по образцу `flow_sole`);
  2. папка ассетов `doc_templates/assets/<key>/` (logo.png, signature.png, stamp.png);
  3. строка в `PAYIN_ACCOUNT_AGENT` — какой счёт прихода ведёт к этой компании
     (плюс реквизиты счёта в `ACCOUNT_REQUISITES`, если счёт надо узнавать по тексту).
Больше нигде править не нужно.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, replace

DEFAULT_AGENT = 'mf_corp'
ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'doc_templates', 'assets')


@dataclass(frozen=True)
class Agent:
    """Профиль компании-агента. Все поля, которые в документах различаются."""
    key: str
    name: str                       # полное название: «MF Corporation Company Limited»
    short_name: str                 # «MF» / «Flow Sole» — «менеджеру X», «send to the X manager»
    contact_name: str               # «менеджер X / X manager» в контакте для подтверждения
    header_name: str                # название в шапке (в шаблоне — «MF Corporation Co. Ltd»)
    jurisdiction_ru: str            # «учрежденное по праву <...>»
    jurisdiction_en: str            # «incorporated under the laws of <...>»
    reg_ru: str                     # вид номера в преамбуле: «регистрационный и налоговый номер»
    reg_en: str                     # «registration and tax number»
    reg_label_en: str               # подпись в блоке реквизитов: «Registration / Tax No.»
    reg_no: str
    address: str
    header_address: tuple           # две строки адреса в шапке
    director: str
    director_title: str             # «Director»
    acting_ru: str                  # «действующей» / «действующего» — по роду директора
    phone: str
    email: str | None               # None — строку E-mail не выводим
    place_ru: str                   # «г. Пхукет, Таиланд»
    place_en: str                   # «Phuket, Thailand»
    fee_label: str                  # «Комиссия MF» / «Комиссия Агента»
    file_prefix: str                # начало имени файла: MF_Agreement_… / FSC_Agreement_…
    rub_account_role: str           # роль получателя, когда рублёвый счёт принадлежит самому Агенту
    payin_recipients: tuple         # наименования получателя, которые считаются самим Агентом
    assets_dir: str                 # папка ассетов относительно doc_templates/assets
    logo: str                       # файл логотипа для шапки
    signature: str
    stamp: str
    signature_width_in: float = 1.4
    stamp_width_in: float = 1.2
    logo_height_emu: int = 0        # 0 — оставить размер логотипа из шаблона
    footer: str | None = None       # слоган в футере; None — футера нет
    footer_icon: str | None = None  # иконка футера; None — без иконки
    native_template: bool = False   # шаблоны .docx уже в фирменном виде этой компании

    def asset(self, name: str) -> str:
        return os.path.join(ASSETS_DIR, self.assets_dir, name)

    @property
    def confirmation_contact(self) -> str:
        """Контакт для подтверждения платежа: почта (если есть) и менеджер компании."""
        manager = f'менеджер {self.contact_name} / {self.contact_name} manager'
        return f'{self.email}; {manager}' if self.email else manager

    @property
    def signature_path(self) -> str:
        return self.asset(self.signature)

    @property
    def stamp_path(self) -> str:
        return self.asset(self.stamp)

    @property
    def logo_path(self) -> str:
        return self.asset(self.logo)


MF_CORP = Agent(
    key='mf_corp',
    name='MF Corporation Company Limited',
    short_name='MF',
    contact_name='MF Corporation',
    header_name='MF Corporation Co. Ltd',
    jurisdiction_ru='Таиланда',
    jurisdiction_en='Thailand',
    reg_ru='регистрационный и налоговый номер',
    reg_en='registration and tax number',
    reg_label_en='Registration / Tax No.',
    reg_no='0835565024547',
    address='9/31, Mu 5, Choeng Thale Sub-district, Thalang District, Phuket Province 83110, Thailand',
    header_address=('9/31, Mu 5, Choeng Thale, Thalang District, ', 'Phuket, 83110,Thailand'),
    director='Miss Katika Sakornnoi',
    director_title='Director',
    acting_ru='действующей',
    phone='+66 991971701',
    email='mfcorpthai@gmail.com',
    place_ru='г. Пхукет, Таиланд',
    place_en='Phuket, Thailand',
    fee_label='Комиссия MF',
    file_prefix='MF',
    rub_account_role='Агент (рублёвый счёт MF в РФ) / Agent (MF RUB account in Russia)',
    payin_recipients=('ООО «ЭМ ЭФ КОРПОРЕЙШН»',),
    assets_dir='',
    logo='mfcorp_logo.png',
    signature='signature.png',
    stamp='stamp.png',
    footer='RELIABLE PARTNER. SUCCESSFUL BUSINESS',
    native_template=True,
)

FLOW_SOLE = Agent(
    key='flow_sole',
    name='Flow Sole Company Limited',
    short_name='Flow Sole',
    contact_name='Flow Sole',
    header_name='Flow Sole Company Limited',
    jurisdiction_ru='Лаосской Народно-Демократической Республики',
    jurisdiction_en='the Lao People’s Democratic Republic',
    reg_ru='налоговый номер',
    reg_en='Tax Identification No.',
    reg_label_en='Tax Identification No.',
    reg_no='284530232-000',
    address='Thongkang Village, Sisattanak District, Vientiane Capital, Lao PDR',
    header_address=('Thongkang Village, Sisattanak District, ', 'Vientiane Capital, Lao PDR'),
    director='Mr. Souvahn Phanthavong',
    director_title='Director',
    acting_ru='действующего',
    phone='+856 20 59932483',
    email=None,
    place_ru='г. Вьентьян, Лаос',
    place_en='Vientiane, Lao PDR',
    fee_label='Комиссия Агента',
    file_prefix='FSC',
    rub_account_role='Агент (рублёвый счёт в РФ) / Agent (RUB account in Russia)',
    payin_recipients=('ФЛОУ СОЛЕ КО., ЛТД',),
    assets_dir='flow_sole',
    logo='logo.png',
    signature='signature.png',
    stamp='stamp.png',
    signature_width_in=1.0,
    logo_height_emu=770000,
    footer=None,
)

AGENTS: dict[str, Agent] = {a.key: a for a in (MF_CORP, FLOW_SOLE)}

# Счёт прихода → компания-агент. Ключи — «личность» счёта из stand_funding.account_identity
# (sber, flow_sole). Всё, чего здесь нет (чужие custom-счета, USDT, наличные, СБП), — MF.
PAYIN_ACCOUNT_AGENT = {
    'sber': 'mf_corp',
    'flow_sole': 'flow_sole',
}

# Реквизиты известных счетов: нужны, чтобы узнать счёт по свободному тексту
# («Реквизиты для оплаты» в разделе «Документы» CRM). Номера счетов обязаны
# совпадать с stand_funding.ACCOUNT_ALIASES — это проверяет тест.
ACCOUNT_REQUISITES = {
    'sber': {'inn': '9909726886', 'account': '40807810938720000286'},
    'flow_sole': {'inn': '9909773251', 'account': '40807810819000000261'},
}


class UnknownAgent(ValueError):
    """Ключа агента нет в реестре."""


def get_agent(agent=None) -> Agent:
    """Ключ или профиль → профиль. None и пустая строка — агент по умолчанию (MF)."""
    if isinstance(agent, Agent):
        return agent
    key = (agent or DEFAULT_AGENT)
    try:
        return AGENTS[key]
    except (KeyError, TypeError):
        raise UnknownAgent(f'неизвестная компания-агент: {agent!r}') from None


def normalize_key(value) -> str:
    """Ключ агента из сохранённых данных; пусто / неизвестно (старые записи) — MF."""
    return value if value in AGENTS else DEFAULT_AGENT


def agent_for_account(identity) -> str:
    """Личность счёта прихода (sber / flow_sole / other:… / None) → ключ агента."""
    return PAYIN_ACCOUNT_AGENT.get(identity, DEFAULT_AGENT)


def _account_in_text(text: str) -> str | None:
    """Известный счёт (по ИНН или номеру счёта) в свободном тексте реквизитов."""
    found = set()
    tokens = set(re.findall(r'\d{9,}', text or ''))
    for identity, req in ACCOUNT_REQUISITES.items():
        if tokens & {req['inn'], req['account']}:
            found.add(identity)
    # Реквизиты двух разных компаний в одном тексте — неоднозначность; не угадываем.
    return found.pop() if len(found) == 1 else None


def agent_for_requisites(*texts) -> str:
    """Агент по свободному тексту реквизитов получателя (CRM: payin_recipient + payin_details)."""
    return agent_for_account(_account_in_text(' '.join(str(t) for t in texts if t)))


def agent_for_money(money) -> str:
    """Агент для выпуска из CRM: явный `agent` в money, иначе по реквизитам прихода.

    Явный неизвестный ключ — ошибка (UnknownAgent), а не тихий откат на MF:
    документ не должен уйти от чужого имени.
    """
    money = money or {}
    explicit = money.get('agent')
    if explicit:
        return get_agent(explicit).key
    if money.get('payin_method', 'bank') != 'bank':
        return DEFAULT_AGENT          # USDT, наличные, СБП — всегда MF
    return agent_for_requisites(money.get('payin_recipient'), money.get('payin_details'))


def route_key(pair: str, method: str, agent=None) -> str:
    """Маршрут договора: пара + способ оплаты + агент.

    Для MF ключ прежний («RUB_THB:bank») — старые договоры без ключа агента
    остаются договорами MF и не требуют миграции.
    """
    key = get_agent(agent).key
    base = f'{pair}:{method}'
    return base if key == DEFAULT_AGENT else f'{base}:{key}'


def agent_of_route_key(value) -> str:
    """Агент из ключа маршрута; нет третьей части (старые записи) — MF."""
    parts = str(value or '').split(':')
    return normalize_key(parts[2]) if len(parts) > 2 else DEFAULT_AGENT


def foreign_markers(agent) -> list[str]:
    """Признаки ЧУЖИХ компаний (название, рег. номер, директор) — для проверки готового документа."""
    own = get_agent(agent).key
    out = []
    for key, other in AGENTS.items():
        if key != own:
            out += [other.name, other.reg_no, other.director]
    return out


def with_overrides(agent, **kwargs) -> Agent:
    """Копия профиля с правками — для тестов."""
    return replace(get_agent(agent), **kwargs)
