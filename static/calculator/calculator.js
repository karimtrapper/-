// Конфигурация
// Используем ваш основной API сервер
// Same-origin: API живёт в том же Flask-приложении, что отдаёт эту страницу.
// Абсолютный URL ломался при смене домена Railway → 404 → фоллбэк на заглушку (курс 2.8).
const API_URL = '/api';

// Toast-уведомления вместо системных alert/confirm
function showToast(message, type = 'info', duration = 3000) {
    const existing = document.getElementById('toast-container');
    if (existing) existing.remove();
    const container = document.createElement('div');
    container.id = 'toast-container';
    const colors = { success: '#22c55e', error: '#ef4444', info: '#3b82f6', warning: '#f59e0b' };
    container.innerHTML = `<div style="position:fixed;top:20px;left:50%;transform:translateX(-50%);z-index:10000;
        background:${colors[type] || colors.info};color:#fff;padding:12px 24px;border-radius:12px;
        font-size:14px;font-weight:500;box-shadow:0 4px 20px rgba(0,0,0,0.15);max-width:90vw;text-align:center;
        animation:toastIn .3s ease">${message.replace(/\n/g, '<br>')}</div>`;
    document.body.appendChild(container);
    setTimeout(() => container.remove(), duration);
}

function showConfirm(message) {
    return new Promise(resolve => {
        const overlay = document.createElement('div');
        overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:10000;display:flex;align-items:center;justify-content:center';
        overlay.innerHTML = `<div style="background:#fff;border-radius:16px;padding:24px;max-width:400px;width:90vw;box-shadow:0 20px 60px rgba(0,0,0,0.3)">
            <div style="font-size:15px;line-height:1.5;margin-bottom:20px">${message.replace(/\n/g, '<br>')}</div>
            <div style="display:flex;gap:12px;justify-content:flex-end">
                <button id="confirm-cancel" style="padding:10px 20px;border-radius:10px;border:1px solid #ddd;background:#fff;cursor:pointer;font-size:14px">Отмена</button>
                <button id="confirm-ok" style="padding:10px 20px;border-radius:10px;border:none;background:#FF6B35;color:#fff;cursor:pointer;font-size:14px;font-weight:600">OK</button>
            </div></div>`;
        document.body.appendChild(overlay);
        overlay.querySelector('#confirm-cancel').onclick = () => { overlay.remove(); resolve(false); };
        overlay.querySelector('#confirm-ok').onclick = () => { overlay.remove(); resolve(true); };
        overlay.onclick = (e) => { if (e.target === overlay) { overlay.remove(); resolve(false); } };
    });
}

const CONFIG = {
    API_URL: API_URL,
    USE_API: true,
    
    FALLBACK_RATES: {
        usdt_thb: 31.08,
        rub_usdt: 82.6035
    },
    
    // Комиссии для Doverka
    DOVERKA_COMMISSIONS: {
        'до_500к': {
            min: 0,
            max: 500000,
            usdt_thb_commission: 0.0272,
            withdrawal_percent: 0.0025,
            withdrawal_fixed: 20,
            bonus_percent: 0.024
        },
        '500к_1млн': {
            min: 500000,
            max: 1000000,
            usdt_thb_commission: 0.017,
            withdrawal_percent: 0.0025,
            withdrawal_fixed: 20,
            bonus_percent: 0.024
        },
        'от_1млн': {
            min: 1000000,
            max: Infinity,
            usdt_thb_commission: 0.0067,
            withdrawal_percent: 0.0025,
            withdrawal_fixed: 20,
            bonus_percent: 0.024
        }
    }
};

// Глобальное состояние
let state = {
    method: 'doverka',  // 'doverka' или 'broker'
    scenario: 'rub-to-thb',  // текущий сценарий
    direction: 'amount',  // 'amount' (вношу) или 'target' (хочу получить)
    profitMargin: 4.0,    // чистая прибыль брокера в %
    rates: CONFIG.FALLBACK_RATES,
    customRubUsdt: null,  // кастомный курс для broker/custom (null = не введён)
    customUsdtThb: null,  // кастомный курс THB-USDT для метода 'custom' (null = не введён)
    detailsOpen: false,
    infoOpen: false,
    applyDiscount: false,
    lastResult: null, // Храним последний результат для создания платежа
    lastUpdateTimestamp: 0, // Время последнего обновления курсов
    preciseRateTimestamp: 0, // Когда получен точный курс Binance
    preciseRateLocked: false, // Точный курс зафиксирован (не обновлять 5 мин)
    preciseRateTimer: null, // ID таймера обратного отсчёта
    _calcVersion: 0 // Счётчик версий расчёта (защита от race condition)
};

// Проверка авторизации — редирект на логин если не залогинен
async function checkAuth() {
    try {
        const resp = await fetch('/api/auth/me');
        if (!resp.ok) {
            window.location.href = '/login';
            return false;
        }
        return true;
    } catch(e) {
        window.location.href = '/login';
        return false;
    }
}

// Инициализация
document.addEventListener('DOMContentLoaded', async () => {
    if (!await checkAuth()) return;
    refreshRates();
    // Фоновое обновление курсов каждые 5 минут
    setInterval(refreshRates, 5 * 60 * 1000);
});

// Очистка результатов при изменении ввода
function hideResults() {
    document.getElementById('resultsSection').style.display = 'none';
}

// Переключение метода
function switchMethod(method) {
    state.method = method;
    
    // Обновляем кнопки метода
    document.querySelectorAll('.method-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.method === method);
    });
    
    // Секция комиссий теперь доступна для обоих методов
    document.getElementById('commissionLevelSection').style.display = 'block';
    
    // Показываем/скрываем элементы UI
    if (method === 'broker' || method === 'custom') {
        document.getElementById('customRateSection').style.display = 'block';
        document.getElementById('directionSwitcher').style.display = 'block';
        document.getElementById('rubUsdtLabel').textContent = 'RUB-USDT (Кастомный)';

        // Очищаем курсы — менеджер должен ввести сам
        const customInput = document.getElementById('customRubUsdt');
        customInput.value = '';
        state.customRubUsdt = null;
        const customThbInput = document.getElementById('customUsdtThb');
        customThbInput.value = '';
        state.customUsdtThb = null;

        // Карточка THB-USDT — только для метода 'custom'
        document.getElementById('customUsdtThbCard').style.display = method === 'custom' ? 'block' : 'none';

        updateBrokerRateUI();

        // Показываем broker сценарии (custom использует те же сценарии), скрываем doverka
        document.querySelectorAll('.scenario-btn').forEach(btn => {
            if (btn.dataset.method === 'broker') {
                btn.style.display = 'flex';
            } else {
                btn.style.display = 'none';
            }
        });

        // Выбираем первый сценарий
        state.scenario = 'rub-to-thb';
        updateScenarioUI();
        updateRatesDisplay();

    } else {
        document.getElementById('customRateSection').style.display = 'none';
        document.getElementById('directionSwitcher').style.display = 'none';
        document.getElementById('rubUsdtLabel').textContent = 'RUB-USDT';
        
        // Показываем doverka сценарии, скрываем broker
        document.querySelectorAll('.scenario-btn').forEach(btn => {
            if (btn.dataset.method === 'doverka') {
                btn.style.display = 'flex';
            } else {
                btn.style.display = 'none';
            }
        });
        
        // Выбираем первый doverka сценарий
        state.scenario = 'rub-to-thb';
        updateScenarioUI();
        updateRatesDisplay();
    }
    
    hideResults();
}

// Нужен ли курс RUB-USDT для текущего сценария?
// USDT→THB и THB→USDT — прямые, без рубля
function scenarioNeedsRubRate(scenario) {
    return scenario !== 'usdt-to-thb' && scenario !== 'thb-to-usdt';
}

// Переключение сценария
function switchScenario(scenario) {
    state.scenario = scenario;
    updateScenarioUI();
    hideResults();

    // Показываем/скрываем поля кастомных курсов в зависимости от сценария
    if (state.method === 'broker' || state.method === 'custom') {
        const section = document.getElementById('customRateSection');
        const needsRub = scenarioNeedsRubRate(scenario);
        const needsThb = scenarioNeedsThbRate(scenario);
        // Скрываем карточку RUB-USDT если сценарий её не требует
        const rubCard = document.querySelector('#customRateSection .custom-rate-card:first-child');
        if (rubCard) rubCard.style.display = needsRub ? 'block' : 'none';
        // Карточка THB-USDT — только для custom и если сценарий её требует
        document.getElementById('customUsdtThbCard').style.display =
            (state.method === 'custom' && needsThb) ? 'block' : 'none';
        // Прячем всю секцию если оба поля не нужны
        section.style.display = (needsRub || (state.method === 'custom' && needsThb)) ? 'block' : 'none';
    }
}

// Нужен ли курс THB-USDT (для custom): все сценарии кроме rub-to-usdt
function scenarioNeedsThbRate(scenario) {
    return scenario !== 'rub-to-usdt' && scenario !== 'usdt-from-rub';
}

// Обновление UI сценария
function updateScenarioUI() {
    // Обновляем активную кнопку
    document.querySelectorAll('.scenario-btn').forEach(btn => {
        const isActive = btn.dataset.scenario === state.scenario && 
                        btn.dataset.method === state.method;
        btn.classList.toggle('active', isActive);
    });
    
    // Обновляем метки и плейсхолдеры с учетом direction
    let config;
    
    if (state.scenario === 'rub-to-thb') {
        if (state.direction === 'target') {
            // Хочу получить конкретную сумму THB
            config = {
                input: 'Введите желаемую сумму в батах (฿)',
                currency: '฿',
                placeholder: '1000000',
                result: 'Клиент должен внести:',
                rateCurrency: '₽/฿'
            };
        } else {
            // Вношу конкретную сумму RUB
            config = {
                input: 'Введите сумму в рублях (₽)',
                currency: '₽',
                placeholder: '2741',
                result: 'Клиент получит:',
                rateCurrency: '₽/฿'
            };
        }
    } else if (state.scenario === 'thb-to-usdt') {
        if (state.direction === 'target') {
            // Хочу получить конкретную сумму USDT
            config = {
                input: 'Введите желаемую сумму в USDT',
                currency: 'USDT',
                placeholder: '13050',
                result: 'Клиент должен внести:',
                rateCurrency: '฿/USDT'
            };
        } else {
            // Вношу конкретную сумму THB
            config = {
                input: 'Введите сумму в батах (฿)',
                currency: '฿',
                placeholder: '400000',
                result: 'Клиент получит:',
                rateCurrency: '฿/USDT'
            };
        }
    } else if (state.scenario === 'usdt-to-thb') {
        if (state.direction === 'target') {
            // Хочу получить конкретную сумму THB
            config = {
                input: 'Введите желаемую сумму в батах (฿)',
                currency: '฿',
                placeholder: '400000',
                result: 'Клиент должен внести:',
                rateCurrency: '฿/USDT'
            };
        } else {
            // Вношу конкретную сумму USDT
            config = {
                input: 'Введите сумму в USDT',
                currency: 'USDT',
                placeholder: '13050',
                result: 'Клиент получит:',
                rateCurrency: '฿/USDT'
            };
        }
    } else if (state.scenario === 'rub-to-usdt') {
        if (state.direction === 'target') {
            // Хочу получить конкретную сумму USDT
            config = {
                input: 'Введите желаемую сумму в USDT',
                currency: 'USDT',
                placeholder: '10000',
                result: 'Клиент должен внести:',
                rateCurrency: '₽/USDT'
            };
        } else {
            // Вношу конкретную сумму RUB
            config = {
                input: 'Введите сумму в рублях (₽)',
                currency: '₽',
                placeholder: '1000000',
                result: 'Клиент получит:',
                rateCurrency: '₽/USDT'
            };
        }
    } else if (state.scenario === 'usdt-from-rub') {
        // Doverka: USDT ← RUB (клиент хочет получить конкретную сумму USDT)
        config = {
            input: 'Введите желаемую сумму в USDT',
            currency: 'USDT',
            placeholder: '1000',
            result: 'Клиент должен внести:',
            rateCurrency: '₽/USDT'
        };
    } else if (state.scenario === 'thb-to-rub') {
        // Doverka: THB ← RUB (клиент хочет получить конкретную сумму THB)
        config = {
            input: 'Введите желаемую сумму в батах (฿)',
            currency: '฿',
            placeholder: '148001',
            result: 'Клиент должен внести:',
            rateCurrency: '₽/฿'
        };
    } else {
        // Doverka: RUB → THB (клиент вносит сумму в рублях)
        config = {
            input: 'Введите сумму в рублях (₽)',
            currency: '₽',
            placeholder: '100000',
            result: 'Клиент получит:',
            rateCurrency: '₽/฿'
        };
    }
    
    document.getElementById('inputLabel').textContent = config.input;
    document.getElementById('inputCurrency').textContent = config.currency;
    document.getElementById('amount').placeholder = config.placeholder;
    document.getElementById('resultLabel').textContent = config.result;
    document.getElementById('rateCurrency').textContent = config.rateCurrency;
    
    // Очищаем поле ввода
    document.getElementById('amount').value = '';
    document.getElementById('resultsSection').style.display = 'none';

    // Точный курс автозапускается после «Рассчитать» только если в сценарии есть THB.
    // Для rub-to-usdt / usdt-from-rub Playwright не нужен — Binance тут не участвует.
    // Скрываем индикаторы при смене сценария.
    hidePreciseRateStatus();
    hidePreciseRateFallback();
}

