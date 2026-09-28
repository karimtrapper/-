// Generated from static/crm/crm.html by scripts/build_stand_crm_draft_core.py.
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
        function _customFormProfitVolume() {
            const payinAmount = parseFloat(document.getElementById('customPayinAmount').value) || 0;
            const payinCurrency = document.getElementById('customPayinCurrency').value;
            const payinRate = parseFloat(document.getElementById('customPayinRate').value) || 0;
            const payoutAmount = parseFloat(document.getElementById('customPayoutAmount').value) || 0;
            const payoutCurrency = document.getElementById('customPayoutCurrency').value;
            const payoutRate = parseFloat(document.getElementById('customPayoutRate').value) || 0;
            const payinUsdt = payinCurrency === 'USDT' ? payinAmount : (payinRate > 0 ? payinAmount / payinRate : 0);
            const payoutUsdt = payoutCurrency === 'USDT' ? payoutAmount : (payoutRate > 0 ? payoutAmount / payoutRate : 0);
            return { profit: payinUsdt - payoutUsdt, volume: Math.max(payinUsdt, payoutUsdt) };
        }

        function customAgentsPreset(mode) {
            customAgentsMode = mode;
            if (mode === 'cascade') customAgents.forEach((a, i) => a.tier = i + 1);
            else customAgents.forEach(a => a.tier = 1);
            renderCustomAgents();
            calcCustomProfit();
        }

        function customAgentsAdd() {
            const nextTier = customAgentsMode === 'flat' ? 1 : (customAgents.reduce((m, a) => Math.max(m, a.tier || 1), 0) + 1);
            customAgents.push({ referrer_id: null, name: '', tier: nextTier, comp_model: 'revshare', percent: 10, fixed_usdt: 0 });
            renderCustomAgents();
            calcCustomProfit();
        }
        function customAgentsRemove(i) { customAgents.splice(i, 1); renderCustomAgents(); calcCustomProfit(); }
        function customAgentsTier(i, d) { customAgents[i].tier = Math.max(1, (customAgents[i].tier || 1) + d); customAgentsMode = null; renderCustomAgents(); calcCustomProfit(); }
        function customAgentsField(i, k, v) {
            if (k === 'percent' || k === 'fixed_usdt') v = parseFloat(v) || 0;
            customAgents[i][k] = v;
            if (k === 'referrer_id') {
                const r = (_referrersCache || []).find(x => String(x.id) === String(v));
                if (r) {
                    customAgents[i].name = r.name;
                    customAgents[i].comp_model = r.comp_model || 'revshare';
                    customAgents[i].percent = r.comp_model === 'markup' ? (r.markup_percent || 0) : (r.default_percent || 0);
                }
            }
            // Перерисовываем и при выборе реферера: из профиля подставляются модель
            // и процент, а селект оставался на прежнем значении — на экране revshare,
            // в данных markup, и выплата считалась от объёма (кейс 06.08: $299.70 вместо $6)
            if (k === 'comp_model' || k === 'referrer_id') renderCustomAgents();
            calcCustomProfit();
        }

        function renderCustomAgents() {
            const box = document.getElementById('agentsBlockCustom');
            if (!box) return;
            const refs = (_referrersCache || []).filter(r => r.active);
            box.innerHTML = customAgents.map((a, i) => {
                const opts = '<option value="">— выбрать агента —</option>' + refs.map(r =>
                    `<option value="${r.id}" ${String(r.id) === String(a.referrer_id) ? 'selected' : ''}>${escapeHtml(r.name)}</option>`).join('');
                const valField = a.comp_model === 'fixed'
                    ? `<input type="number" step="any" class="form-control" value="${a.fixed_usdt || 0}" data-crm-action="custom-agent-field" data-crm-event="input" data-index="${i}" data-key="fixed_usdt" placeholder="$" style="width:90px;">`
                    : `<input type="number" step="any" class="form-control" value="${a.percent || 0}" data-crm-action="custom-agent-field" data-crm-event="input" data-index="${i}" data-key="percent" placeholder="%" style="width:90px;">`;
                return `
                <div style="background:white;border:1px solid #d1fae5;border-radius:8px;padding:10px;margin-bottom:8px;">
                    <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
                        <span style="display:inline-flex;align-items:center;gap:4px;background:#6366f1;color:white;border-radius:999px;padding:3px 6px 3px 10px;font-size:12px;font-weight:700;">
                            <button type="button" data-crm-action="custom-agent-tier" data-crm-event="click" data-index="${i}" data-delta="-1" style="border:none;background:rgba(255,255,255,.25);color:white;border-radius:50%;width:18px;height:18px;cursor:pointer;">−</button>
                            Ур.${a.tier || 1}
                            <button type="button" data-crm-action="custom-agent-tier" data-crm-event="click" data-index="${i}" data-delta="1" style="border:none;background:rgba(255,255,255,.25);color:white;border-radius:50%;width:18px;height:18px;cursor:pointer;">+</button>
                        </span>
                        <select class="form-control" data-crm-action="custom-agent-field" data-crm-event="change" data-index="${i}" data-key="referrer_id" style="flex:1;">${opts}</select>
                        <button type="button" data-crm-action="custom-agent-remove" data-crm-event="click" data-index="${i}" style="border:none;background:transparent;color:#94a3b8;font-size:16px;cursor:pointer;">🗑</button>
                    </div>
                    <div style="display:flex;align-items:center;gap:8px;">
                        <select class="form-control" data-crm-action="custom-agent-field" data-crm-event="change" data-index="${i}" data-key="comp_model" style="flex:1;">
                            <option value="revshare" ${a.comp_model === 'revshare' ? 'selected' : ''}>revshare (% от прибыли)</option>
                            <option value="markup" ${a.comp_model === 'markup' ? 'selected' : ''}>markup (+% к курсу)</option>
                            <option value="fixed" ${a.comp_model === 'fixed' ? 'selected' : ''}>fixed ($ сумма)</option>
                        </select>
                        ${valField}
                        <span style="min-width:90px;text-align:right;font-weight:700;color:#16a34a;" id="caPay${i}">$0</span>
                    </div>
                </div>`;
            }).join('');
            document.getElementById('caPreCascade')?.classList.toggle('active', customAgentsMode === 'cascade');
            document.getElementById('caPreFlat')?.classList.toggle('active', customAgentsMode === 'flat');
        }

        function customAgentsRecalc() {
            const { profit, volume } = _customFormProfitVolume();
            const net = _agentsCascade(profit, volume, customAgents);
            customAgents.forEach((a, i) => { const el = document.getElementById('caPay' + i); if (el) el.textContent = '$' + (a._payout || 0).toFixed(2); });
            const total = customAgents.reduce((s, a) => s + (a._payout || 0), 0);
            const netEl = document.getElementById('agentsBlockCustomNet');
            if (netEl) netEl.innerHTML = customAgents.length
                ? `Агентам всего: <b>$${total.toFixed(2)}</b> · Чистая наша: <b>$${net.toFixed(2)}</b>`
                : '';
            return net;
        }

        function customAgentsSerialize() {
            return customAgents.filter(a => a.referrer_id || a.name).map(a => ({
                referrer_id: a.referrer_id ? parseInt(a.referrer_id) : null,
                name: a.name || null, tier: a.tier || 1,
                comp_model: a.comp_model || 'revshare',
                percent: a.comp_model === 'fixed' ? 0 : (+a.percent || 0),
                fixed_usdt: a.comp_model === 'fixed' ? (+a.fixed_usdt || 0) : 0,
            }));
        }

        function customAgentsLoad(arr) {
            customAgents = (arr || []).map(a => ({
                referrer_id: a.referrer_id || null, name: a.name || '', tier: a.tier || 1,
                comp_model: a.comp_model || 'revshare',
                percent: a.percent || 0, fixed_usdt: a.fixed_usdt || 0,
            }));
            customAgentsMode = customAgents.length && customAgents.every(a => (a.tier || 1) === 1) ? 'flat'
                             : (customAgents.length ? 'cascade' : 'cascade');
            renderCustomAgents();
            calcCustomProfit();
        }

        // Что считаем производным: 'rate' (ввели курс → считаем USDT) или 'usdt' (ввели USDT → считаем курс)
        let customUsdtMode = { payin: 'rate', payout: 'rate' };
        function onCustomRateInput(side) { customUsdtMode[side] = 'rate'; calcCustomProfit(); }
        function onCustomUsdtInput(side) { customUsdtMode[side] = 'usdt'; calcCustomProfit(); }

        // Конвертация суммы в USDT — зеркалит backend to_usdt (app.py _deal_usdt_volume_cost).
        // RUB/THB: курс хранится как «валюта за 1 USD» → делим.
        // EUR: курс хранится как «USD за 1 EUR» (напр. 1.1783) → умножаем.
        // USD/USDT: 1:1. Иначе фронт и бэк считали объём EUR-сделок по-разному.
        function customToUsdt(amount, currency, rate) {
            const a = parseFloat(amount) || 0;
            const r = parseFloat(rate) || 0;
            const cur = (currency || '').toUpperCase();
            if (!a) return 0;
            if (cur === 'USD' || cur === 'USDT') return a;
            if (cur === 'EUR') return r ? a * r : 0;
            return r ? a / r : 0;
        }
        // Обратная конвертация: курс из суммы и введённого USDT (та же конвенция).
        function customRateFromUsdt(amount, currency, usdt) {
            const a = parseFloat(amount) || 0;
            const u = parseFloat(usdt) || 0;
            const cur = (currency || '').toUpperCase();
            if (!a || !u) return '';
            if (cur === 'EUR') return (u / a).toFixed(4);
            return (a / u).toFixed(4);
        }

        // Считает USDT для одной стороны, синхронизируя парное поле (курс↔USDT)
        function _sideUsdt(side) {
            const amount = parseFloat(document.getElementById('custom' + (side === 'payin' ? 'Payin' : 'Payout') + 'Amount').value) || 0;
            const currency = document.getElementById('custom' + (side === 'payin' ? 'Payin' : 'Payout') + 'Currency').value;
            const rateEl = document.getElementById('custom' + (side === 'payin' ? 'Payin' : 'Payout') + 'Rate');
            const usdtEl = document.getElementById('custom' + (side === 'payin' ? 'Payin' : 'Payout') + 'Usdt');
            if (currency === 'USDT') { usdtEl.value = amount > 0 ? amount.toFixed(2) : ''; return amount; }
            if (customUsdtMode[side] === 'usdt') {
                // Ввели USDT → выводим курс (конвенция как в customToUsdt)
                const usdt = parseFloat(usdtEl.value) || 0;
                rateEl.value = customRateFromUsdt(amount, currency, usdt);
                return usdt;
            } else {
                // Ввели курс → USDT по единой конвенции (RUB/THB делим, EUR умножаем)
                const rate = parseFloat(rateEl.value) || 0;
                const usdt = customToUsdt(amount, currency, rate);
                usdtEl.value = usdt > 0 ? usdt.toFixed(2) : '';
                return usdt;
            }
        }

        function calcCustomProfit() {
            const payinAmount = parseFloat(document.getElementById('customPayinAmount').value) || 0;
            const payinCurrency = document.getElementById('customPayinCurrency').value;
            const payoutAmount = parseFloat(document.getElementById('customPayoutAmount').value) || 0;
            const payoutCurrency = document.getElementById('customPayoutCurrency').value;

            // Показать/скрыть поле курса для USDT
            document.getElementById('customPayinRateGroup').style.display = payinCurrency === 'USDT' ? 'none' : 'block';
            document.getElementById('customPayoutRateGroup').style.display = payoutCurrency === 'USDT' ? 'none' : 'block';
            document.getElementById('customPayinUsdtGroup').style.display = payinCurrency === 'USDT' ? 'none' : 'block';
            document.getElementById('customPayoutUsdtGroup').style.display = payoutCurrency === 'USDT' ? 'none' : 'block';

            // Конвертация в USDT (синхронизирует курс↔USDT по режиму ввода)
            const payinUsdt = _sideUsdt('payin');
            const payoutUsdt = _sideUsdt('payout');

            // Прибыль
            const profit = payinUsdt - payoutUsdt;
            const profitEl = document.getElementById('customProfitUsdt');
            const netProfitEl = document.getElementById('customNetProfit');

            // Выплаты агентам и чистая прибыль — через виджет мультиагентов (каскад)
            const netProfit = customAgentsRecalc();

            if (payinUsdt > 0 && payoutUsdt > 0) {
                profitEl.value = '$' + profit.toFixed(2);
                profitEl.style.color = profit >= 0 ? '#10b981' : '#ef4444';
                netProfitEl.value = '$' + netProfit.toFixed(2);
                netProfitEl.style.color = netProfit >= 0 ? '#10b981' : '#ef4444';
            } else {
                profitEl.value = '';
                netProfitEl.value = '';
            }
        }

        async function onCustomPayinMethodChange() {
            const method = document.getElementById('customPayinMethod').value;
            const picker = document.getElementById('customPayinPicker');
            const label = document.getElementById('customPickerLabel');
            const select = document.getElementById('customPayinTxSelect');
            document.getElementById('customPayinPickerInfo').textContent = '';
            // Сберовские методы: общий пул выписки (СБП — эквайринг, реквизиты — перевод)
            const sberGroupC = document.getElementById('sberReqsGroupC');
            const usesPool = methodUsesSberPool(method);
            if (sberGroupC) sberGroupC.style.display = usesPool ? 'block' : 'none';
            if (usesPool) {
                sberSetKindFilter(method === 'sber_wl' ? 'acquiring' : 'transfer');
                sberLoadIncomes();
            }
            if (method === 'sber_reqs') {
                picker.style.display = 'none';
                select.innerHTML = '';
                return;
            }
            if (method === 'sber_wl') {
                picker.style.display = 'flex';
                label.textContent = 'Выбрать Сбер-транзакцию (WL Bot)';
                await loadCustomWlTransactions();
            } else if (method === 'crypto_direct') {
                picker.style.display = 'flex';
                label.textContent = 'Выбрать входящую крипто-транзакцию';
                await loadCustomCryptoTransactions();
            } else {
                picker.style.display = 'none';
                select.innerHTML = '';
            }
        }

        // Загрузка WL Сбер транзакций (мерчант grusha) в кастомный пикер
        async function loadCustomWlTransactions() {
            const select = document.getElementById('customPayinTxSelect');
            select.innerHTML = '<option value="">Загрузка...</option>';
            try {
                const resp = await fetch(`${API_URL}/api/wl-transactions?merchant=grusha`);
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    select.innerHTML = `<option value="">Ошибка: ${escapeHtml(err.error || resp.status)}</option>`;
                    return;
                }
                const txs = await resp.json();
                if (!txs.length) { select.innerHTML = '<option value="">Нет транзакций</option>'; return; }
                select.innerHTML = '<option value="">-- Выберите транзакцию --</option>';
                txs.forEach(tx => {
                    const opt = document.createElement('option');
                    opt.value = JSON.stringify({ kind: 'wl', amount_rub: tx.amount_rub, amount_usdt: tx.amount_usdt, final_rate: tx.final_rate, display_name: tx.display_name });
                    const dateStr = tx.paid_at ? tx.paid_at.substring(0, 10) : '';
                    opt.textContent = `${tx.display_name} · ${Number(tx.amount_rub).toLocaleString('ru')} ₽ · ${dateStr}`;
                    select.appendChild(opt);
                });
            } catch (e) {
                select.innerHTML = `<option value="">Ошибка: ${escapeHtml(e.message)}</option>`;
            }
        }

        // Загрузка входящих крипто-транзакций в кастомный пикер
        async function loadCustomCryptoTransactions() {
            const select = document.getElementById('customPayinTxSelect');
            select.innerHTML = '<option value="">Загрузка...</option>';
            try {
                const startDate = document.getElementById('txStartDate')?.value || '2025-12-01';
                const endDate = document.getElementById('txEndDate')?.value || '';
                let url = `${API_URL}/api/transactions/incoming?start_date=${startDate}`;
                if (endDate) url += `&end_date=${endDate}`;
                const resp = await fetch(url);
                const data = await resp.json();
                const avail = (data.success && data.available) ? data.available : [];
                if (!avail.length) { select.innerHTML = '<option value="">Нет входящих транзакций</option>'; return; }
                select.innerHTML = '<option value="">-- Выберите транзакцию --</option>';
                avail.slice(0, 100).forEach(tx => {
                    const opt = document.createElement('option');
                    opt.value = JSON.stringify({ kind: 'crypto', amount_usdt: tx.amount_usdt, tx_hash: tx.tx_hash });
                    opt.textContent = `+$${Number(tx.amount_usdt).toFixed(2)} · ${(tx.from_address || '').substring(0, 10)}… · ${formatDate(tx.timestamp)}`;
                    select.appendChild(opt);
                });
            } catch (e) {
                select.innerHTML = `<option value="">Ошибка: ${escapeHtml(e.message)}</option>`;
            }
        }

        // Выбор транзакции из кастомного пикера → заполняем поля Pay-In
        function selectCustomPayinTx(select) {
            if (!select.value) return;
            const tx = JSON.parse(select.value);
            const info = document.getElementById('customPayinPickerInfo');
            if (tx.kind === 'wl') {
                document.getElementById('customPayinCurrency').value = 'RUB';
                document.getElementById('customPayinAmount').value = tx.amount_rub;
                document.getElementById('customPayinRate').value = parseFloat(tx.final_rate).toFixed(4);
                document.getElementById('customPayinUsdt').value = parseFloat(tx.amount_usdt).toFixed(2);
                customUsdtMode.payin = 'usdt';  // используем точный клиентский USDT
                info.textContent = `${tx.display_name} · ${Number(tx.amount_rub).toLocaleString('ru')} ₽ → $${parseFloat(tx.amount_usdt).toFixed(2)} · курс ${parseFloat(tx.final_rate).toFixed(2)}`;
            } else if (tx.kind === 'crypto') {
                document.getElementById('customPayinCurrency').value = 'USDT';
                document.getElementById('customPayinAmount').value = parseFloat(tx.amount_usdt).toFixed(2);
                document.getElementById('customPayinUsdt').value = parseFloat(tx.amount_usdt).toFixed(2);
                document.getElementById('customPayinTxHash').value = tx.tx_hash;
                customUsdtMode.payin = 'usdt';
                info.textContent = `+$${parseFloat(tx.amount_usdt).toFixed(2)} · ${tx.tx_hash.substring(0, 14)}…`;
            }
            calcCustomProfit();
        }

        function upgradeSelect(select) {
            if (select.dataset.upgraded || select.style.display === 'none') return;
            select.dataset.upgraded = 'true';
            select.style.display = 'none';

            const wrap = document.createElement('div');
            wrap.className = 'custom-select-wrap';
            select.parentNode.insertBefore(wrap, select);
            wrap.appendChild(select);

            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'custom-select-btn';

            const list = document.createElement('div');
            list.className = 'custom-select-list';

            function renderOptions() {
                const opts = Array.from(select.options);
                const selectedVal = select.value;
                btn.textContent = select.selectedOptions[0]?.text || 'Выберите...';
                list.innerHTML = opts.map((o, i) => `<div class="custom-select-opt ${o.value === selectedVal ? 'selected' : ''}" data-index="${i}" data-value="${escapeHtml(o.value)}">${escapeHtml(o.text)}</div>`).join('');
            }
            renderOptions();

            wrap.appendChild(btn);
            wrap.appendChild(list);

            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                // Закрыть другие
                document.querySelectorAll('.custom-select-wrap.open').forEach(w => { if (w !== wrap) w.classList.remove('open'); });
                wrap.classList.toggle('open');
                if (wrap.classList.contains('open')) renderOptions();
            });

            list.addEventListener('click', (e) => {
                const opt = e.target.closest('.custom-select-opt');
                if (!opt) return;
                select.selectedIndex = parseInt(opt.dataset.index);
                select.dispatchEvent(new Event('change', { bubbles: true }));
                btn.textContent = opt.textContent;
                wrap.classList.remove('open');
            });

            // Обновление при программном изменении select. MutationObserver ловит
            // только смену списка опций и атрибутов, а `select.value = 'RUB'` из
            // заполнения редактора мутацией не считается — подпись кнопки оставалась
            // от прошлой сделки или от дефолта (кейс #463: в базе RUB, на экране THB).
            // Перехватываем сеттеры value/selectedIndex на самом элементе.
            const observer = new MutationObserver(renderOptions);
            observer.observe(select, { childList: true, attributes: true });
            ['value', 'selectedIndex'].forEach(prop => {
                const native = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, prop);
                Object.defineProperty(select, prop, {
                    configurable: true,
                    get() { return native.get.call(this); },
                    set(v) { native.set.call(this, v); renderOptions(); }
                });
            });
            // `option.selected = true` и dispatchEvent('change') сеттеры обходят
            select.addEventListener('change', renderOptions);
            // form.reset() возвращает опцию с атрибутом selected, минуя сеттеры;
            // событие reset приходит ДО сброса значений — рисуем на следующем тике
            if (select.form) select.form.addEventListener('reset', () => setTimeout(renderOptions, 0));

            // Закрытие при клике вне
            root.addEventListener('click', (e) => {
                if (!wrap.contains(e.target)) wrap.classList.remove('open');
            });
        }

        function upgradeAllSelects() {
            document.querySelectorAll('select.form-control').forEach(upgradeSelect);
        }

        function formatDate(dateStr) {
            if (!dateStr) return '-';
            const date = new Date(dateStr);
            return date.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
        }

        function reportInvalidField(form) {
            /* Возвращает true, если форму отправлять нельзя, и объясняет почему.
               Нативная валидация тут не годится: невалидное поле часто скрыто
               (кастомная сделка, недвижимость), и браузер просто ничего не делает. */
            for (const el of form.elements) {
                if (el.willValidate && !el.checkValidity()) {
                    const group = el.closest('.form-group');
                    const label = group ? (group.querySelector('.form-label') || {}).textContent : '';
                    showToast('Заполните поле: ' + ((label || el.name || '').trim() || 'обязательное'), 'warning', 4000);
                    if (el.offsetParent !== null) { el.focus(); el.reportValidity(); }
                    return true;
                }
            }
            return false;
        }

        function _agentsCascade(profit, volume, agents) {
            const byTier = {};
            agents.forEach(a => { (byTier[a.tier || 1] = byTier[a.tier || 1] || []).push(a); });
            let base = profit;
            Object.keys(byTier).map(Number).sort((x, y) => x - y).forEach(t => {
                let tot = 0;
                byTier[t].forEach(a => {
                    const m = a.comp_model || 'revshare';
                    let pay = m === 'markup' ? volume * ((+a.percent || 0) / 100)
                            : m === 'fixed' ? (+a.fixed_usdt || 0)
                            : base * ((+a.percent || 0) / 100);
                    pay = Math.round(pay * 100) / 100;
                    a._payout = pay; a._base = Math.round(base * 100) / 100;
                    tot += pay;
                });
                base -= tot;
            });
            return Math.round(base * 100) / 100;
        }

        function _stdProfitVolume() { return _stdGross; }

        function _stdApplyAgents(profit, volume){
            _stdGross = { profit, volume };
            const net = stdAgentsRecalc();
            const total = stdAgents.reduce((s,a)=>s+(a._payout||0),0);
            document.getElementById('referrerPayout').value = total>0?'$'+total.toFixed(2):'0';
            document.getElementById('referrerPayoutRaw').value = total.toFixed(2);
            document.getElementById('netProfit').value = '$'+net.toFixed(2);
            document.getElementById('netProfitRaw').value = net.toFixed(2);
            document.getElementById('netProfit').style.color = net>=0?'#10b981':'#ef4444';
        }

        function calculateProfit() {
            const form = document.getElementById('createDealForm');
            const payinUsdt = parseFloat(form.payin_amount_usdt.value) || 0;
            const payoutThb = parseFloat(form.payout_amount_thb.value) || 0;
            const payoutSource = form.payout_source.value;

            // Личные фаундера: себестоимость известна, как только отмечены переводы
            // выдачи — раньше её узнавали только на возмещении, и до тех пор
            // прибыль по сделке висела «неизвестно» (иногда неделями).
            // Своими батами — себестоимость это сумма, которую вписал менеджер;
            // переводов в такой сделке нет по определению
            const founderCost = noConversionCost() || payoutTxPoolTotal();
            if (payoutSource === 'founder_personal' && founderCost > 0) {
                const cost = founderCost;
                const profit = payinUsdt - cost;
                const profitPercent = cost > 0 ? (profit / cost) * 100 : 0;
                document.getElementById('cashBatchCostUsdt').value = '$' + cost.toFixed(2);
                const exRate = payinUsdt > 0 && payoutThb > 0 ? payoutThb / payinUsdt : 0;
                document.getElementById('exchangeRateCalc').value = exRate.toFixed(2);
                if (payinUsdt <= 0) { markProfitPending(cost); return; }
                document.getElementById('profitUsdt').value = profit.toFixed(2);
                document.getElementById('profitUsdt').placeholder = 'Авто';
                document.getElementById('profitUsdt').style.color = profit >= 0 ? '#10b981' : '#ef4444';
                document.getElementById('profitPercent').value = profitPercent.toFixed(1);
                document.getElementById('profitPercent').placeholder = '%';
                _stdApplyAgents(profit, Math.max(payinUsdt, cost));
                return;
            }

            // Переводы не отмечены — себестоимость появится только с возвратом
            if (payoutSource === 'founder_personal') {
                document.getElementById('profitUsdt').value = '';
                document.getElementById('profitUsdt').placeholder = 'После возмещения';
                document.getElementById('profitPercent').value = '';
                document.getElementById('profitPercent').placeholder = '?';
                document.getElementById('cashBatchCostUsdt').value = 'Неизвестно';
                document.getElementById('referrerPayout').value = 'После возмещения';
                document.getElementById('netProfit').value = 'Неизвестно';
                document.getElementById('netProfit').style.color = '#f59e0b';
                // Очищаем hidden-поля, чтобы не отправить мусорные значения
                document.getElementById('netProfitRaw').value = '';
                document.getElementById('referrerPayoutRaw').value = '';
                return;
            }

            // Определяем курс в зависимости от источника.
            // Если живой курс не загружен или устарел (>10 мин) — предупреждаем
            // менеджера и подтягиваем свежий, вместо тихого хардкода.
            const rateStale = !currentUsdtThbRate || (Date.now() - currentUsdtThbRateAt > 600000);
            if (rateStale) {
                loadCurrentRate();  // фоновое обновление
                if (Date.now() - _rateWarnShownAt > 30000) {
                    _rateWarnShownAt = Date.now();
                    showToast('Курс USDT-THB не загружен/устарел — расчёт приблизительный, обновляю', 'error', 4000);
                }
            }
            const fallbackRate = currentUsdtThbRate || 31.50; // запасной курс, если API недоступен
            let avgRate = fallbackRate;

            if (payoutSource === 'cash_batch' && cashBatchesData.length > 0) {
                // Рассчитываем средневзвешенный курс для FIFO
                let remaining = payoutThb;
                let totalUsdt = 0;
                for (const batch of cashBatchesData) {
                    if (remaining <= 0) break;
                    const take = Math.min(batch.remaining_thb, remaining);
                    totalUsdt += take / batch.purchase_rate;
                    remaining -= take;
                }
                avgRate = remaining <= 0 ? payoutThb / totalUsdt : fallbackRate;
            } else if (payoutSource === 'bank_card') {
                const select = document.getElementById('bankCardSelect');
                const selected = select.options[select.selectedIndex];
                avgRate = parseFloat(selected?.dataset?.rate) || fallbackRate;
            } else if (payoutSource === 'binance') {
                // Binance - USDT напрямую из поля
                const binanceUsdt = parseFloat(document.getElementById('binanceUsdt')?.value) || 0;
                if (binanceUsdt > 0) {
                    // Используем прямое значение USDT, не через курс
                    const profit = payinUsdt - binanceUsdt;
                    const profitPercent = binanceUsdt > 0 ? (profit / binanceUsdt) * 100 : 0;

                    // Прибыль/курс + агенты (каскад) считают net
                    const volume = Math.max(payinUsdt, binanceUsdt);
                    const exchangeRate = payinUsdt > 0 && payoutThb > 0 ? payoutThb / payinUsdt : 0;
                    document.getElementById('cashBatchCostUsdt').value = '$' + binanceUsdt.toFixed(2);
                    document.getElementById('exchangeRateCalc').value = exchangeRate.toFixed(2);
                    if (payinUsdt <= 0) { markProfitPending(binanceUsdt); return; }
                    document.getElementById('profitUsdt').value = profit.toFixed(2);
                    document.getElementById('profitUsdt').style.color = profit >= 0 ? '#10b981' : '#ef4444';
                    document.getElementById('profitPercent').value = profitPercent.toFixed(2);
                    _stdApplyAgents(profit, volume);
                    return;
                }
                avgRate = fallbackRate;
            }

            const payoutUsdt = payoutThb / avgRate;
            const profit = payinUsdt - payoutUsdt;
            const profitPercent = payoutUsdt > 0 ? (profit / payoutUsdt) * 100 : 0;

            document.getElementById('cashBatchCostUsdt').value = '$' + payoutUsdt.toFixed(2);

            // Приход ещё не пересчитан в USDT — прибыли пока нет
            if (payinUsdt <= 0) { markProfitPending(payoutUsdt); return; }

            // Обновляем поля прибыли
            document.getElementById('profitUsdt').value = profit.toFixed(2);
            document.getElementById('profitUsdt').placeholder = 'Авто';
            document.getElementById('profitUsdt').style.color = profit >= 0 ? '#10b981' : '#ef4444';
            document.getElementById('profitPercent').value = profitPercent.toFixed(1);
            document.getElementById('profitPercent').placeholder = '%';

            // Агенты (каскад) считают выплаты и чистую прибыль
            _stdApplyAgents(profit, Math.max(payinUsdt, payoutUsdt));
        }

        function markProfitPending(payoutUsdt) {
            const profitEl = document.getElementById('profitUsdt');
            profitEl.value = '';
            profitEl.placeholder = 'После конвертации';
            profitEl.style.color = '';
            const pctEl = document.getElementById('profitPercent');
            pctEl.value = '';
            pctEl.placeholder = '—';
            const net = document.getElementById('netProfit');
            if (net) {
                net.value = 'Ждём курс прихода';
                net.style.color = '#f59e0b';
            }
            const ref = document.getElementById('referrerPayout');
            if (ref) ref.value = 'После конвертации';
            // hidden-поля чистим, иначе в сделку уедет минус с прошлого пересчёта
            const netRaw = document.getElementById('netProfitRaw');
            if (netRaw) netRaw.value = '';
            const refRaw = document.getElementById('referrerPayoutRaw');
            if (refRaw) refRaw.value = '';
        }

        function payoutTxPoolTotal() {
            return payoutTxPool.reduce((s, t) => s + (t.amount_usdt || 0), 0);
        }

        function noConversionOn() {
            return !!document.getElementById('payoutNoConversion')?.checked;
        }

        function noConversionCost() {
            if (!noConversionOn()) return 0;
            const n = parseFloat(document.getElementById('noConvUsdt')?.value);
            return isNaN(n) || n <= 0 ? 0 : n;
        }

        async function loadCashBatchesForSelect() {
            try {
                const response = await fetch(`${API_URL}/api/cash/batches`);
                const data = await response.json();

                if (data.success) {
                    // Используем только активные партии для расчетов и списка
                    const activeBatches = data.batches.filter(b => b.status === 'active');
                    cashBatchesData = activeBatches;

                    // Info about cash balance
                    const totalThb = data.summary?.total_remaining_thb || 0;
                    const infoHtml = activeBatches.length > 0
                        ? `<strong>${formatNumber(totalThb)} THB</strong> доступно (${activeBatches.length} партий)<br>
                           <small>Авто-списание FIFO: сначала старые партии</small>`
                        : '<span style="color: #ef4444;">Касса пуста</span>';

                    const el = document.getElementById('cashBalanceInfo');
                    if (el) el.innerHTML = infoHtml;

                    // For card source batch
                    const cardSourceSelect = document.getElementById('cardSourceBatch');
                    if (cardSourceSelect) {
                        cardSourceSelect.innerHTML = '<option value="">Выберите партию</option>' +
                            activeBatches.map(b =>
                                `<option value="${b.id}" data-rate="${b.purchase_rate}" data-remaining="${b.remaining_thb}">Партия #${b.id}: ${formatNumber(b.remaining_thb)} THB (курс ${b.purchase_rate})</option>`
                            ).join('');
                    }
                }
            } catch (error) {
                console.error('Error loading cash batches:', error);
            }
        }

        async function loadBankCardsForSelect() {
            try {
                const response = await fetch(`${API_URL}/api/cards/balance`);
                const data = await response.json();

                if (data.success) {
                    const select = document.getElementById('bankCardSelect');
                    if (select) {
                        select.innerHTML = data.cards.length > 0
                            ? data.cards.map(c =>
                                `<option value="${c.id}" data-rate="${c.avg_rate}" data-remaining="${c.balance_thb}">
                                    ${c.bank_name} (${c.holder_name}): ${formatNumber(c.balance_thb)} THB
                                </option>`
                            ).join('')
                            : '<option value="">Нет доступных карт</option>';

                        // Update info for first card
                        if (data.cards.length > 0) {
                            const first = data.cards[0];
                            document.getElementById('bankCardInfo').value =
                                `${formatNumber(first.balance_thb)} THB / курс ${first.avg_rate}`;
                        }
                    }
                }
            } catch (error) {
                console.error('Error loading bank cards:', error);
            }
        }

        function methodUsesSberPool(method) { return method === 'sber_reqs' || method === 'sber_wl'; }

        // Архивные методы (spp_doverka) убраны из выпадашки, но у старых сделок они
        // в базе: если просто присвоить value, селект останется пустым и сохранение
        // молча сменит метод. Поэтому опцию для такого значения раскрываем обратно.

        function peHashes(p) {
            // Старые части хранили один tx_hash — открываем их без миграции
            if (!p.tx_hashes) p.tx_hashes = p.tx_hash ? [{ hash: p.tx_hash, amount_usdt: p.amount_usdt ?? null }] : [];
            return p.tx_hashes;
        }

        function peHashTotal(p) {
            return peHashes(p).reduce((s, t) => s + (t.amount_usdt || 0), 0);
        }

        // Кэш входящих транзакций для пикеров ЧАСТЕЙ (у экрана возмещений
        // свой incomingTxCache — имена не пересекаем). Наполняется
        // loadIncomingTxForSelect — тем же запросом, что кормит основной блок
        let payinExtraTxCache = [];

        // Хэши, уже занятые в этой форме: основной пул, ручное поле и все части.
        // Показывать их в выборе нельзя — один приход списался бы дважды.
        // Свой выбранный хэш тоже убираем из списка: он виден в поле рядом
        function payinUsedHashes() {
            const used = new Set(payinTxPool.map(t => t.hash));
            const manual = document.querySelector('[name="payin_tx_hash"]')?.value?.trim();
            if (manual) used.add(manual);
            payinExtra.forEach(p => peHashes(p).forEach(t => { if (t.hash) used.add(t.hash.trim()); }));
            return used;
        }

        function payinExtraPickTx(i, select) {
            const opt = select.selectedOptions[0];
            const hash = select.value;
            select.selectedIndex = 0;
            if (!hash) return;
            const amount = parseFloat(opt?.dataset?.amount);
            payinExtraHashPush(i, hash, isNaN(amount) ? null : amount);
        }

        // Добавляет хэш части и подтягивает сумму. Первый хэш задаёт сумму части
        // (она же курс), последующие — прибавляются: часть закрыта несколькими
        // переводами, и её приход равен их сумме
        function payinExtraHashPush(i, hash, amountUsdt) {
            hash = String(hash || '').trim();
            if (!hash) return;
            const p = payinExtra[i];
            if (payinUsedHashes().has(hash)) {
                showToast('Этот хэш уже привязан', 'error');
                return;
            }
            peHashes(p).push({ hash, amount_usdt: amountUsdt });
            const total = peHashTotal(p);
            if (total > 0) {
                p.amount_usdt = +total.toFixed(2);
                if (p.amount_rub) p.rate_rub_usdt = +(p.amount_rub / p.amount_usdt).toFixed(4);
            }
            payinExtraRender();
        }

        function payinExtraHashManual(i) {
            const input = document.getElementById(`pe-${i}-hash`);
            if (!input) return;
            payinExtraHashPush(i, input.value, null);
            input.value = '';
        }

        function payinExtraHashRemove(i, k) {
            peHashes(payinExtra[i]).splice(k, 1);
            payinExtraRender();
        }

        // Доля перевода, идущая в эту часть: один перевод может закрывать
        // несколько частей или сделок, поэтому сумма правится руками
        function payinExtraHashShare(i, k, value) {
            const p = payinExtra[i];
            const n = parseFloat(String(value).replace(/\s/g, '').replace(',', '.'));
            peHashes(p)[k].amount_usdt = isNaN(n) || n <= 0 ? null : n;
            const total = peHashTotal(p);
            if (total > 0) {
                p.amount_usdt = +total.toFixed(2);
                if (p.amount_rub) p.rate_rub_usdt = +(p.amount_rub / p.amount_usdt).toFixed(4);
                const usdtInput = document.getElementById(`pe-${i}-usdt`);
                if (usdtInput) usdtInput.value = p.amount_usdt;
                const rateInput = document.getElementById(`pe-${i}-rate`);
                if (rateInput && p.rate_rub_usdt) rateInput.value = p.rate_rub_usdt;
            }
            const sum = document.getElementById(`pe-${i}-hashsum`);
            if (sum) sum.textContent = `${peHashes(p).length} · $${peHashTotal(p).toFixed(2)}`;
            payinExtraSummary();
        }

        // Лейблы для селекта части. spp_doverka не показываем — провайдер умер,
        // опция оставлена только для открытия старых сделок
        const PAYIN_EXTRA_METHODS = [
            ['sber_wl', 'СБП'],
            ['sber_reqs', 'Сбер (реквизиты)'],
            ['crypto_direct', 'Крипта напрямую'],
            ['partners_cash', 'Партнеры (наличные)'],
        ];

        function payinExtraAdd() {
            payinExtra.push({ method: 'crypto_direct', amount_rub: null,
                              rate_rub_usdt: null, amount_usdt: null,
                              partner_name: '', tx_hashes: [], note: '', _mode: 'rate',
                              sber_parts: [] });
            payinExtraRender();
        }

        function payinExtraRemove(i) { payinExtra.splice(i, 1); payinExtraRender(); }

        // Ввод текста НЕ перерисовывает карточки: innerHTML заменяется целиком,
        // и поле теряет фокус после каждого символа. Меняем только состояние,
        // парное поле правим точечно по id, сводку пересчитываем.
        // Перерисовка — только на структурных изменениях (добавили, убрали,
        // сменили метод, выбрали хэш).
        // Поля частей текстовые (type=number терял «86.» на середине ввода),
        // поэтому разбираем сами: запятая как разделитель и пробелы-разряды
        function peNum(v) {
            const n = parseFloat(String(v).replace(/\s/g, '').replace(',', '.'));
            return isNaN(n) || n <= 0 ? null : n;
        }

        function payinExtraSet(i, field, value) {
            const num = ['amount_rub', 'rate_rub_usdt', 'amount_usdt'].includes(field);
            payinExtra[i][field] = num ? peNum(value) : value;

            const p = payinExtra[i];
            const put = (name, val) => {
                const el = document.getElementById(`pe-${i}-${name}`);
                if (el && document.activeElement !== el) el.value = val ?? '';
            };
            // Что менеджер задал руками, то и источник истины — как payinMode
            // у основного прихода. Введён USDT (это факт, сколько реально пришло)
            // → правка рублей двигает КУРС. Введён курс → правка рублей двигает USDT.
            // Без этого поправка рублей молча переписывала бы факт прихода:
            // 6920 превращалось в 6920.0002 из округлённого до 4 знаков курса.
            if (field === 'amount_usdt') p._mode = 'usdt';
            if (field === 'rate_rub_usdt') p._mode = 'rate';

            if (p.amount_rub && p.amount_usdt && (field === 'amount_usdt' || p._mode === 'usdt')) {
                p.rate_rub_usdt = +(p.amount_rub / p.amount_usdt).toFixed(4);
                put('rate', p.rate_rub_usdt);
            } else if (p.amount_rub && p.rate_rub_usdt) {
                p.amount_usdt = +(p.amount_rub / p.rate_rub_usdt).toFixed(4);
                put('usdt', p.amount_usdt);
            }
            payinExtraSummary();
        }

        // Смена метода меняет набор полей — тут перерисовка нужна
        function payinExtraSetMethod(i, value) {
            payinExtra[i].method = value;
            // Уходим со сберовского метода — забранные приходы надо отпустить,
            // иначе они остались бы занятыми за сделкой, которая их не использует
            if (!methodUsesSberPool(value)) payinExtra[i].sber_parts = [];
            payinExtraRender();
            // Пул мог быть не загружен: основной метод не сберовский, а часть — да
            if (methodUsesSberPool(value) && !sberIncomesCache.length) sberLoadIncomes();
        }

        // Приходы Сбера, занятые где-либо в этой форме: основной блок + все части
        function payinSberTakenUuids(exceptIndex) {
            const taken = new Set(sberParts.filter(p => p.uuid).map(p => p.uuid));
            payinExtra.forEach((p, i) => {
                if (i === exceptIndex) return;
                (p.sber_parts || []).forEach(x => x.uuid && taken.add(x.uuid));
            });
            return taken;
        }

        function payinExtraSberAdd(i, uuid) {
            const inc = sberIncomesCache.find(x => x.uuid === uuid);
            const part = payinExtra[i];
            if (!inc || (part.sber_parts || []).some(x => x.uuid === uuid)) return;
            // Как в основном блоке: в сделку идёт то, что заплатил КЛИЕНТ.
            // У эквайринга на счёт падает меньше — банк снимает комиссию сразу
            part.sber_parts = part.sber_parts || [];
            part.sber_parts.push({
                uuid: inc.uuid, amount_rub: inc.gross_rub ?? inc.amount_rub,
                payer: inc.payer || '', date: (inc.operation_date || '').substring(0, 10),
                kind: inc.kind || 'transfer', fee_rub: inc.fee_rub || 0,
                net_rub: inc.amount_rub,
            });
            payinExtraSberSync(i);
            // Доля USDT из пачки — как в основном блоке: если рубли уже
            // конвертированы, считать нечего
            const usdt = inc.usdt ?? inc.usdt_expected;
            if (usdt && !(payinExtra[i].amount_usdt > 0)) {
                payinExtraSet(i, 'amount_usdt', usdt);
                const el = document.getElementById(`pe-${i}-usdt`);
                if (el) el.value = usdt;
            }
        }

        function payinExtraSberRemove(i, k) {
            payinExtra[i].sber_parts.splice(k, 1);
            payinExtraSberSync(i);
        }

        // Рубли части = сумма забранных приходов. Поле остаётся редактируемым:
        // часть суммы могла прийти мимо выписки, менеджер дополнит руками
        function payinExtraSberSync(i) {
            const part = payinExtra[i];
            const sum = (part.sber_parts || []).reduce((s, x) => s + (+x.amount_rub || 0), 0);
            if (sum > 0) {
                part.amount_rub = +sum.toFixed(2);
                if (part._mode === 'usdt' && part.amount_usdt) {
                    part.rate_rub_usdt = +(part.amount_rub / part.amount_usdt).toFixed(4);
                } else if (part.rate_rub_usdt) {
                    part.amount_usdt = +(part.amount_rub / part.rate_rub_usdt).toFixed(4);
                }
            }
            payinExtraRender();
        }

        function payinExtraRender() {
            const box = document.getElementById('payinExtraList');
            if (!box) return;
            box.innerHTML = payinExtra.map((p, i) => {
                const isCrypto = p.method === 'crypto_direct';
                const isCash = p.method === 'partners_cash';
                return `
                <div style="border:1px solid #e2e8f0;border-radius:8px;padding:10px;margin-bottom:6px;background:#fafafa;">
                    <div style="display:flex;gap:8px;align-items:center;margin-bottom:6px;">
                        <strong style="white-space:nowrap;">Приход ${i + 2}</strong>
                        <select class="form-control" style="max-width:220px;"
                            data-crm-action="extra-method" data-crm-event="change" data-index="${i}">
                            ${PAYIN_EXTRA_METHODS.map(([k, v]) =>
                                `<option value="${k}" ${p.method === k ? 'selected' : ''}>${v}</option>`).join('')}
                        </select>
                        <button type="button" class="btn btn-danger" style="margin-left:auto;"
                            data-crm-action="extra-remove" data-crm-event="click" data-index="${i}">✕</button>
                    </div>
                    <div style="display:flex;gap:8px;flex-wrap:wrap;">
                        ${isCrypto ? '' : `
                        <input type="text" inputmode="decimal" class="form-control" style="max-width:150px;"
                            placeholder="Сумма RUB" value="${p.amount_rub ?? ''}"
                            id="pe-${i}-rub" data-crm-action="extra-set" data-crm-event="input" data-index="${i}" data-key="amount_rub">
                        <input type="text" inputmode="decimal" class="form-control" style="max-width:150px;"
                            placeholder="Курс RUB/USDT" value="${p.rate_rub_usdt ?? ''}"
                            id="pe-${i}-rate" data-crm-action="extra-set" data-crm-event="input" data-index="${i}" data-key="rate_rub_usdt">`}
                        <input type="text" inputmode="decimal" class="form-control" style="max-width:150px;"
                            placeholder="Пришло USDT" value="${p.amount_usdt ?? ''}"
                            id="pe-${i}-usdt" data-crm-action="extra-set" data-crm-event="input" data-index="${i}" data-key="amount_usdt">
                        ${isCash ? `
                        <input type="text" class="form-control" style="max-width:150px;"
                            placeholder="Партнёр" value="${escapeHtml(p.partner_name || '')}"
                            id="pe-${i}-partner" data-crm-action="extra-set" data-crm-event="input" data-index="${i}" data-key="partner_name">` : ''}
                    </div>
                    ${methodUsesSberPool(p.method) ? `
                    <div style="margin-top:8px;padding:8px;background:#f0f9ff;border:1px solid #bae6fd;border-radius:6px;">
                        <div style="font-size:12px;font-weight:700;color:#0369a1;margin-bottom:6px;">🏦 Приходы Сбера</div>
                        ${(p.sber_parts || []).map((x, k) => `
                            <div style="display:flex;justify-content:space-between;align-items:center;padding:4px 8px;background:white;border:1px solid #bae6fd;border-radius:6px;margin-bottom:4px;font-size:13px;gap:8px;">
                                <span>${x.kind === 'acquiring' ? '📲' : '🏦'} <b>${rub2(x.amount_rub)} ₽</b>${x.kind === 'acquiring'
                                    ? ` <span style="color:#64748b;">(на счёт ${rub2(x.net_rub)} + комиссия ${rub2(x.fee_rub)})</span>`
                                    : (x.payer ? ' · ' + escapeHtml(x.payer) : '')}${x.date ? ' · ' + escapeHtml(x.date) : ''}</span>
                                <span data-crm-action="extra-sber-remove" data-crm-event="click" data-index="${i}" data-subindex="${k}" style="cursor:pointer;color:#ef4444;font-weight:700;padding:0 4px;">✕</span>
                            </div>`).join('')}
                        ${(() => {
                            const taken = payinSberTakenUuids(i);
                            const own = new Set((p.sber_parts || []).map(x => x.uuid));
                            const free = sberIncomesCache.filter(x => !taken.has(x.uuid) && !own.has(x.uuid));
                            if (!free.length) return '<div style="color:#94a3b8;font-size:12px;padding:2px;">Нет незабранных приходов</div>';
                            return free.map(x => `
                                <div style="display:flex;justify-content:space-between;align-items:center;padding:4px 8px;border-bottom:1px solid #e0f2fe;font-size:13px;gap:8px;">
                                    <span>${sberIncomeLine(x)}</span>
                                    <button type="button" class="btn btn-success btn-sm" data-crm-action="extra-sber-add" data-crm-event="click" data-index="${i}" data-uuid="${escapeHtml(x.uuid)}">Забрать</button>
                                </div>`).join('');
                        })()}
                    </div>` : ''}
                    <div style="margin-top:8px;padding:8px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;">
                        <div style="display:flex;justify-content:space-between;align-items:center;font-size:12px;font-weight:700;color:#334155;margin-bottom:6px;">
                            <span>🔗 Переводы этой части</span>
                            <span id="pe-${i}-hashsum" style="color:#166534;">${peHashes(p).length} · $${peHashTotal(p).toFixed(2)}</span>
                        </div>
                        ${peHashes(p).map((t, k) => `
                            <div style="display:flex;align-items:center;gap:6px;background:white;border:1px solid #e2e8f0;border-radius:6px;padding:3px 6px;margin-bottom:4px;font-size:0.85rem;">
                                <span style="color:#059669;font-weight:700;">$</span>
                                <input type="text" inputmode="decimal" class="form-control"
                                    style="max-width:110px;padding:2px 6px;height:auto;font-size:0.85rem;"
                                    value="${t.amount_usdt ?? ''}" title="сколько из перевода идёт в эту часть"
                                    data-crm-action="extra-hash-share" data-crm-event="input" data-index="${i}" data-subindex="${k}">
                                <code style="flex:1;color:#64748b;overflow:hidden;text-overflow:ellipsis;">${escapeHtml(String(t.hash).substring(0, 20))}...</code>
                                <button type="button" class="btn btn-sm btn-danger" style="padding:1px 6px;"
                                    data-crm-action="extra-hash-remove" data-crm-event="click" data-index="${i}" data-subindex="${k}">✕</button>
                            </div>`).join('')}
                        <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
                            ${(() => {
                                const used = payinUsedHashes();
                                const free = payinExtraTxCache.filter(t => !used.has(t.tx_hash));
                                if (!free.length) return '';
                                return `<select class="form-control" style="max-width:340px;"
                                    data-crm-action="extra-pick" data-crm-event="change" data-index="${i}">
                                    <option value="">-- Добавить хэш из входящих --</option>
                                    ${free.map(t => `<option value="${escapeHtml(t.tx_hash)}" data-amount="${t.amount_usdt}">+$${t.amount_usdt.toFixed(2)} | ${escapeHtml((t.from_address || '').substring(0, 10))}… | ${formatDate(t.timestamp)}</option>`).join('')}
                                </select>`;
                            })()}
                            <input type="text" class="form-control" style="max-width:260px;"
                                placeholder="Или TxHash вручную..." id="pe-${i}-hash">
                            <button type="button" class="btn btn-sm btn-secondary"
                                data-crm-action="extra-hash-manual" data-crm-event="click" data-index="${i}">Добавить</button>
                        </div>
                    </div>
                </div>`;
            }).join('');
            payinExtraSummary();
        }

        function payinExtraSummary() {
            const el = document.getElementById('payinExtraSummary');
            if (!el) return;
            if (!payinExtra.length) { el.textContent = ''; return; }
            const main = parseFloat(document.querySelector('[name="payin_amount_usdt"]')?.value) || 0;
            const total = main + payinExtra.reduce((s, p) => s + (p.amount_usdt || 0), 0);
            const money = v => '$' + v.toLocaleString('en-US',
                { minimumFractionDigits: 2, maximumFractionDigits: 2 });
            el.innerHTML = `<strong>Итого приход: ${money(total)}</strong>
                <span style="color:#64748b;">— основной ${money(main)} + ${payinExtra.length} доп.</span>`;
            // Прибыль недвижимости считается от ИТОГОВОГО прихода, а не от основной части
            if (typeof realtyPayinRecalc === 'function') realtyPayinRecalc();
        }

        function payinExtraSerialize() {
            return payinExtra
                .filter(p => p.amount_usdt > 0)
                .map(p => ({
                    method: p.method,
                    amount_rub: p.amount_rub,
                    rate_rub_usdt: p.rate_rub_usdt,
                    amount_usdt: p.amount_usdt,
                    partner_name: p.partner_name || null,
                    // Сумма пишется по каждому переводу отдельно: приписать всей
                    // части один хэш нельзя — перевод бывает крупнее части
                    // (остаток уходит в другую сделку) и мельче (частей несколько)
                    tx_hashes: peHashes(p)
                        .filter(t => t.hash && String(t.hash).trim())
                        .map(t => ({ hash: String(t.hash).trim(),
                                     amount_usdt: t.amount_usdt ?? null })),
                    sber_uuids: (p.sber_parts || []).map(x => x.uuid).filter(Boolean),
                    note: p.note || '',
                }));
        }

        // Сумма всех дополнительных приходов — нужна сводке недвижимости,
        // которая должна считать прибыль от итога, а не от основной части
        function payinExtraTotalUsdt() {
            return payinExtra.reduce((s, p) => s + (p.amount_usdt || 0), 0);
        }

        function applyPayinMethodFields() {
            const method = document.getElementById('payinMethod');
            const partnerGroup = document.getElementById('payinPartnerGroup');
            const rubGroup = document.getElementById('payinRubGroup');
            const doverkaGroup = document.getElementById('doverkaGroup');
            const txHashGroup = document.getElementById('payinTxHashGroup');
            const rateGroup = document.getElementById('payinRateGroup');
            const exchangeRateGroup = document.getElementById('exchangeRateGroup');

            const isCryptoDirect = method.value === 'crypto_direct';
            const isSberWL = method.value === 'sber_wl';
            const isSberReqs = method.value === 'sber_reqs';

            // Пул выписки Сбера — для обоих сберовских методов. СБП раньше не имел
            // доступа к пулу: платёж клиента лежал в выписке эквайрингом и не
            // привязывался ни к чему, поэтому «где эти деньги» было не ответить.
            const sberGroup = document.getElementById('sberReqsGroup');
            const usesPool = methodUsesSberPool(method.value);
            if (sberGroup) sberGroup.style.display = usesPool ? 'block' : 'none';
            if (usesPool) {
                sberSetKindFilter(isSberWL ? 'acquiring' : 'transfer');
                sberLoadIncomes();
            }

            // Партнеры
            partnerGroup.style.display = method.value === 'partners_cash' ? 'block' : 'none';

            // Рубли и курс RUB/USDT
            if (method.value === 'spp_doverka' || method.value === 'partners_cash' || isSberWL || isSberReqs) {
                rubGroup.style.display = 'block';
                rateGroup.style.display = 'block';
            } else {
                rubGroup.style.display = 'none';
                rateGroup.style.display = 'none';
            }

            // Курс для клиента
            exchangeRateGroup.style.display = isCryptoDirect ? 'none' : 'block';

            // Доверка
            doverkaGroup.style.display = method.value === 'spp_doverka' ? 'flex' : 'none';

            // Блок хэшей виден при ЛЮБОМ методе. Раньше он прятался на сберовских
            // (кроме недвижимости) — считалось, что при рублёвом приходе крипты нет.
            // Это неверно: рубли собираются пулом, на них покупается USDT, и хэш
            // этой покупки — единственный ответ на вопрос «обменяли или лежат».
            // Плюс в дополнительных приходах пикер хэша есть всегда, и разное
            // поведение двух блоков одной формы путало больше, чем экономило место
            txHashGroup.style.display = 'block';
        }

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
                        <button type="button" class="btn btn-success btn-sm" data-crm-action="sber-add" data-crm-event="click" data-uuid="${escapeHtml(i.uuid)}">Забрать</button>
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
                        <span data-crm-action="sber-remove" data-crm-event="click" data-index="${i}" style="cursor:pointer;color:#ef4444;font-weight:700;padding:0 4px;">✕</span>
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

        function payinTxPoolTotal() {
            return payinTxPool.reduce((s, t) => s + (t.amount_usdt || 0), 0);
        }

        function renderPayinTxPool() {
            const box = document.getElementById('payinTxPoolBox');
            if (!box) return;
            if (!payinTxPool.length) { box.innerHTML = ''; return; }
            box.innerHTML = payinTxPool.map((t, i) => {
                const led = payinTxLedger[t.hash];
                // Один перевод может обслуживать несколько сделок: показываем,
                // сколько по нему пришло и сколько уже разобрано другими
                let hint = '';
                if (led) {
                    const others = (led.deal_ids || []).filter(id => id !== editingDealId);
                    hint = `<div style="font-size:0.78rem;color:#64748b;padding:0 4px 2px 8px;">
                        в сети $${led.amount_usdt.toFixed(2)}${led.source !== 'tronscan' ? ' <span style="color:#b45309;">(не сверено)</span>' : ''}
                        · разобрано $${led.used_usdt.toFixed(2)}${others.length ? ' (сделки #' + others.join(', #') + ')' : ''}
                        · <b style="color:${led.free_usdt > 0.01 ? '#166534' : '#94a3b8'};">остаток $${led.free_usdt.toFixed(2)}</b>
                    </div>`;
                }
                return `
                <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:4px 8px;margin-bottom:4px;font-size:0.85rem;">
                    <div style="display:flex;align-items:center;gap:0.5rem;">
                        <span style="color:#059669;font-weight:700;">$</span>
                        <input type="text" inputmode="decimal" class="form-control"
                            style="max-width:120px;padding:2px 6px;height:auto;font-size:0.85rem;"
                            value="${t.amount_usdt ?? ''}" title="сколько из перевода идёт в эту сделку"
                            data-crm-action="payin-share" data-crm-event="input" data-index="${i}">
                        <span style="color:#166534;font-size:0.75rem;font-weight:700;">${escapeHtml((t.network || 'trc20').toUpperCase())}</span>
                        <code style="flex:1;color:#64748b;overflow:hidden;text-overflow:ellipsis;">${t.hash.substring(0, 20)}...</code>
                        <span style="color:#94a3b8;">${t.date || ''}</span>
                        <button type="button" class="btn btn-sm btn-danger" style="padding:1px 6px;" data-crm-action="payin-remove" data-crm-event="click" data-index="${i}">✕</button>
                    </div>
                    ${hint}
                </div>`;
            }).join('') +
                `<div style="text-align:right;font-weight:700;color:#166534;">Частей: ${payinTxPool.length} · итого $${payinTxPoolTotal().toFixed(2)}</div>`;
        }

        const round2 = v => Math.round((v || 0) * 100) / 100;

        function payinTxShareChanged(i, value) {
            const n = parseFloat(String(value).replace(/\s/g, '').replace(',', '.'));
            payinTxPool[i].amount_usdt = isNaN(n) || n <= 0 ? null : n;
            payinTxPool[i]._auto = false;   // менеджер задал долю сам — не переписываем
            const amountInput = document.querySelector('[name="payin_amount_usdt"]');
            if (amountInput) amountInput.value = payinTxPoolTotal().toFixed(2);
            payinMode = 'usdt';
            autoCalcUsdt();
            const box = document.getElementById('payinTxPoolBox');
            const total = box?.querySelector('div[style*="text-align:right"]');
            if (total) total.innerHTML = `Частей: ${payinTxPool.length} · итого $${payinTxPoolTotal().toFixed(2)}`;
        }

        async function loadPayinTxLedger(hash) {
            if (!hash || payinTxLedger[hash]) return;
            try {
                const r = await fetch(`${API_URL}/api/payin-txs/${hash}`);
                if (!r.ok) return;
                const d = await r.json();
                if (!d.success) return;
                payinTxLedger[hash] = d.tx;

                // Перевод уже частично разобран другими сделками: в долю
                // подставляем ОСТАТОК, а не всю сумму из сети. Иначе менеджер
                // вбивал бы $2760 там, где свободно $407, и упирался в отказ
                const mine = (d.uses || []).find(u => u.deal_id === editingDealId);
                const forMe = round2(d.tx.free_usdt + (mine ? mine.amount_usdt : 0));
                payinTxPool.forEach(t => {
                    if (t.hash === hash && t._auto && forMe > 0 && forMe < (t.amount_usdt || 0)) {
                        t.amount_usdt = forMe;
                    }
                });
                syncPayinAmountFromPool();
                renderPayinTxPool();
            } catch (e) { /* реестр не критичен для сохранения */ }
        }

        function syncPayinAmountFromPool() {
            const amountInput = document.querySelector('[name="payin_amount_usdt"]');
            const hashInput = document.querySelector('[name="payin_tx_hash"]');
            if (payinTxPool.length) {
                if (amountInput) amountInput.value = payinTxPoolTotal().toFixed(2);
                // Первый хэш дублируем в поле — его читают карточка сделки и выгрузка
                if (hashInput) hashInput.value = payinTxPool[0].hash;
                // Сумма пула — это факт прихода, значит курс выводим из рублей,
                // а не наоборот; заодно пересчитываем сводку недвижимости
                payinMode = 'usdt';
                autoCalcUsdt();
            }
            renderPayinTxPool();
        }

        function selectPayinTx(select) {
            const opt = select.selectedOptions[0];
            const txHash = select.value;
            select.selectedIndex = 0;
            if (!txHash) return;

            if (payinTxPool.some(t => t.hash === txHash)) {
                showToast('Эта транзакция уже добавлена', 'error');
                return;
            }
            const amount = parseFloat(opt?.dataset?.amount);
            // Доля по умолчанию — приход ЭТОЙ сделки, а не весь перевод: один
            // перевод часто обслуживает несколько сделок, и сделка на $416
            // записывала на себя $1402 остатка (#469/#481). Приход берём из
            // поля USDT, иначе выводим из рублей по курсу; уже добавленные
            // части пула вычитаем — они закрывают свой кусок прихода.
            const form = document.getElementById('createDealForm');
            let expected = parseFloat(form?.payin_amount_usdt?.value) || 0;
            if (!expected) {
                const rub = parseFloat(form?.payin_amount_rub?.value) || 0;
                const rate = parseFloat(form?.payin_rate_rub_usdt?.value) || 0;
                if (rub > 0 && rate > 0) expected = round2(rub / rate);
            }
            expected = round2(expected - payinTxPoolTotal());
            let share = isNaN(amount) ? null : amount;
            if (share != null && expected > 0 && expected < share) share = expected;
            payinTxPool.push({
                hash: txHash,
                network: 'trc20',
                amount_usdt: share,
                date: opt?.dataset?.date || '',
                // Подставлено из сети, руками не трогали: когда приедет реестр,
                // такую долю можно ужать до остатка перевода
                _auto: true,
            });
            syncPayinAmountFromPool();
            loadPayinTxLedger(txHash);
        }

        function removePayinTx(index) {
            payinTxPool.splice(index, 1);
            if (!payinTxPool.length) {
                // Пул опустел — поля освобождаем под ручной ввод
                const hashInput = document.querySelector('[name="payin_tx_hash"]');
                if (hashInput) hashInput.value = '';
            }
            syncPayinAmountFromPool();
        }

        function resetPayinTxPool(parts) {
            payinTxPool = (parts || []).map(p => ({
                hash: p.hash,
                network: p.network || 'trc20',
                amount_usdt: p.amount_usdt != null ? Number(p.amount_usdt) : null,
                date: '',
            }));
            renderPayinTxPool();
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

        function renderMfSummary(r) {
            _mfLast = r;
            const box = document.getElementById('mfSummary');
            const money = v => '$' + (v || 0).toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
            const baht = v => '฿' + (v || 0).toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
            // Пустые поля процента/суммы дозаполняем расчётом — оператор видит обе стороны
            const pctEl = document.getElementById('mfPercent');
            const sentEl = document.getElementById('mfSentThb');
            if (!pctEl.value) pctEl.placeholder = r.company_percent.toFixed(2) + ' %';
            if (!sentEl.value) sentEl.placeholder = r.company_sent_thb.toLocaleString('ru-RU');

            const modelLabel = {
                markup: '% от курса', fixed: 'фикс',
                revshare: '% от прибыли', crypto_share: '% от прибыли в крипте',
            };
            const agents = (r.agents || []).map(a =>
                `<div style="display:flex;justify-content:space-between;"><span style="color:#6b7280;">— ур.${a.tier || 1} ${escapeHtml(a.name || 'агент')} · ${modelLabel[a.comp_model] || a.comp_model}</span><strong>−${money(a._payout)}</strong></div>`
            ).join('');

            const short = r.crypto_shortfall_usdt < 0;
            // Партнёрам мы обязаны заплатить из крипты, поэтому их выплаты вычитаем
            // ДО комиссии компании: иначе кажется, что в компанию можно оставить
            // весь валовый доход, а на выплаты денег уже не остаётся.
            const available = r.gross_profit_usdt - r.agents_total_usdt;  // приход − инвойс/курс − выплаты
            const invoiceThb = r.company_sent_thb - r.company_fee_thb;
            const overLimit = r.company_fee_usdt > available + 0.01;
            // Переводы отмечены — показываем, что себестоимость взята по факту, и где
            // разошлась с курсовым расчётом (комиссии сети, округление)
            const diff = r.cost_diff_usdt || 0;
            const factLine = mfPayoutTxPool.length ? `
                <div style="display:flex;justify-content:space-between;"><span style="color:#9ca3af;padding-left:12px;">— по факту ${mfPayoutTxPool.length} перевод(а/ов), по курсу ${money(r.computed_cost_usdt)}</span><span style="color:${Math.abs(diff) > 1 ? '#b45309' : '#9ca3af'};">${diff > 0 ? '+' : ''}${money(diff)}</span></div>` : '';
            box.innerHTML = `
              <div style="background:#faf5ff;border:1px solid #e9d5ff;border-radius:8px;padding:0.75rem;">
                <div style="display:flex;justify-content:space-between;"><span style="color:#6b7280;">Приход от клиента</span><strong>${money(r.payin_usdt)}</strong></div>
                <div style="display:flex;justify-content:space-between;"><span style="color:#6b7280;">Отправлено в компанию ${baht(r.company_sent_thb)}</span><strong>−${money(r.cost_usdt)}</strong></div>
                <div style="display:flex;justify-content:space-between;"><span style="color:#9ca3af;padding-left:12px;">— инвойс застройщику ${baht(invoiceThb)}</span><span style="color:#6b7280;">${money(r.invoice_cost_usdt)}</span></div>
                <div style="display:flex;justify-content:space-between;"><span style="color:#9ca3af;padding-left:12px;">— комиссия компании ${baht(r.company_fee_thb)} (${r.company_percent.toFixed(2)}%)</span><span style="color:#6b7280;">${money(r.company_fee_usdt)}</span></div>
                ${factLine}
                <div style="display:flex;justify-content:space-between;border-top:1px solid #e9d5ff;margin-top:4px;padding-top:4px;"><span>Осталось в крипте</span><strong style="color:${r.crypto_profit_usdt < 0 ? '#dc2626' : 'inherit'};">${money(r.crypto_profit_usdt)}</strong></div>
                ${r.agents_total_usdt ? `<div style="display:flex;justify-content:space-between;"><span style="color:#6b7280;">Выплаты партнёрам</span><strong>−${money(r.agents_total_usdt)}</strong></div>${agents}` : ''}
                <div style="display:flex;justify-content:space-between;">
                  <span>Останется в крипте</span>
                  <strong style="color:${short ? '#dc2626' : '#166534'};">${money(r.crypto_remainder_usdt)}</strong>
                </div>
                <div style="display:flex;justify-content:space-between;"><span style="color:#6b7280;">+ комиссия, осевшая в компании</span><strong style="color:${overLimit ? '#dc2626' : 'inherit'};">+${money(r.company_fee_usdt)}</strong></div>
                <div style="display:flex;justify-content:space-between;font-size:1.05rem;border-top:1px solid #e9d5ff;margin-top:4px;padding-top:4px;">
                  <span><strong>Чистый доход</strong> <span style="color:#6b7280;font-size:0.85rem;">крипта + компания</span></span>
                  <strong style="color:#7c3aed;">${money(r.net_profit_usdt)}</strong>
                </div>
                ${(r.company_percent > 3 || r.company_percent < 0) ? `<div style="margin-top:6px;color:#b45309;font-size:0.9rem;">⚠️ Комиссия компании ${r.company_percent.toFixed(2)}% — обычно около 1%. Проверь сумму отправки: она привязана к текущему инвойсу.</div>` : ''}
                ${short ? `<div style="margin-top:6px;color:#dc2626;font-size:0.9rem;">⚠️ Не хватает ${money(-r.crypto_shortfall_usdt)} в крипте на выплаты — придётся конвертировать баты обратно или платить из кармана. Нажми «Подобрать процент».</div>` : ''}
              </div>`;
        }

        function renderFhSummary(r) {
            _fhLast = r;
            const box = document.getElementById('fhSummary');
            const money = v => '$' + (v || 0).toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
            // Отправку не ввели — подсказываем расчётную в placeholder, как у процента лизхолда
            const sentEl = document.getElementById('fhSentUsd');
            if (sentEl && !sentEl.value) sentEl.placeholder = r.sent_usd.toLocaleString('ru-RU');

            const modelLabel = {
                markup: '% от курса', fixed: 'фикс',
                revshare: '% от прибыли', crypto_share: '% от прибыли в крипте',
            };
            const agents = (r.agents || []).map(a =>
                `<div style="display:flex;justify-content:space-between;"><span style="color:#6b7280;">— ур.${a.tier || 1} ${escapeHtml(a.name || 'агент')} · ${modelLabel[a.comp_model] || a.comp_model}</span><strong>−${money(a._payout)}</strong></div>`
            ).join('');

            const gap = r.invoice_gap_usd || 0;
            const negative = r.gross_profit_usdt < 0;
            // Markup берётся от ОБЪЁМА, а не от прибыли: на марже фрихолда 0.4%
            // наценка 0.5% больше всего заработка сделки. Это не ошибка расчёта —
            // наценку партнёра клиент должен оплатить в курсе (калькулятор её
            // закладывает). Не заложили — она съедает нашу прибыль, и это видно.
            const markupAgent = (r.agents || []).some(a => a.comp_model === 'markup');
            box.innerHTML = `
              <div style="background:#ecfeff;border:1px solid #a5f3fc;border-radius:8px;padding:0.75rem;">
                <div style="display:flex;justify-content:space-between;"><span style="color:#6b7280;">Приход от клиента</span><strong>${money(r.payin_usdt)}</strong></div>
                <div style="display:flex;justify-content:space-between;"><span style="color:#6b7280;">Отправлено застройщику</span><strong>−${money(r.sent_usd)}</strong></div>
                <div style="display:flex;justify-content:space-between;"><span style="color:#9ca3af;padding-left:12px;">— комиссия за перевод (${(r.fee_percent || 0).toFixed(2)}% + ${money(r.fee_fixed_usd)})</span><span style="color:#6b7280;">${money(r.fee_usd)}</span></div>
                <div style="display:flex;justify-content:space-between;"><span style="color:#9ca3af;padding-left:12px;">— дойдёт застройщику</span><span style="color:#6b7280;">${money(r.arrive_usd)}</span></div>
                <div style="display:flex;justify-content:space-between;border-top:1px solid #a5f3fc;margin-top:4px;padding-top:4px;">
                  <span>Прибыль после расходов</span>
                  <strong style="color:${negative ? '#dc2626' : 'inherit'};">${money(r.gross_profit_usdt)}</strong>
                </div>
                ${r.agents_total_usdt ? `<div style="display:flex;justify-content:space-between;"><span style="color:#6b7280;">Выплаты партнёрам</span><strong>−${money(r.agents_total_usdt)}</strong></div>${agents}` : ''}
                <div style="display:flex;justify-content:space-between;font-size:1.05rem;border-top:1px solid #a5f3fc;margin-top:4px;padding-top:4px;">
                  <span><strong>Чистый доход</strong> <span style="color:#6b7280;font-size:0.85rem;">после расходов и выплат</span></span>
                  <strong style="color:${r.net_profit_usdt < 0 ? '#dc2626' : '#0e7490'};">${money(r.net_profit_usdt)}</strong>
                </div>
                ${gap < -0.01 ? `<div style="margin-top:6px;color:#dc2626;font-size:0.9rem;">⚠️ До застройщика дойдёт на ${money(-gap)} меньше инвойса — доотправь или пересчитай сумму.</div>` : ''}
                ${gap > 0.01 ? `<div style="margin-top:6px;color:#b45309;font-size:0.9rem;">Переотправлено на ${money(gap)} сверх инвойса.</div>` : ''}
                ${r.net_shortfall_usdt < 0 ? `<div style="margin-top:6px;color:#dc2626;font-size:0.9rem;">⚠️ Выплаты партнёрам больше заработка сделки на ${money(-r.net_shortfall_usdt)} — платим из своего кармана.</div>` : ''}
                ${markupAgent ? `<div style="margin-top:6px;color:#0e7490;font-size:0.85rem;">ℹ️ Наценка партнёра считается от объёма (${money(Math.max(r.payin_usdt, r.sent_usd))}), а не от прибыли — она должна быть заложена в курс клиенту. Если нет, она вычитается из нашего заработка.</div>` : ''}
              </div>`;
        }

        function stdAgentsPreset(mode){ stdAgentsMode=mode; if(mode==='cascade') stdAgents.forEach((a,i)=>a.tier=i+1); else stdAgents.forEach(a=>a.tier=1); renderStdAgents(); calculateProfit(); }

        function stdAgentsAdd(){ const t=stdAgentsMode==='flat'?1:(stdAgents.reduce((m,a)=>Math.max(m,a.tier||1),0)+1); stdAgents.push({referrer_id:null,name:'',tier:t,comp_model:'revshare',percent:10,fixed_usdt:0}); renderStdAgents(); calculateProfit(); }

        function stdAgentsRemove(i){ stdAgents.splice(i,1); renderStdAgents(); calculateProfit(); }

        function stdAgentsTier(i,d){ stdAgents[i].tier=Math.max(1,(stdAgents[i].tier||1)+d); stdAgentsMode=null; renderStdAgents(); calculateProfit(); }

        function stdAgentsField(i,k,v){ if(k==='percent'||k==='fixed_usdt') v=parseFloat(v)||0; stdAgents[i][k]=v; if(k==='referrer_id'){ const r=(_referrersCache||[]).find(x=>String(x.id)===String(v)); if(r){ stdAgents[i].name=r.name; stdAgents[i].comp_model=r.comp_model||'revshare'; stdAgents[i].percent=r.comp_model==='markup'?(r.markup_percent||0):(r.default_percent||0);} } if(k==='comp_model'||k==='referrer_id') renderStdAgents(); calculateProfit(); if(document.getElementById('mfDealToggle')?.checked) mfRecalc(); if(document.getElementById('fhDealToggle')?.checked) fhRecalc(); }

        function renderStdAgents(){ const box=document.getElementById('agentsBlockStd'); if(!box) return; const refs=(_referrersCache||[]).filter(r=>r.active); box.innerHTML=stdAgents.map((a,i)=>{ const placeholder=(!a.referrer_id&&a.name)?`<option value="" selected>${escapeHtml(a.name)} (вручную)</option>`:'<option value="">— выбрать агента —</option>'; const opts=placeholder+refs.map(r=>`<option value="${r.id}" ${String(r.id)===String(a.referrer_id)?'selected':''}>${escapeHtml(r.name)}</option>`).join(''); const valField=a.comp_model==='fixed'?`<input type="number" step="any" class="form-control" value="${a.fixed_usdt||0}" data-crm-action="agent-field" data-crm-event="input" data-index="${i}" data-key="fixed_usdt" placeholder="$" style="width:90px;">`:`<input type="number" step="any" class="form-control" value="${a.percent||0}" data-crm-action="agent-field" data-crm-event="input" data-index="${i}" data-key="percent" placeholder="%" style="width:90px;">`; return `<div style="background:white;border:1px solid #d1fae5;border-radius:8px;padding:10px;margin-bottom:8px;"><div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;"><span style="display:inline-flex;align-items:center;gap:4px;background:#6366f1;color:white;border-radius:999px;padding:3px 6px 3px 10px;font-size:12px;font-weight:700;"><button type="button" data-crm-action="agent-tier" data-crm-event="click" data-index="${i}" data-delta="-1" style="border:none;background:rgba(255,255,255,.25);color:white;border-radius:50%;width:18px;height:18px;cursor:pointer;">−</button>Ур.${a.tier||1}<button type="button" data-crm-action="agent-tier" data-crm-event="click" data-index="${i}" data-delta="1" style="border:none;background:rgba(255,255,255,.25);color:white;border-radius:50%;width:18px;height:18px;cursor:pointer;">+</button></span><select class="form-control" data-crm-action="agent-field" data-crm-event="change" data-index="${i}" data-key="referrer_id" style="flex:1;">${opts}</select><button type="button" data-crm-action="agent-remove" data-crm-event="click" data-index="${i}" style="border:none;background:transparent;color:#94a3b8;font-size:16px;cursor:pointer;">🗑</button></div><div style="display:flex;align-items:center;gap:8px;"><select class="form-control" data-crm-action="agent-field" data-crm-event="change" data-index="${i}" data-key="comp_model" style="flex:1;"><option value="revshare" ${a.comp_model==='revshare'?'selected':''}>revshare (% от прибыли)</option><option value="markup" ${a.comp_model==='markup'?'selected':''}>markup (+% к курсу)</option><option value="fixed" ${a.comp_model==='fixed'?'selected':''}>fixed ($ сумма)</option><option value="crypto_share" ${a.comp_model==='crypto_share'?'selected':''}>% от прибыли в крипте (MF Corp)</option></select>${valField}<span style="min-width:90px;text-align:right;font-weight:700;color:#16a34a;" id="saPay${i}">$0</span></div></div>`; }).join(''); document.getElementById('saPreCascade')?.classList.toggle('active',stdAgentsMode==='cascade'); document.getElementById('saPreFlat')?.classList.toggle('active',stdAgentsMode==='flat'); }

        function stdAgentsRecalc(){
            // Недвижимость через MF Corp считается по своим формулам (два кармана).
            // Обычный каскад тут дал бы неверные числа: он не знает про комиссию,
            // запертую в батах, и трактует crypto_share как revshare.
            if (document.getElementById('mfDealToggle')?.checked) {
                const netEl = document.getElementById('agentsBlockStdNet');
                if (netEl) {
                    netEl.innerHTML = _mfLast
                        ? `Агентам всего: <b>$${(_mfLast.agents_total_usdt || 0).toFixed(2)}</b> · В крипте останется: <b>$${(_mfLast.crypto_remainder_usdt || 0).toFixed(2)}</b> · Чистый доход: <b>$${(_mfLast.net_profit_usdt || 0).toFixed(2)}</b>`
                        : '';
                }
                (_mfLast?.agents || []).forEach((a, i) => {
                    const el = document.getElementById('saPay' + i);
                    if (el) el.textContent = '$' + (a._payout || 0).toFixed(2);
                });
                return _mfLast?.crypto_remainder_usdt || 0;
            }
            // Фрихолд: база выплат — прибыль ПОСЛЕ расходов на перевод, обычный
            // каскад её не знает (он считает от полей выдачи, которых тут нет)
            if (document.getElementById('fhDealToggle')?.checked) {
                const netEl = document.getElementById('agentsBlockStdNet');
                if (netEl) {
                    netEl.innerHTML = _fhLast
                        ? `Агентам всего: <b>$${(_fhLast.agents_total_usdt || 0).toFixed(2)}</b> · База (после расходов): <b>$${(_fhLast.gross_profit_usdt || 0).toFixed(2)}</b> · Чистый доход: <b>$${(_fhLast.net_profit_usdt || 0).toFixed(2)}</b>`
                        : '';
                }
                (_fhLast?.agents || []).forEach((a, i) => {
                    const el = document.getElementById('saPay' + i);
                    if (el) el.textContent = '$' + (a._payout || 0).toFixed(2);
                });
                return _fhLast?.net_profit_usdt || 0;
            }
            const {profit,volume}=_stdProfitVolume(); const net=_agentsCascade(profit,volume,stdAgents); stdAgents.forEach((a,i)=>{const el=document.getElementById('saPay'+i); if(el) el.textContent='$'+(a._payout||0).toFixed(2);}); const total=stdAgents.reduce((s,a)=>s+(a._payout||0),0); const netEl=document.getElementById('agentsBlockStdNet'); if(netEl) netEl.innerHTML=stdAgents.length?`Агентам всего: <b>$${total.toFixed(2)}</b> · Чистая наша: <b>$${net.toFixed(2)}</b>`:''; return net; }

        function stdAgentsSerialize(){ return stdAgents.filter(a=>a.referrer_id||a.name).map(a=>({referrer_id:a.referrer_id?parseInt(a.referrer_id):null,name:a.name||null,tier:a.tier||1,comp_model:a.comp_model||'revshare',percent:a.comp_model==='fixed'?0:(+a.percent||0),fixed_usdt:a.comp_model==='fixed'?(+a.fixed_usdt||0):0})); }

        function stdAgentsLoad(arr){ stdAgents=(arr||[]).map(a=>({referrer_id:a.referrer_id||null,name:a.name||'',tier:a.tier||1,comp_model:a.comp_model||'revshare',percent:a.percent||0,fixed_usdt:a.fixed_usdt||0})); stdAgentsMode=stdAgents.length&&stdAgents.every(a=>(a.tier||1)===1)?'flat':'cascade'; renderStdAgents(); calculateProfit(); }

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
                    <span style="color:#7f1d1d;font-size:0.75rem;font-weight:700;">${escapeHtml((t.network || 'trc20').toUpperCase())}</span>
                    <span style="color:#334155;">→ ${escapeHtml((t.to_address || '').substring(0, 12))}${t.to_address ? '…' : ''}</span>
                    <code style="flex:1;color:#94a3b8;overflow:hidden;text-overflow:ellipsis;">${escapeHtml(t.hash.substring(0, 14))}…</code>
                    <span style="color:#94a3b8;">${escapeHtml(t.date || '')}</span>
                    <button type="button" class="btn btn-sm btn-danger" style="padding:1px 6px;" data-crm-action="mf-remove" data-crm-event="click" data-index="${i}">✕</button>
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
                            data-crm-action="mf-check" data-crm-event="change" data-hash="${escapeHtml(tx.tx_hash)}">
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
