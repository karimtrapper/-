// Конфигурация
// Автоматически определяем API URL: локально - localhost, на продакшене - относительный путь
const API_URL = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
    ? 'http://localhost:5001/api'
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
    commissionLevel: 'medium',  // для broker: 'high', 'medium', 'low'
    rates: CONFIG.FALLBACK_RATES,
    customRubUsdt: 80.90,  // кастомный курс для broker
    detailsOpen: false,
    infoOpen: false
};

// Инициализация
document.addEventListener('DOMContentLoaded', () => {
    refreshRates();
});

// Переключение метода
function switchMethod(method) {
    state.method = method;
    
    // Обновляем кнопки метода
    document.querySelectorAll('.method-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.method === method);
    });
    
    // Показываем/скрываем элементы UI
    if (method === 'broker') {
        document.getElementById('customRateSection').style.display = 'block';
        document.getElementById('commissionLevelSelector').style.display = 'block';
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
        document.getElementById('commissionLevelSelector').style.display = 'none';
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
    
    calculate();
}

// Переключение сценария
function switchScenario(scenario) {
    state.scenario = scenario;
    updateScenarioUI();
    calculate();
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
                rateCurrency: 'USDT/฿',
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
                rateCurrency: 'USDT/฿',
                quickAmounts: [1000, 5000, 13000, 30000]
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
    
    // Обновляем быстрые кнопки
    const quickAmountsDiv = document.getElementById('quickAmounts');
    quickAmountsDiv.innerHTML = config.quickAmounts.map(amount => {
        const label = amount >= 1000000 ? `${amount/1000000}M` : `${amount/1000}k`;
        return `<button class="quick-btn" onclick="setAmount(${amount})">${label}</button>`;
    }).join('');
    
    // Очищаем поле ввода
    document.getElementById('amount').value = '';
    document.getElementById('resultsSection').style.display = 'none';
}

// Установка уровня комиссий
function setCommissionLevel(level) {
    state.commissionLevel = level;
    
    document.querySelectorAll('.commission-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.level === level);
    });
    
    calculate();
}

