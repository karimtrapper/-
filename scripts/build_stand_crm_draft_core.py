"""Проверяемая выборка чистой логики формы CRM для черновика задачника.

Исходник CRM не меняем. --check нужен в тестах: изменение исходника без
перегенерации адаптера должно падать, а не создавать тихое расхождение.
"""

from pathlib import Path
import argparse


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "static/crm/crm.html"
TARGET = ROOT / "static/stand/crm-draft-core.js"

# Правая граница каждой выборки включается только в следующую выборку. Маркеры
# намеренно точные: если CRM перестроит участок, генератор остановится.
SLICES = [
    ("        function _customFormProfitVolume()", "        // Каскад (зеркало backend compute_agent_cascade)"),
    ("        function customAgentsPreset(", "        // ===== Виджет агентов для СТАНДАРТНОЙ формы"),
    ("        // Что считаем производным: 'rate'", "        // Подбор входящей транзакции в кастомной сделке"),
    ("        async function onCustomPayinMethodChange()", "        let _customDealSubmitting = false;"),
    ("        function upgradeSelect(select)", "        // ==================== HTML escape"),
    ("        function formatDate(dateStr)", "        function getStatusLabel("),
    ("        function reportInvalidField(form)", "        document.getElementById('createDealForm').addEventListener('submit'"),
    ("        function _agentsCascade(", "        function customAgentsPreset("),
    ("        function _stdProfitVolume(", "        function stdAgentsPreset("),
    ("        function _stdApplyAgents(", "        // Что считаем производным"),
    ("        function calculateProfit(", "        /**\n         * Приход по СБП"),
    ("        function markProfitPending(", "        // Auto-calculate on input change"),
    ("        function payoutTxPoolTotal(", "        function renderPayoutTxPool("),
    ("        function noConversionOn(", "        // ===== «Деньги за выдачу уже у нас»"),
    ("        async function loadCashBatchesForSelect(", "        // Update card info when selected"),
    ("        function methodUsesSberPool(", "        function setPayinMethodValue("),
    ("        function peHashes(", "        function applyPayinMethodFields("),
    ("        function applyPayinMethodFields()", "        // ==================== Сбер (реквизиты):"),
    ("        function sberSfx()", "        function sberSetKindFilter("),
    ("        function sberSetKindFilter(", "        function sberKindChanged("),
    ("        function sberKindChanged(", "        async function sberLoadIncomes("),
    ("        async function sberLoadIncomes(", "        function sberAddIncome("),
    ("        function sberAddIncome(", "        // Приход уже прошёл через пачку конвертации"),
    ("        function applyConversionUsdt(", "        function sberAddManual("),
    ("        function sberAddManual(", "        function sberRemovePart("),
    ("        function sberRemovePart(", "        const rub2 ="),
    ("        const rub2 =", "        // Строка прихода в пуле."),
    ("        function sberIncomeLine(", "        function sberPartsSum("),
    ("        function sberPartsSum(", "        function sberRender("),
    ("        function sberRender(", "        function sberReset("),
    ("        function payinTxPoolTotal(", "        function renderPayinTxPool("),
    ("        function renderPayinTxPool(", "        // Реестр переводов:"),
    ("        const round2 =", "        // Доля перевода, которая идёт в ЭТУ сделку."),
    ("        function payinTxShareChanged(", "        // Данные реестра подтягиваются лениво:"),
    ("        async function loadPayinTxLedger(", "        function syncPayinAmountFromPool("),
    ("        function syncPayinAmountFromPool(", "        function selectPayinTx("),
    ("        function selectPayinTx(", "        function removePayinTx("),
    ("        function removePayinTx(", "        function resetPayinTxPool("),
    ("        function resetPayinTxPool(", "        // Загрузка исходящих транзакций для Binance"),
    ("        function autoCalcUsdt(", "        function calculateProfit("),
    ("        function renderMfSummary(", "        async function mfSuggestPercent("),
    ("        function renderFhSummary(", "        function fhFormData("),
    ("        function stdAgentsPreset(", "        function stdAgentsAdd("),
    ("        function stdAgentsAdd(", "        function stdAgentsRemove("),
    ("        function stdAgentsRemove(", "        function stdAgentsTier("),
    ("        function stdAgentsTier(", "        function stdAgentsField("),
    ("        function stdAgentsField(", "        function renderStdAgents("),
    ("        function renderStdAgents(", "        function stdAgentsRecalc("),
    ("        function stdAgentsRecalc(", "        function stdAgentsSerialize("),
    ("        function stdAgentsSerialize(", "        function stdAgentsLoad("),
    ("        function stdAgentsLoad(", "        // Применяет агентов в стандартной форме"),
    ("        function mfPayoutTxTotal(", "        function renderMfPayoutTxPool("),
    ("        function renderMfPayoutTxPool(", "        // Список исходящих для выбора"),
    ("        function toggleMfPayoutPicker(", "        function mfPayoutVisible("),
    ("        function mfPayoutVisible(", "        function renderMfPayoutPicker("),
    ("        function renderMfPayoutPicker(", "        function mfPayoutCheck("),
    ("        function mfPayoutCheck(", "        function mfPayoutCheckAll("),
    ("        function mfPayoutCheckAll(", "        let mfPayoutAdding ="),
    ("        async function addMfPayoutChecked(", "        async function addMfPayoutManual("),
    ("        async function addMfPayoutManual(", "        function removeMfPayoutTx("),
    ("        function removeMfPayoutTx(", "        // Пул переводов общий"),
    ("        function resetMfPayoutTxPool(", "        async function loadMfPayoutTx("),
    ("        async function loadMfPayoutTx(", "        function toggleCustomDeal("),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    source = SOURCE.read_text()
    pieces = []
    for start, end in SLICES:
        if source.count(start) != 1 or source.count(end) != 1:
            raise SystemExit(f"CRM marker missing or ambiguous: {start!r} / {end!r}")
        a, b = source.index(start), source.index(end)
        if b <= a:
            raise SystemExit(f"CRM marker order changed: {start!r}")
        pieces.append(source[a:b].rstrip())
    # CRM's extra-Pay-In renderer writes free text into innerHTML. A draft may
    # contain user input, so escape these slots without changing its calculations.
    extra_index = next(i for i, (start, _) in enumerate(SLICES)
                       if start == "        function peHashes(")
    extra = pieces[extra_index]
    for old, new in [
        ("${p.partner_name || ''}", "${escapeHtml(p.partner_name || '')}"),
        ('value="${t.tx_hash}"', 'value="${escapeHtml(t.tx_hash)}"'),
        ("${(t.from_address || '').substring(0, 10)}", "${escapeHtml((t.from_address || '').substring(0, 10))}"),
    ]:
        if extra.count(old) != 1:
            raise SystemExit(f"CRM draft safety substitution changed: {old}")
        extra = extra.replace(old, new)
    pieces[extra_index] = extra
    # Text from local/chain datasets is still untrusted when inserted into a
    # CRM template literal. Escape the remaining draft-specific HTML slots.
    safety_slots = [
        ("${r.name}</option>", "${escapeHtml(r.name)}</option>", 2),
        ("${x.date ? ' · ' + x.date : ''}", "${x.date ? ' · ' + escapeHtml(x.date) : ''}", 1),
        ("${(t.network || 'trc20').toUpperCase()}", "${escapeHtml((t.network || 'trc20').toUpperCase())}", 2),
        ("${err.error || resp.status}", "${escapeHtml(err.error || resp.status)}", 1),
        ("${e.message}", "${escapeHtml(e.message)}", 2),
    ]
    for old, new, expected in safety_slots:
        hits = sum(piece.count(old) for piece in pieces)
        if hits != expected:
            raise SystemExit(f"CRM draft safety slot changed ({hits}): {old}")
        pieces = [piece.replace(old, new) for piece in pieces]
    select_index = next(i for i, (start, _) in enumerate(SLICES)
                        if start == "        function upgradeSelect(select)")
    select_code = pieces[select_index]
    for old, new in [
        ("document.addEventListener('click', (e) => {", "root.addEventListener('click', (e) => {"),
        ('${o.text}</div>', '${escapeHtml(o.text)}</div>'),
        ('data-value="${o.value}"', 'data-value="${escapeHtml(o.value)}"'),
    ]:
        if select_code.count(old) != 1:
            raise SystemExit(f"CRM draft select safety substitution changed: {old}")
        select_code = select_code.replace(old, new)
    pieces[select_index] = select_code
    # CRM renders dynamic rows with inline handlers. In the draft these must
    # remain inert data, with only the adapter's scoped delegation executing
    # allowlisted actions. Exact source strings make drift fail generation.
    dynamic_handlers = [
        ('onclick="customAgentsRemove(${i})"', 'data-crm-action="custom-agent-remove" data-crm-event="click" data-index="${i}"'),
        ('onclick="customAgentsTier(${i},-1)"', 'data-crm-action="custom-agent-tier" data-crm-event="click" data-index="${i}" data-delta="-1"'),
        ('onclick="customAgentsTier(${i},1)"', 'data-crm-action="custom-agent-tier" data-crm-event="click" data-index="${i}" data-delta="1"'),
        ('onchange="customAgentsField(${i},\'referrer_id\',this.value)"', 'data-crm-action="custom-agent-field" data-crm-event="change" data-index="${i}" data-key="referrer_id"'),
        ('onchange="customAgentsField(${i},\'comp_model\',this.value)"', 'data-crm-action="custom-agent-field" data-crm-event="change" data-index="${i}" data-key="comp_model"'),
        ('oninput="customAgentsField(${i},\'fixed_usdt\',this.value)"', 'data-crm-action="custom-agent-field" data-crm-event="input" data-index="${i}" data-key="fixed_usdt"'),
        ('oninput="customAgentsField(${i},\'percent\',this.value)"', 'data-crm-action="custom-agent-field" data-crm-event="input" data-index="${i}" data-key="percent"'),
        ('onclick="sberAddIncome(\'${escapeHtml(i.uuid)}\')"', 'data-crm-action="sber-add" data-crm-event="click" data-uuid="${escapeHtml(i.uuid)}"'),
        ('onclick="sberRemovePart(${i})"', 'data-crm-action="sber-remove" data-crm-event="click" data-index="${i}"'),
        ('onchange="mfPayoutCheck(\'${tx.tx_hash}\', this.checked)"', 'data-crm-action="mf-check" data-crm-event="change" data-hash="${escapeHtml(tx.tx_hash)}"'),
        ('onclick="removeMfPayoutTx(${i})"', 'data-crm-action="mf-remove" data-crm-event="click" data-index="${i}"'),
        ('onclick="removePayinTx(${i})"', 'data-crm-action="payin-remove" data-crm-event="click" data-index="${i}"'),
        ('oninput="payinTxShareChanged(${i}, this.value)"', 'data-crm-action="payin-share" data-crm-event="input" data-index="${i}"'),
        ('onclick="payinExtraRemove(${i})"', 'data-crm-action="extra-remove" data-crm-event="click" data-index="${i}"'),
        ('onchange="payinExtraSetMethod(${i}, this.value)"', 'data-crm-action="extra-method" data-crm-event="change" data-index="${i}"'),
        ('onchange="payinExtraPickTx(${i}, this)"', 'data-crm-action="extra-pick" data-crm-event="change" data-index="${i}"'),
        ('onclick="payinExtraSberAdd(${i}, \'${escapeHtml(x.uuid)}\')"', 'data-crm-action="extra-sber-add" data-crm-event="click" data-index="${i}" data-uuid="${escapeHtml(x.uuid)}"'),
        ('onclick="payinExtraSberRemove(${i}, ${k})"', 'data-crm-action="extra-sber-remove" data-crm-event="click" data-index="${i}" data-subindex="${k}"'),
        ('onclick="payinExtraHashRemove(${i}, ${k})"', 'data-crm-action="extra-hash-remove" data-crm-event="click" data-index="${i}" data-subindex="${k}"'),
        ('onclick="payinExtraHashManual(${i})"', 'data-crm-action="extra-hash-manual" data-crm-event="click" data-index="${i}"'),
        ('oninput="payinExtraHashShare(${i}, ${k}, this.value)"', 'data-crm-action="extra-hash-share" data-crm-event="input" data-index="${i}" data-subindex="${k}"'),
        ('onclick="stdAgentsRemove(${i})"', 'data-crm-action="agent-remove" data-crm-event="click" data-index="${i}"'),
        ('onclick="stdAgentsTier(${i},-1)"', 'data-crm-action="agent-tier" data-crm-event="click" data-index="${i}" data-delta="-1"'),
        ('onclick="stdAgentsTier(${i},1)"', 'data-crm-action="agent-tier" data-crm-event="click" data-index="${i}" data-delta="1"'),
        ('onchange="stdAgentsField(${i},\'referrer_id\',this.value)"', 'data-crm-action="agent-field" data-crm-event="change" data-index="${i}" data-key="referrer_id"'),
        ('onchange="stdAgentsField(${i},\'comp_model\',this.value)"', 'data-crm-action="agent-field" data-crm-event="change" data-index="${i}" data-key="comp_model"'),
        ('oninput="stdAgentsField(${i},\'fixed_usdt\',this.value)"', 'data-crm-action="agent-field" data-crm-event="input" data-index="${i}" data-key="fixed_usdt"'),
        ('oninput="stdAgentsField(${i},\'percent\',this.value)"', 'data-crm-action="agent-field" data-crm-event="input" data-index="${i}" data-key="percent"'),
    ]
    for key in ('amount_rub', 'amount_usdt', 'partner_name', 'rate_rub_usdt'):
        dynamic_handlers.append((
            f'oninput="payinExtraSet(${{i}}, \'{key}\', this.value)"',
            f'data-crm-action="extra-set" data-crm-event="input" data-index="${{i}}" data-key="{key}"'))
    for old, new in dynamic_handlers:
        hits = sum(piece.count(old) for piece in pieces)
        if hits != 1:
            raise SystemExit(f"CRM dynamic handler changed ({hits}): {old}")
        pieces = [piece.replace(old, new) for piece in pieces]
    if any('onclick=' in piece or 'onchange=' in piece or 'oninput=' in piece for piece in pieces):
        raise SystemExit('CRM draft extraction contains an unscoped inline handler')
    output = """// Generated from static/crm/crm.html by scripts/build_stand_crm_draft_core.py.
// Do not edit here. No CRM bootstrap, listeners or side effects are imported.
window.createCrmDraftCore = function createCrmDraftCore(root, adapters) {
    const document = {
        getElementById(id) { return id === 'createDealForm' ? adapters.form : root.getElementById(id); },
        querySelector(selector) { return root.querySelector(selector); },
        querySelectorAll(selector) { return root.querySelectorAll(selector); },
        createElement(tag) { return window.document.createElement(tag); },
        get activeElement() { return root.activeElement; },
    };
    const API_URL = '';
    const fetch = adapters.fetch;
    const showToast = adapters.toast;
    const escapeHtml = adapters.escapeHtml;
    const formatNumber = adapters.formatNumber;
    const loadCurrentRate = adapters.loadCurrentRate || (() => {});
    const realtyPayinRecalc = adapters.realtyPayinRecalc || (() => {});
    const realtyPayoutRecalc = adapters.realtyPayoutRecalc;
    const mfRecalc = adapters.realtyPayoutRecalc;
    const fhRecalc = adapters.realtyPayoutRecalc;
    // The bounded CRM custom calculator is included below; no CRM boot.
    let payinExtra = [];
    let sberParts = adapters.sberParts || [];
    let payinTxPool = adapters.payinTxPool || [];
    let payinTxLedger = {};
    let sberIncomesCache = [];
    let sberKindFilter = '';
    let mfPayoutTxPool = adapters.mfPayoutTxPool || [];
    let mfPayoutTxOptions = [];
    let mfPayoutChecked = new Set();
    let mfPayoutAdding = false;
    let payinMode = 'rate';
    const editingDealId = adapters.editingDealId;
    let _mfLast = null;
    let _fhLast = null;
    let stdAgents = [];
    let customAgents = [];
    let customAgentsMode = 'cascade';
    let stdAgentsMode = 'cascade';
    let _stdGross = { profit: 0, volume: 0 };
    let currentUsdtThbRate = adapters.currentUsdtThbRate || null;
    let currentUsdtThbRateAt = adapters.currentUsdtThbRateAt || 0;
    let _rateWarnShownAt = 0;
    let payoutTxPool = adapters.payoutTxPool || [];
    let cashBatchesData = [];
    let _referrersCache = adapters.referrers || [];
""" + "\n\n".join(pieces) + """
    return {
        calcCustomProfit, onCustomRateInput, onCustomUsdtInput,
        get customUsdtMode() { return { ...customUsdtMode }; },
        onCustomPayinMethodChange, selectCustomPayinTx,
        customAgentsPreset, customAgentsAdd, customAgentsRemove,
        customAgentsTier, customAgentsField, customAgentsRecalc,
        customAgentsSerialize, customAgentsLoad,
        get customAgents() { return customAgents; },
        upgradeAllSelects, reportInvalidField, applyPayinMethodFields,
        sberKindChanged, sberLoadIncomes, sberAddIncome, sberAddManual,
        loadCashBatchesForSelect, loadBankCardsForSelect,
        get cashBatchesData() { return cashBatchesData; },
        calculateProfit,
        set currentUsdtThbRate(v) { currentUsdtThbRate = v; currentUsdtThbRateAt = Date.now(); },
        get payoutTxPool() { return payoutTxPool; },
        set payoutTxPool(v) { payoutTxPool = v || []; calculateProfit(); },
        sberRemovePart, sberRender, sberIncomeLine, sberPartsSum,
        autoCalcUsdt, setPayinMode(mode) { payinMode = mode; },
        payinTxPoolTotal, renderPayinTxPool, payinTxShareChanged,
        selectPayinTx, removePayinTx, resetPayinTxPool,
        payinExtraAdd, payinExtraRemove, payinExtraSet, payinExtraSetMethod,
        payinExtraPickTx, payinExtraHashManual, payinExtraHashRemove,
        payinExtraHashShare, payinExtraSberAdd, payinExtraSberRemove,
        payinExtraRender, payinExtraSerialize, payinExtraTotalUsdt,
        get payinExtra() { return payinExtra; },
        set payinExtra(v) { payinExtra = v || []; payinExtraRender(); },
        set payinExtraTxCache(v) { payinExtraTxCache = v || []; payinExtraRender(); },
        get payinTxPool() { return payinTxPool; },
        renderMfSummary, renderFhSummary,
        stdAgentsPreset, stdAgentsAdd, stdAgentsRemove, stdAgentsTier,
        stdAgentsField, renderStdAgents, stdAgentsSerialize, stdAgentsLoad,
        get stdAgents() { return stdAgents; },
        set referrers(v) { _referrersCache = v; renderStdAgents(); },
        get sberParts() { return sberParts; },
        set sberParts(v) { sberParts = v; sberRender(); },
        get sberIncomesCache() { return sberIncomesCache; },
        set sberIncomesCache(v) { sberIncomesCache = v; sberRender(); },
        toggleMfPayoutPicker, mfPayoutVisible, renderMfPayoutPicker,
        mfPayoutCheck, mfPayoutCheckAll, renderMfPayoutPicker,
        renderMfPayoutTxPool, mfPayoutTxTotal, addMfPayoutChecked,
        addMfPayoutManual, removeMfPayoutTx, resetMfPayoutTxPool,
        loadMfPayoutTx,
        get mfPayoutTxPool() { return mfPayoutTxPool; },
        set mfPayoutTxPool(v) { mfPayoutTxPool = v; renderMfPayoutTxPool(); },
        get mfPayoutTxOptions() { return mfPayoutTxOptions; },
        set mfPayoutTxOptions(v) { mfPayoutTxOptions = v; renderMfPayoutPicker(); },
    };
};
"""
    if args.check:
        if not TARGET.exists() or TARGET.read_text() != output:
            raise SystemExit("CRM draft core differs from crm.html; regenerate and review")
    else:
        TARGET.write_text(output)


if __name__ == "__main__":
    main()
