"""
Flask API сервер для калькулятора
Предоставляет реальные курсы валют для веб-интерфейса
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import asyncio
import sys
import os

# Импортируем calculator из текущей папки (для деплоя все файлы в одной папке)
from calculator import ExchangeRateProvider, ExchangeCalculator, CommissionCalculator

# Настройка Flask для продакшена (отдаёт статические файлы и API)
app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)  # Разрешаем CORS для локальной разработки

# Маршрут для главной страницы
@app.route('/')
def index():
    """Главная страница калькулятора"""
    return app.send_static_file('index.html')


@app.route('/api/rates', methods=['GET'])
def get_rates():
    """
    Получить актуальные курсы
    
    Returns:
        JSON: {"usdt_thb": float, "rub_usdt": float}
    """
    try:
        # Запускаем асинхронную функцию
        rates = asyncio.run(ExchangeRateProvider.get_all_rates())
        
        return jsonify({
            'usdt_thb': rates['usdt_thb'],
            'rub_usdt': rates['rub_usdt'],
            'timestamp': asyncio.run(get_timestamp())
        }), 200
        
    except Exception as e:
        return jsonify({
            'error': str(e),
            'usdt_thb': 31.16,  # Фоллбэк
            'rub_usdt': 84.2271
        }), 500


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
            commission_level = data.get('commission_level', 'medium')
            
            broker_calc = BrokerCalculatorDetailed(
                rates['usdt_thb'],  # USDT-THB от Binance API (реальный)
                custom_rub_usdt,    # RUB-USDT кастомный от менеджера
                commission_level
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
            else:
                return jsonify({'error': 'Invalid scenario for broker'}), 400
                
        else:
            # Режим Doverka (старая логика)
            calculator = ExchangeCalculator(rates['usdt_thb'], rates['rub_usdt'])
            
            if scenario == 'rub-to-thb':
                result = calculator.rub_to_thb(amount)
            else:
                result = calculator.thb_to_rub(amount)
        
        return jsonify(result), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/health', methods=['GET'])
def health_check():
    """Проверка здоровья API"""
    return jsonify({
        'status': 'ok',
        'message': 'Exchange Calculator API is running'
    }), 200


async def get_timestamp():
    """Получить текущий timestamp"""
    from datetime import datetime
    return datetime.now().isoformat()


@app.route('/')
def index():
    """Главная страница API"""
    return jsonify({
        'name': 'Exchange Calculator API',
        'version': '1.0.0',
        'endpoints': {
            '/api/rates': 'GET - Получить актуальные курсы',
            '/api/calculate': 'POST - Рассчитать обмен',
            '/api/health': 'GET - Проверка здоровья'
        }
    })


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

