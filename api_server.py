"""
Flask API сервер для калькулятора
Предоставляет реальные курсы валют для веб-интерфейса
"""

import asyncio
import sys
import os
import requests
import aiohttp
from flask import Flask, jsonify, request
from flask_cors import CORS

# Импортируем calculator из текущей папки (для деплоя все файлы в одной папке)
from calculator import ExchangeRateProvider, ExchangeCalculator, CommissionCalculator

# Настройка Flask для продакшена (отдаёт статические файлы и API)
app = Flask(__name__, static_folder='.')
CORS(app)  # Разрешаем CORS для локальной разработки

@app.before_request
def log_request_info():
    """Логировать вообще каждый запрос к серверу для отладки"""
    if request.method == 'POST':
        print(f"📡 DEBUG: Received POST to {request.path}")
        print(f"📡 Body: {request.get_data(as_text=True)}")

# Маршрут для главной страницы
@app.route('/')
def index():
    """Главная страница калькулятора"""
    return app.send_static_file('index.html')


@app.route('/api/rates', methods=['GET'])
def get_rates():
    """
    Получить актуальные курсы для лендинга
    """
    try:
        # Запускаем асинхронную функцию
        rates = asyncio.run(ExchangeRateProvider.get_all_rates())
        print(f"📊 RAW RATES FETCHED: {rates}", flush=True)
        
        # Если API выдало ошибку (None), используем актуальные фоллбэки (на 20.01.2026)
        usdt_thb = rates.get('usdt_thb') or 34.50
        rub_usdt = rates.get('rub_usdt') or 92.80
        
        if not rates.get('usdt_thb') or not rates.get('rub_usdt'):
            print(f"⚠️ Using fallback rates! Binance: {rates.get('usdt_thb')}, Doverka: {rates.get('rub_usdt')}", flush=True)
        
        return jsonify({
            'usdt_thb': usdt_thb,
            'rub_usdt': rub_usdt,
            'success': True
        }), 200
        
    except Exception as e:
        print(f"❌ Ошибка получения курсов: {e}")
        return jsonify({
            'error': str(e),
            'usdt_thb': 35.20,
            'rub_usdt': 86.50,
            'success': False
        }), 200 # Возвращаем 200 даже при ошибке, но с фоллбэками


@app.route('/api/calculate', methods=['POST'])
def calculate():
    """
    Рассчитать обмен
    
    Request JSON:
        {
            "method": "doverka" | "broker",
            "scenario": "rub-to-thb" | "thb-to-rub" | "thb-to-usdt" | "usdt-to-thb",
            "direction": "target" | "amount",
            "amount": float,
            "custom_rub_usdt": float (optional, для broker),
            "commission_level": "high" | "medium" | "low" (optional, для broker)
        }
    
    Returns:
        JSON: Детальный расчет
    """
    try:
        data = request.get_json()
        print(f"📥 Received calculation request: {data}")
        method = data.get('method', 'doverka')
        scenario = data.get('scenario', 'rub-to-thb')
        direction = data.get('direction', 'amount')
        amount = float(data.get('amount', 0))
        
        if amount <= 0:
            return jsonify({'error': 'Invalid amount'}), 400
        
        # Получаем актуальные курсы
        rates = asyncio.run(ExchangeRateProvider.get_all_rates())
        
        if method == 'broker':
            # Режим брокера: USDT-THB от Binance, RUB-USDT кастомный
            from broker_detailed import BrokerCalculatorDetailed
            
            custom_rub_usdt = float(data.get('custom_rub_usdt', 80.9))
            # Принимаем profit_margin как число (1.5, 3.0, 5.0)
            profit_margin = float(data.get('profit_margin', 4.0))
            
            broker_calc = BrokerCalculatorDetailed(
                rates['usdt_thb'],  # USDT-THB от Binance API (реальный)
                custom_rub_usdt,    # RUB-USDT кастомный от менеджера
                profit_margin       # Передаем динамическую маржу
            )
            
            # Выбираем операцию
            if scenario == 'rub-to-thb':
                if direction == 'target':
                    result = broker_calc.rub_to_thb_target(amount)
                else:
                    result = broker_calc.rub_to_thb_amount(amount)
            elif scenario == 'thb-to-usdt':
                if direction == 'target':
                    result = broker_calc.thb_to_usdt_target(amount)
                else:
                    result = broker_calc.thb_to_usdt_amount(amount)
            elif scenario == 'usdt-to-thb':
                if direction == 'target':
                    result = broker_calc.usdt_to_thb_target(amount)
                else:
                    result = broker_calc.usdt_to_thb_amount(amount)
            elif scenario == 'rub-to-usdt':
                if direction == 'target':
                    result = broker_calc.rub_to_usdt_target(amount)
                else:
                    result = broker_calc.rub_to_usdt_amount(amount)
            else:
                return jsonify({'error': 'Invalid scenario for broker'}), 400
                
        else:
            # Режим Doverka (SBP)
            calculator = ExchangeCalculator(rates['usdt_thb'], rates['rub_usdt'])
            # Принимаем profit_margin для Doverka тоже
            profit_margin_raw = data.get('profit_margin')
            profit_margin = float(profit_margin_raw) if profit_margin_raw is not None else None
            
            if scenario == 'rub-to-thb':
                if direction == 'target':
                    result = calculator.rub_to_thb_target(amount, custom_profit_margin=profit_margin)
                else:
                    result = calculator.rub_to_thb(amount, custom_profit_margin=profit_margin)
            elif scenario == 'thb-to-usdt':
                if direction == 'target':
                    result = calculator.thb_to_usdt_target(amount, custom_profit_margin=profit_margin)
                else:
                    result = calculator.thb_to_usdt(amount, custom_profit_margin=profit_margin)
            elif scenario == 'usdt-to-thb':
                if direction == 'target':
                    result = calculator.usdt_to_thb_target(amount, custom_profit_margin=profit_margin)
                else:
                    result = calculator.usdt_to_thb(amount, custom_profit_margin=profit_margin)
            elif scenario == 'rub-to-usdt':
                if direction == 'target':
                    result = calculator.rub_to_usdt_target(amount, custom_profit_margin=profit_margin)
                else:
                    result = calculator.rub_to_usdt_amount(amount, custom_profit_margin=profit_margin)
            else:
                return jsonify({'error': f'Invalid scenario {scenario} for doverka'}), 400
        
        return jsonify(result), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/payments', methods=['POST'])
