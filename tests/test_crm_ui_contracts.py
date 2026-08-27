"""Контракты UI-разметки CRM (static/crm/crm.html).

Ловят класс багов «JS адресует уникальный элемент селектором, который
неоднозначен в рантайме». Реальный кейс: кнопка сохранения кастомной сделки
бралась как `#customDealSection .btn-success`, а внутри той же секции JS
рендерит кнопки «Забрать» с тем же классом (пул приходов Сбера). Селектор
цеплял «Забрать», кнопка submit оставалась в режиме создания — правка сделки
(в т.ч. добавление реферала/агента) уходила в POST и создавала новую сделку.

Тесты статические: парсят HTML+JS без браузера, чтобы работать в обычном
pytest-прогоне.
"""
import re
from pathlib import Path

import pytest

CRM_HTML = Path(__file__).resolve().parent.parent / 'static' / 'crm' / 'crm.html'


@pytest.fixture(scope='module')
def html():
    return CRM_HTML.read_text(encoding='utf-8')


# ==================== helpers ====================

TAG_RE = re.compile(r'<(/?)(\w+)([^>]*?)(/?)>')
VOID_TAGS = {'br', 'hr', 'img', 'input', 'meta', 'link', 'source', 'area', 'base', 'col'}


def extract_subtree(html: str, elem_id: str) -> str:
    """Возвращает HTML элемента с данным id вместе с потомками (баланс тегов)."""
    start = re.search(r'<(\w+)[^>]*\bid=["\']%s["\']' % re.escape(elem_id), html)
    if not start:
        raise AssertionError(f'элемент #{elem_id} не найден в crm.html')
    tag = start.group(1)
    depth = 0
    pos = start.start()
    for m in TAG_RE.finditer(html, pos):
        if m.group(2) != tag:
            continue
        if m.group(1) == '/':
            depth -= 1
            if depth == 0:
                return html[start.start():m.end()]
        elif not m.group(4) and m.group(2) not in VOID_TAGS:
            depth += 1
    raise AssertionError(f'не закрыт тег <{tag}> элемента #{elem_id}')


def class_occurrences(fragment: str, cls: str) -> int:
    """Сколько раз класс встречается в атрибутах class= внутри фрагмента."""
    return sum(
        1 for attr in re.findall(r'class=["\']([^"\']*)["\']', fragment)
        if cls in attr.split()
    )


def ids_inside(fragment: str) -> set:
    return set(re.findall(r'\bid=["\']([\w-]+)["\']', fragment))


def innerhtml_templates(html: str):
    """[(ключ id, prefix?, шаблон)] — куда и чем JS пишет через `.innerHTML =`.

    Покрывает две формы: `getElementById('x').innerHTML = ...` и
    `const el = getElementById('x' + sfx); ... el.innerHTML = ...`.
    Во второй форме id часто склеивается с суффиксом ('sberIncomesAvail' + 'C'),
    поэтому такой ключ помечается как префикс и матчится по startswith.
    """
    out = []
    # прямая форма
    for m in re.finditer(
        r"getElementById\(\s*['\"]([\w-]+)['\"]\s*(\+)?[^)]*\)\s*\.innerHTML\s*=\s*(.{0,4000}?);\n",
        html, re.S,
    ):
        out.append((m.group(1), bool(m.group(2)), m.group(3)))
    # через переменную
    for m in re.finditer(
        r"(?:const|let|var)\s+(\w+)\s*=\s*document\.getElementById\(\s*['\"]([\w-]+)['\"]\s*(\+)?",
        html,
    ):
        var, cid, concat = m.group(1), m.group(2), bool(m.group(3))
        tail = html[m.end():m.end() + 4000]
        for t in re.finditer(rf"\b{re.escape(var)}\.innerHTML\s*=\s*(.{{0,4000}}?);\n", tail, re.S):
            out.append((cid, concat, t.group(1)))
    return out


def templates_for(templates, container_id: str):
    """Шаблоны, которые пишут в контейнер с данным id (с учётом склеенных id)."""
    return [
        tpl for key, is_prefix, tpl in templates
        if key == container_id or (is_prefix and container_id.startswith(key))
    ]


# ==================== тесты ====================

def test_custom_submit_button_has_unique_id(html):
    """Кнопка сохранения кастомной сделки адресуема по стабильному id."""
    assert html.count('id="customDealSubmit"') == 1, \
        'кнопка submit кастомной формы должна иметь ровно один id="customDealSubmit"'
    section = extract_subtree(html, 'customDealSection')
    assert 'id="customDealSubmit"' in section, \
        'кнопка customDealSubmit должна лежать внутри #customDealSection'


