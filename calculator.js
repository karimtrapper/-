// Конфигурация
// Автоматически определяем API URL: локально - используем текущий hostname, на продакшене - относительный путь
const API_URL = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
    ? `http://${window.location.hostname}:5001/api`
    : '/api';

const CONFIG = {
    API_URL: API_URL,
    USE_API: true,
    
    FALLBACK_RATES: {
        usdt_thb: 31.16,
        rub_usdt: 84.23
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
    customRubUsdt: 80.90,  // кастомный курс для broker
    detailsOpen: false,
    infoOpen: false,
    applyDiscount: false
};

// Инициализация
document.addEventListener('DOMContentLoaded', () => {
    refreshRates();
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
    if (method === 'broker') {
        document.getElementById('customRateSection').style.display = 'block';
        document.getElementById('directionSwitcher').style.display = 'block';
        document.getElementById('rubUsdtLabel').textContent = 'RUB-USDT (Кастомный)';
        
        // Показываем broker сценарии, скрываем doverka
        document.querySelectorAll('.scenario-btn').forEach(btn => {
            if (btn.dataset.method === 'broker') {
                btn.style.display = 'flex';
            } else {
                btn.style.display = 'none';
            }
        });
        
        // Выбираем первый broker сценарий
        state.scenario = 'rub-to-thb';
        updateScenarioUI();
        
    } else {
        document.getElementById('customRateSection').style.display = 'none';
        document.getElementById('directionSwitcher').style.display = 'none';
        document.getElementById('rubUsdtLabel').textContent = 'RUB-USDT (Doverka)';
        
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
    }
    
    hideResults();
}

// Переключение сценария
function switchScenario(scenario) {
    state.scenario = scenario;
    updateScenarioUI();
    hideResults();
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
                resultCurrency: '₽',
                rateCurrency: '₽/฿',
                quickAmounts: [100000, 500000, 1000000, 2000000]
            };
        } else {
            // Вношу конкретную сумму RUB
            config = {
                input: 'Введите сумму в рублях (₽)',
                currency: '₽',
                placeholder: '2741',
                result: 'Клиент получит:',
                resultCurrency: '฿',
                rateCurrency: '₽/฿',
                quickAmounts: [1000, 5000, 10000, 50000]
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
                resultCurrency: '฿',
                rateCurrency: '฿/USDT',
                quickAmounts: [1000, 5000, 13000, 30000]
            };
        } else {
            // Вношу конкретную сумму THB
            config = {
                input: 'Введите сумму в батах (฿)',
                currency: '฿',
                placeholder: '400000',
                result: 'Клиент получит:',
                resultCurrency: 'USDT',
                rateCurrency: '฿/USDT',
                quickAmounts: [100000, 400000, 1000000, 2000000]
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
                resultCurrency: 'USDT',
                rateCurrency: '฿/USDT',
                quickAmounts: [100000, 400000, 1000000, 2000000]
            };
        } else {
            // Вношу конкретную сумму USDT
            config = {
                input: 'Введите сумму в USDT',
                currency: 'USDT',
                placeholder: '13050',
                result: 'Клиент получит:',
                resultCurrency: '฿',
                rateCurrency: '฿/USDT',
                quickAmounts: [1000, 5000, 13000, 30000]
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
                resultCurrency: '₽',
                rateCurrency: '₽/USDT',
                quickAmounts: [1000, 5000, 10000, 20000]
            };
        } else {
            // Вношу конкретную сумму RUB
            config = {
                input: 'Введите сумму в рублях (₽)',
                currency: '₽',
                placeholder: '1000000',
                result: 'Клиент получит:',
                resultCurrency: 'USDT',
                rateCurrency: '₽/USDT',
                quickAmounts: [100000, 500000, 1000000, 5000000]
            };
        }
    } else if (state.scenario === 'thb-to-rub') {
        // Doverka: THB ← RUB (клиент хочет получить конкретную сумму THB)
        config = {
            input: 'Введите желаемую сумму в батах (฿)',
            currency: '฿',
            placeholder: '148001',
            result: 'Клиент должен внести:',
            resultCurrency: '₽',
            rateCurrency: '₽/฿',
            quickAmounts: [10000, 100000, 500000, 1000000]
        };
    } else {
        // Doverka: RUB → THB (клиент вносит сумму в рублях)
        config = {
            input: 'Введите сумму в рублях (₽)',
            currency: '₽',
            placeholder: '100000',
            result: 'Клиент получит:',
            resultCurrency: '฿',
            rateCurrency: '₽/฿',
            quickAmounts: [10000, 100000, 500000, 1000000]
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
            // Определяем базу для расчета (рубли)
            let baseAmount = amount;
            if (state.scenario === 'thb-to-rub' || state.scenario === 'usdt-to-thb' && state.direction === 'target') {
                baseAmount = amount * 2.8; // Примерный эквивалент для оценки порога
            }
            
            if (baseAmount < 500000) defaultProfit = 5.0;
            else if (baseAmount < 1000000) defaultProfit = 4.0;
            else defaultProfit = 3.0;
            
            // Устанавливаем маржу (это также обновит кнопки)
            setProfitMargin(defaultProfit);
        }
    } else {
        wrapper.style.display = 'none';
    }
    
    // СРАЗУ вызываем расчет если сумма введена
    const amount = getAmount();
    if (amount > 0) {
        calculate();
    } else {
        hideResults();
    }
}