def create_payment():
    """
    Создать платеж в DoverkaPay через наш бэкенд
    """
    try:
        data = request.get_json()
        print(f"💳 REQUEST TO CREATE PAYMENT: {data}")
        
        doverka_key = os.environ.get('DOVERKA_API_KEY', '')
        if not doverka_key:
            print("❌ ERROR: DOVERKA_API_KEY is missing in env variables")
            return jsonify({'error': 'DOVERKA_API_KEY not configured on server'}), 500
            
        # Формируем запрос к Doverka
        url = f"{ExchangeRateProvider.DOVERKA_API}/v1/payments"
        headers = {
            'Authorization': f'Bearer {doverka_key}',
            'Content-Type': 'application/json',
            'accept': 'application/json'
        }
        
        # Пробрасываем все данные, пришедшие с фронта, 
        # и принудительно устанавливаем наш callback_url
        payload = data.copy()
        payload['callback_url'] = "https://proud-renewal-production-e9b8.up.railway.app/api/webhook/doverka"
        
        print(f"📤 Forwarding request to Doverka: {url}")
        response = requests.post(url, json=payload, headers=headers, timeout=15)
        
        print(f"📥 Doverka response status: {response.status_code}")
        
        if response.status_code in [200, 201]:
            result = response.json()
            print(f"✅ Payment created successfully: {result.get('id')}")
            return jsonify(result), 200
        else:
            error_text = response.text
            print(f"❌ Doverka Error: {response.status_code} - {error_text}")
            return jsonify({
                'error': f'Doverka API error: {response.status_code}',
                'details': error_text
            }), response.status_code
            
    except Exception as e:
        import traceback
        error_msg = traceback.format_exc()
        print(f"❌ CRITICAL EXCEPTION during payment creation:\n{error_msg}")
        return jsonify({'error': str(e), 'traceback': error_msg}), 500


def send_telegram_notification(text):
    """Отправить уведомление в Telegram (синхронно для Flask)"""
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '8157701216:AAFxDQcrKm8zwcs6CzzascxTf0jFcndKX5U')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID', '-1003678845665')
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code != 200:
            print(f"❌ Telegram Error: {response.status_code} - {response.text}")
        return response.status_code == 200
    except Exception as e:
        print(f"❌ Telegram Exception: {e}")
        return False