// Переключение скидки
function toggleDiscount() {
    state.applyDiscount = document.getElementById('applyDiscount').checked;
    const wrapper = document.getElementById('profitMarginWrapper');
    
    if (state.applyDiscount) {
        wrapper.style.display = 'block';
        
        // Автоматически выбираем дефолтный процент в зависимости от суммы
        const amount = getAmount();
        if (amount > 0) {
            let defaultProfit = 4.0;
            // Для USDT-сценариев дефолт 2% (решение Карима 10.08; до этого 2.5%,
            // причём такой кнопки в пресетах нет — активной не подсвечивалась ни одна)
            const isUsdtScenario = ['usdt-to-thb', 'thb-to-usdt'].includes(state.scenario);
            if (isUsdtScenario) {
                defaultProfit = 2.0;
            } else {
                // Определяем базу для расчета (рубли)
                let baseAmount = amount;
                if (state.scenario === 'thb-to-rub') {
                    baseAmount = amount * 2.8;
                } else if (state.scenario === 'usdt-from-rub' || (state.scenario === 'rub-to-usdt' && state.direction === 'target')) {
                    baseAmount = amount * (state.rates.rub_usdt || 82);
                }

                if (baseAmount < 500000) defaultProfit = 5.0;
                else if (baseAmount < 1000000) defaultProfit = 4.0;
                else defaultProfit = 3.0;
            }
            
            // Устанавливаем маржу (это также обновит кнопки)
            setProfitMargin(defaultProfit);
        }
    } else {
        wrapper.style.display = 'none';
        // Скидка выключена — пересчитываем без маржи
        const amount = getAmount();
        if (amount > 0) {
            calculate();
        } else {
            hideResults();
        }
    }
}

// Установка маржи (прибыли)
function setProfitMargin(profit) {
    state.profitMargin = parseFloat(profit);

    // Скрываем кастом-инпут и чистим его (вызов из пресета)
    const customWrapper = document.getElementById('customProfitWrapper');
    const customInput = document.getElementById('customProfitInput');
    if (customWrapper) customWrapper.style.display = 'none';
    if (customInput) customInput.value = '';

    // Обновляем визуальное состояние кнопок
    document.querySelectorAll('.commission-btn').forEach(btn => {
        const btnProfit = parseFloat(btn.dataset.profit);
        btn.classList.toggle('active', btnProfit === state.profitMargin);
    });

    console.log(`🎯 Выбрана маржа: ${state.profitMargin}%`);

    // СРАЗУ вызываем расчет если сумма введена
    const amount = getAmount();
    if (amount > 0) {
        calculate();
    } else {
        hideResults();
    }
}

// Переключение «Своё» — раскрытие инпута для произвольного %
function toggleCustomProfit() {
    const wrapper = document.getElementById('customProfitWrapper');
    const input = document.getElementById('customProfitInput');
    const isOpen = wrapper.style.display !== 'none';

    if (isOpen) {
        wrapper.style.display = 'none';
        return;
    }

    wrapper.style.display = 'block';
    // Сбрасываем подсветку пресетов и активируем «Своё»
    document.querySelectorAll('.commission-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.profit === 'custom');
    });
    setTimeout(() => input.focus(), 50);
}

// Обработчик ввода произвольного %
function onCustomProfitInput(el) {
    // Нормализация: запятая в точку, только числа
    let raw = el.value.replace(',', '.').replace(/[^\d.]/g, '');
    // Один разделитель максимум
    const parts = raw.split('.');
    if (parts.length > 2) raw = parts[0] + '.' + parts.slice(1).join('');
    el.value = raw;

    const val = parseFloat(raw);
    if (isNaN(val) || val < 0) {
        hideResults();
        return;
    }
    // Капаем на 99 чтобы избежать деления на 0 в обратных сценариях
    const capped = Math.min(val, 99);
    if (capped !== val) el.value = String(capped);

    state.profitMargin = capped;
    console.log(`🎯 Кастомная маржа: ${state.profitMargin}%`);

    const amount = getAmount();
    if (amount > 0) {
        calculate();
    } else {
        hideResults();
    }
}

// Установка direction (целевая/вносимая)
function setDirection(direction) {
    state.direction = direction;
    
    document.querySelectorAll('.direction-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.direction === direction);
    });
    
    // Обновляем метки в зависимости от direction
    updateScenarioUI();
    hideResults();
}

// Получение курсов
async function refreshRates() {
    // Если точный курс зафиксирован — не обновлять автоматически
    if (state.preciseRateLocked) {
        console.log('🔒 Точный курс зафиксирован, пропускаем обновление');
        return;
    }

    const refreshBtn = document.getElementById('refreshBtn');
    refreshBtn.classList.add('loading');

    try {
        if (CONFIG.USE_API) {
            const response = await fetch(`${CONFIG.API_URL}/rates`);
            if (response.ok) {
                const data = await response.json();
                state.rates = data;
                state.lastUpdateTimestamp = Date.now();
            } else {
                throw new Error('API error');
            }
        } else {
            await new Promise(resolve => setTimeout(resolve, 500));
            state.rates = {
                usdt_thb: CONFIG.FALLBACK_RATES.usdt_thb + (Math.random() - 0.5) * 0.2,
                rub_usdt: CONFIG.FALLBACK_RATES.rub_usdt + (Math.random() - 0.5) * 0.5
            };
        }

        updateRatesDisplay();
        hideResults();

    } catch (error) {
        console.error('Error fetching rates:', error);
        state.rates = CONFIG.FALLBACK_RATES;
        updateRatesDisplay();
    } finally {
        refreshBtn.classList.remove('loading');
    }
}

// Обновление отображения курсов
function updateRatesDisplay() {
    // В режиме брокера скрываем блок примерных расчетов до нажатия "Рассчитать", 
    // чтобы не путать менеджера старыми или оценочными данными
    const estimatedEl = document.getElementById('estimatedRate');
    const rubUsdt = (state.method === 'broker' || state.method === 'custom') ? state.customRubUsdt : state.rates.rub_usdt;

    // Показываем USDT-THB (в режиме custom — ручной курс)
    const usdtThbEl = document.getElementById('usdtThbRate');
    const usdtThbLabel = document.getElementById('usdtThbLabel');
    const usdtThbSub = document.getElementById('usdtThbSub');
    const srcToggle = document.getElementById('rateSourceToggle');
    // Тумблер источника прячем в custom (там курс ручной)
    if (srcToggle) srcToggle.style.display = (state.method === 'custom') ? 'none' : 'inline-flex';
    if (usdtThbSub) usdtThbSub.style.display = 'none';

    if (state.method === 'custom') {
        if (usdtThbLabel) usdtThbLabel.textContent = 'USDT-THB (ручной)';
        if (state.customUsdtThb) {
            usdtThbEl.textContent = `${state.customUsdtThb.toFixed(4)} ฿`;
            usdtThbEl.classList.remove('rate-error');
        } else {
            usdtThbEl.textContent = '— ฿';
            usdtThbEl.classList.add('rate-error');
        }
        usdtThbEl.style.color = '';
        usdtThbEl.style.fontWeight = '';
    } else if (state.rateSource === 'bitazza') {
        // Bitazza — дефолтный источник, эффективный курс (VWAP − 0.15%)
        if (usdtThbLabel) usdtThbLabel.textContent = 'USDT-THB (Bitazza)';
        const eff = state.rates.bitazza_usdt_thb;
        if (eff) {
            usdtThbEl.textContent = `${eff.toFixed(2)} ฿`;
            usdtThbEl.classList.remove('rate-error');
            if (usdtThbSub) {
                const raw = state.rates.bitazza_raw;
                const feeP = state.rates.bitazza_fee_percent ?? 0.15;
                const feeF = state.rates.bitazza_fee_fixed_thb ?? 20;
                usdtThbSub.textContent = `VWAP ${raw ? raw.toFixed(2) : '—'} · −${feeP}% · −${feeF}฿/сделку`;
                usdtThbSub.style.display = 'block';
            }
        } else if (state.rates.usdt_thb) {
            // Bitazza недоступна — фоллбэк на Binance с пометкой
            usdtThbEl.textContent = `${state.rates.usdt_thb.toFixed(2)} ฿`;
            usdtThbEl.classList.remove('rate-error');
            if (usdtThbLabel) usdtThbLabel.textContent = 'USDT-THB (Binance — фоллбэк)';
        } else {
            usdtThbEl.textContent = '—';
            usdtThbEl.classList.add('rate-error');
        }
        usdtThbEl.style.color = '';
        usdtThbEl.style.fontWeight = '';
    } else if (state.rates.usdt_thb) {
        if (usdtThbLabel) usdtThbLabel.textContent = 'USDT-THB (Binance)';
        usdtThbEl.textContent = `${state.rates.usdt_thb.toFixed(2)} ฿`;
        usdtThbEl.classList.remove('rate-error');
        // Сбрасываем красную подсветку точного курса при обновлении
        usdtThbEl.style.color = '';
        usdtThbEl.style.fontWeight = '';
    } else {
        usdtThbEl.textContent = '—';
        usdtThbEl.classList.add('rate-error');
    }

    // Скрываем метку точного курса при обновлении курсов
    const preciseRateTime = document.getElementById('preciseRateTime');
    if (preciseRateTime) {
        preciseRateTime.style.display = 'none';
    }
    
    // Показываем RUB-USDT
    const rubUsdtEl = document.getElementById('rubUsdtRate');
    if (state.method === 'broker' || state.method === 'custom') {
        if (state.customRubUsdt && state.customRubUsdt > 0) {
            rubUsdtEl.textContent = `${state.customRubUsdt.toFixed(4)} ₽`;
            rubUsdtEl.classList.remove('rate-error');
            const thbForEst = state.method === 'custom' ? state.customUsdtThb : state.rates.usdt_thb;
            if (thbForEst) {
                const estimatedRate = (state.customRubUsdt / thbForEst).toFixed(2);
                estimatedEl.textContent = `~${estimatedRate} ₽/฿`;
                estimatedEl.classList.remove('rate-error', 'rate-info-pending');
            }
        } else {
            rubUsdtEl.textContent = '— ₽';
            rubUsdtEl.classList.add('rate-error');
            estimatedEl.textContent = '—';
            estimatedEl.classList.add('rate-info-pending');
        }
    } else {
        if (state.rates.rub_usdt) {
            rubUsdtEl.textContent = `${state.rates.rub_usdt.toFixed(4)} ₽`;
            rubUsdtEl.classList.remove('rate-error');
        } else {
            rubUsdtEl.textContent = '—';
            rubUsdtEl.classList.add('rate-error');
        }

        if (rubUsdt && state.rates.usdt_thb) {
            const estimatedRate = (rubUsdt / state.rates.usdt_thb).toFixed(2);
            estimatedEl.textContent = `~${estimatedRate} ₽/฿`;
            estimatedEl.classList.remove('rate-error', 'rate-info-pending');
        } else {
            estimatedEl.textContent = '—';
            estimatedEl.classList.add('rate-error');
        }
    }
    
    // Время обновления
    const now = new Date();
    document.getElementById('updateTime').textContent = now.toLocaleTimeString('ru-RU');
}