// Установка direction (целевая/вносимая)
function setDirection(direction) {
    state.direction = direction;
    
    document.querySelectorAll('.direction-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.direction === direction);
    });
    
    // Обновляем метки в зависимости от direction
    updateScenarioUI();
    calculate();
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
        calculate();
        
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
    // Показываем USDT-THB с 2 знаками (достаточно точно)
    document.getElementById('usdtThbRate').textContent = `${state.rates.usdt_thb.toFixed(2)} ฿`;
    
    if (state.method === 'broker') {
        // Показываем кастомный курс с 4 знаками
        const customRate = parseFloat(document.getElementById('customRubUsdt').value.replace(/\s/g, '')) || 80.90;
        document.getElementById('rubUsdtRate').textContent = `${customRate.toFixed(4)} ₽`;
        state.customRubUsdt = customRate;
    } else {
        // Показываем курс от Doverka API с 4 знаками для точности!
        document.getElementById('rubUsdtRate').textContent = `${state.rates.rub_usdt.toFixed(4)} ₽`;
    }
    
    // Примерный курс
    const rubUsdt = state.method === 'broker' ? state.customRubUsdt : state.rates.rub_usdt;
    const estimatedRate = (rubUsdt / state.rates.usdt_thb).toFixed(2);
    document.getElementById('estimatedRate').textContent = `~${estimatedRate} ₽/฿`;
    
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
    calculate();
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
                direction: state.direction,  // используем direction из state
                amount: amount,
                custom_rub_usdt: state.customRubUsdt,  // Только RUB-USDT кастомный
                commission_level: state.commissionLevel
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
            // Используем API для Doverka
            const requestData = {
                method: 'doverka',
                scenario: state.scenario,
                direction: 'amount',
                amount: amount
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
            final_rate: amount / thbNet,
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
            final_rate: rub_to_pay / amount,
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
    
    // Определяем что показывать по scenario и direction
    // ВАЖНО: проверяем результат (output), а не вход (input)!
    
    if (result.scenario === 'USDT → THB') {
        if (result.thb_received !== undefined) {
            // amount: вношу USDT → получаю THB
            resultValue = `${formatNumber(result.thb_received)} ฿`;
            rateValue = result.usdt_thb_rate_sell ? result.usdt_thb_rate_sell.toFixed(2) : result.final_rate.toFixed(2);
            rateCurrency = '฿/USDT';
        } else if (result.usdt_amount !== undefined) {
            // target: хочу получить THB → плачу USDT
            resultValue = `${formatNumber(result.usdt_amount)} USDT`;
            rateValue = result.usdt_thb_rate_sell ? result.usdt_thb_rate_sell.toFixed(2) : result.final_rate.toFixed(2);
            rateCurrency = '฿/USDT';
        }
    } else if (result.scenario === 'THB → USDT') {
        if (result.usdt_received !== undefined) {
            // amount: вношу THB → получаю USDT
            resultValue = `${formatNumber(result.usdt_received)} USDT`;
            rateValue = result.final_rate.toFixed(4);
            rateCurrency = '฿/USDT';
        } else if (result.thb_amount !== undefined) {
            // target: хочу получить USDT → плачу THB
            resultValue = `${formatNumber(result.thb_amount)} ฿`;
            rateValue = result.final_rate.toFixed(4);
            rateCurrency = '฿/USDT';
        }
    } else if (result.scenario === 'RUB → THB') {
        if (result.thb_received !== undefined) {
            // amount: вношу RUB → получаю THB
            resultValue = `${formatNumber(result.thb_received)} ฿`;
            rateValue = result.final_rate.toFixed(4);
            rateCurrency = '₽/฿';
        } else if (result.rub_amount !== undefined) {
            // target: хочу получить THB → плачу RUB
            resultValue = `${formatNumber(result.rub_amount)} ₽`;
            rateValue = result.final_rate.toFixed(4);
            rateCurrency = '₽/฿';
        }
    } else if (result.scenario === 'THB ← RUB') {
        // Doverka: хочу получить THB → плачу RUB
        resultValue = `${formatNumber(result.rub_to_pay)} ₽`;
        rateValue = result.final_rate.toFixed(4);
        rateCurrency = '₽/฿';
    } else if (result.thb_received !== undefined) {
        resultValue = `${formatNumber(result.thb_received)} ฿`;
        rateValue = result.final_rate.toFixed(4);
        rateCurrency = '₽/฿';
    } else if (result.rub_to_pay !== undefined) {
        resultValue = `${formatNumber(result.rub_to_pay)} ₽`;
        rateValue = result.final_rate.toFixed(4);
        rateCurrency = '₽/฿';
    } else {
        // Fallback
        resultValue = 'N/A';
        rateValue = '0';
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
    
    // Сумма THB к выдаче
    if (result.thb_target !== undefined) {
        html += `<div class="detail-row"><span class="detail-label">Сумма THB к выдаче:</span><span class="detail-value">${formatNumber(result.thb_target)} ฿</span></div>`;
    }
    
    // Комиссии за выдачу
    if (result.withdrawal_fixed !== undefined) {
        html += `<div class="detail-row"><span class="detail-label">Комиссия брокера за выдачу (фикс 20 THB):</span><span class="detail-value">${result.withdrawal_fixed} ฿</span></div>`;
    }
    if (result.withdrawal_percent !== undefined) {
        html += `<div class="detail-row"><span class="detail-label">Комиссия брокера за выдачу (0,25%):</span><span class="detail-value">${formatNumber(result.withdrawal_percent)} ฿</span></div>`;
    }
    
    // Сумма THB к обмену
    if (result.thb_to_exchange !== undefined) {
        html += `<div class="detail-row"><span class="detail-label">Сумма THB к обмену за USDT:</span><span class="detail-value highlight">${formatNumber(result.thb_to_exchange)} ฿</span></div>`;
    }
    
    // Курс брокера USDT-THB
    if (result.usdt_thb_rate !== undefined) {
        html += `<div class="detail-row"><span class="detail-label">Курс брокера USDT-THB:</span><span class="detail-value">${result.usdt_thb_rate.toFixed(2)} ฿</span></div>`;
    }
    
    // Комиссия на этапе USDT-THB
    if (result.usdt_thb_commission !== undefined) {
        html += `<div class="detail-row"><span class="detail-label">Комиссия на этапе USDT-THB:</span><span class="detail-value">${result.usdt_thb_commission.toFixed(2)}%</span></div>`;
    }
    
    // Курс продажи USDT-THB
    if (result.usdt_thb_rate_sell !== undefined) {
        html += `<div class="detail-row"><span class="detail-label">Курс продажи USDT-THB:</span><span class="detail-value highlight">${result.usdt_thb_rate_sell.toFixed(2)} ฿</span></div>`;
    }
    
    // Сумма USDT
    if (result.usdt_amount !== undefined) {
        html += `<div class="detail-row"><span class="detail-label">Сумма USDT:</span><span class="detail-value highlight">${formatNumber(result.usdt_amount)} USDT</span></div>`;
    }
    
    // Курс брокера RUB-USDT
    if (result.rub_usdt_rate !== undefined) {
        html += `<div class="detail-row"><span class="detail-label">Курс брокера RUB-USDT:</span><span class="detail-value">${result.rub_usdt_rate.toFixed(4)} ₽</span></div>`;
    }
    
    // Комиссия на этапе RUB-USDT
    if (result.rub_usdt_commission !== undefined) {
        html += `<div class="detail-row"><span class="detail-label">Комиссия на этапе RUB-USDT:</span><span class="detail-value">${result.rub_usdt_commission.toFixed(2)}%</span></div>`;
    }
    
    // Курс продажи RUB-USDT
    if (result.rub_usdt_rate_sell !== undefined) {
        html += `<div class="detail-row"><span class="detail-label">Курс продажи RUB-USDT:</span><span class="detail-value highlight">${result.rub_usdt_rate_sell.toFixed(4)} ₽</span></div>`;
    }
    
    // Сумма RUB (для broker)
    if (result.rub_amount !== undefined) {
        html += `<div class="detail-row"><span class="detail-label">Сумма RUB, вносимая клиентом:</span><span class="detail-value highlight-final">${formatNumber(result.rub_amount)} ₽</span></div>`;
    }
    // Сумма RUB (для doverka thb-to-rub)
    if (result.rub_to_pay !== undefined) {
        html += `<div class="detail-row"><span class="detail-label">Сумма RUB, вносимая клиентом:</span><span class="detail-value highlight-final">${formatNumber(result.rub_to_pay)} ₽</span></div>`;
    }
    // Сумма RUB (для doverka rub-to-thb)
    if (result.rub_paid !== undefined) {
        html += `<div class="detail-row"><span class="detail-label">Сумма RUB (внесено):</span><span class="detail-value highlight">${formatNumber(result.rub_paid)} ₽</span></div>`;
    }
    
    // Сумма THB к выдаче (для rub-to-thb)
    if (result.thb_received !== undefined) {
        html += `<div class="detail-row"><span class="detail-label">Сумма THB к выдаче:</span><span class="detail-value highlight-final">${formatNumber(result.thb_received)} ฿</span></div>`;
    }
    
    // Курс продажи RUB-THB
    html += `<div class="detail-row"><span class="detail-label">Курс продажи RUB-THB:</span><span class="detail-value highlight-final">${result.final_rate.toFixed(4)}</span></div>`;
    
    html += `</div>`;
    
    // Прибыльность (если есть данные)
    if (result.incoming_usdt !== undefined || result.profit_usdt !== undefined) {
        html += `<div class="detail-section profitability-section">`;
        html += `<h4>💰 Прибыльность</h4>`;
        
        // Бонус 2.4% (ТОЛЬКО для Doverka, НЕ для Broker!)
        if (result.bonus_usdt !== undefined && result.bonus_percent !== undefined && state.method === 'doverka') {
            html += `<div class="detail-row"><span class="detail-label">${result.bonus_percent}% - от курса:</span><span class="detail-value">${formatNumber(result.bonus_usdt)} USDT</span></div>`;
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
        if (result.profit_percent_actual !== undefined) {
            html += `<div class="detail-row"><span class="detail-label">% прибыли:</span><span class="detail-value">${result.profit_percent_actual.toFixed(2)}%</span></div>`;
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
    
    calculate();
}