def test_custom_submit_bound_only_through_helper(html):
    """Переключение create ↔ edit идёт через setCustomSubmitMode, не по классу."""
    assert "querySelector('#customDealSection .btn-success')" not in html, \
        ('регрессия: submit кастомной формы снова ищется по классу — селектор '
         'цепляет кнопки «Забрать» пула приходов Сбера')
    assert "document.getElementById('customDealSubmit')" in html
    # edit-режим вешает update, create-режим — create
    helper = re.search(r'function setCustomSubmitMode\(dealId\)\s*\{(.+?)\n        \}', html, re.S)
    assert helper, 'функция setCustomSubmitMode не найдена'
    body = helper.group(1)
    assert 'updateCustomDeal(dealId)' in body, 'edit-режим должен вызывать updateCustomDeal'
    assert 'createCustomDeal' in body, 'create-режим должен вызывать createCustomDeal'
    # обе точки переключения используют хелпер
    assert 'setCustomSubmitMode(dealId)' in html, 'openDealEditor должен звать setCustomSubmitMode(dealId)'
    assert 'setCustomSubmitMode(null)' in html, 'cancelEditMode должен звать setCustomSubmitMode(null)'


def test_no_ambiguous_container_class_selectors(html):
    """querySelector('#контейнер .класс') должен указывать на уникальный элемент.

    Неоднозначность возникает, если класс встречается в контейнере несколько раз
    в статике ИЛИ если JS рендерит его в один из вложенных контейнеров.
    """
    templates = innerhtml_templates(html)
    problems = []
    for container, cls in set(re.findall(r"querySelector\(\s*['\"]#([\w-]+)\s+\.([\w-]+)['\"]", html)):
        subtree = extract_subtree(html, container)
        static_hits = class_occurrences(subtree, cls)
        if static_hits > 1:
            problems.append(
                f"#{container} .{cls}: {static_hits} совпадений в статике — нужен id"
            )
        for cid in ids_inside(subtree):
            for tpl in templates_for(templates, cid):
                if re.search(rf'class=["\'][^"\']*\b{re.escape(cls)}\b', tpl):
                    problems.append(
                        f"#{container} .{cls}: JS рендерит этот класс в #{cid} "
                        f"(innerHTML) — селектор поймает динамический элемент, нужен id"
                    )
    assert not problems, 'неоднозначные селекторы:\n' + '\n'.join(problems)


def test_legacy_referrer_visible_in_both_editor_forms(html):
    """Легаси-реферер подставляется агентом ур.1 и в стандартной, и в кастомной форме."""
    assert 'function dealAgentsOrLegacy(deal)' in html, \
        'общий хелпер dealAgentsOrLegacy не найден'
    assert 'stdAgentsLoad(dealAgentsOrLegacy(deal))' in html, \
        'стандартная форма должна грузить агентов через dealAgentsOrLegacy'
    assert 'customAgentsLoad(dealAgentsOrLegacy(deal))' in html, \
        ('кастомная форма должна грузить агентов через dealAgentsOrLegacy — иначе '
         'легаси-реферер невидим и молча теряется при сохранении')


def test_sber_income_pool_renders_btn_success(html):
    """Страховка сценария: пул приходов Сбера действительно рендерит .btn-success.

    Если это перестанет быть правдой, тест выше про неоднозначные селекторы
    потеряет смысл — лучше узнать об этом явно.
    """
    assert re.search(r"class=[\"']btn btn-success btn-sm[\"'][^>]*onclick=\\?[\"']sberAddIncome", html), \
        'кнопка «Забрать» пула приходов Сбера больше не .btn-success — пересмотреть контракт'


# ==================== состояние редактора сделки ====================
# Кейс #463 (06.08): открыли редактор одной сделки, не дождались загрузки —
# перешли в другую. Ответ первого запроса заполнял форму ПОСЛЕ переключения
# editingDealId, и обычная сделка сохранилась как «фрихолд» с пустыми полями.
# Сохранение уходит в ту сделку, что в editingDealId, поэтому любое заполнение
# формы устаревшим ответом = порча чужих данных.

def _function_body(html: str, name: str) -> str:
    """Тело функции верхнего уровня (по отступу закрывающей скобки)."""
    m = re.search(rf'^([ \t]*)(?:async +)?function {re.escape(name)}\s*\([^)]*\)\s*\{{',
                  html, re.M)
    assert m, f'функция {name} не найдена в crm.html'
    indent = m.group(1)
    end = html.find(f'\n{indent}}}', m.end())
    assert end != -1, f'не найден конец функции {name}'
    return html[m.end():end]


def test_editor_ignores_stale_response(html):
    """openDealEditor не заполняет форму ответом устаревшего запроса."""
    body = _function_body(html, 'openDealEditor')
    assert '_editorRequestId' in body, \
        ('регрессия: пропала защита от гонки редакторов — открытие второй сделки '
         'до загрузки первой снова заполнит форму чужими данными')
    guard = re.search(r'if\s*\(\s*reqId\s*!==\s*_editorRequestId\s*\)\s*return', body)
    assert guard, 'нужен ранний выход, когда пока грузили — открыли другую сделку'
    fill = body.find('if (data.success)')
    assert fill != -1 and guard.start() < fill, \
        'проверка актуальности запроса должна стоять ДО заполнения формы'


DEAL_KIND_TOGGLES = ['customDealToggle', 'mfDealToggle', 'fhDealToggle']