// Обновление UI полей кастомных курсов (пустое / заполненное)
function updateBrokerRateUI() {
    // RUB-USDT card (первая)
    const rubCard = document.querySelector('#customRateSection .custom-rate-card');
    const rubHint = document.getElementById('customRateHint');
    if (rubCard && rubHint) {
        if (state.customRubUsdt && state.customRubUsdt > 0) {
            rubCard.classList.remove('rate-empty');
            rubCard.classList.add('rate-filled');
            rubHint.classList.add('hidden');
        } else {
            rubCard.classList.add('rate-empty');
            rubCard.classList.remove('rate-filled');
            rubHint.classList.remove('hidden');
        }
    }

    // THB-USDT card (custom)
    const thbCard = document.getElementById('customUsdtThbCard');
    const thbHint = document.getElementById('customUsdtThbHint');
    if (thbCard && thbHint) {
        if (state.customUsdtThb && state.customUsdtThb > 0) {
            thbCard.classList.remove('rate-empty');
            thbCard.classList.add('rate-filled');
            thbHint.classList.add('hidden');
        } else {
            thbCard.classList.add('rate-empty');
            thbCard.classList.remove('rate-filled');
            thbHint.classList.remove('hidden');
        }
    }
}

// Обновление кастомного курса (вызывается при изменении поля)
function updateCustomRate() {
    if (state.method !== 'broker' && state.method !== 'custom') return;

    // RUB-USDT
    const rawRub = document.getElementById('customRubUsdt').value.replace(/\s/g, '');
    const customRubUsdt = parseFloat(rawRub) || 0;
    state.customRubUsdt = customRubUsdt > 0 ? customRubUsdt : null;

    // THB-USDT (только для custom)
    if (state.method === 'custom') {
        const rawThb = document.getElementById('customUsdtThb').value.replace(/\s/g, '');
        const customUsdtThb = parseFloat(rawThb) || 0;
        state.customUsdtThb = customUsdtThb > 0 ? customUsdtThb : null;
    }

    updateBrokerRateUI();

    // Эффективный курс THB-USDT (custom > rates)
    const effThb = state.method === 'custom' ? state.customUsdtThb : state.rates.usdt_thb;

    if (state.customRubUsdt) {
        document.getElementById('rubUsdtRate').textContent = `${customRubUsdt.toFixed(4)} ₽`;
        if (effThb) {
            const estimatedRate = (state.customRubUsdt / effThb).toFixed(2);
            document.getElementById('estimatedRate').textContent = `~${estimatedRate} ₽/฿`;
        }
    } else {
        document.getElementById('rubUsdtRate').textContent = '— ₽';
        document.getElementById('estimatedRate').textContent = '—';
    }

    // Отображение THB-USDT для custom
    if (state.method === 'custom') {
        const usdtThbEl = document.getElementById('usdtThbRate');
        if (state.customUsdtThb) {
            usdtThbEl.textContent = `${state.customUsdtThb.toFixed(4)} ฿`;
            usdtThbEl.classList.remove('rate-error');
        } else {
            usdtThbEl.textContent = '— ฿';
            usdtThbEl.classList.add('rate-error');
        }
    }
}

// Форматирование ввода
function formatInput(input) {
    let value = input.value.replace(/[^\d.]/g, '');
    
    // Разрешаем только одну точку
    const parts = value.split('.');
    if (parts.length > 2) {
        value = parts[0] + '.' + parts.slice(1).join('');
    }
    
    // Форматируем с пробелами (целую часть)
    if (value) {
        const [integer, decimal] = value.split('.');
        const formattedInteger = parseInt(integer || 0).toLocaleString('ru-RU');
        value = decimal !== undefined ? `${formattedInteger}.${decimal}` : formattedInteger;
    }
    
    input.value = value;
}

// Получение числового значения
function getAmount() {
    const input = document.getElementById('amount');
    const value = input.value.replace(/\s/g, '').replace(/,/g, '');
    return parseFloat(value) || 0;
}

// Основная функция расчета
async function calculate() {
    // Защита от race condition: запоминаем версию, проверяем перед отображением
    const thisCalcVersion = ++state._calcVersion;

    const amount = getAmount();
    const resultsSection = document.getElementById('resultsSection');
    const calculateBtn = document.getElementById('calculateBtn');

    if (amount <= 0) {
        resultsSection.style.display = 'none';
        hidePreciseRateStatus();
        hidePreciseRateFallback();
        return;
    }

    // Блокируем расчёт в режиме брокера/кастома без курса RUB-USDT (только для RUB-сценариев)
    if ((state.method === 'broker' || state.method === 'custom') && !state.customRubUsdt && scenarioNeedsRubRate(state.scenario)) {
        const customInput = document.getElementById('customRubUsdt');
        customInput.focus();
        const card = document.querySelector('#customRateSection .custom-rate-card');
        if (card) {
            card.classList.add('rate-empty');
            card.style.animation = 'none';
            card.offsetHeight; // force reflow
            card.style.animation = '';
        }
        return;
    }

    // В режиме custom — обязателен курс THB-USDT для сценариев с THB
    if (state.method === 'custom' && !state.customUsdtThb && scenarioNeedsThbRate(state.scenario)) {
        const customThbInput = document.getElementById('customUsdtThb');
        customThbInput.focus();
        const card = document.getElementById('customUsdtThbCard');
        if (card) {
            card.classList.add('rate-empty');
            card.style.animation = 'none';
            card.offsetHeight;
            card.style.animation = '';
        }
        return;
    }

    // Если сценарий требует точный курс Binance (есть THB) — НЕ показываем быстрый результат.
    // Менеджер не должен увидеть приблизительное число и сообщить его клиенту.
    // Идём сразу на Playwright, результат отрисуется после получения точного курса.
    // _skipNextPrecise=true — мы уже во вторичном вызове из getPreciseRate()/fallback, считаем как обычно.
    if (state.method !== 'custom' && scenarioNeedsPrecise(state.scenario) && !state._skipNextPrecise) {
        resultsSection.style.display = 'none';
        hidePreciseRateFallback();
        showPreciseRateStatus('⏳ Получаем точный курс Binance... (~8 сек)');

        const originalText = calculateBtn.innerHTML;
        calculateBtn.disabled = true;
        calculateBtn.innerHTML = '⏳ Точный курс...';

        try {
            await getPreciseRate();  // сам вызовет calculate() с _skipNextPrecise=true при успехе
        } finally {
            calculateBtn.disabled = false;
            calculateBtn.innerHTML = originalText;
        }
        return;
    }

    const originalText = calculateBtn.innerHTML;
    calculateBtn.disabled = true;

    try {
        // Если курсы устарели (более 1 минуты), обновляем их принудительно перед расчетом
        // Но НЕ обновляем, если точный курс зафиксирован
        if (!state.preciseRateLocked) {
            const timeSinceUpdate = Date.now() - state.lastUpdateTimestamp;
            if (timeSinceUpdate > 60000) {
                console.log('🔄 Курсы устарели, обновляю перед расчетом...');
                calculateBtn.innerHTML = '⏳ ОБНОВЛЕНИЕ КУРСОВ...';
                await refreshRates();
            }
        }
        
        // Проверка наличия курсов перед расчетом
        const rubUsdt = (state.method === 'broker' || state.method === 'custom') ? state.customRubUsdt : state.rates.rub_usdt;
        const usdtThb = state.method === 'custom' ? state.customUsdtThb : state.rates.usdt_thb;
        const needsRub = scenarioNeedsRubRate(state.scenario);
        const needsThb = scenarioNeedsThbRate(state.scenario);
        if ((needsRub && !rubUsdt) || (needsThb && !usdtThb)) {
            showToast('Курсы валют не получены. Расчет невозможен.', 'error');
            return;
        }

        calculateBtn.innerHTML = '⏳ РАСЧЕТ...';

        if (CONFIG.USE_API && (state.method === 'broker' || state.method === 'custom')) {
            // Используем API для расчёта через брокера (custom — тот же путь, но оба курса ручные)
            const requestData = {
                method: 'broker',
                rate_source: state.method === 'custom' ? 'custom' : state.rateSource,
                scenario: state.scenario,
                direction: state.direction,
                amount: amount,
                custom_rub_usdt: state.customRubUsdt,
                // Для custom — ручной THB-USDT, для broker — точный курс с Playwright (если был)
                custom_usdt_thb: state.method === 'custom' ? state.customUsdtThb : state.rates.usdt_thb,
                profit_margin: state.profitMargin
            };
            
            const response = await fetch(`${CONFIG.API_URL}/calculate`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(requestData)
            });
            
            if (response.ok) {
                const result = await response.json();
                if (thisCalcVersion !== state._calcVersion) return;
                displayResult(result);
            } else {
                throw new Error('Calculation API error');
            }

        } else if (CONFIG.USE_API && state.method === 'doverka') {
            // Для Doverka сценарии rub-to-thb и thb-to-rub - это direction amount/target для одного сценария
            let effectiveScenario = state.scenario;
            let effectiveDirection = state.direction;

            if (state.scenario === 'thb-to-rub') {
                effectiveScenario = 'rub-to-thb';
                effectiveDirection = 'target';
            } else if (state.scenario === 'usdt-from-rub') {
                effectiveScenario = 'rub-to-usdt';
                effectiveDirection = 'target';
            }

            const requestData = {
                method: 'doverka',
                rate_source: state.rateSource,
                scenario: effectiveScenario,
                direction: effectiveDirection,
                amount: amount,
                custom_usdt_thb: state.rates.usdt_thb,  // Передаём точный курс если был запрошен
                // Передаем маржу только если включена "скидка" (ручной режим)
                profit_margin: state.applyDiscount ? state.profitMargin : null
            };
            
            console.log('📤 Sending Doverka request:', requestData);
            
            const response = await fetch(`${CONFIG.API_URL}/calculate`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(requestData)
            });
            
            if (response.ok) {
                const result = await response.json();
                if (thisCalcVersion !== state._calcVersion) return;
                displayResult(result);
            } else {
                throw new Error('Calculation API error');
            }

        } else {
            // Локальный расчет (фоллбэк)
            const result = calculateLocal(amount);
            if (thisCalcVersion !== state._calcVersion) return;
            displayResult(result);
        }
        
        if (thisCalcVersion === state._calcVersion) {
            resultsSection.style.display = 'block';
        }

    } catch (error) {
        console.error('Calculation error:', error);
        if (thisCalcVersion !== state._calcVersion) return;
        // Фоллбэк на локальный расчет
        const result = calculateLocal(amount);
        displayResult(result);
        resultsSection.style.display = 'block';
    } finally {
        calculateBtn.disabled = false;
        calculateBtn.innerHTML = originalText;
    }
}

