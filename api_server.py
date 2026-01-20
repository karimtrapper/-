"""
Flask API сервер для калькулятора
Предоставляет реальные курсы валют для веб-интерфейса
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import sys
import os
import requests
import asyncio

# Импортируем calculator из текущей папки (для деплоя все файлы в одной папке)
from calculator import ExchangeRateProvider, ExchangeCalculator, CommissionCalculator

# Настройка Flask для продакшена (отдаёт статические файлы и API)
app = Flask(__name__, static_folder='.')
CORS(app)  # Разрешаем CORS для локальной разработки

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
        
        # Если API выдало ошибку (None), используем фоллбэки
        usdt_thb = rates.get('usdt_thb') or 35.20
        rub_usdt = rates.get('rub_usdt') or 86.50
        
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
        print(f"🔔 Received Doverka Webhook: {data}")
        
        status = data.get('status')
        order_id = data.get('order_transaction_id') or data.get('order_id')
        amount_from = data.get('amount_from')
        currency = data.get('currency_symbol', 'RUB')
        payer = data.get('payer_name', 'Неизвестно')
        
        if status == 'PAID':
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
            print(f"✅ Уведомление об оплате {order_id} отправлено в Telegram")
            
        return jsonify({'status': 'ok'}), 200
        
    except Exception as e:
        print(f"❌ Ошибка в Webhook: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/webhook/test', methods=['GET'])
def test_webhook_send():
    """Тестовая отправка сообщения"""
    success = send_telegram_notification("🔔 Тестовое уведомление от калькулятора")
    return jsonify({"success": success})


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
    import os
    
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
        import aiohttp
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
    print("   - GET  / - Главная страница")
    print("   - GET  /api/rates - Актуальные курсы")
    print("   - POST /api/calculate - Расчет обмена")
    print("   - GET  /api/health - Проверка здоровья")
    
    app.run(debug=debug_mode, host='0.0.0.0', port=port)


# Trigger rebuild for Railway registry fix
