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