// === Автозапрос точного курса Binance (Playwright) ===
// Точный курс запрашивается автоматически после «Рассчитать»,
// если сценарий требует связку USDT↔THB. Кнопка «🎯 Precise» убрана.

function scenarioNeedsPrecise(scenario) {
    // Точный курс парсится с Binance через Playwright. Если считаем по Bitazza —
    // курс берётся из её стакана по API, дёргать Binance незачем.
    if (state.rateSource === 'bitazza') return false;
    // Playwright нужен только там где есть THB (USDT-THB курс с Binance)
    return scenario !== 'rub-to-usdt' && scenario !== 'usdt-from-rub';
}

let _preciseDebounceTimer = null;
let _preciseAbortController = null;
let _preciseStatusSlowTimer = null;
// Параметры последнего запроса — чтобы fallback-кнопка могла посчитать по-быстрому
let _lastPreciseArgs = null;

function schedulePreciseRefresh() {
    // Debounce 700 ms — если пользователь жмёт «Рассчитать» подряд, ждём последний
    if (_preciseDebounceTimer) clearTimeout(_preciseDebounceTimer);
    _preciseDebounceTimer = setTimeout(() => {
        _preciseDebounceTimer = null;
        getPreciseRate();
    }, 700);
}

function showPreciseRateStatus(text) {
    const box = document.getElementById('preciseRateStatus');
    const txt = document.getElementById('preciseRateStatusText');
    if (box && txt) {
        txt.textContent = text;
        box.style.display = 'block';
    }
}

function hidePreciseRateStatus() {
    const box = document.getElementById('preciseRateStatus');
    if (box) box.style.display = 'none';
    const time = document.getElementById('preciseRateTime');
    if (time) time.style.display = 'none';
}

function showPreciseRateFallback() {
    const btn = document.getElementById('preciseRateFallbackBtn');
    if (btn) btn.style.display = 'block';
}

function hidePreciseRateFallback() {
    const btn = document.getElementById('preciseRateFallbackBtn');
    if (btn) btn.style.display = 'none';
}

// Fallback: Playwright недоступен / очередь перегружена — пользователь согласен на быстрый курс.
// Делаем быстрый расчёт через state.rates.usdt_thb (обновлён при refreshRates).
async function usePreciseRateFallback() {
    hidePreciseRateFallback();
    showPreciseRateStatus('⚡ Используется быстрый курс API (~0.2% погрешность)');
    // Убедиться что быстрый курс в state актуален — refreshRates уже должен был его обновить
    state._skipNextPrecise = true;
    try {
        await calculate();
    } finally {
        state._skipNextPrecise = false;
    }
}

// Флаг активного запроса точного курса — защита от двойного запуска
let isPreciseRateLoading = false;

async function getPreciseRate() {
    const amount = getAmount();
    if (amount <= 0) return;

    // Если сценарий не требует Playwright — ничего не делаем
    if (!scenarioNeedsPrecise(state.scenario)) return;

    // Защита от параллельных запросов — отменяем предыдущий
    if (_preciseAbortController) {
        try { _preciseAbortController.abort(); } catch (_) {}
    }
    _preciseAbortController = new AbortController();

    isPreciseRateLoading = true;
    hidePreciseRateFallback();
    showPreciseRateStatus('⏳ Точный курс Binance... (~8 сек)');

    // Через 10 сек сменить текст на "в очереди"
    if (_preciseStatusSlowTimer) clearTimeout(_preciseStatusSlowTimer);
    _preciseStatusSlowTimer = setTimeout(() => {
        showPreciseRateStatus('⏳ В очереди к Binance-парсеру...');
    }, 10000);

    try {
        const rubUsdt = state.method === 'broker' ? state.customRubUsdt : state.rates.rub_usdt;

        // Маппинг сценария thb-to-rub → rub-to-thb + target (как в calculate())
        let preciseScenario = state.scenario;
        let preciseDirection = state.direction;
        if (state.scenario === 'thb-to-rub') {
            preciseScenario = 'rub-to-thb';
            preciseDirection = 'target';
        } else if (state.scenario === 'usdt-from-rub') {
            preciseScenario = 'rub-to-usdt';
            preciseDirection = 'target';
        }

        const body = {
            scenario: preciseScenario,
            amount: amount,
            direction: preciseDirection,
            method: state.method,
            rub_usdt: rubUsdt,
            profit_margin: state.profitMargin
        };

        const response = await fetch(`${CONFIG.API_URL}/rates/precise`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
            signal: _preciseAbortController.signal
        });

        // Очередь перегружена или Playwright недоступен — показываем fallback
        if (response.status === 503) {
            const errData = await response.json().catch(() => ({}));
            const isQueueTimeout = errData.error === 'queue_timeout';
            showPreciseRateStatus(isQueueTimeout
                ? '⚠️ Binance-парсер перегружен — попробуйте позже'
                : '⚠️ Binance-парсер временно недоступен');
            showPreciseRateFallback();
            return;
        }

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            const errorMsg = errorData.error || `HTTP ${response.status}`;
            throw new Error(errorMsg);
        }

        const result = await response.json();
        if (!result.success) throw new Error(result.error || 'Unknown error');

        console.log('✅ Точный курс получен:', result);

        // Обновляем курс USDT-THB в state и UI
        state.rates.usdt_thb = result.rate_used;
        const usdtThbRateEl = document.getElementById('usdtThbRate');
        if (usdtThbRateEl) {
            usdtThbRateEl.textContent = `${result.rate_used.toFixed(2)} ฿`;
            usdtThbRateEl.style.color = '#ff4444';
            usdtThbRateEl.style.fontWeight = 'bold';
        }

        // Подпись с временем получения точного курса
        const formattedAmount = amount.toLocaleString('ru-RU');
        let currencyLabel = '';
        if (state.scenario === 'rub-to-thb' || state.scenario === 'thb-to-rub') {
            currencyLabel = state.scenario === 'rub-to-thb' ? '₽' : '฿';
        } else if (state.scenario === 'usdt-to-thb' || state.scenario === 'thb-to-usdt') {
            currencyLabel = state.scenario === 'usdt-to-thb' ? 'USDT' : '฿';
        }
        showPreciseRateStatus(`✅ Точный курс для ${formattedAmount} ${currencyLabel} (${result.time} сек)`);

        // Фиксируем точный курс на 5 минут
        lockPreciseRate();

        // Пересчитываем с точным курсом — но без повторного авто-precise (чтобы не зациклить)
        state._skipNextPrecise = true;
        await calculate();
        state._skipNextPrecise = false;

    } catch (error) {
        if (error.name === 'AbortError') {
            console.log('⏹ Precise запрос отменён (пришёл новый)');
            return;
        }
        console.error('❌ Ошибка получения точного курса:', error);
        showPreciseRateStatus('⚠️ Binance-парсер недоступен');
        showPreciseRateFallback();
    } finally {
        if (_preciseStatusSlowTimer) {
            clearTimeout(_preciseStatusSlowTimer);
            _preciseStatusSlowTimer = null;
        }
        isPreciseRateLoading = false;
    }
}