@app.route('/api/webhook/doverka', methods=['POST'])
def doverka_webhook():
    """
    Webhook для получения уведомлений об оплате от Doverka
    """
    try:
        data = request.get_json()
        print(f"🔔 WEBHOOK RECEIVED! Full data: {data}")
        
        if not data:
            print("⚠️ Webhook received empty data")
            return jsonify({'status': 'empty data'}), 400
            
        status = str(data.get('status', '')).upper()
        order_id = data.get('order_transaction_id') or data.get('order_id')
        amount_from = data.get('amount_from') or data.get('amount_to')
        currency = data.get('currency_symbol', 'RUB')
        payer = data.get('payer_name', 'Неизвестно')
        
        print(f"🧐 Processing order: {order_id}, status: {status}")
        
        if status in ['PAID', 'COMPLETED', 'SUCCESS']:
            # Пробуем достать данные из метаданных, если они там есть
            metadata = data.get('metadata', {})
            thb_amount = metadata.get('thb_amount', '—')
            profit_usdt = metadata.get('profit_usdt', 0)
            comment = metadata.get('comment', '—')
            
            msg = (
                f"✅ <b>Оплата получена!</b>\n\n"
                f"💰 Сумма: <b>{amount_from} {currency}</b>\n"
                f"🇹🇭 Выдать клиенту: <b>{thb_amount} THB</b>\n"
                f"📈 Доход: <b>{profit_usdt:.2f} USDT</b>\n"
                f"📅 Дата: {data.get('date', '—')}\n"
                f"🆔 Заказ: <code>{order_id}</code>\n"
                f"💬 Комментарий: {comment}"
            )
            
            # Отправляем уведомление синхронно
            send_telegram_notification(msg)
            print(f"🚀 SUCCESS: Notification sent for {order_id}")
        else:
            print(f"ℹ️ Skipping status {status} for order {order_id}")
            
        return jsonify({'status': 'ok'}), 200
        
    except Exception as e:
        print(f"❌ Ошибка в Webhook: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/webhook/test', methods=['GET'])
def test_webhook_send():
    """Тестовая отправка сообщения"""
    success = send_telegram_notification("🔔 Тестовое уведомление от калькулятора")
    return jsonify({"success": success})


@app.route('/test-tg', methods=['GET'])
def test_tg_direct():
    """Тестовая отправка сообщения напрямую"""
    success = send_telegram_notification("🚀 Прямой тест уведомления")
    return f"Telegram notification sent: {success}"


@app.route('/api/health', methods=['GET'])
def health_check():
    """Проверка здоровья API"""
    return jsonify({
        'status': 'ok',
        'message': 'Exchange Calculator API is running'
    }), 200


@app.route('/api/test-doverka', methods=['GET'])
def test_doverka():
    """Тестовый endpoint для проверки Doverka API"""
    doverka_key = os.getenv('DOVERKA_API_KEY', '')
    
    result = {
        'api_key_configured': bool(doverka_key),
        'api_key_length': len(doverka_key) if doverka_key else 0,
        'api_key_prefix': doverka_key[:10] + '...' if len(doverka_key) > 10 else 'not set',
    }
    
    if not doverka_key:
        result['error'] = 'DOVERKA_API_KEY не настроен в переменных окружения'
        return jsonify(result), 200
    
    try:
        # Пробуем получить курс
        rate = asyncio.run(ExchangeRateProvider.get_doverka_rate())
        result['rate_received'] = rate
        result['status'] = 'success'
        
        # Пробуем получить сырой ответ от API
        async def get_raw_response():
            async with aiohttp.ClientSession() as session:
                url = f"{ExchangeRateProvider.DOVERKA_API}/v1/currencies"
                headers = {
                    'Authorization': f'Bearer {doverka_key}',
                    'accept': 'application/json'
                }
                async with session.get(url, headers=headers, timeout=10) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        return {'error': f'Status {response.status}', 'text': await response.text()}
        
        raw_data = asyncio.run(get_raw_response())
        result['api_response'] = raw_data
        
    except Exception as e:
        result['error'] = str(e)
        result['status'] = 'error'
        import traceback
        result['traceback'] = traceback.format_exc()
    
    return jsonify(result), 200


async def get_timestamp():
    """Получить текущий timestamp"""
    from datetime import datetime
    return datetime.now().isoformat()


@app.route('/api')
def api_info():
    """Информация об API"""
    return jsonify({
        'name': 'Exchange Calculator API',
        'version': '1.0.0',
        'endpoints': {
            '/api/rates': 'GET - Получить актуальные курсы',
            '/api/calculate': 'POST - Рассчитать обмен',
            '/api/health': 'GET - Проверка здоровья',
            '/api/test-doverka': 'GET - Тест Doverka API'
        }
    })


# Маршруты для статических файлов (CSS, JS) - должен быть последним!
@app.route('/<path:filename>')
def static_files(filename):
    """Отдача статических файлов (CSS, JS, и т.д.)"""
    # Игнорируем API маршруты
    if filename.startswith('api'):
        return '', 404
    
    # Разрешаем только известные статические файлы
    allowed_extensions = ['.css', '.js', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico']
    if not any(filename.endswith(ext) for ext in allowed_extensions):
        return '', 404
    
    try:
        return app.send_static_file(filename)
    except:
        return '', 404


if __name__ == '__main__':
    # Поддержка PORT переменной для продакшена (Railway, Render, Heroku и т.д.)
    port = int(os.environ.get('PORT', 5001))
    debug_mode = os.environ.get('FLASK_ENV') == 'development'
    
    print("🚀 Starting Exchange Calculator API server...")
    print(f"📍 Server running on http://0.0.0.0:{port}")
    print("📊 API endpoints:")
    for rule in app.url_map.iter_rules():
        print(f"   - {rule.methods} {rule.rule}")
    
    app.run(debug=debug_mode, host='0.0.0.0', port=port)
