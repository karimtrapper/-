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
    ("        function autoCalcUsdt(", "        function calculateProfit("),
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
    output = """// Generated from static/crm/crm.html by scripts/build_stand_crm_draft_core.py.
// Do not edit here. No CRM bootstrap, listeners or side effects are imported.
window.createCrmDraftCore = function createCrmDraftCore(root, adapters) {
    const document = {
        getElementById(id) { return id === 'createDealForm' ? adapters.form : root.getElementById(id); },
        querySelector(selector) { return root.querySelector(selector); },
    };
    const API_URL = '';
    const fetch = adapters.fetch;
    const showToast = adapters.toast;
    const escapeHtml = adapters.escapeHtml;
    const formatDate = adapters.formatDate;
    const calculateProfit = adapters.calculateProfit || (() => {});
    const realtyPayinRecalc = adapters.realtyPayinRecalc || (() => {});
    const payinExtraSummary = () => {};
    const realtyPayoutRecalc = adapters.realtyPayoutRecalc;
    const payinExtraRender = () => {};
    const calcCustomProfit = () => {};
    let payinExtra = [];
    let sberParts = adapters.sberParts || [];
    let sberIncomesCache = [];
    let sberKindFilter = '';
    let mfPayoutTxPool = adapters.mfPayoutTxPool || [];
    let mfPayoutTxOptions = [];
    let mfPayoutChecked = new Set();
    let mfPayoutAdding = false;
    let payinMode = 'rate';
    const editingDealId = adapters.editingDealId;
""" + "\n\n".join(pieces) + """
    return {
        sberKindChanged, sberLoadIncomes, sberAddIncome, sberAddManual,
        sberRemovePart, sberRender, sberIncomeLine, sberPartsSum,
        autoCalcUsdt, setPayinMode(mode) { payinMode = mode; },
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