// Локальный расчет (фоллбэк)
function calculateLocal(amount) {
    // В локальном режиме (file://) берем профит из стейта, если включена скидка,
    // иначе определяем его по порогам Doverka (имитируем поведение сервера)
    const isUsdtScenario = ['usdt-to-thb', 'thb-to-usdt'].includes(state.scenario);
    let targetProfit = isUsdtScenario ? 2.0 : 4.0;   // USDT-дефолт 2%, см. toggleDiscount
    if (state.applyDiscount) {
        targetProfit = state.profitMargin;
    } else if (!isUsdtScenario) {
        let baseAmount = amount;
        if (state.scenario === 'thb-to-rub') {
            baseAmount = amount * 2.8;
        }

        if (baseAmount < 500000) targetProfit = 5.0;
        else if (baseAmount < 1000000) targetProfit = 4.0;
        else targetProfit = 3.0;
    }

    // Комиссия в USDT-THB (Doverka использует прогрессивную шкалу, но мы привязываем её к профиту)
    // 5% прибыли -> 2.72% комиссия, 4% -> 1.7%, 3% -> 0.67%
    const commMap = { 5.0: 0.0272, 4.0: 0.017, 3.0: 0.0067 };
    const usdt_thb_comm = commMap[targetProfit] || (targetProfit / 100 * 0.6); // Примерная пропорция

    const rub_usdt_rate = state.rates.rub_usdt;
    const usdt_thb_rate = state.rates.usdt_thb;
    const bonus_pct = 0.024; // 2.4% бонус

    // ПРАВИЛЬНЫЙ расчет для Doverka
    if (state.method === 'doverka' && state.scenario === 'rub-to-thb') {
        // 1. RUB → USDT (без комиссии на этом этапе)
        const usdt_initial = amount / rub_usdt_rate;
        
        // 2. USDT → THB с комиссией
        const usdt_thb_rate_sell = usdt_thb_rate * (1 - usdt_thb_comm);
        const thb_before_fees = usdt_initial * usdt_thb_rate_sell;
        
        // 3. Комиссии за выдачу
        const wdRate = state.rateSource === 'bitazza' ? 0.0015 : 0.0025;
        const withdrawal_percent_fee = thb_before_fees * wdRate;
        const withdrawal_fixed = 20;
        const thbNet = thb_before_fees - withdrawal_percent_fee - withdrawal_fixed;
        
        // 4. Прибыльность
        const bonus_usdt = usdt_initial * bonus_pct;
        const incoming_usdt = usdt_initial + bonus_usdt;
        const outgoing_usdt = (thbNet + withdrawal_fixed + withdrawal_percent_fee) / usdt_thb_rate;
        const profit_usdt = incoming_usdt - outgoing_usdt;

        return {
            scenario: 'RUB → THB',
            direction: 'amount',
            rub_paid: amount,
            thb_received: thbNet,
            final_rate: amount / Math.max(1, thbNet),
            usdt_amount: usdt_initial,
            usdt_thb_rate: usdt_thb_rate,
            usdt_thb_commission: usdt_thb_comm * 100,
            usdt_thb_rate_sell: usdt_thb_rate_sell,
            rub_usdt_rate: rub_usdt_rate,
            withdrawal_percent: withdrawal_percent_fee,
            withdrawal_fixed: withdrawal_fixed,
            bonus_usdt: bonus_usdt,
            incoming_usdt: incoming_usdt,
            outgoing_usdt: outgoing_usdt,
            profit_usdt: profit_usdt,
            profit_percent_actual: targetProfit,
            commission_level: `СБП (${targetProfit}%)`
        };
    }
    
    // Doverka: THB ← RUB (клиент хочет получить конкретную сумму THB)
    if (state.method === 'doverka' && state.scenario === 'thb-to-rub') {
        // 1. Комиссии за выдачу
        const withdrawal_fixed = 20;
        const wdRate2 = state.rateSource === 'bitazza' ? 0.0015 : 0.0025;
        const withdrawal_percent_fee = amount * wdRate2;  // amount - это THB
        
        // 2. THB к обмену
        const thb_to_exchange = amount + withdrawal_fixed + withdrawal_percent_fee;
        
        // 3. USDT
        const usdt_thb_rate_sell = usdt_thb_rate * (1 - usdt_thb_comm);
        const usdt_required = thb_to_exchange / usdt_thb_rate_sell;
        
        // 4. RUB
        const rub_to_pay = usdt_required * rub_usdt_rate;
        
        // 5. Прибыльность
        const bonus_usdt = usdt_required * bonus_pct;
        const incoming_usdt = usdt_required + bonus_usdt;
        const outgoing_usdt = thb_to_exchange / usdt_thb_rate;
        const profit_usdt = incoming_usdt - outgoing_usdt;

        return {
            scenario: 'THB ← RUB',
            direction: 'target',
            thb_target: amount,
            rub_to_pay: rub_to_pay,
            final_rate: rub_to_pay / Math.max(1, amount),
            usdt_amount: usdt_required,
            usdt_thb_rate: usdt_thb_rate,
            usdt_thb_commission: usdt_thb_comm * 100,
            usdt_thb_rate_sell: usdt_thb_rate_sell,
            rub_usdt_rate: rub_usdt_rate,
            withdrawal_percent: withdrawal_percent_fee,
            withdrawal_fixed: withdrawal_fixed,
            bonus_usdt: bonus_usdt,
            incoming_usdt: incoming_usdt,
            outgoing_usdt: outgoing_usdt,
            profit_usdt: profit_usdt,
            profit_percent_actual: targetProfit,
            commission_level: `СБП (${targetProfit}%)`
        };
    }
    
    // Fallback для Broker (если API не отвечает)
    if (state.method === 'broker') {
        const rub_usdt = state.customRubUsdt;
        const usdt_thb = state.rates.usdt_thb;
        const profit = state.profitMargin / 100;
        
        if (state.scenario === 'rub-to-thb') {
            const isTarget = state.direction === 'target';
            if (isTarget) {
                const rub = (amount * rub_usdt) / (usdt_thb * (1 - profit));
                return { scenario: 'RUB → THB', direction: 'target', rub_to_pay: rub, final_rate: rub / amount, usdt_amount: rub / rub_usdt, profit_percent: state.profitMargin };
            } else {
                const thb = (amount / rub_usdt) * usdt_thb * (1 - profit);
                return { scenario: 'RUB → THB', direction: 'amount', thb_received: thb, final_rate: amount / thb, usdt_amount: amount / rub_usdt, profit_percent: state.profitMargin };
            }
        }
    }

    return {
        scenario: state.scenario,
        direction: state.direction,
        thb_received: amount * 0.35,
        final_rate: 2.8,
        usdt_amount: amount / 85,
        profit_percent: 4.0
    };
}

// Применение наценки партнёра (markup) к result: курс ухудшается для клиента
// на markupPct%. Наш profit_usdt НЕ меняется — markup добавляется поверх нашей прибыли.
function applyPartnerMarkup(result) {
    const hasPartner = document.getElementById('hasPartner')?.checked;
    const model = document.querySelector('input[name="partnerModel"]:checked')?.value || 'revshare';
    const markupPct = parseFloat(document.getElementById('partnerPercent')?.value) || 0;
    if (!hasPartner || model !== 'markup' || markupPct <= 0) {
        result.__partner_markup_applied = false;
        return result;
    }

    const m = markupPct / 100;
    const adj = 1 - m;   // множитель для outgoing (клиент получит меньше)
    const inv = 1 + m;   // множитель для incoming (клиент заплатит больше)

    // Сохраняем "исходные" значения для отображения дельты. Если расход фрихолда
    // уже сдвинул курс — базой остаётся курс ДО него, иначе дельта покажет только
    // часть ухудшения
    if (result.__base_final_rate === undefined) result.__base_final_rate = result.final_rate;
    if (typeof result.thb_received === 'number') result.__base_thb_received = result.thb_received;
    if (typeof result.usdt_received === 'number') result.__base_usdt_received = result.usdt_received;
    if (typeof result.rub_to_pay === 'number') result.__base_rub_to_pay = result.rub_to_pay;
    if (typeof result.thb_to_pay === 'number') result.__base_thb_to_pay = result.thb_to_pay;
    if (typeof result.usdt_to_pay === 'number') result.__base_usdt_to_pay = result.usdt_to_pay;

    if (result.direction === 'target') {
        // Клиент должен внести больше на markup%
        if (typeof result.rub_to_pay === 'number') result.rub_to_pay *= inv;
        if (typeof result.rub_amount === 'number' && !('rub_to_pay' in result)) result.rub_amount *= inv;
        if (typeof result.thb_to_pay === 'number') result.thb_to_pay *= inv;
        if (typeof result.usdt_to_pay === 'number') result.usdt_to_pay *= inv;
    } else {
        // Клиент получит меньше на markup%
        if (typeof result.thb_received === 'number') result.thb_received *= adj;
        if (typeof result.usdt_received === 'number') result.usdt_received *= adj;
    }

    // Курс: ухудшается на m% (направление зависит от единицы измерения)
    if (typeof result.final_rate === 'number') {
        const s = result.scenario;
        if (s === 'USDT → THB') {
            // ฿/USDT — клиент получит меньше ฿ за USDT
            result.final_rate *= adj;
        } else {
            // ₽/฿, ₽/USDT, ฿/USDT (для THB→USDT — больше ฿ за USDT) — курс растёт
            result.final_rate *= inv;
        }
    }

    result.__partner_markup_applied = true;
    result.__partner_markup_pct = markupPct;
    return result;
}

// Расход на перевод застройщику (фрихолд): комиссия % + фикс $ в USD.
// Это наша себестоимость, поэтому она закладывается в курс, а не съедает прибыль:
// иначе выбранная «желаемая прибыль» была бы враньём.
//
// Комиссия начисляется НА СУММУ ПЛАТЕЖА и добавляется сверху (правка 10.08,
// сверено с реальным траншем по сделкам Радимира), поэтому «вношу» и «хочу
// получить» считаются по-разному:
//   • вношу S       → до застройщика дойдёт  X = (S − F) / (1+p)
//   • хочу X дойдёт → отправить придётся     S = X·(1+p) + F
// Раньше здесь стоял gross-up (X + F)/(1−p) — он брал процент с самой отправки
// и завышал её на p·комиссию.
function applyPropertyFee(result) {
    result.__prop_fee_applied = false;
    if (state.dealCategory !== 'property_freehold') return result;

    const pct = parseFloat(document.getElementById('propFeePercent')?.value) || 0;
    const fixed = parseFloat(document.getElementById('propFeeFixed')?.value) || 0;
    if (pct <= 0 && fixed <= 0) return result;
    const p = pct / 100;

    const s = result.scenario;
    // Расход задан в USD — для THB-сценариев переводим его через курс USDT/THB
    const outIsThb = (s === 'RUB → THB' || s === 'THB ← RUB' || s === 'USDT → THB');
    const usdtThb = result.usdt_thb_rate || state.rates.usdt_thb || 0;
    if (outIsThb && !usdtThb) return result;   // без курса пересчитать нечем

    // Курс USDT→THB считается как out/in, остальные — как in/out: направление,
    // в которое «ухудшение» двигает число, у них противоположное
    const rateIsOutPerIn = (s === 'USDT → THB');
    // Курс до расхода — для строки «курс без расхода». Базу партнёрского markup
    // не трогаем: у него своя точка отсчёта
    result.__prop_rate_before = result.final_rate;

    if (result.direction === 'target') {
        // Клиент хочет, чтобы застройщик получил X — отправить надо X·(1+p) + F,
        // значит клиент вносит больше в той же пропорции
        const target = getAmount();
        if (!target) return result;
        const targetUsdt = outIsThb ? target / usdtThb : target;
        const sendUsdt = targetUsdt * (1 + p) + fixed;
        if (!(sendUsdt > 0)) return result;
        const feeUsdt = sendUsdt - targetUsdt;
        const k = sendUsdt / targetUsdt;
        if (!isFinite(k) || k <= 0) return result;

        ['rub_to_pay', 'thb_to_pay', 'usdt_to_pay', 'rub_amount'].forEach(f => {
            if (typeof result[f] === 'number') result[f] *= k;
        });
        if (typeof result.final_rate === 'number') {
            result.final_rate = rateIsOutPerIn ? result.final_rate / k : result.final_rate * k;
        }
        result.__prop_send_usdt = sendUsdt;
        result.__prop_arrive_usdt = targetUsdt;
        result.__prop_fee_usdt = feeUsdt;
    } else {
        // Клиент вносит сумму — она и есть отправляемая, комиссия сидит внутри неё
        const outField = ['usdt_received', 'thb_received', 'usdt_amount']
            .find(f => typeof result[f] === 'number' && result[f] > 0);
        if (!outField) return result;
        const out = result[outField];
        const sendUsdt = outIsThb ? out / usdtThb : out;
        const arriveUsdt = (sendUsdt - fixed) / (1 + p);
        if (!(arriveUsdt > 0)) return result;   // расход съел всю сумму — не калечим расчёт
        const k = arriveUsdt / sendUsdt;

        result[outField] = out * k;
        if (typeof result.final_rate === 'number') {
            result.final_rate = rateIsOutPerIn ? result.final_rate * k : result.final_rate / k;
        }
        result.__prop_send_usdt = sendUsdt;
        result.__prop_arrive_usdt = arriveUsdt;
        result.__prop_fee_usdt = sendUsdt - arriveUsdt;
    }

    result.__prop_fee_applied = true;
    result.__prop_fee_pct = pct;
    result.__prop_fee_fixed = fixed;
    return result;
}

