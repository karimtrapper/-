"""
Unified Service: Calculator + CRM
Объединённый сервис калькулятора и CRM для Railway
"""

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from datetime import datetime, timedelta
import os
import requests
import threading
import asyncio

# ==================== FLASK APP ====================
app = Flask(__name__, static_folder='static')
CORS(app)

# ==================== DATABASE ====================
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session

# Автоматически выбираем PostgreSQL для прода или SQLite для локальной разработки
DATABASE_URL = os.environ.get('DATABASE_URL', '')
if DATABASE_URL:
    # Railway PostgreSQL (иногда начинается с postgres://, нужно postgresql://)
    if DATABASE_URL.startswith('postgres://'):
        DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
    engine = create_engine(DATABASE_URL, echo=False)
else:
    # Локальная SQLite
    DATABASE_PATH = os.path.join(os.path.dirname(__file__), 'local.db')
    DATABASE_URL = f'sqlite:///{DATABASE_PATH}'
    engine = create_engine(DATABASE_URL, echo=False, connect_args={'check_same_thread': False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
Session = scoped_session(SessionLocal)

def get_session():
    return Session()

# ==================== MODELS ====================
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, ForeignKey, Enum as SQLEnum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from enum import Enum

Base = declarative_base()

class DealType(str, Enum):
    PAY_IN = "pay_in"
    PAY_OUT = "pay_out"

class PayInMethod(str, Enum):
    SPP_DOVERKA = "spp_doverka"
    PARTNERS_CASH = "partners_cash"
    CRYPTO_DIRECT = "crypto_direct"

class PayOutMethod(str, Enum):
    OFFICE = "office"
    COURIER = "courier"
    ATM = "atm"
    TRANSFER = "transfer"

class PayOutSource(str, Enum):
    CASH_BATCH = "cash_batch"
    BANK_CARD = "bank_card"
    BINANCE = "binance"
    FOUNDER_PERSONAL = "founder_personal"

class DealStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    VERIFIED = "verified"
    CANCELLED = "cancelled"

class CashBatchStatus(str, Enum):
    ACTIVE = "active"
    DEPLETED = "depleted"
    ARCHIVED = "archived"

class DoverkaStatus(str, Enum):
    PENDING = "pending"
    PAID = "paid"
    CONFIRMED = "confirmed"

class Manager(Base):
    __tablename__ = 'managers'
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=True)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {'id': self.id, 'name': self.name, 'active': self.active,
                'created_at': self.created_at.isoformat() if self.created_at else None}

class Client(Base):
    __tablename__ = 'clients'
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    telegram = Column(String(50))
    phone = Column(String(20))
    preferred_method = Column(String(50))
    total_deals = Column(Integer, default=0)
    total_volume_usdt = Column(Float, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    notes = Column(Text)
    deals = relationship("Deal", back_populates="client")
    
    def to_dict(self):
        return {'id': self.id, 'name': self.name, 'telegram': self.telegram, 'phone': self.phone,
                'total_deals': self.total_deals, 'total_volume_usdt': self.total_volume_usdt}

class CashBatch(Base):
    __tablename__ = 'cash_batches'
    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    amount_thb = Column(Float, nullable=False)
    cost_usdt = Column(Float, nullable=False)
    purchase_rate = Column(Float, nullable=False)
    remaining_thb = Column(Float, nullable=False)
    purchase_method = Column(String(50))
    founder_name = Column(String(100))
    tx_hash = Column(String(100))
    notes = Column(Text)
    status = Column(SQLEnum(CashBatchStatus), default=CashBatchStatus.ACTIVE)
    deals = relationship("Deal", back_populates="cash_batch")
    allocations = relationship("CashAllocation", back_populates="batch")
    
    def to_dict(self):
        return {
            'id': self.id, 'created_at': self.created_at.isoformat() if self.created_at else None,
            'amount_thb': self.amount_thb, 'cost_usdt': self.cost_usdt, 'purchase_rate': self.purchase_rate,
            'remaining_thb': self.remaining_thb, 'used_thb': self.amount_thb - self.remaining_thb,
            'used_percent': round((1 - self.remaining_thb / self.amount_thb) * 100, 1) if self.amount_thb > 0 else 0,
            'purchase_method': self.purchase_method, 'founder_name': self.founder_name,
            'tx_hash': self.tx_hash, 'notes': self.notes,
            'status': self.status.value if self.status else None
        }

class BankCard(Base):
    __tablename__ = 'bank_cards'
    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    bank_name = Column(String(100), nullable=False)
    card_name = Column(String(100))
    holder_name = Column(String(100))
    balance_thb = Column(Float, default=0)
    notes = Column(Text)
    status = Column(SQLEnum(CashBatchStatus), default=CashBatchStatus.ACTIVE)
    allocations = relationship("CardAllocation", back_populates="card")
    topups = relationship("CardTopup", back_populates="card")
    
    def to_dict(self):
        total_thb = sum(t.amount_thb for t in self.topups) if self.topups else 0
        total_usdt = sum(t.cost_usdt for t in self.topups) if self.topups else 0
        avg_rate = total_thb / total_usdt if total_usdt > 0 else 0
        return {
            'id': self.id, 'created_at': self.created_at.isoformat() if self.created_at else None,
            'bank_name': self.bank_name, 'card_name': self.card_name, 'holder_name': self.holder_name,
            'balance_thb': self.balance_thb, 'avg_rate': round(avg_rate, 4) if avg_rate else 0,
            'status': self.status.value if self.status else None,
            'topups': [t.to_dict() for t in self.topups] if self.topups else []
        }

class CardTopup(Base):
    __tablename__ = 'card_topups'
    id = Column(Integer, primary_key=True)
    card_id = Column(Integer, ForeignKey('bank_cards.id'), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    amount_thb = Column(Float, nullable=False)
    cost_usdt = Column(Float, nullable=False)
    purchase_rate = Column(Float, nullable=False)
    source_type = Column(String(50))
    source_batch_id = Column(Integer, ForeignKey('cash_batches.id'), nullable=True)
    notes = Column(Text)
    card = relationship("BankCard", back_populates="topups")
    
    def to_dict(self):
        return {'id': self.id, 'card_id': self.card_id, 'amount_thb': self.amount_thb,
                'cost_usdt': self.cost_usdt, 'purchase_rate': self.purchase_rate,
                'source_type': self.source_type, 'source_batch_id': self.source_batch_id,
                'created_at': self.created_at.isoformat() if self.created_at else None}

class Reimbursement(Base):
    __tablename__ = 'reimbursements'
    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    founder_name = Column(String(100), nullable=False)
    amount_usdt = Column(Float, nullable=False)
    tx_hash = Column(String(100))
    tx_verified = Column(Boolean, default=False)
    notes = Column(Text)
    deals = relationship("Deal", back_populates="reimbursement")
    
    def to_dict(self):
        return {'id': self.id, 'founder_name': self.founder_name, 'amount_usdt': self.amount_usdt,
                'tx_hash': self.tx_hash, 'tx_verified': self.tx_verified,
                'created_at': self.created_at.isoformat() if self.created_at else None}

class CashAllocation(Base):
    __tablename__ = 'cash_allocations'
    id = Column(Integer, primary_key=True)
    deal_id = Column(Integer, ForeignKey('deals.id'), nullable=False)
    batch_id = Column(Integer, ForeignKey('cash_batches.id'), nullable=False)
    amount_thb = Column(Float, nullable=False)
    cost_usdt = Column(Float, nullable=False)
    batch_rate = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    deal = relationship("Deal", back_populates="cash_allocations")
    batch = relationship("CashBatch", back_populates="allocations")
    
    def to_dict(self):
        return {'id': self.id, 'deal_id': self.deal_id, 'batch_id': self.batch_id,
                'amount_thb': self.amount_thb, 'cost_usdt': self.cost_usdt, 'batch_rate': self.batch_rate}

class CardAllocation(Base):
    __tablename__ = 'card_allocations'
    id = Column(Integer, primary_key=True)
    deal_id = Column(Integer, ForeignKey('deals.id'), nullable=False)
    card_id = Column(Integer, ForeignKey('bank_cards.id'), nullable=False)
    amount_thb = Column(Float, nullable=False)
    cost_usdt = Column(Float, nullable=False)
    card_rate = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    deal = relationship("Deal", back_populates="card_allocations")
    card = relationship("BankCard", back_populates="allocations")

class Transaction(Base):
    __tablename__ = 'transactions'
    id = Column(Integer, primary_key=True)
    tx_hash = Column(String(100), unique=True, nullable=False)
    blockchain = Column(String(20), default='TRON')
    from_address = Column(String(100))
    to_address = Column(String(100))
    amount_usdt = Column(Float)
    timestamp = Column(DateTime)
    confirmed = Column(Boolean, default=False)
    deal_id = Column(Integer, ForeignKey('deals.id'), nullable=True)
    deal = relationship("Deal", back_populates="transactions")

class Wallet(Base):
    __tablename__ = 'wallets'
    id = Column(Integer, primary_key=True)
    address = Column(String(100), unique=True, nullable=False)
    blockchain = Column(String(20), default='TRON')
    label = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)
    active = Column(Boolean, default=True)
    
    def to_dict(self):
        return {
            'id': self.id, 'address': self.address, 'blockchain': self.blockchain,
            'label': self.label, 'created_at': self.created_at.isoformat() if self.created_at else None,
            'active': self.active
        }

class Deal(Base):
    __tablename__ = 'deals'
    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    manager_name = Column(String(100))
    deal_type = Column(SQLEnum(DealType), nullable=False)
    status = Column(SQLEnum(DealStatus), default=DealStatus.PENDING)
    client_id = Column(Integer, ForeignKey('clients.id'), nullable=True)
    client = relationship("Client", back_populates="deals")
    client_name = Column(String(100))
    payin_method = Column(SQLEnum(PayInMethod), nullable=True)
    payin_amount_rub = Column(Float)
    payin_amount_thb = Column(Float)
    payin_amount_usdt = Column(Float)
    payin_rate_rub_usdt = Column(Float)
    payin_rate_usdt_thb = Column(Float)
    payin_partner_name = Column(String(100))
    payin_tx_hash = Column(String(100))
    payin_tx_verified = Column(Boolean, default=False)
    doverka_transaction_id = Column(String(100))
    doverka_status = Column(SQLEnum(DoverkaStatus), nullable=True)
    doverka_payout_hash = Column(String(100))
    doverka_confirmed_at = Column(DateTime)
    payout_method = Column(SQLEnum(PayOutMethod), nullable=True)
    payout_source = Column(SQLEnum(PayOutSource), nullable=True)
    payout_amount_thb = Column(Float)
    payout_amount_usdt = Column(Float)
    payout_tx_hash = Column(String(100))
    cash_batch_id = Column(Integer, ForeignKey('cash_batches.id'), nullable=True)
    cash_batch = relationship("CashBatch", back_populates="deals")
    cash_batch_rate = Column(Float)
    payout_founder_name = Column(String(100))
    reimbursement_id = Column(Integer, ForeignKey('reimbursements.id'), nullable=True)
    reimbursement = relationship("Reimbursement", back_populates="deals")
    profit_usdt = Column(Float)
    profit_percent = Column(Float)
    exchange_rate = Column(Float)
    referrer_name = Column(String(100))
    referrer_percent = Column(Float)
    referrer_fixed_usdt = Column(Float)
    referrer_payout_usdt = Column(Float)
    referrer_paid = Column(Boolean, default=False)
    net_profit_usdt = Column(Float)
    is_custom = Column(Boolean, default=False)
    custom_payin_currency = Column(String(10))
    custom_payin_amount = Column(Float)
    custom_payin_rate = Column(Float)
    custom_payout_currency = Column(String(10))
    custom_payout_amount = Column(Float)
    custom_payout_rate = Column(Float)
    notes = Column(Text)
    transactions = relationship("Transaction", back_populates="deal")
    cash_allocations = relationship("CashAllocation", back_populates="deal")
    card_allocations = relationship("CardAllocation", back_populates="deal")
    
    def to_dict(self):
        return {
            'id': self.id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'manager_name': self.manager_name,
            'deal_type': self.deal_type.value if self.deal_type else None,
            'status': self.status.value if self.status else None,
            'client_id': self.client_id,
            'client_name': self.client.name if self.client else self.client_name,
            'client': self.client.to_dict() if self.client else None,
            'payin_method': self.payin_method.value if self.payin_method else None,
            'payin_amount_rub': self.payin_amount_rub,
            'payin_amount_usdt': self.payin_amount_usdt,
            'payin_rate_rub_usdt': self.payin_rate_rub_usdt,
            'payin_tx_hash': self.payin_tx_hash,
            'payin_tx_verified': self.payin_tx_verified,
            'payin_partner_name': self.payin_partner_name,
            'doverka_transaction_id': self.doverka_transaction_id,
            'doverka_status': self.doverka_status.value if self.doverka_status else None,
            'doverka_payout_hash': self.doverka_payout_hash,
            'payout_method': self.payout_method.value if self.payout_method else None,
            'payout_source': self.payout_source.value if self.payout_source else None,
            'payout_amount_thb': self.payout_amount_thb,
            'payout_amount_usdt': self.payout_amount_usdt,
            'payout_tx_hash': self.payout_tx_hash,
            'cash_batch_rate': self.cash_batch_rate,
            'payout_founder_name': self.payout_founder_name,
            'profit_usdt': self.profit_usdt,
            'profit_percent': self.profit_percent,
            'net_profit_usdt': self.net_profit_usdt,
            'referrer_name': self.referrer_name,
            'referrer_percent': self.referrer_percent,
            'referrer_payout_usdt': self.referrer_payout_usdt,
            'is_custom': self.is_custom,
            'custom_payin_currency': self.custom_payin_currency,
            'custom_payin_amount': self.custom_payin_amount,
            'custom_payin_rate': self.custom_payin_rate,
            'custom_payout_currency': self.custom_payout_currency,
            'custom_payout_amount': self.custom_payout_amount,
            'custom_payout_rate': self.custom_payout_rate,
            'notes': self.notes
        }

# Создание таблиц
Base.metadata.create_all(bind=engine)
print("✅ Database initialized")

# ==================== WEBHOOK CONFIG ====================
WEBHOOK_URL = os.environ.get('CRM_WEBHOOK_URL', '')

def send_webhook_async(url, data):
    def _send():
        try:
            response = requests.post(url, json=data, timeout=10)
            print(f"✅ Webhook sent: {response.status_code}")
        except Exception as e:
            print(f"❌ Webhook error: {e}")
    if url:
        threading.Thread(target=_send).start()

def send_deal_completed_webhook(deal):
    if not WEBHOOK_URL:
        return
    data = {
        'event': 'deal_completed',
        'timestamp': datetime.now().isoformat(),
        'deal': deal.to_dict()
    }
    send_webhook_async(WEBHOOK_URL, data)

# ==================== CALCULATOR IMPORTS ====================
from calculator import ExchangeRateProvider, ExchangeCalculator

# ==================== PAGES ====================

@app.route('/')
def calculator_index():
    """Главная страница - Калькулятор"""
    return send_from_directory('static/calculator', 'index.html')

@app.route('/crm')
def crm_index():
    """CRM страница"""
    response = send_from_directory('static/crm', 'crm.html')
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

# ==================== CALCULATOR API ====================

@app.route('/api/rates', methods=['GET'])
def get_rates():
    try:
        rates = asyncio.run(ExchangeRateProvider.get_all_rates())
        usdt_thb = rates.get('usdt_thb') or 35.20
        rub_usdt = rates.get('rub_usdt') or 86.50
        return jsonify({'usdt_thb': usdt_thb, 'rub_usdt': rub_usdt, 'success': True})
    except Exception as e:
        return jsonify({'error': str(e), 'usdt_thb': 35.20, 'rub_usdt': 86.50, 'success': False})

@app.route('/api/calculate', methods=['POST'])
def calculate():
    try:
        data = request.get_json()
        method = data.get('method', 'doverka')
        scenario = data.get('scenario', 'rub-to-thb')
        direction = data.get('direction', 'amount')
        amount = float(data.get('amount', 0))
        
        if amount <= 0:
            return jsonify({'error': 'Invalid amount'}), 400
        
        rates = asyncio.run(ExchangeRateProvider.get_all_rates())
        
        if method == 'broker':
            from broker_detailed import BrokerCalculatorDetailed
            custom_rub_usdt = float(data.get('custom_rub_usdt', 80.9))
            profit_margin = float(data.get('profit_margin', 4.0))
            broker_calc = BrokerCalculatorDetailed(rates['usdt_thb'], custom_rub_usdt, profit_margin)
            
            if scenario == 'rub-to-thb':
                result = broker_calc.rub_to_thb_target(amount) if direction == 'target' else broker_calc.rub_to_thb_amount(amount)
            elif scenario == 'thb-to-usdt':
                result = broker_calc.thb_to_usdt_target(amount) if direction == 'target' else broker_calc.thb_to_usdt_amount(amount)
            elif scenario == 'usdt-to-thb':
                result = broker_calc.usdt_to_thb_target(amount) if direction == 'target' else broker_calc.usdt_to_thb_amount(amount)
            elif scenario == 'rub-to-usdt':
                result = broker_calc.rub_to_usdt_target(amount) if direction == 'target' else broker_calc.rub_to_usdt_amount(amount)
            else:
                return jsonify({'error': 'Invalid scenario'}), 400
        else:
            calculator = ExchangeCalculator(rates['usdt_thb'], rates['rub_usdt'])
            profit_margin = float(data.get('profit_margin')) if data.get('profit_margin') else None
            
            if scenario == 'rub-to-thb':
                result = calculator.rub_to_thb_target(amount, custom_profit_margin=profit_margin) if direction == 'target' else calculator.rub_to_thb(amount, custom_profit_margin=profit_margin)
            elif scenario == 'thb-to-usdt':
                result = calculator.thb_to_usdt_target(amount, custom_profit_margin=profit_margin) if direction == 'target' else calculator.thb_to_usdt(amount, custom_profit_margin=profit_margin)
            elif scenario == 'usdt-to-thb':
                result = calculator.usdt_to_thb_target(amount, custom_profit_margin=profit_margin) if direction == 'target' else calculator.usdt_to_thb(amount, custom_profit_margin=profit_margin)
            elif scenario == 'rub-to-usdt':
                result = calculator.rub_to_usdt_target(amount, custom_profit_margin=profit_margin) if direction == 'target' else calculator.rub_to_usdt_amount(amount, custom_profit_margin=profit_margin)
            else:
                return jsonify({'error': 'Invalid scenario'}), 400
        
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== CRM API - DEALS ====================

@app.route('/api/deals', methods=['GET'])
def get_deals():
    session = get_session()
    try:
        query = session.query(Deal).order_by(Deal.created_at.desc())
        status = request.args.get('status')
        if status:
            query = query.filter(Deal.status == DealStatus(status))
        limit = int(request.args.get('limit', 50))
        deals = query.limit(limit).all()
        return jsonify({'success': True, 'count': len(deals), 'deals': [d.to_dict() for d in deals]})
    finally:
        session.close()

@app.route('/api/deals/<int:deal_id>', methods=['GET'])
def get_deal(deal_id):
    session = get_session()
    try:
        deal = session.query(Deal).filter(Deal.id == deal_id).first()
        if not deal:
            return jsonify({'success': False, 'error': 'Сделка не найдена'}), 404
        return jsonify({'success': True, 'deal': deal.to_dict()})
    finally:
        session.close()

@app.route('/api/deals', methods=['POST'])
def create_deal():
    session = get_session()
    try:
        data = request.get_json()
        
        # #region agent log
        print(f"[DEBUG] create_deal: keys={list(data.keys()) if data else []}, created_at={data.get('created_at')}, type={type(data.get('created_at')).__name__ if data else None}")
        # #endregion
        
        # Парсим дату если передана
        created_at = None
        if data.get('created_at'):
            try:
                # Поддерживаем разные форматы даты
                date_str = data['created_at']
                # #region agent log
                print(f"[DEBUG] Parsing date: date_str={date_str}, has_T={'T' in str(date_str)}")
                # #endregion
                if 'T' in date_str:
                    created_at = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                else:
                    created_at = datetime.strptime(date_str, '%Y-%m-%d')
                # #region agent log
                print(f"[DEBUG] Date parsed OK: created_at={created_at}")
                # #endregion
            except Exception as parse_err:
                # #region agent log
                print(f"[DEBUG] Date parse FAILED: error={parse_err}")
                # #endregion
                created_at = datetime.now()
        else:
            # #region agent log
            print(f"[DEBUG] No created_at in request, using now()")
            # #endregion
            created_at = datetime.now()
        
        deal = Deal(
            created_at=created_at,
            manager_name=data.get('manager_name'),
            deal_type=DealType(data.get('deal_type', 'pay_in')),
            status=DealStatus(data.get('status', 'pending')),
            client_name=data.get('client_name'),
            payin_method=PayInMethod(data['payin_method']) if data.get('payin_method') else None,
            payin_amount_rub=data.get('payin_amount_rub'),
            payin_amount_usdt=data.get('payin_amount_usdt'),
            payin_rate_rub_usdt=data.get('payin_rate_rub_usdt'),
            payin_tx_hash=data.get('payin_tx_hash'),
            doverka_transaction_id=data.get('doverka_transaction_id'),
            payout_method=PayOutMethod(data['payout_method']) if data.get('payout_method') else None,
            payout_source=PayOutSource(data['payout_source']) if data.get('payout_source') else None,
            payout_amount_thb=data.get('payout_amount_thb'),
            payout_amount_usdt=data.get('payout_amount_usdt'),
            payout_tx_hash=data.get('payout_tx_hash'),
            payout_founder_name=data.get('payout_founder_name'),
            referrer_name=data.get('referrer_name'),
            referrer_percent=data.get('referrer_percent'),
            profit_usdt=data.get('profit_usdt'),
            profit_percent=data.get('profit_percent'),
            net_profit_usdt=data.get('net_profit_usdt'),
            is_custom=data.get('is_custom', False),
            custom_payin_currency=data.get('custom_payin_currency'),
            custom_payin_amount=data.get('custom_payin_amount'),
            custom_payin_rate=data.get('custom_payin_rate'),
            custom_payout_currency=data.get('custom_payout_currency'),
            custom_payout_amount=data.get('custom_payout_amount'),
            custom_payout_rate=data.get('custom_payout_rate'),
            notes=data.get('notes')
        )
        session.add(deal)
        session.commit()
        return jsonify({'success': True, 'deal': deal.to_dict()}), 201
    except Exception as e:
        session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        session.close()

@app.route('/api/deals/<int:deal_id>', methods=['PUT'])
def update_deal(deal_id):
    session = get_session()
    try:
        deal = session.query(Deal).filter(Deal.id == deal_id).first()
        if not deal:
            return jsonify({'success': False, 'error': 'Сделка не найдена'}), 404
        
        data = request.get_json()
        old_status = deal.status
        
        # Обновляем дату если передана
        if data.get('created_at'):
            try:
                date_str = data['created_at']
                if 'T' in date_str:
                    deal.created_at = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                else:
                    deal.created_at = datetime.strptime(date_str, '%Y-%m-%d')
            except:
                pass
        
        for field in ['manager_name', 'client_name', 'payin_amount_rub', 'payin_amount_usdt',
                      'payin_rate_rub_usdt', 'payin_tx_hash', 'payout_amount_thb', 'payout_amount_usdt',
                      'payout_tx_hash', 'profit_usdt', 'profit_percent', 'net_profit_usdt', 'referrer_name',
                      'referrer_percent', 'referrer_payout_usdt', 'notes']:
            if field in data:
                setattr(deal, field, data[field])
        
        if 'status' in data:
            deal.status = DealStatus(data['status'])
        
        session.commit()
        
        # Webhook при завершении
        if deal.status == DealStatus.COMPLETED and old_status != DealStatus.COMPLETED:
            send_deal_completed_webhook(deal)
        
        return jsonify({'success': True, 'deal': deal.to_dict()})
    except Exception as e:
        session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        session.close()

@app.route('/api/deals/<int:deal_id>', methods=['DELETE'])
def delete_deal(deal_id):
    session = get_session()
    try:
        deal = session.query(Deal).filter(Deal.id == deal_id).first()
        if not deal:
            return jsonify({'success': False, 'error': 'Сделка не найдена'}), 404
        session.delete(deal)
        session.commit()
        return jsonify({'success': True})
    except Exception as e:
        session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        session.close()

# ==================== CRM API - CASH BATCHES ====================

@app.route('/api/cash/batches', methods=['GET'])
def get_cash_batches():
    session = get_session()
    try:
        batches = session.query(CashBatch).order_by(CashBatch.created_at.desc()).all()
        total_remaining = sum(b.remaining_thb for b in batches if b.status == CashBatchStatus.ACTIVE)
        total_cost_usdt = sum((b.remaining_thb / b.purchase_rate) if b.purchase_rate else 0 
                              for b in batches if b.status == CashBatchStatus.ACTIVE)
        weighted_rate = total_remaining / total_cost_usdt if total_cost_usdt > 0 else 0
        return jsonify({
            'success': True, 'batches': [b.to_dict() for b in batches],
            'summary': {'total_remaining_thb': total_remaining, 'total_cost_usdt': round(total_cost_usdt, 2),
                        'weighted_avg_rate': round(weighted_rate, 4)}
        })
    finally:
        session.close()

@app.route('/api/cash/batches', methods=['POST'])
def create_cash_batch():
    session = get_session()
    try:
        data = request.get_json()
        amount_thb = float(data['amount_thb'])
        cost_usdt = float(data['cost_usdt'])
        batch = CashBatch(
            amount_thb=amount_thb, cost_usdt=cost_usdt,
            purchase_rate=amount_thb / cost_usdt, remaining_thb=amount_thb,
            purchase_method=data.get('purchase_method'), founder_name=data.get('founder_name'),
            tx_hash=data.get('tx_hash'), notes=data.get('notes'), status=CashBatchStatus.ACTIVE
        )
        session.add(batch)
        session.commit()
        return jsonify({'success': True, 'batch': batch.to_dict()}), 201
    except Exception as e:
        session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        session.close()

@app.route('/api/cash/batches/<int:batch_id>/adjust', methods=['POST'])
def adjust_cash_batch(batch_id):
    session = get_session()
    try:
        data = request.get_json()
        new_remaining = float(data.get('new_remaining', 0))
        reason = data.get('reason', 'Ручная корректировка')
        
        batch = session.query(CashBatch).filter(CashBatch.id == batch_id).first()
        if not batch:
            return jsonify({'success': False, 'error': 'Партия не найдена'}), 404
        
        old_remaining = batch.remaining_thb
        batch.remaining_thb = new_remaining
        batch.status = CashBatchStatus.DEPLETED if new_remaining <= 0 else CashBatchStatus.ACTIVE
        
        change_note = f"\n[{datetime.now().strftime('%d.%m.%Y %H:%M')}] {old_remaining:,.0f} → {new_remaining:,.0f} THB ({reason})"
        batch.notes = (batch.notes or '') + change_note
        
        session.commit()
        return jsonify({'success': True, 'batch': batch.to_dict()})
    except Exception as e:
        session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        session.close()

# ==================== CRM API - MANAGERS ====================

@app.route('/api/managers', methods=['GET'])
def get_managers():
    session = get_session()
    try:
        managers = session.query(Manager).order_by(Manager.name).all()
        return jsonify({'success': True, 'managers': [m.to_dict() for m in managers]})
    finally:
        session.close()

@app.route('/api/managers', methods=['POST'])
def create_manager():
    session = get_session()
    try:
        data = request.get_json()
        name = data.get('name', '').strip()
        if not name:
            return jsonify({'success': False, 'error': 'Имя обязательно'}), 400
        manager = Manager(name=name)
        session.add(manager)
        session.commit()
        return jsonify({'success': True, 'manager': manager.to_dict()})
    except Exception as e:
        session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        session.close()

# ==================== CRM API - WALLETS ====================

@app.route('/api/wallets', methods=['GET'])
def get_wallets():
    session = get_session()
    try:
        wallets = session.query(Wallet).filter(Wallet.active == True).order_by(Wallet.created_at.desc()).all()
        wallets_with_balance = []
        
        for wallet in wallets:
            wallet_data = wallet.to_dict()
            wallet_data['usdt_balance'] = 0
            wallet_data['trx_balance'] = 0
            
            # Получаем баланс с TronScan
            try:
                balance_url = f'https://apilist.tronscanapi.com/api/account?address={wallet.address}'
                balance_resp = requests.get(balance_url, timeout=5)
                if balance_resp.status_code == 200:
                    balance_data = balance_resp.json()
                    wallet_data['trx_balance'] = float(balance_data.get('balance', 0)) / 1_000_000
                    for token in balance_data.get('trc20token_balances', []):
                        if token.get('tokenId') == 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t':
                            wallet_data['usdt_balance'] = float(token.get('balance', 0)) / 1_000_000
                            break
            except:
                pass
            
            wallets_with_balance.append(wallet_data)
        
        return jsonify({'success': True, 'wallets': wallets_with_balance})
    finally:
        session.close()

@app.route('/api/wallets', methods=['POST'])
def add_wallet():
    session = get_session()
    try:
        data = request.get_json()
        address = data.get('address', '').strip()
        if not address:
            return jsonify({'success': False, 'error': 'Адрес обязателен'}), 400
        
        # Проверяем что кошелёк не дублируется
        existing = session.query(Wallet).filter(Wallet.address == address).first()
        if existing:
            return jsonify({'success': False, 'error': 'Кошелёк уже добавлен'}), 400
        
        wallet = Wallet(
            address=address,
            blockchain=data.get('blockchain', 'TRON'),
            label=data.get('label', '')
        )
        session.add(wallet)
        session.commit()
        
        # Frontend ожидает usdt_balance и trx_balance
        wallet_data = wallet.to_dict()
        wallet_data['usdt_balance'] = 0
        wallet_data['trx_balance'] = 0
        
        # Попробуем получить реальный баланс
        try:
            balance_url = f'https://apilist.tronscanapi.com/api/account?address={address}'
            balance_resp = requests.get(balance_url, timeout=5)
            if balance_resp.status_code == 200:
                balance_data = balance_resp.json()
                # TRX баланс
                wallet_data['trx_balance'] = float(balance_data.get('balance', 0)) / 1_000_000
                # USDT баланс (ищем в trc20token_balances)
                for token in balance_data.get('trc20token_balances', []):
                    if token.get('tokenId') == 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t':
                        wallet_data['usdt_balance'] = float(token.get('balance', 0)) / 1_000_000
                        break
        except:
            pass
        
        return jsonify({'success': True, 'wallet': wallet_data})
    except Exception as e:
        session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        session.close()

@app.route('/api/wallets/<int:wallet_id>', methods=['DELETE'])
def delete_wallet(wallet_id):
    session = get_session()
    try:
        wallet = session.query(Wallet).filter(Wallet.id == wallet_id).first()
        if not wallet:
            return jsonify({'success': False, 'error': 'Кошелёк не найден'}), 404
        session.delete(wallet)
        session.commit()
        return jsonify({'success': True})
    except Exception as e:
        session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        session.close()

# ==================== TRANSACTIONS API (Frontend compatible) ====================

@app.route('/api/transactions/incoming', methods=['GET'])
def get_incoming_transactions():
    """Получить входящие USDT транзакции по всем кошелькам"""
    session = get_session()
    try:
        wallets = session.query(Wallet).filter(Wallet.active == True).all()
        
        if not wallets:
            return jsonify({
                'success': True,
                'available': [],
                'used': [],
                'wallets_checked': []
            })
        
        all_incoming = []
        wallets_checked = []
        
        for wallet in wallets:
            wallets_checked.append(wallet.address)
            try:
                # TronScan API
                usdt_contract = 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t'
                url = 'https://apilist.tronscanapi.com/api/token_trc20/transfers'
                params = {
                    'relatedAddress': wallet.address,
                    'contract_address': usdt_contract,
                    'limit': 50,
                    'start': 0
                }
                
                response = requests.get(url, params=params, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    for tx in data.get('token_transfers', []):
                        # Только входящие (to_address == наш кошелёк)
                        if tx.get('to_address') == wallet.address:
                            amount = float(tx.get('quant', 0)) / 1_000_000
                            all_incoming.append({
                                'tx_hash': tx.get('transaction_id'),
                                'from_address': tx.get('from_address'),
                                'to_address': tx.get('to_address'),
                                'amount_usdt': amount,
                                'timestamp': datetime.fromtimestamp(tx.get('block_ts', 0) / 1000).isoformat(),
                                'confirmed': tx.get('confirmed', False)
                            })
            except Exception as e:
                print(f"[DEBUG] TronScan error for {wallet.address}: {e}")
        
        # Получаем использованные транзакции из БД
        used_txs = session.query(Transaction).filter(Transaction.deal_id != None).all()
        used_hashes = {tx.tx_hash for tx in used_txs}
        
        # Фильтруем: available = не использованные
        available = [tx for tx in all_incoming if tx['tx_hash'] not in used_hashes]
        used = [tx for tx in all_incoming if tx['tx_hash'] in used_hashes]
        
        return jsonify({
            'success': True,
            'available': available,
            'used': used,
            'wallets_checked': wallets_checked
        })
    except Exception as e:
        print(f"[DEBUG] get_incoming_transactions error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        session.close()

@app.route('/api/transactions/outgoing', methods=['GET'])
def get_outgoing_transactions():
    """Получить исходящие USDT транзакции по всем кошелькам"""
    session = get_session()
    try:
        wallets = session.query(Wallet).filter(Wallet.active == True).all()
        
        if not wallets:
            return jsonify({'success': True, 'available': []})
        
        all_outgoing = []
        
        for wallet in wallets:
            try:
                usdt_contract = 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t'
                url = 'https://apilist.tronscanapi.com/api/token_trc20/transfers'
                params = {
                    'relatedAddress': wallet.address,
                    'contract_address': usdt_contract,
                    'limit': 50,
                    'start': 0
                }
                
                response = requests.get(url, params=params, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    for tx in data.get('token_transfers', []):
                        # Только исходящие (from_address == наш кошелёк)
                        if tx.get('from_address') == wallet.address:
                            amount = float(tx.get('quant', 0)) / 1_000_000
                            all_outgoing.append({
                                'tx_hash': tx.get('transaction_id'),
                                'from_address': tx.get('from_address'),
                                'to_address': tx.get('to_address'),
                                'amount_usdt': amount,
                                'timestamp': datetime.fromtimestamp(tx.get('block_ts', 0) / 1000).isoformat(),
                                'confirmed': tx.get('confirmed', False)
                            })
            except Exception as e:
                print(f"[DEBUG] TronScan outgoing error for {wallet.address}: {e}")
        
        return jsonify({'success': True, 'available': all_outgoing})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        session.close()

@app.route('/api/transactions/verify', methods=['POST'])
def verify_transaction_post():
    """Проверить транзакцию по хэшу (POST версия)"""
    try:
        data = request.get_json()
        tx_hash = data.get('tx_hash', '').strip()
        
        if not tx_hash:
            return jsonify({'success': False, 'error': 'Не указан хэш транзакции'}), 400
        
        url = f'https://apilist.tronscanapi.com/api/transaction-info?hash={tx_hash}'
        response = requests.get(url, timeout=10)
        
        if response.status_code != 200:
            return jsonify({'success': False, 'error': 'Транзакция не найдена'}), 404
        
        tx_data = response.json()
        
        # Парсим TRC20 transfer
        trc20_info = tx_data.get('trc20TransferInfo', [])
        if trc20_info:
            transfer = trc20_info[0]
            amount = float(transfer.get('amount_str', 0)) / 1_000_000
            return jsonify({
                'success': True,
                'tx_hash': tx_hash,
                'from_address': transfer.get('from_address'),
                'to_address': transfer.get('to_address'),
                'amount_usdt': amount,
                'confirmed': tx_data.get('confirmed', False),
                'timestamp': datetime.fromtimestamp(tx_data.get('timestamp', 0) / 1000).isoformat()
            })
        
        return jsonify({'success': False, 'error': 'Не USDT транзакция'}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ==================== TRONSCAN API (legacy) ====================

@app.route('/api/tronscan/transactions/<address>', methods=['GET'])
def get_tronscan_transactions(address):
    """Получить USDT транзакции с TronScan API"""
    try:
        # TronScan API для TRC20 транзакций (USDT)
        usdt_contract = 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t'
        url = f'https://apilist.tronscanapi.com/api/token_trc20/transfers'
        params = {
            'relatedAddress': address,
            'contract_address': usdt_contract,
            'limit': 50,
            'start': 0
        }
        
        response = requests.get(url, params=params, timeout=10)
        if response.status_code != 200:
            return jsonify({'success': False, 'error': f'TronScan API error: {response.status_code}'}), 500
        
        data = response.json()
        transactions = []
        
        for tx in data.get('token_transfers', []):
            # Конвертируем количество (USDT имеет 6 decimals)
            amount = float(tx.get('quant', 0)) / 1_000_000
            
            transactions.append({
                'tx_hash': tx.get('transaction_id'),
                'from_address': tx.get('from_address'),
                'to_address': tx.get('to_address'),
                'amount_usdt': amount,
                'timestamp': datetime.fromtimestamp(tx.get('block_ts', 0) / 1000).isoformat(),
                'confirmed': tx.get('confirmed', False),
                'direction': 'in' if tx.get('to_address') == address else 'out'
            })
        
        return jsonify({
            'success': True,
            'address': address,
            'transactions': transactions,
            'total': len(transactions)
        })
    except requests.exceptions.Timeout:
        return jsonify({'success': False, 'error': 'TronScan API timeout'}), 500
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/tronscan/verify/<tx_hash>', methods=['GET'])
def verify_transaction(tx_hash):
    """Проверить транзакцию по хэшу"""
    try:
        url = f'https://apilist.tronscanapi.com/api/transaction-info?hash={tx_hash}'
        response = requests.get(url, timeout=10)
        
        if response.status_code != 200:
            return jsonify({'success': False, 'error': 'Транзакция не найдена'}), 404
        
        data = response.json()
        
        # Парсим TRC20 transfer
        trc20_info = data.get('trc20TransferInfo', [])
        if trc20_info:
            transfer = trc20_info[0]
            amount = float(transfer.get('amount_str', 0)) / 1_000_000
            return jsonify({
                'success': True,
                'tx_hash': tx_hash,
                'from_address': transfer.get('from_address'),
                'to_address': transfer.get('to_address'),
                'amount_usdt': amount,
                'confirmed': data.get('confirmed', False),
                'timestamp': datetime.fromtimestamp(data.get('timestamp', 0) / 1000).isoformat()
            })
        
        return jsonify({'success': False, 'error': 'Не USDT транзакция'}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ==================== CRM API - CLIENTS ====================

@app.route('/api/clients', methods=['GET'])
def get_clients():
    session = get_session()
    try:
        clients = session.query(Client).order_by(Client.total_deals.desc()).limit(50).all()
        return jsonify({'success': True, 'clients': [c.to_dict() for c in clients]})
    finally:
        session.close()

# ==================== CRM API - DASHBOARD ====================

@app.route('/api/analytics/dashboard', methods=['GET'])
def get_dashboard():
    session = get_session()
    try:
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        week_ago = today - timedelta(days=7)
        
        today_deals = session.query(Deal).filter(Deal.created_at >= today).all()
        week_deals = session.query(Deal).filter(Deal.created_at >= week_ago).all()
        cash_batches = session.query(CashBatch).filter(CashBatch.status == CashBatchStatus.ACTIVE).all()
        pending_deals = session.query(Deal).filter(Deal.status == DealStatus.PENDING).all()
        
        return jsonify({
            'success': True,
            'dashboard': {
                'today': {
                    'deals_count': len(today_deals),
                    'profit_usdt': round(sum(d.net_profit_usdt or d.profit_usdt or 0 for d in today_deals), 2),
                    'volume_usdt': round(sum(d.payin_amount_usdt or 0 for d in today_deals), 2)
                },
                'week': {
                    'deals_count': len(week_deals),
                    'profit_usdt': round(sum(d.net_profit_usdt or d.profit_usdt or 0 for d in week_deals), 2)
                },
                'cash_balance': {
                    'total_thb': sum(b.remaining_thb for b in cash_batches),
                    'batches_count': len(cash_batches)
                },
                'attention': {
                    'pending_deals': len(pending_deals)
                }
            }
        })
    finally:
        session.close()

# ==================== REIMBURSEMENTS API ====================

@app.route('/api/reimbursements/pending', methods=['GET'])
def get_pending_reimbursements():
    """Get deals awaiting reimbursement, grouped by founder"""
    session = get_session()
    try:
        # Find deals with founder_personal source that haven't been reimbursed
        deals = session.query(Deal).filter(
            Deal.payout_source == PayOutSource.FOUNDER_PERSONAL,
            Deal.reimbursement_id == None,
            Deal.payout_founder_name != None
        ).order_by(Deal.payout_founder_name, Deal.created_at.desc()).all()
        
        # Group by founder
        by_founder = {}
        for deal in deals:
            founder = deal.payout_founder_name
            if founder not in by_founder:
                by_founder[founder] = []
            by_founder[founder].append(deal.to_dict())
        
        result = [{'founder_name': k, 'deals': v} for k, v in by_founder.items()]
        return jsonify({'success': True, 'by_founder': result})
    finally:
        session.close()

@app.route('/api/reimbursements', methods=['GET'])
def get_reimbursements():
    """Get reimbursement history"""
    session = get_session()
    try:
        reimbursements = session.query(Reimbursement).order_by(Reimbursement.created_at.desc()).all()
        result = []
        for r in reimbursements:
            data = r.to_dict()
            data['deals_count'] = len(r.deals)
            result.append(data)
        return jsonify({'success': True, 'reimbursements': result})
    finally:
        session.close()

@app.route('/api/reimbursements', methods=['POST'])
def create_reimbursement():
    """Create a reimbursement for founder"""
    session = get_session()
    try:
        data = request.get_json()
        founder_name = data.get('founder_name')
        deal_ids = data.get('deal_ids', [])
        amount_usdt = data.get('amount_usdt')
        tx_hash = data.get('tx_hash')
        
        if not founder_name or not deal_ids or not amount_usdt:
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400
        
        # Create reimbursement
        reimbursement = Reimbursement(
            founder_name=founder_name,
            amount_usdt=amount_usdt,
            tx_hash=tx_hash
        )
        session.add(reimbursement)
        session.flush()  # Get the ID
        
        # Update deals
        deals = session.query(Deal).filter(Deal.id.in_(deal_ids)).all()
        total_thb = 0
        for deal in deals:
            deal.reimbursement_id = reimbursement.id
            deal.payout_amount_usdt = amount_usdt * (deal.payout_amount_thb / sum(d.payout_amount_thb for d in deals)) if deal.payout_amount_thb else 0
            total_thb += deal.payout_amount_thb or 0
            
            # Recalculate profit now that we know payout USDT
            if deal.payin_amount_usdt and deal.payout_amount_usdt:
                deal.profit_usdt = deal.payin_amount_usdt - deal.payout_amount_usdt
                deal.profit_percent = (deal.profit_usdt / deal.payout_amount_usdt * 100) if deal.payout_amount_usdt > 0 else 0
                
                # Recalculate net profit
                referrer_payout = deal.referrer_payout_usdt or 0
                deal.net_profit_usdt = deal.profit_usdt - referrer_payout
        
        session.commit()
        return jsonify({
            'success': True, 
            'reimbursement': reimbursement.to_dict(),
            'deals_updated': len(deals),
            'total_thb': total_thb
        })
    except Exception as e:
        session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        session.close()

# ==================== WEBHOOK CONFIG ====================

@app.route('/api/webhook/config', methods=['GET'])
def get_webhook_config():
    return jsonify({'success': True, 'webhook_url': WEBHOOK_URL, 'is_configured': bool(WEBHOOK_URL)})

@app.route('/api/webhook/config', methods=['POST'])
def set_webhook_config():
    global WEBHOOK_URL
    data = request.get_json()
    WEBHOOK_URL = data.get('webhook_url', '').strip()
    return jsonify({'success': True, 'webhook_url': WEBHOOK_URL})

# ==================== TELEGRAM NOTIFICATION ====================

def send_telegram_notification(text):
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID', '')
    if not token or not chat_id:
        return False
    try:
        response = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=10)
        return response.status_code == 200
    except:
        return False

@app.route('/api/webhook/doverka', methods=['POST'])
def doverka_webhook():
    try:
        data = request.get_json()
        if data.get('status') == 'PAID':
            metadata = data.get('metadata', {})
            msg = f"✅ <b>Оплата получена!</b>\n💰 Сумма: {data.get('amount_from')} {data.get('currency_symbol', 'RUB')}\n🆔 Заказ: {data.get('order_transaction_id')}"
            send_telegram_notification(msg)
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== HEALTH CHECK ====================

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({
        'success': True, 'status': 'ok',
        'service': 'CalcCRM Unified Service',
        'database': 'postgresql' if 'postgresql' in DATABASE_URL else 'sqlite',
        'timestamp': datetime.now().isoformat()
    })

# ==================== STATIC FILES ====================

@app.route('/calculator/<path:filename>')
def calculator_static(filename):
    return send_from_directory('static/calculator', filename)

@app.route('/crm/<path:filename>')
def crm_static(filename):
    return send_from_directory('static/crm', filename)

@app.route('/<path:filename>')
def static_files(filename):
    if filename.startswith('api'):
        return '', 404
    allowed = ['.css', '.js', '.png', '.jpg', '.svg', '.ico']
    if any(filename.endswith(ext) for ext in allowed):
        # Сначала ищем в calculator, потом в crm
        try:
            return send_from_directory('static/calculator', filename)
        except:
            return send_from_directory('static/crm', filename)
    return '', 404

# ==================== MAIN ====================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"\n🚀 CalcCRM Unified Service")
    print(f"📍 http://localhost:{port}")
    print(f"📍 http://localhost:{port}/crm")
    print(f"💾 Database: {'PostgreSQL' if 'postgresql' in DATABASE_URL else 'SQLite'}")
    app.run(debug=True, host='0.0.0.0', port=port)
