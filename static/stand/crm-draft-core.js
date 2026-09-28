// Generated from static/crm/crm.html by scripts/build_stand_crm_draft_core.py.
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
        function sberSfx() { return document.getElementById('customDealToggle')?.checked ? 'C' : ''; }

        function sberSetKindFilter(kind) {
            sberKindFilter = kind || '';
            ['sberKindSelect', 'sberKindSelectC'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.value = sberKindFilter;
            });
        }

        function sberKindChanged(kind) { sberSetKindFilter(kind); sberLoadIncomes(); }

        async function sberLoadIncomes() {
            try {
                // with_conversion — чтобы у прихода была доля USDT из пачки:
                // если рубли уже конвертированы, вводить сумму руками не нужно
                const url = `${API_URL}/api/sber-incomes?with_conversion=1`
                          + (sberKindFilter ? `&kind=${sberKindFilter}` : '');
                const resp = await fetch(url);
                const data = await resp.json();
                sberIncomesCache = data.incomes || [];
            } catch (e) { sberIncomesCache = []; }
            sberRender();
            // Части тоже показывают пул — список приезжает асинхронно, позже них
            if (typeof payinExtraRender === 'function' && payinExtra.length) payinExtraRender();
        }

        function sberAddIncome(uuid) {
            const inc = sberIncomesCache.find(i => i.uuid === uuid);
            if (!inc || sberParts.some(p => p.uuid === uuid)) return;
            // В сделку идёт то, что заплатил КЛИЕНТ. У эквайринга на счёт падает
            // меньше — банк удерживает комиссию сразу, поэтому берём gross,
            // иначе курс клиента и объём сделки занижены на размер комиссии.
            sberParts.push({ uuid: inc.uuid, amount_rub: inc.gross_rub ?? inc.amount_rub,
                             payer: inc.payer || '', date: (inc.operation_date || '').substring(0, 10),
                             note: '', kind: inc.kind || 'transfer',
                             fee_rub: inc.fee_rub || 0, net_rub: inc.amount_rub });
            sberRender();
            applyConversionUsdt(inc);
        }

        function applyConversionUsdt(inc) {
            const hint = document.getElementById('payinUsdtConvHint');
            const c = Array.isArray(inc.conversion) ? inc.conversion[0] : inc.conversion;
            const usdt = inc.usdt ?? inc.usdt_expected;
            const el = document.querySelector('[name="payin_amount_usdt"]');

            // Доля известна — подставляем, но введённое руками не трогаем
            if (usdt && el && !(parseFloat(el.value) > 0)) {
                el.value = usdt;
                el.dispatchEvent(new Event('input', {bubbles: true}));
            }
            if (!hint) return;
            hint.style.display = 'block';
            if (usdt && inc.usdt) {
                hint.innerHTML = `✅ подставлено из конвертации <b>${c.display_name}</b> ·
                                  ${c.broker || ''} @ ${c.rate_rub_usdt || '—'}`;
                hint.style.color = '#059669';
            } else if (usdt) {
                hint.innerHTML = `🚚 ожидание по <b>${c.display_name}</b> · ${c.broker || ''}
                                  @ ${c.rate_rub_usdt || '—'}
                                  <span style="color:#94a3b8">— уточнится, когда придёт USDT</span>`;
                hint.style.color = '#b45309';
            } else {
                // Конвертации по этому приходу ещё не было: сумму не выдумываем,
                // просто фиксируем, что приход привязан к сделке
                hint.innerHTML = '⏳ приход ещё не сконвертирован — USDT появится после пачки';
                hint.style.color = '#94a3b8';
            }
        }

        function sberAddManual(sfx) {
            sfx = sfx ?? sberSfx();
            const amtEl = document.getElementById('sberManualAmount' + sfx);
            const noteEl = document.getElementById('sberManualNote' + sfx);
            const amt = parseFloat(amtEl?.value) || 0;
            if (amt <= 0) { showToast('Укажите сумму прихода', 'error'); return; }
            sberParts.push({ uuid: null, amount_rub: amt, payer: '', date: '', note: (noteEl?.value || '').trim() });
            if (amtEl) amtEl.value = '';
            if (noteEl) noteEl.value = '';
            sberRender();
        }

        function sberRemovePart(i) { sberParts.splice(i, 1); sberRender(); }

        const rub2 = v => Number(v || 0).toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

        function sberIncomeLine(i) {
            const date = (i.operation_date || '').substring(0, 10);
            if (i.kind === 'acquiring') {
                const mer = i.merchant ? ` · мерчант …${String(i.merchant).slice(-4)}` : '';
                return `<span style="background:#dbeafe;color:#1d4ed8;border-radius:4px;padding:1px 5px;font-size:11px;">СБП</span> `
                    + `<b>${rub2(i.gross_rub)} ₽</b> `
                    + `<span style="color:#64748b;">(зачислено ${rub2(i.amount_rub)} + комиссия ${rub2(i.fee_rub)})</span>`
                    + `${mer} · ${date}`;
            }
            return `<span style="background:#dcfce7;color:#15803d;border-radius:4px;padding:1px 5px;font-size:11px;">реквизиты</span> `
                + `<b>${rub2(i.amount_rub)} ₽</b> · ${escapeHtml(i.payer || '—')} · ${date}`;
        }

        function sberPartsSum() { return sberParts.reduce((s, p) => s + (+p.amount_rub || 0), 0); }

        function sberRender() {
            const sfx = sberSfx();
            // Доступные приходы пула (минус уже выбранные в этой сделке)
            const availEl = document.getElementById('sberIncomesAvail' + sfx);
            if (availEl) {
                const chosen = new Set(sberParts.filter(p => p.uuid).map(p => p.uuid));
                const avail = sberIncomesCache.filter(i => !chosen.has(i.uuid));
                availEl.innerHTML = avail.length ? avail.map(i => `
                    <div style="display:flex;justify-content:space-between;align-items:center;padding:6px 8px;border-bottom:1px solid #e0f2fe;font-size:13px;gap:8px;">
                        <span>${sberIncomeLine(i)}</span>
                        <button type="button" class="btn btn-success btn-sm" onclick="sberAddIncome('${escapeHtml(i.uuid)}')">Забрать</button>
                    </div>`).join('') : '<div style="color:#94a3b8;font-size:13px;padding:4px;">Нет незабранных приходов</div>';
            }
            // Выбранные части
            const listEl = document.getElementById('sberPartsList' + sfx);
            if (listEl) {
                listEl.innerHTML = sberParts.map((p, i) => {
                    const isAcq = p.kind === 'acquiring';
                    const tail = isAcq
                        ? `<span style="color:#64748b;">эквайринг: на счёт ${rub2(p.net_rub)} + комиссия ${rub2(p.fee_rub)}</span>`
                        : (p.payer ? escapeHtml(p.payer) : '');
                    return `
                    <div style="display:flex;justify-content:space-between;align-items:center;padding:5px 8px;background:white;border:1px solid #bae6fd;border-radius:6px;margin-bottom:4px;font-size:13px;gap:8px;">
                        <span>${p.uuid ? (isAcq ? '📲' : '🏦') : '✍️'} <b>${rub2(p.amount_rub)} ₽</b>${tail ? ' · ' + tail : ''}${p.date ? ' · ' + p.date : ''}${p.note ? ' · ' + escapeHtml(p.note) : ''}</span>
                        <span onclick="sberRemovePart(${i})" style="cursor:pointer;color:#ef4444;font-weight:700;padding:0 4px;">✕</span>
                    </div>`;
                }).join('');
            }
            const totalEl = document.getElementById('sberPartsTotal' + sfx);
            const total = sberPartsSum();
            const feeTotal = sberParts.reduce((s, p) => s + (+p.fee_rub || 0), 0);
            if (totalEl) totalEl.textContent = sberParts.length
                ? `Итого от клиента: ${rub2(total)} ₽ (частей: ${sberParts.length})`
                  + (feeTotal ? ` · комиссия эквайринга ${rub2(feeTotal)} ₽ → на счёт ${rub2(total - feeTotal)} ₽` : '')
                : '';
            // Сумма частей → в поле суммы формы
            if (sberParts.length) {
                if (sfx === 'C') {
                    document.getElementById('customPayinCurrency').value = 'RUB';
                    document.getElementById('customPayinAmount').value = total.toFixed(2);
                    calcCustomProfit();
                } else {
                    const rub = document.querySelector('[name="payin_amount_rub"]');
                    if (rub) rub.value = total.toFixed(2);
                    autoCalcUsdt();
                }
            }
        }

        function autoCalcUsdt() {
            const form = document.getElementById('createDealForm');
            const rub = parseFloat(form.payin_amount_rub.value) || 0;
            const rate = parseFloat(form.payin_rate_rub_usdt.value) || 0;
            const usdt = parseFloat(form.payin_amount_usdt.value) || 0;
            if (payinMode === 'usdt') {
                // Приход в USDT задан руками — он источник истины (это то, что реально
                // купили), поэтому из рублей выводим КУРС, а не наоборот
                if (rub > 0 && usdt > 0) form.payin_rate_rub_usdt.value = (rub / usdt).toFixed(4);
            } else if (editingDealId === null && rub > 0 && rate > 0) {
                // При редактировании USDT не перезаписываем: там уже стоит факт сделки
                form.payin_amount_usdt.value = (rub / rate).toFixed(2);
            }
            calculateProfit();
            realtyPayinRecalc();
            payinExtraSummary();
        }

        function mfPayoutTxTotal() {
            return mfPayoutTxPool.reduce((s, t) => s + (t.amount_usdt || 0), 0);
        }

        function renderMfPayoutTxPool() {
            const box = document.getElementById('mfPayoutTxPoolBox');
            if (!box) return;
            if (!mfPayoutTxPool.length) { box.innerHTML = ''; return; }
            box.innerHTML = mfPayoutTxPool.map((t, i) => `
                <div style="display:flex;align-items:center;gap:0.5rem;background:#fef2f2;border:1px solid #fecaca;border-radius:6px;padding:4px 8px;margin-bottom:4px;font-size:0.85rem;">
                    <strong style="color:#dc2626;">${t.amount_usdt != null ? '−$' + t.amount_usdt.toLocaleString('ru-RU', {minimumFractionDigits: 2, maximumFractionDigits: 2}) : '—'}</strong>
                    <span style="color:#7f1d1d;font-size:0.75rem;font-weight:700;">${(t.network || 'trc20').toUpperCase()}</span>
                    <span style="color:#334155;">→ ${escapeHtml((t.to_address || '').substring(0, 12))}${t.to_address ? '…' : ''}</span>
                    <code style="flex:1;color:#94a3b8;overflow:hidden;text-overflow:ellipsis;">${escapeHtml(t.hash.substring(0, 14))}…</code>
                    <span style="color:#94a3b8;">${escapeHtml(t.date || '')}</span>
                    <button type="button" class="btn btn-sm btn-danger" style="padding:1px 6px;" onclick="removeMfPayoutTx(${i})">✕</button>
                </div>`).join('') +
                `<div style="text-align:right;font-weight:700;color:#b91c1c;">Переводов: ${mfPayoutTxPool.length} · итого $${mfPayoutTxTotal().toLocaleString('ru-RU', {minimumFractionDigits: 2, maximumFractionDigits: 2})}</div>`;
        }

        function toggleMfPayoutPicker() {
            const box = document.getElementById('mfPayoutPicker');
            if (!box) return;
            const open = box.style.display === 'none';
            box.style.display = open ? 'block' : 'none';
            if (open) renderMfPayoutPicker();
        }

        function mfPayoutVisible() {
            const q = (document.getElementById('mfPayoutSearch')?.value || '').trim().toLowerCase();
            const inPool = h => mfPayoutTxPool.some(t => t.hash === h);
            return mfPayoutTxOptions.filter(tx => {
                if (inPool(tx.tx_hash)) return false;   // уже добавленные не показываем
                if (!q) return true;
                return (tx.to_address || '').toLowerCase().includes(q)
                    || (tx.tx_hash || '').toLowerCase().includes(q)
                    || String(tx.amount_usdt).includes(q);
            });
        }

        function renderMfPayoutPicker() {
            const list = document.getElementById('mfPayoutPickerList');
            if (!list) return;
            const rows = mfPayoutVisible();
            if (!rows.length) {
                list.innerHTML = '<div style="color:#94a3b8;font-size:0.85rem;padding:6px;">Нет подходящих переводов</div>';
            } else {
                list.innerHTML = rows.map(tx => `
                    <label style="display:flex;align-items:center;gap:0.5rem;padding:4px 6px;border-radius:6px;font-size:0.85rem;cursor:pointer;background:${mfPayoutChecked.has(tx.tx_hash) ? '#eef2ff' : 'transparent'};">
                        <input type="checkbox" ${mfPayoutChecked.has(tx.tx_hash) ? 'checked' : ''}
                            onchange="mfPayoutCheck('${tx.tx_hash}', this.checked)">
                        <strong style="color:#b91c1c;min-width:110px;">−$${(tx.amount_usdt || 0).toLocaleString('ru-RU', {minimumFractionDigits: 2, maximumFractionDigits: 2})}</strong>
                        <span style="color:#334155;">→ ${escapeHtml((tx.to_address || '').substring(0, 14))}…</span>
                        <span style="flex:1;"></span>
                        <span style="color:#94a3b8;">${formatDate(tx.timestamp)}</span>
                    </label>`).join('');
            }
            const sum = mfPayoutTxOptions
                .filter(tx => mfPayoutChecked.has(tx.tx_hash))
                .reduce((s, tx) => s + (tx.amount_usdt || 0), 0);
            const el = document.getElementById('mfPayoutPickerSum');
            if (el) el.textContent = mfPayoutChecked.size
                ? `Отмечено: ${mfPayoutChecked.size} · $${sum.toLocaleString('ru-RU', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`
                : 'Ничего не отмечено';
        }

        function mfPayoutCheck(hash, on) {
            if (on) mfPayoutChecked.add(hash); else mfPayoutChecked.delete(hash);
            renderMfPayoutPicker();
        }

        function mfPayoutCheckAll(on) {
            // Только видимые: с фильтром «все» означает «все по этому адресу»,
            // иначе кнопка молча цепляла бы отфильтрованное
            mfPayoutVisible().forEach(tx => on ? mfPayoutChecked.add(tx.tx_hash) : mfPayoutChecked.delete(tx.tx_hash));
            renderMfPayoutPicker();
        }

        async function addMfPayoutChecked() {
            if (mfPayoutAdding) return;
            const picked = mfPayoutTxOptions.filter(tx => mfPayoutChecked.has(tx.tx_hash)
                && !mfPayoutTxPool.some(t => t.hash === tx.tx_hash));
            if (!picked.length) { showToast('Отметь хотя бы один перевод', 'error'); return; }
            mfPayoutAdding = true;
            showToast(`Проверяю в TronScan: ${picked.length} перевод(а/ов)…`);
            const checked = await Promise.all(picked.map(async tx => {
                const listedAmount = tx.amount_usdt != null ? Number(tx.amount_usdt) : null;
                try {
                    const response = await fetch(`/api/tx/lookup?network=trc20&hash=${encodeURIComponent(tx.tx_hash)}`);
                    const result = await response.json();
                    if (response.ok && result.success) {
                        const mainAmount = Number(result.amount_usdt || 0);
                        const totalOut = Number(result.total_out_usdt || mainAmount);
                        return {
                            hash: tx.tx_hash, network: 'trc20',
                            // Один TRON-хэш = один полный расход: основной Transfer
                            // плюс отдельный Transfer комиссии внутри того же батча.
                            amount_usdt: totalOut > 0 ? totalOut : listedAmount,
                            main_amount_usdt: mainAmount,
                            from_address: result.from_address || '',
                            to_address: result.to_address || tx.to_address || '',
                            date: formatDate(tx.timestamp) || '', verified: true,
                        };
                    }
                } catch (error) {
                    console.warn('TronScan lookup failed for payout:', tx.tx_hash, error);
                }
                return {
                    hash: tx.tx_hash, network: 'trc20', amount_usdt: listedAmount,
                    to_address: tx.to_address || '', date: formatDate(tx.timestamp) || '',
                    verified: false,
                };
            }));
            mfPayoutAdding = false;
            checked.forEach(tx => mfPayoutTxPool.push(tx));
            mfPayoutChecked.clear();
            document.getElementById('mfPayoutPicker').style.display = 'none';
            const extra = checked.reduce((sum, tx) =>
                sum + Math.max(0, (tx.amount_usdt || 0) - (tx.main_amount_usdt || tx.amount_usdt || 0)), 0);
            const unverified = checked.filter(tx => !tx.verified).length;
            if (extra > 0.000001) {
                showToast(`Добавлено: ${checked.length}. Полный расход включает комиссию +$${extra.toFixed(6)}`);
            } else if (unverified) {
                showToast(`Добавлено: ${checked.length}; ${unverified} не удалось пересверить в TronScan`, 'error');
            } else {
                showToast(`Добавлено переводов: ${checked.length}`);
            }
            renderMfPayoutTxPool();
            realtyPayoutRecalc();
        }

        async function addMfPayoutManual() {
            const hashEl = document.getElementById('mfPayoutManualHash');
            const amountEl = document.getElementById('mfPayoutManualAmount');
            const networkEl = document.getElementById('mfPayoutManualNetwork');
            const hash = (hashEl?.value || '').trim();
            let amount = Number(amountEl?.value);
            const network = networkEl?.value || 'trc20';
            if (hash.length < 32) {
                showToast('Вставьте полный хэш транзакции', 'error');
                hashEl?.focus();
                return;
            }
            if (mfPayoutTxPool.some(t => t.hash === hash)) {
                showToast('Этот перевод уже добавлен', 'error');
                return;
            }
            let chain = null;
            try {
                const response = await fetch(`/api/tx/lookup?network=${encodeURIComponent(network)}&hash=${encodeURIComponent(hash)}`);
                const result = await response.json();
                if (response.ok && result.success) {
                    chain = result;
                    const mainAmount = Number(result.amount_usdt || 0);
                    const totalOut = Number(result.total_out_usdt || mainAmount);
                    // Один хэш = один полный расход. В batch-транзакции это
                    // основной перевод плюс отдельный Transfer комиссии.
                    if (!(amount > 0)) amount = totalOut;
                    if (amount > totalOut + 0.01) {
                        showToast(`В сети ушло $${totalOut.toFixed(2)} — нельзя указать $${amount.toFixed(2)}`, 'error');
                        amountEl?.focus();
                        return;
                    }
                    const provider = result.source === 'etherscan' ? 'Etherscan' : 'TronScan';
                    const extra = totalOut - mainAmount;
                    showToast(extra > 0.000001
                        ? `${provider}: расход $${totalOut.toFixed(2)} (перевод $${mainAmount.toFixed(2)} + ещё $${extra.toFixed(6)})`
                        : `${provider} подтвердил расход $${totalOut.toFixed(2)}`);
                } else if (response.status === 422) {
                    showToast(result.error || 'Транзакция не подтверждает перевод USDT', 'error');
                    return;
                } else if (amount > 0) {
                    showToast(`${result.error || 'Сеть не ответила'} — сохраню сумму как не сверенную`, 'error');
                }
            } catch (error) {
                if (amount > 0) showToast('Сеть не ответила — сохраню сумму как не сверенную', 'error');
            }
            if (!(amount > 0)) {
                showToast('Сеть не подтвердила сумму — укажите её вручную', 'error');
                amountEl?.focus();
                return;
            }
            mfPayoutTxPool.push({
                hash, network, amount_usdt: amount,
                from_address: chain?.from_address || '',
                to_address: chain?.to_address || '',
                date: new Date().toLocaleDateString('ru-RU'),
            });
            hashEl.value = '';
            amountEl.value = '';
            renderMfPayoutTxPool();
            realtyPayoutRecalc();
        }

        function removeMfPayoutTx(index) {
            mfPayoutTxPool.splice(index, 1);
            renderMfPayoutTxPool();
            renderMfPayoutPicker();   // снятый перевод снова доступен для выбора
            realtyPayoutRecalc();
        }

        function resetMfPayoutTxPool(parts) {
            mfPayoutChecked.clear();
            const picker = document.getElementById('mfPayoutPicker');
            if (picker) picker.style.display = 'none';
            mfPayoutTxPool = (parts || []).map(p => ({
                hash: p.hash,
                network: p.network || 'trc20',
                amount_usdt: p.amount_usdt != null ? Number(p.amount_usdt) : null,
                to_address: p.to_address || '',
                date: p.date || '',
            }));
            renderMfPayoutTxPool();
        }

        async function loadMfPayoutTx() {
            if (!document.getElementById('mfPayoutPicker')) return;
            try {
                const startDate = document.getElementById('txStartDate')?.value || '2025-12-01';
                let url = `${API_URL}/api/transactions/outgoing?start_date=${startDate}&limit=200`;
                const resp = await fetch(url);
                const data = await resp.json();
                if (!data.success) return;
                // Кошельки, не ответившие из-за лимита TronScan: список неполный — говорим об этом,
                // иначе оператор решит, что перевода не было
                const failed = (data.wallets_errors || []).length;
                const warn = document.getElementById('mfPayoutTxWarn');
                if (warn) {
                    warn.innerHTML = failed
                        ? `⚠️ TronScan ответил не по всем кошелькам (${failed}) — список может быть неполным.`
                        : '';
                    warn.style.display = failed ? 'block' : 'none';
                }
                mfPayoutTxOptions = (data.available || []).slice(0, 300);
                const btn = document.getElementById('mfPayoutPickerBtn');
                if (btn) btn.textContent = `➕ Выбрать переводы (${mfPayoutTxOptions.length} исходящих)`;
                renderMfPayoutPicker();
            } catch (e) {
                console.error('Error loading outgoing for MF:', e);
            }
        }
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