// Отображение результата
function displayResult(result) {
    // Применяем markup партнёра (если включено) — курс реально меняется
    applyPartnerMarkup(result);
    // Расход на перевод — последним: комиссия банка снимается с суммы, которая
    // реально уходит, а она уже уменьшена на наценку партнёра
    applyPropertyFee(result);

    // Сохраняем результат в state для дальнейшего использования (например, создания платежа)
    state.lastResult = result;
    
    // Показываем/скрываем секцию создания платежа (только для Doverka)
    const paymentSection = document.getElementById('paymentActionSection');
    if (state.method === 'doverka') {
        paymentSection.style.display = 'block';
        // Сбрасываем старый результат платежа при новом расчете
        document.getElementById('paymentResult').style.display = 'none';
    } else {
        paymentSection.style.display = 'none';
    }

    // Кнопка "Создать сделку в CRM" — всегда видна после расчёта
    const dealSection = document.getElementById('createDealSection');
    if (dealSection) dealSection.style.display = 'block';

    // Определяем что показывать (ПОРЯДОК ВАЖЕН!)
    let resultValue = '';
    let rateValue = '';
    let rateCurrency = '';
    
    // ВАЖНО: сначала проверяем direction, чтобы понять, показываем мы "получит" или "должен внести"
    const isTarget = result.direction === 'target';
    
    if (result.scenario === 'USDT → THB') {
        if (isTarget) {
            // Хочу получить конкретную сумму THB → плачу USDT
            resultValue = `${formatNumber(result.usdt_to_pay || result.usdt_amount)} USDT`;
            rateValue = result.final_rate.toFixed(6);
            rateCurrency = '฿/USDT';
        } else {
            // Вношу USDT → получаю THB
            resultValue = `${formatNumber(result.thb_received)} ฿`;
            rateValue = result.final_rate.toFixed(6);
            rateCurrency = '฿/USDT';
        }
    } else if (result.scenario === 'THB → USDT') {
        if (isTarget) {
            // Хочу получить USDT → плачу THB
            resultValue = `${formatNumber(result.thb_to_pay || result.thb_amount)} ฿`;
            rateValue = result.final_rate.toFixed(6);
            rateCurrency = '฿/USDT';
        } else {
            // Вношу THB → получаю USDT
            resultValue = `${formatNumber(result.usdt_received)} USDT`;
            rateValue = result.final_rate.toFixed(6);
            rateCurrency = '฿/USDT';
        }
    } else if (result.scenario === 'RUB → THB' || result.scenario === 'THB ← RUB') {
        if (isTarget) {
            // Хочу получить THB → плачу RUB
            resultValue = `${formatNumber(result.rub_to_pay || result.rub_amount)} ₽`;
            rateValue = result.final_rate.toFixed(6);
            rateCurrency = '₽/฿';
        } else {
            // Вношу RUB → получаю THB
            resultValue = `${formatNumber(result.thb_received)} ฿`;
            rateValue = result.final_rate.toFixed(6);
            rateCurrency = '₽/฿';
        }
    } else if (result.scenario === 'RUB → USDT') {
        if (isTarget) {
            // Хочу получить USDT → плачу RUB
            resultValue = `${formatNumber(result.rub_to_pay || result.rub_amount)} ₽`;
            rateValue = result.final_rate.toFixed(6);
            rateCurrency = '₽/USDT';
        } else {
            // Вношу RUB → получаю USDT
            resultValue = `${formatNumber(result.usdt_received || result.usdt_amount)} USDT`;
            rateValue = result.final_rate.toFixed(6);
            rateCurrency = '₽/USDT';
        }
    } else {
        // Запасной вариант если сценарий не распознан
        if (result.rub_to_pay) resultValue = `${formatNumber(result.rub_to_pay)} ₽`;
        else if (result.thb_received) resultValue = `${formatNumber(result.thb_received)} ฿`;
        else if (result.usdt_received) resultValue = `${formatNumber(result.usdt_received)} USDT`;
        else resultValue = 'N/A';
        
        rateValue = result.final_rate ? result.final_rate.toFixed(4) : '0';
        rateCurrency = '';
    }
    
    // При фрихолде итог — это то, что дойдёт до застройщика, а не «клиент получит»:
    // разница как раз и есть предмет вопроса «а сколько реально уйдёт»
    const resLabel = document.getElementById('resultLabel');
    if (resLabel) {
        if (result.__prop_fee_applied && result.direction !== 'target') {
            resLabel.textContent = 'Дойдёт застройщику:';
        } else if (resLabel.textContent === 'Дойдёт застройщику:') {
            resLabel.textContent = 'Клиент получит:';
        }
    }

    document.getElementById('resultValue').textContent = resultValue;
    document.getElementById('finalRate').textContent = rateValue;
    document.getElementById('rateCurrency').textContent = rateCurrency;

    // Показываем процент прибыли
    const profitEl = document.getElementById('resultProfit');
    const profitPct = result.profit_percent_actual || result.profit_percent || 0;
    if (profitPct > 0) {
        const profitClass = profitPct >= 5 ? 'profit-high' : profitPct >= 4 ? 'profit-medium' : 'profit-low';
        profitEl.className = `result-profit ${profitClass}`;
        profitEl.textContent = `Прибыль: ${profitPct.toFixed(2)}%`;
        if (result.profit_usdt !== undefined) {
            profitEl.textContent += ` (${formatNumber(result.profit_usdt)} USDT)`;
        }
        profitEl.style.display = '';
    } else {
        profitEl.style.display = 'none';
    }

    // Блок для копирования клиенту
    const copyBlock = document.getElementById('clientCopyBlock');
    const copyText = document.getElementById('clientCopyText');

    let inputAmount = getAmount();
    let inputCurrency = document.getElementById('inputCurrency').textContent;
    let outputAmount = resultValue;

    // Форматирование без лишних .00 для копирования клиенту
    const fmtClean = (n) => { const s = n % 1 === 0 ? n.toFixed(0) : n.toFixed(2); return s.replace(/\B(?=(\d{3})+(?!\d))/g, ' '); };
    const cleanOutput = outputAmount.replace(/\.00(?=\s)/, '').replace(/\.00$/, '');

    // Определяем текст для клиента
    let clientMsg;
    if (isTarget) {
        clientMsg = `Отдаёте: ${cleanOutput}\nПолучаете: ${fmtClean(inputAmount)} ${inputCurrency}\nКурс: ${rateValue} ${rateCurrency}`;
    } else {
        clientMsg = result.__prop_fee_applied
            ? `Отдаёте: ${fmtClean(inputAmount)} ${inputCurrency}\nЗастройщик получит: ${cleanOutput}\nКурс: ${rateValue} ${rateCurrency}`
            : `Отдаёте: ${fmtClean(inputAmount)} ${inputCurrency}\nПолучаете: ${cleanOutput}\nКурс: ${rateValue} ${rateCurrency}`;
    }

    copyText.textContent = clientMsg;
    copyBlock.style.display = '';

    // Генерируем детальные шаги расчета
    displayDetailedSteps(result);
}