// Установка маржи (прибыли)
function setProfitMargin(profit) {
    state.profitMargin = parseFloat(profit);
    
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

// Установка уровня комиссий (старая функция для совместимости, если где-то осталась)
function setCommissionLevel(level) {
    const marginMap = { 'high': 5.0, 'medium': 4.0, 'low': 3.0 };
    setProfitMargin(marginMap[level] || 4.0);
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
    const refreshBtn = document.getElementById('refreshBtn');
    refreshBtn.classList.add('loading');
    
    try {
        if (CONFIG.USE_API) {
            const response = await fetch(`${CONFIG.API_URL}/rates`);
            if (response.ok) {
                const data = await response.json();
                state.rates = data;
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
    const rubUsdt = state.method === 'broker' ? state.customRubUsdt : state.rates.rub_usdt;

    // Показываем USDT-THB
    const usdtThbEl = document.getElementById('usdtThbRate');
    if (state.rates.usdt_thb) {
        usdtThbEl.textContent = `${state.rates.usdt_thb.toFixed(2)} ฿`;
        usdtThbEl.classList.remove('rate-error');
    } else {
        usdtThbEl.textContent = '—';
        usdtThbEl.classList.add('rate-error');
    }
    
    // Показываем RUB-USDT
    const rubUsdtEl = document.getElementById('rubUsdtRate');
    if (state.method === 'broker') {
        const customRate = parseFloat(document.getElementById('customRubUsdt').value.replace(/\s/g, '')) || 80.90;
        rubUsdtEl.textContent = `${customRate.toFixed(4)} ₽`;
        state.customRubUsdt = customRate;
        rubUsdtEl.classList.remove('rate-error');
        
        // В брокере заменяем примерный курс на прочерк, пока нет суммы
        estimatedEl.textContent = '—';
        estimatedEl.classList.add('rate-info-pending');
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

// Обновление кастомного курса (вызывается при изменении поля)
function updateCustomRate() {
    if (state.method === 'broker') {
        const customRubUsdt = parseFloat(document.getElementById('customRubUsdt').value.replace(/\s/g, '')) || 80.90;
        
        // Обновляем state
        state.customRubUsdt = customRubUsdt;
        
        // Обновляем отображение курса RUB-USDT с 4 знаками
        document.getElementById('rubUsdtRate').textContent = `${customRubUsdt.toFixed(4)} ₽`;
        
        // Обновляем примерный курс RUB-THB (USDT-THB от Binance API)
        const estimatedRate = (customRubUsdt / state.rates.usdt_thb).toFixed(2);
        document.getElementById('estimatedRate').textContent = `~${estimatedRate} ₽/฿`;
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

// Установка быстрой суммы
function setAmount(amount) {
    const input = document.getElementById('amount');
    input.value = amount.toLocaleString('ru-RU');
    hideResults();
}

// Получение числового значения
function getAmount() {
    const input = document.getElementById('amount');
    const value = input.value.replace(/\s/g, '').replace(/,/g, '');
    return parseFloat(value) || 0;
}

// Основная функция расчета
async function calculate() {
    const amount = getAmount();
    const resultsSection = document.getElementById('resultsSection');
    const calculateBtn = document.getElementById('calculateBtn');
    
    // Проверка наличия курсов перед расчетом
    const rubUsdt = state.method === 'broker' ? state.customRubUsdt : state.rates.rub_usdt;
    if (!rubUsdt || !state.rates.usdt_thb) {
        alert('⚠️ Ошибка: Курсы валют не получены. Расчет невозможен.');
        return;
    }

    if (amount <= 0) {
        resultsSection.style.display = 'none';
        return;
    }
    
    try {
        if (CONFIG.USE_API && state.method === 'broker') {
            // Используем API для расчета через брокера
            const requestData = {
                method: 'broker',
                scenario: state.scenario,
                direction: state.direction,
                amount: amount,
                custom_rub_usdt: state.customRubUsdt,
                profit_margin: state.profitMargin
            };
            
            const response = await fetch(`${CONFIG.API_URL}/calculate`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(requestData)
            });
            
            if (response.ok) {
                const result = await response.json();
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
            }

            const requestData = {
                method: 'doverka',
                scenario: effectiveScenario,
                direction: effectiveDirection,
                amount: amount,
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
                displayResult(result);
            } else {
                throw new Error('Calculation API error');
            }
            
        } else {
            // Локальный расчет (фоллбэк)
            const result = calculateLocal(amount);
            displayResult(result);
        }
        
        resultsSection.style.display = 'block';
        
    } catch (error) {
        console.error('Calculation error:', error);
        // Фоллбэк на локальный расчет
        const result = calculateLocal(amount);
        displayResult(result);
        resultsSection.style.display = 'block';
    }
}

// Локальный расчет (фоллбэк)
function calculateLocal(amount) {
    // ПРАВИЛЬНЫЙ расчет для Doverka
    if (state.method === 'doverka' && state.scenario === 'rub-to-thb') {
        // 1. RUB → USDT (без комиссии на этом этапе)
        const usdt = amount / state.rates.rub_usdt;
        
        // 2. USDT → THB с комиссией 2.72%
        const usdt_thb_rate_sell = state.rates.usdt_thb * (1 - 0.0272);
        const thb_before_fees = usdt * usdt_thb_rate_sell;
        
        // 3. Комиссии за выдачу
        const withdrawal_percent_fee = thb_before_fees * 0.0025;
        const withdrawal_fixed = 20;
        const thbNet = thb_before_fees - withdrawal_percent_fee - withdrawal_fixed;
        
        return {
            scenario: 'RUB → THB',
            rub_paid: amount,
            thb_received: thbNet,
            final_rate: thbNet / usdt,
            usdt_amount: usdt,
            withdrawal_fees: withdrawal_percent_fee + withdrawal_fixed,
            commission_level: 'Doverka (до 500к)'
        };
    }
    
    // Doverka: THB ← RUB (клиент хочет получить конкретную сумму THB)
    if (state.method === 'doverka' && state.scenario === 'thb-to-rub') {
        // 1. Комиссии за выдачу
        const withdrawal_fixed = 20;
        const withdrawal_percent_fee = amount * 0.0025;  // amount - это THB
        
        // 2. THB к обмену
        const thb_to_exchange = amount + withdrawal_fixed + withdrawal_percent_fee;
        
        // 3. USDT
        const usdt_thb_rate_sell = state.rates.usdt_thb * (1 - 0.0272);
        const usdt = thb_to_exchange / usdt_thb_rate_sell;
        
        // 4. RUB
        const rub_to_pay = usdt * state.rates.rub_usdt;
        
        return {
            scenario: 'THB ← RUB',
            thb_target: amount,
            rub_to_pay: rub_to_pay,
            final_rate: amount / usdt,
            usdt_amount: usdt,
            withdrawal_fees: withdrawal_fixed + withdrawal_percent_fee,
            commission_level: 'Doverka (до 500к)'
        };
    }
    
    // Для остальных случаев возвращаем заглушку
    return {
        scenario: state.scenario,
        thb_received: amount * 0.35,
        final_rate: 2.8,
        usdt_amount: amount / 85,
        commission_level: state.commissionLevel
    };
}

// Отображение результата
function displayResult(result) {
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
    
    document.getElementById('resultValue').textContent = resultValue;
    document.getElementById('finalRate').textContent = rateValue;
    document.getElementById('rateCurrency').textContent = rateCurrency;
    
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

    // Курс продажи RUB-USDT
    if (result.rub_usdt_rate_sell !== undefined) {
        html += `<div class="detail-row"><span class="detail-label">Курс продажи RUB-USDT:</span><span class="detail-value highlight">${result.rub_usdt_rate_sell.toFixed(4)} ₽</span></div>`;
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
        html += `<div class="detail-row"><span class="detail-label">Комиссия за выдачу (0,25%):</span><span class="detail-value">${formatNumber(result.withdrawal_percent)} ฿</span></div>`;
    }
    if (result.withdrawal_fixed !== undefined) {
        html += `<div class="detail-row"><span class="detail-label">Комиссия за выдачу (фикс 20 THB):</span><span class="detail-value">${result.withdrawal_fixed} ฿</span></div>`;
    }
    
    // Итоговая сумма THB
    if (result.thb_received !== undefined) {
        html += `<div class="detail-row"><span class="detail-label">Сумма THB к выдаче:</span><span class="detail-value highlight-final">${formatNumber(result.thb_received)} ฿</span></div>`;
    } else if (result.thb_target !== undefined) {
        html += `<div class="detail-row"><span class="detail-label">Сумма THB к выдаче:</span><span class="detail-value highlight-final">${formatNumber(result.thb_target)} ฿</span></div>`;
    }
    
    // Курс продажи RUB-THB
    let finalRateLabel = 'Курс продажи RUB-THB:';
    if (result.scenario === 'USDT → THB') finalRateLabel = 'Курс продажи USDT-THB:';
    else if (result.scenario === 'THB → USDT') finalRateLabel = 'Курс продажи THB-USDT:';
    else if (result.scenario === 'RUB → USDT') finalRateLabel = 'Курс продажи RUB-USDT:';
    
    html += `<div class="detail-row"><span class="detail-label">${finalRateLabel}</span><span class="detail-value highlight-final">${result.final_rate.toFixed(4)}</span></div>`;
    
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
        
        // Расчет партнера (на клиенте)
        const hasPartner = document.getElementById('hasPartner');
        if (hasPartner && hasPartner.checked && result.profit_usdt !== undefined) {
            const partnerPercentEl = document.getElementById('partnerPercent');
            const partnerPercent = partnerPercentEl ? (parseFloat(partnerPercentEl.value) || 0) : 0;
            const partnerPayout = (result.profit_usdt * partnerPercent / 100);
            const netProfit = result.profit_usdt - partnerPayout;
            
            html += `<div class="detail-row partner-row"><span class="detail-label">% партнера:</span><span class="detail-value">${partnerPercent.toFixed(2)}%</span></div>`;
            html += `<div class="detail-row partner-row"><span class="detail-label">Выплата партнеру:</span><span class="detail-value partner-payout">${formatNumber(partnerPayout)} USDT</span></div>`;
            html += `<div class="detail-row partner-row"><span class="detail-label">Чистая прибыль:</span><span class="detail-value highlight-final">${formatNumber(netProfit)} USDT</span></div>`;
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