def test_editor_resets_every_kind_toggle(html):
    """Каждая ветка редактора выставляет ВСЕ переключатели типа сделки.

    Иначе тип протекает между сделками: открыл фрихолд, следом кастомную —
    и она сохраняется с полями фрихолда.
    """
    body = _function_body(html, 'openDealEditor')
    for toggle in DEAL_KIND_TOGGLES:
        assert f"getElementById('{toggle}').checked =" in body, \
            f'openDealEditor не выставляет {toggle} — состояние прошлой сделки останется'


def test_cancel_and_submit_reset_all_toggles(html):
    """Отмена редактирования и успешное сохранение чистят все типы."""
    cancel = _function_body(html, 'cancelEditMode')
    for toggle in DEAL_KIND_TOGGLES:
        assert toggle in cancel, f'cancelEditMode не сбрасывает {toggle}'
    # после успешного сохранения форма возвращается в режим создания
    submit = html[html.find('showToast(isEditMode ?'):][:1500]
    for toggle in DEAL_KIND_TOGGLES:
        assert toggle in submit, f'после сохранения не сброшен {toggle}'


def test_kind_select_options_match_toggles(html):
    """Каждый пункт «Тип сделки» имеет обработку в onDealKindChange."""
    select = extract_subtree(html, 'dealKindSelect')
    values = set(re.findall(r'<option value="([\w_]+)"', select))
    assert values == {'exchange', 'custom', 'mf_realty', 'mf_freehold'}, values
    body = _function_body(html, 'onDealKindChange')
    for value in values - {'exchange'}:
        assert f"'{value}'" in body, f'onDealKindChange не обрабатывает тип {value}'
    sync = _function_body(html, 'syncDealKindSelect')
    for value in values - {'exchange'}:
        assert f"'{value}'" in sync, f'syncDealKindSelect не знает про тип {value}'


def test_agent_model_rerenders_on_referrer_pick(html):
    """Выбор реферера перерисовывает блок агентов.

    Регрессия 06.08: модель и процент подставлялись из профиля в данные, но
    селект оставался прежним — на экране revshare, считался markup ($299.70
    вместо $6.00), и сделка сохранялась по невидимой модели.
    """
    for field_fn, render_fn in (('stdAgentsField', 'renderStdAgents'),
                                ('customAgentsField', 'renderCustomAgents')):
        body = _function_body(html, field_fn)
        assert re.search(rf"referrer_id'\s*\)\s*{re.escape(render_fn)}\(\)|"
                         rf"k\s*===\s*'comp_model'\s*\|\|\s*k\s*===\s*'referrer_id'\s*\)\s*{re.escape(render_fn)}\(\)",
                         body), \
            f'{field_fn}: после выбора реферера нужен {render_fn}() — иначе модель на экране врёт'


def test_realty_payout_block_is_shared_not_duplicated(html):
    """Блок фактических переводов один на оба типа недвижимости."""
    assert html.count('id="realtyPayoutTxBlock"') == 1
    for slot in ('mfPayoutSlot', 'fhPayoutSlot'):
        assert f'id="{slot}"' in html, f'нет слота {slot} для переезда блока переводов'
    body = _function_body(html, 'moveRealtyPayoutBlock')
    assert 'appendChild' in body, 'блок переводов должен переезжать в активную форму'


def test_conversion_return_has_tx_picker(html):
    """Возврат оунеру из раскладки пачки выбирается из списка, а не вбивается.

    Возмещение создаётся одним и тем же POST /api/reimbursements из двух мест —
    вкладки «Возмещения» и раскладки прихода. Во вкладке список исходящих был,
    в раскладке оставался только ручной хеш: одно действие двумя способами,
    причём в неудобном хеш переписывали глазами.
    """
    render = _function_body(html, 'renderConvDistribution')
    assert 'convRetSel${g.wallet_id}' in render, 'в группе возврата нет селекта переводов'
    assert 'convRetTxOptions(g.address)' in render, \
        'список переводов должен строиться от адреса кошелька группы'
    assert 'convRetHash${g.wallet_id}' in render, 'ручной ввод хеша остаётся запасным путём'

    options = _function_body(html, 'convRetTxOptions')
    assert 'На этот кошелёк' in options, 'переводы на кошелёк оунера должны идти первыми'

    pick = _function_body(html, 'pickConvRetTx')
    assert 'convRetHash' in pick, 'выбор из списка должен подставлять хеш в поле возврата'

    show = _function_body(html, 'showConversion')
    assert '/api/transactions/outgoing' in show, 'список переводов не грузится при открытии пачки'


def test_settled_checkbox_lives_in_deal_form(html):
    """Возмещать или нет — отмечается в сделке, а не в форме возмещений.

    Карим (27.08): «мы не расширяем интерфейс в возмещении, это всё делаем
    в моменте, в создании сделки — это ускоряет работу». Селект типа в форме
    возмещений был убран, вместо него галка рядом с переводами выдачи.
    """
    assert 'id="payoutSettledByPayin"' in html
    assert 'reimburse-kind' not in html, 'селект типа в возмещениях должен быть убран'
    # Галка управляет именно флагом возмещения
    assert 'data.needs_reimbursement = !payoutSettledOn()' in html