// Отображение детальных шагов расчета
function displayDetailedSteps(result) {
    const detailsContent = document.getElementById('detailsContent');
    let html = '';
    
    // Индикатор уровня комиссий вверху (для Broker и Doverka)
    const levelName = result.commission_level || result.level || '-';
    const profitPercent = result.profit_percent || result.profit_percent_actual || 0;
    
    if (levelName !== '-') {
        const levelClass = profitPercent >= 5 ? 'level-high' : profitPercent >= 4 ? 'level-medium' : 'level-low';
        html += `<div class="commission-indicator ${levelClass}">`;
        html += `<span class="indicator-icon">📊</span>`;
        html += `<div class="indicator-content">`;
        html += `<div class="indicator-title">${levelName}</div>`;
        html += `<div class="indicator-subtitle">% прибыли: ${profitPercent.toFixed(2)}%</div>`;
        html += `</div>`;
        html += `</div>`;
    }
    
    // Базовая информация
    html += `<div class="detail-section">`;
    html += `<h4>📋 Основная информация</h4>`;
    html += `<div class="detail-row"><span class="detail-label">Сценарий:</span><span class="detail-value">${result.scenario || '-'}</span></div>`;
    if (result.operation_name) {
        html += `<div class="detail-row"><span class="detail-label">Операция:</span><span class="detail-value">${result.operation_name}</span></div>`;
    }
    html += `<div class="detail-row"><span class="detail-label">Направление:</span><span class="detail-value">${result.direction === 'target' ? 'Целевая сумма' : 'Вносимая сумма'}</span></div>`;
    html += `</div>`;
    
    // Полная таблица данных (как в CSV)
    html += `<div class="detail-section full-table">`;
    html += `<h4>📊 Полные данные расчета</h4>`;
    
    // Сумма RUB
    if (result.rub_paid !== undefined) {
        html += `<div class="detail-row"><span class="detail-label">Сумма RUB, вносимая клиентом:</span><span class="detail-value highlight">${formatNumber(result.rub_paid)} ₽</span></div>`;
    } else if (result.rub_to_pay !== undefined) {
        html += `<div class="detail-row"><span class="detail-label">Сумма RUB, вносимая клиентом:</span><span class="detail-value highlight">${formatNumber(result.rub_to_pay)} ₽</span></div>`;
    }

    // Курс RUB-USDT
    if (result.rub_usdt_rate !== undefined) {
        html += `<div class="detail-row"><span class="detail-label">Курс брокера RUB-USDT:</span><span class="detail-value">${result.rub_usdt_rate.toFixed(4)} ₽</span></div>`;
    }
    
    // Комиссия RUB-USDT
    if (result.rub_usdt_commission !== undefined) {
        html += `<div class="detail-row"><span class="detail-label">Комиссия на этапе RUB-USDT:</span><span class="detail-value">${result.rub_usdt_commission.toFixed(2)}%</span></div>`;
    }

    // Курс продажи RUB-USDT (базовый курс + комиссия)
    if (result.rub_usdt_rate_sell !== undefined) {
        html += `<div class="detail-row"><span class="detail-label">Курс продажи RUB-USDT:</span><span class="detail-value highlight">${result.rub_usdt_rate_sell.toFixed(4)} ₽</span></div>`;
        html += `<div class="detail-row detail-hint"><span class="detail-label" style="font-size:0.8rem;color:#888;">= базовый курс + ${result.rub_usdt_commission !== undefined ? result.rub_usdt_commission.toFixed(2) + '% комиссия' : 'комиссия'}</span></div>`;
    }

    // Сумма USDT
    if (result.usdt_amount !== undefined) {
        html += `<div class="detail-row"><span class="detail-label">Сумма USDT:</span><span class="detail-value highlight">${formatNumber(result.usdt_amount)} USDT</span></div>`;
    }

    // Курс брокера USDT-THB (Binance)
    if (result.usdt_thb_rate !== undefined) {
        html += `<div class="detail-row"><span class="detail-label">Курс брокера USDT-THB (Binance):</span><span class="detail-value">${result.usdt_thb_rate.toFixed(2)} ฿</span></div>`;
    }
    
    // Комиссия USDT-THB
    if (result.usdt_thb_commission !== undefined) {
        const commVal = result.usdt_thb_commission;
        const commClass = commVal < 0 ? 'profit-value' : ''; // Зеленый если отрицательная (скидка)
        html += `<div class="detail-row"><span class="detail-label">Комиссия на этапе USDT-THB:</span><span class="detail-value ${commClass}">${commVal.toFixed(2)}%</span></div>`;
    }
    
    // Курс продажи USDT-THB
    if (result.usdt_thb_rate_sell !== undefined) {
        html += `<div class="detail-row"><span class="detail-label">Курс продажи USDT-THB:</span><span class="detail-value highlight">${result.usdt_thb_rate_sell.toFixed(4)} ฿</span></div>`;
    }

    // Сумма THB к обмену
    if (result.thb_to_exchange !== undefined) {
        html += `<div class="detail-row"><span class="detail-label">Сумма THB к обмену за USDT:</span><span class="detail-value">${formatNumber(result.thb_to_exchange)} ฿</span></div>`;
    }

    // Комиссии за выдачу
    if (result.withdrawal_percent !== undefined) {
        const wdPct = (result.withdrawal_percent_rate !== undefined ? result.withdrawal_percent_rate : 0.25)
            .toString().replace('.', ',');
        html += `<div class="detail-row"><span class="detail-label">Комиссия за выдачу (${wdPct}%):</span><span class="detail-value">${formatNumber(result.withdrawal_percent)} ฿</span></div>`;
    }
    if (result.withdrawal_fixed !== undefined) {
        const isUsdtScenario = result.scenario === 'RUB → USDT';
        const wdLabel = isUsdtScenario ? 'Комиссия за выдачу (фикс 1 USDT):' : 'Комиссия за выдачу (фикс 20 THB):';
        const wdCurrency = isUsdtScenario ? ' USDT' : ' ฿';
        html += `<div class="detail-row"><span class="detail-label">${wdLabel}</span><span class="detail-value">${result.withdrawal_fixed}${wdCurrency}</span></div>`;
    }
    
    // Итоговая сумма THB
    if (result.thb_received !== undefined) {
        html += `<div class="detail-row"><span class="detail-label">Сумма THB к выдаче:</span><span class="detail-value highlight-final">${formatNumber(result.thb_received)} ฿</span></div>`;
    } else if (result.thb_target !== undefined) {
        html += `<div class="detail-row"><span class="detail-label">Сумма THB к выдаче:</span><span class="detail-value highlight-final">${formatNumber(result.thb_target)} ฿</span></div>`;
    }
    
    // Итоговый курс для клиента (с учётом всех комиссий и withdrawal)
    let finalRateLabel = 'Итоговый курс RUB-THB:';
    if (result.scenario === 'USDT → THB') finalRateLabel = 'Итоговый курс USDT-THB:';
    else if (result.scenario === 'THB → USDT') finalRateLabel = 'Итоговый курс THB-USDT:';
    else if (result.scenario === 'RUB → USDT') finalRateLabel = 'Итоговый курс RUB-USDT:';
    
    html += `<div class="detail-row"><span class="detail-label">${finalRateLabel}</span><span class="detail-value highlight-final">${result.final_rate.toFixed(4)}</span></div>`;
    html += `<div class="detail-row detail-hint"><span class="detail-label" style="font-size:0.8rem;color:#888;">= курс продажи + withdrawal fee (размазан по сумме)</span></div>`;
    
    html += `</div>`;
    
    // Прибыльность (если есть данные)
    if (result.profit_usdt !== undefined) {
        html += `<div class="detail-section profitability-section">`;
        html += `<h4>💰 Прибыльность</h4>`;
        
        // Бонус 2.4% (для Доверки)
        if (result.bonus_usdt !== undefined && state.method === 'doverka') {
            html += `<div class="detail-row"><span class="detail-label">2,4% - бонусное начисление:</span><span class="detail-value">${formatNumber(result.bonus_usdt)} USDT</span></div>`;
        }
        if (result.incoming_usdt !== undefined) {
            html += `<div class="detail-row"><span class="detail-label">Поступление:</span><span class="detail-value highlight">${formatNumber(result.incoming_usdt)} USDT</span></div>`;
        }
        if (result.outgoing_usdt !== undefined) {
            html += `<div class="detail-row"><span class="detail-label">Выплата:</span><span class="detail-value">${formatNumber(result.outgoing_usdt)} USDT</span></div>`;
        }
        if (result.profit_usdt !== undefined) {
            html += `<div class="detail-row"><span class="detail-label">Прибыль:</span><span class="detail-value profit-value">${formatNumber(result.profit_usdt)} USDT</span></div>`;
        }
        if (result.profit_percent_actual !== undefined || result.profit_percent !== undefined) {
            const p = result.profit_percent_actual || result.profit_percent;
            html += `<div class="detail-row"><span class="detail-label">% прибыли:</span><span class="detail-value">${p.toFixed(2)}%</span></div>`;
        }
        
        // Расход на перевод застройщику — показываем явно, иначе видно только
        // ухудшившийся курс и непонятно, откуда он взялся
        if (result.__prop_fee_applied) {
            html += `<div class="detail-row"><span class="detail-label">🏠 Комиссия за перевод:</span><span class="detail-value">${result.__prop_fee_pct.toFixed(2)}% + $${result.__prop_fee_fixed}</span></div>`;
            html += `<div class="detail-row"><span class="detail-label">Отправляем:</span><span class="detail-value">${formatNumber(result.__prop_send_usdt)} USDT</span></div>`;
            html += `<div class="detail-row"><span class="detail-label">Съест перевод:</span><span class="detail-value">−${formatNumber(result.__prop_fee_usdt)} USDT</span></div>`;
            html += `<div class="detail-row"><span class="detail-label">Дойдёт застройщику:</span><span class="detail-value highlight-final">${formatNumber(result.__prop_arrive_usdt)} USDT</span></div>`;
            if (typeof result.__prop_rate_before === 'number') {
                html += `<div class="detail-row"><span class="detail-label">Курс без комиссии перевода:</span><span class="detail-value">${result.__prop_rate_before.toFixed(6)}</span></div>`;
            }
        }

        // Расчет партнера (на клиенте)
        const hasPartner = document.getElementById('hasPartner');
        if (hasPartner && hasPartner.checked && result.profit_usdt !== undefined) {
            const partnerPercentEl = document.getElementById('partnerPercent');
            const partnerPercent = partnerPercentEl ? (parseFloat(partnerPercentEl.value) || 0) : 0;
            const partnerModel = (document.querySelector('input[name="partnerModel"]:checked')?.value) || 'revshare';

            html += `<div class="detail-row partner-row"><span class="detail-label">Модель партнера:</span><span class="detail-value">${partnerModel === 'markup' ? 'Markup +' + partnerPercent.toFixed(2) + '% к курсу' : 'Revshare ' + partnerPercent.toFixed(2) + '% от прибыли'}</span></div>`;

            if (partnerModel === 'markup' && result.__partner_markup_applied) {
                // Markup: курс реально ухудшен, наша прибыль не меняется,
                // partner reward = (то, что клиент заплатил больше / получил меньше) в USDT
                const volume = Math.max(result.incoming_usdt || 0, result.outgoing_usdt || 0, 0);
                const partnerPayout = volume * (partnerPercent / 100);
                const baseRate = result.__base_final_rate;
                const newRate = result.final_rate;
                if (typeof baseRate === 'number' && typeof newRate === 'number') {
                    html += `<div class="detail-row partner-row"><span class="detail-label">Базовый курс:</span><span class="detail-value">${baseRate.toFixed(6)}</span></div>`;
                    html += `<div class="detail-row partner-row"><span class="detail-label">Курс клиенту (с наценкой):</span><span class="detail-value partner-payout">${newRate.toFixed(6)}</span></div>`;
                }
                html += `<div class="detail-row partner-row"><span class="detail-label">Выплата партнеру:</span><span class="detail-value partner-payout">${formatNumber(partnerPayout)} USDT</span></div>`;
                html += `<div class="detail-row partner-row"><span class="detail-label">Наша прибыль (без изменения):</span><span class="detail-value highlight-final">${formatNumber(result.profit_usdt)} USDT</span></div>`;
            } else {
                // Revshare: делим нашу прибыль
                const partnerPayout = (result.profit_usdt * partnerPercent / 100);
                const netProfit = result.profit_usdt - partnerPayout;
                html += `<div class="detail-row partner-row"><span class="detail-label">Выплата партнеру:</span><span class="detail-value partner-payout">${formatNumber(partnerPayout)} USDT</span></div>`;
                html += `<div class="detail-row partner-row"><span class="detail-label">Чистая прибыль:</span><span class="detail-value highlight-final">${formatNumber(netProfit)} USDT</span></div>`;
            }
        }
        
        html += `</div>`;
    }
    
    detailsContent.innerHTML = html;
}

// Форматирование чисел
function formatNumber(num) {
    return num.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
}

// Переключение деталей
function toggleDetails() {
    state.detailsOpen = !state.detailsOpen;
    const content = document.getElementById('detailsContent');
    const icon = document.getElementById('toggleIcon');
    
    if (state.detailsOpen) {
        content.classList.add('open');
        icon.classList.add('rotated');
    } else {
        content.classList.remove('open');
        icon.classList.remove('rotated');
    }
}

// Переключение информации
function toggleInfo() {
    state.infoOpen = !state.infoOpen;
    const content = document.getElementById('infoContent');
    const icon = document.getElementById('infoToggleIcon');
    
    if (state.infoOpen) {
        content.classList.add('open');
        icon.classList.add('rotated');
    } else {
        content.classList.remove('open');
        icon.classList.remove('rotated');
    }
}

// Переключение партнера
function togglePartner() {
    const hasPartner = document.getElementById('hasPartner').checked;
    const wrapper = document.getElementById('partnerPercentWrapper');

    if (hasPartner) {
        wrapper.style.display = 'block';
    } else {
        wrapper.style.display = 'none';
    }

    hideResults();
}

// Переключение модели партнёра (revshare/markup)
function onPartnerModelChange() {
    const model = document.querySelector('input[name="partnerModel"]:checked')?.value || 'revshare';
    const lbl = document.getElementById('partnerPercentLabel');
    const inp = document.getElementById('partnerPercent');
    if (model === 'markup') {
        if (lbl) lbl.textContent = '➕ % к курсу клиента (markup)';
        if (inp && (parseFloat(inp.value) || 0) >= 5) inp.value = '0.2';
    } else {
        if (lbl) lbl.textContent = '🤝 % партнера (от прибыли)';
        if (inp && (parseFloat(inp.value) || 0) < 1) inp.value = '50';
    }
    hideResults();
}

// Функция создания платежа через API Doverka
function _buildPaymentPayload(provider) {
    const rubAmount = state.lastResult.rub_paid || state.lastResult.rub_to_pay || 0;
    const thbAmount = state.lastResult.thb_received || state.lastResult.thb_target || 0;
    const profitUsdt = state.lastResult.profit_usdt || 0;
    const comment = document.getElementById('paymentComment').value.trim();
    const orderId = `GR-${Date.now()}`;
    const description = `Обмен ${formatNumber(rubAmount)} RUB на ${formatNumber(thbAmount)} THB`;

    return {
        "provider": provider,
        "amount": parseFloat(rubAmount.toFixed(2)),
        "currency": "RUB",
        "order_id": orderId,
        "merchant_id": "grusha",
        "description": description,
        "success_url": "",
        "cancel_url": "",
        "failure_url": "",
        "metadata": {
            "rub_amount": rubAmount,
            "thb_amount": thbAmount,
            "order_id": orderId,
            "profit_usdt": profitUsdt,
            "comment": comment
        },
        "merchant_image_url": "https://i.ibb.co/h1RX3TTv/2026-01-20-19-39-50.jpg",
        "merchant_description": "grusha exchange"
    };
}

function _showPaymentLink(publicLink, sbpLink) {
    const resultDiv = document.getElementById('paymentResult');
    const linkA = document.getElementById('paymentLink');
    linkA.href = publicLink;
    linkA.innerText = publicLink;
    // Прямая ссылка СБП есть только у сберовского рельса — показываем, когда пришла
    const sbpBox = document.getElementById('sbpLinkBox');
    const sbpA = document.getElementById('sbpLink');
    if (sbpBox && sbpA) {
        if (sbpLink) {
            sbpA.href = sbpLink;
            sbpA.innerText = sbpLink;
            sbpBox.style.display = 'flex';
        } else {
            sbpBox.style.display = 'none';
        }
    }
    resultDiv.style.display = 'block';
    resultDiv.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function copySbpLink() {
    const link = document.getElementById('sbpLink').innerText;
    if (!link) return;
    navigator.clipboard.writeText(link).then(() => showToast('Ссылка СБП скопирована!', 'success'));
}

async function _sendPayment(provider) {
    const response = await fetch('/api/proxy/create-payment', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(_buildPaymentPayload(provider))
    });
    const data = await response.json().catch(() => ({}));
    return { ok: response.ok, status: response.status, data };
}

async function createPayment() {
    if (!state.lastResult || !state.lastResult.usdt_amount) {
        showToast('Сначала выполните расчет суммы', 'warning');
        return;
    }

    const createBtn = document.getElementById('createPaymentBtn');
    const originalText = createBtn.innerText;
    createBtn.disabled = true;
    createBtn.innerText = '⏳ СОЗДАНИЕ...';

    try {
        // Шаг 1: пробуем grushab-2-b.ru
        const result = await _sendPayment('grusha');

        if (result.ok && result.data.public_link) {
            _showPaymentLink(result.data.public_link, result.data.sbp_link);
            return;
        }

        // Шаг 2: страница Grusha Exchange не отвечает. Фоллбэка на Доверку нет —
        // клиент должен видеть только нашу страницу, чужой мерчант ему не уходит.
        if (result.data.grusha_down) {
            throw new Error(
                'Страница оплаты Grusha Exchange не отвечает. Ссылку сейчас не создать — ' +
                'сообщи Кариму и предложи клиенту другой способ оплаты.'
            );
        }

        // Другая ошибка
        if (result.status === 401) {
            throw new Error('Сессия истекла. Перезайдите: ' + window.location.origin + '/login');
        }
        throw new Error(result.data.message || result.data.error || `Ошибка API (${result.status})`);

    } catch (error) {
        console.error('Payment creation error:', error);
        showToast('Ошибка при создании платежа: ' + error.message, 'error', 5000);
    } finally {
        createBtn.disabled = false;
        createBtn.innerText = originalText;
    }
}

// Функция для копирования ссылки в буфер обмена
// Копирование сообщения для клиента
function copyClientMessage() {
    const text = document.getElementById('clientCopyText').textContent;
    if (!text) return;

    navigator.clipboard.writeText(text).then(() => {
        const btn = document.getElementById('copyClientBtn');
        const original = btn.innerHTML;
        btn.innerHTML = '✅ Скопировано!';
        btn.style.background = '#059669';
        setTimeout(() => { btn.innerHTML = original; btn.style.background = '#4F46E5'; }, 2000);
    }).catch(() => {
        const ta = document.createElement('textarea');
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
    });
}

function copyPaymentLink() {
    const link = document.getElementById('paymentLink').innerText;
    if (!link) return;

    navigator.clipboard.writeText(link).then(() => {
        const copyBtn = event.currentTarget;
        const originalText = copyBtn.innerHTML;
        copyBtn.innerHTML = '✅ Скопировано!';
        copyBtn.style.background = '#059669';
        
        setTimeout(() => {
            copyBtn.innerHTML = originalText;
            copyBtn.style.background = '#10B981';
        }, 2000);
    }).catch(err => {
        console.error('Failed to copy:', err);
        // Fallback для старых браузеров
        const input = document.createElement('input');
        input.value = link;
        document.body.appendChild(input);
        input.select();
        document.execCommand('copy');
        document.body.removeChild(input);
        showToast('Ссылка скопирована!', 'success');
    });
}

// === Фиксация точного курса на 5 минут ===
const PRECISE_RATE_LOCK_MS = 5 * 60 * 1000; // 5 минут

function lockPreciseRate() {
    state.preciseRateLocked = true;
    state.preciseRateTimestamp = Date.now();

    // Очищаем предыдущий таймер если был
    if (state.preciseRateTimer) {
        clearInterval(state.preciseRateTimer);
    }

    // Показываем индикатор фиксации
    showPreciseRateLockIndicator();

    // Обратный отсчёт каждую секунду
    state.preciseRateTimer = setInterval(() => {
        const elapsed = Date.now() - state.preciseRateTimestamp;
        const remaining = PRECISE_RATE_LOCK_MS - elapsed;

        if (remaining <= 0) {
            unlockPreciseRate();
        } else {
            updatePreciseRateCountdown(remaining);
        }
    }, 1000);
}

function unlockPreciseRate() {
    state.preciseRateLocked = false;
    state.preciseRateTimestamp = 0;

    if (state.preciseRateTimer) {
        clearInterval(state.preciseRateTimer);
        state.preciseRateTimer = null;
    }

    // Убираем индикатор
    hidePreciseRateLockIndicator();

    // Сбрасываем подсветку точного курса
    const usdtThbRateEl = document.getElementById('usdtThbRate');
    usdtThbRateEl.style.color = '';
    usdtThbRateEl.style.fontWeight = '';

    const preciseRateTime = document.getElementById('preciseRateTime');
    if (preciseRateTime) preciseRateTime.style.display = 'none';

    // Обновляем курсы
    console.log('🔓 Точный курс разблокирован, обновляю курсы...');
    refreshRates();
}

function showPreciseRateLockIndicator() {
    let indicator = document.getElementById('preciseRateLockIndicator');
    if (!indicator) {
        indicator = document.createElement('div');
        indicator.id = 'preciseRateLockIndicator';
        indicator.style.cssText = 'background: linear-gradient(135deg, #fef3c7, #fde68a); border: 1px solid #f59e0b; border-radius: 8px; padding: 8px 16px; margin-top: 8px; display: flex; align-items: center; justify-content: space-between; font-size: 0.9rem; color: #92400e;';
        const ratesCard = document.getElementById('ratesCard');
        ratesCard.appendChild(indicator);
    }
    indicator.style.display = 'flex';
    updatePreciseRateCountdown(PRECISE_RATE_LOCK_MS);
}

function hidePreciseRateLockIndicator() {
    const indicator = document.getElementById('preciseRateLockIndicator');
    if (indicator) indicator.style.display = 'none';
}

function updatePreciseRateCountdown(remainingMs) {
    const indicator = document.getElementById('preciseRateLockIndicator');
    if (!indicator) return;

    const minutes = Math.floor(remainingMs / 60000);
    const seconds = Math.floor((remainingMs % 60000) / 1000);
    const timeStr = `${minutes}:${seconds.toString().padStart(2, '0')}`;

    indicator.innerHTML = `
        <span>🔒 Точный курс зафиксирован <strong>(${timeStr})</strong></span>
        <button onclick="unlockPreciseRate()" style="background: #f59e0b; color: white; border: none; border-radius: 6px; padding: 4px 12px; cursor: pointer; font-size: 0.85rem; font-weight: 600;">Разблокировать</button>
    `;
}

// === Кнопка "Создать сделку в CRM" ===
function createDealFromCalc() {
    if (!state.lastResult) {
        showToast('Сначала выполните расчёт', 'warning');
        return;
    }

    const r = state.lastResult;
    const comment = document.getElementById('paymentComment')?.value?.trim() || '';

    // Маппинг данных калькулятора → поля CRM
    const dealData = {
        payin_amount_rub: r.rub_paid || r.rub_to_pay || null,
        payin_amount_usdt: r.incoming_usdt || r.usdt_amount || null,
        payin_rate_rub_usdt: r.rub_usdt_rate || null,
        payout_amount_thb: r.thb_received || r.thb_target || null,
        profit_usdt: r.profit_usdt || null,
        profit_percent: r.profit_percent_actual || r.profit_percent || null,
        exchange_rate: r.final_rate || null,
        payin_method: state.method === 'doverka' ? 'spp_doverka' : 'crypto_direct',
        notes: comment,
        scenario: r.scenario || '',
        method: state.method,
        // Данные для корректного расчёта прибыли в CRM
        outgoing_usdt: r.outgoing_usdt || null,
        incoming_usdt: r.incoming_usdt || null,
        bonus_usdt: r.bonus_usdt || null
    };

    // Партнер
    const hasPartner = document.getElementById('hasPartner')?.checked;
    if (hasPartner) {
        const partnerPercent = parseFloat(document.getElementById('partnerPercent')?.value) || 0;
        const partnerModel = (document.querySelector('input[name="partnerModel"]:checked')?.value) || 'revshare';
        dealData.referrer_comp_model = partnerModel;
        if (partnerModel === 'markup') {
            dealData.referrer_markup_percent = partnerPercent;
        } else {
            dealData.referrer_percent = partnerPercent;
        }
    }

    // Открываем CRM с данными в URL
    const encoded = encodeURIComponent(JSON.stringify(dealData));
    window.open(`/crm#create?data=${encoded}`, '_blank');
}


// ==========================================
// ТИП СДЕЛКИ + ИСТОЧНИК КУРСА + НЕДВИЖИМОСТЬ
// ==========================================

// Расширяем состояние
state.dealCategory = 'exchange';          // exchange | property_freehold | property_leasehold | other
state.rateSource = 'bitazza';             // bitazza | binance
state.propProfit = 2.0;                   // прибыль Grusha по недвижимости, %

// --- Тип сделки ---
// Тип — это классификатор сделки. Метод обмена, курсы, сценарии и настройки
// (скидка, партнёр) остаются ВО ВСЕХ типах. Разница только в доп-полях:
//   • фрихолд — доп-расход на перевод застройщику (комиссия % + фикс $)
//   • другое  — поле «что за сделка»
//   • лизхолд / обмен — без доп-полей, обычный обмен
function switchDealCategory(cat) {
    state.dealCategory = cat;
    try { localStorage.setItem('grusha_deal_category', cat); } catch(e) {}

    document.querySelectorAll('.dealtype-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.category === cat);
    });

    // Обменный экран и метод видны всегда — тип их не прячет
    const extra = document.getElementById('propertyExtra');
    const feeWrap = document.getElementById('propertyFeeWrapper');
    const noteWrap = document.getElementById('propertyNoteWrapper');
    const badge = document.getElementById('propertyBadge');

    if (cat === 'property_freehold') {
        extra.style.display = 'block';
        feeWrap.style.display = 'block';
        noteWrap.style.display = 'none';
        badge.textContent = '🏠 Фрихолд — доп-расход на перевод застройщику';
        document.getElementById('propFeePercent').value = '0.8';
        document.getElementById('propFeeFixed').value = '50';
    } else if (cat === 'other') {
        extra.style.display = 'block';
        feeWrap.style.display = 'none';
        noteWrap.style.display = 'block';
        badge.textContent = '✏️ Другое — укажите, что за сделка';
    } else {
        // exchange / property_leasehold — обычный обмен, без доп-полей
        extra.style.display = 'none';
    }
    hideResults();
}

// --- Источник курса (Bitazza / Binance) ---
function setRateSource(src) {
    state.rateSource = src;
    document.getElementById('srcBitazza').classList.toggle('active', src === 'bitazza');
    document.getElementById('srcBinance').classList.toggle('active', src === 'binance');
    updateRatesDisplay();
    hideResults();
}

// Восстановление типа сделки при загрузке
(function initDealCategory() {
    document.addEventListener('DOMContentLoaded', () => {
        let saved = 'exchange';
        try { saved = localStorage.getItem('grusha_deal_category') || 'exchange'; } catch(e) {}
        if (saved !== 'exchange') switchDealCategory(saved);
    });
})();
