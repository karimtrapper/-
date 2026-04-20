"""
Unified Service: Calculator + CRM
Объединённый сервис калькулятора и CRM для Railway
"""

from flask import Flask, jsonify, request, send_from_directory, redirect, session as flask_session
from flask_cors import CORS
from datetime import datetime, timedelta
import os
import requests
import threading
import asyncio
import time
import json
import hashlib
import bcrypt
import logging
import gspread
from google.oauth2.service_account import Credentials as GoogleCredentials

# ==================== FLASK APP ====================
from werkzeug.middleware.proxy_fix import ProxyFix
app = Flask(__name__, static_folder='static')
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)  # Railway proxy
app.secret_key = os.environ['SECRET_KEY']  # Без fallback — crash если не задан
cors_origins = os.environ.get('CORS_ORIGINS', 'https://proud-renewal-production-e9b8.up.railway.app').split(',')
CORS(app, origins=cors_origins, supports_credentials=True)
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB макс размер загрузки
app.permanent_session_lifetime = timedelta(days=30)  # Сессия 30 дней
app.config['SESSION_COOKIE_SECURE'] = True            # Только HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True           # Нет доступа из JS
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'         # Защита от CSRF

# Rate limiting
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
limiter = Limiter(get_remote_address, app=app, default_limits=[])

# Публичные пути — без авторизации
PUBLIC_PATHS = [
    '/api/rates', '/api/calculate',           # Калькулятор
    '/api/kyc/status/', '/api/kyc/submit',    # KYC для клиентов
    '/api/partner/',                           # Партнёрский калькулятор
    '/api/ref/',                               # Реферальная статистика
    '/api/health',                             # Health check
    '/api/auth/',                              # Авторизация
]

@app.before_request
def check_auth():
    """Проверка авторизации для всех /api/* и /crm кроме публичных"""
    path = request.path

    # Статика, калькулятор, KYC-страница, логин, партнёрский ЛК — пропускаем
    if not path.startswith('/api/') and not path.startswith('/crm'):
        return None

    # Публичные API — пропускаем
    for pub in PUBLIC_PATHS:
        if path.startswith(pub):
            return None

    # Проверяем сессию
    if not flask_session.get('user_id'):
        if path.startswith('/api/'):
            return jsonify({'success': False, 'error': 'unauthorized'}), 401
        return redirect('/login')

# ==================== DATABASE ====================
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session

# Автоматически выбираем PostgreSQL для прода или SQLite для локальной разработки
DATABASE_URL = os.environ.get('DATABASE_URL', '')
if DATABASE_URL:
    # Railway PostgreSQL (иногда начинается с postgres://, нужно postgresql://)
    if DATABASE_URL.startswith('postgres://'):
        DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
    engine = create_engine(DATABASE_URL, echo=False, connect_args={'connect_timeout': 10})
else:
    # Локальная SQLite
    DATABASE_PATH = os.path.join(os.path.dirname(__file__), 'local.db')
    DATABASE_URL = f'sqlite:///{DATABASE_PATH}'
    engine = create_engine(DATABASE_URL, echo=False, connect_args={'check_same_thread': False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
Session = scoped_session(SessionLocal)

def get_session():
    return Session()

# ==================== TRONSCAN CACHE ====================
TRONSCAN_CACHE = {
    'incoming': {'data': None, 'timestamp': 0},
    'outgoing': {'data': None, 'timestamp': 0},
    'balances': {} # address -> {'data': data, 'timestamp': 0}
}
CACHE_TTL = 300 # 5 минут

# ==================== MODELS ====================
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, ForeignKey, Enum as SQLEnum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from enum import Enum

Base = declarative_base()

class AdminUser(Base):
    """Администратор/менеджер CRM"""
    __tablename__ = 'admin_users'
    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(128), nullable=False)
    display_name = Column(String(100))
    role = Column(String(20), default='admin')  # admin / manager (на будущее)
    created_at = Column(DateTime, default=datetime.utcnow)

    @staticmethod
    def hash_password(password):
        """Bcrypt хэш пароля"""
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    @staticmethod
    def _legacy_hash(password):
        """Старый SHA-256 хэш — только для миграции"""
        salt = 'grusha-salt-2026'
        return hashlib.sha256(f'{salt}{password}'.encode()).hexdigest()

    def check_password(self, password):
        """Проверка пароля с автомиграцией SHA-256 → bcrypt"""
        # Новый bcrypt хэш (начинается с $2b$)
        if self.password_hash.startswith('$2b$'):
            return bcrypt.checkpw(password.encode(), self.password_hash.encode())
        # Старый SHA-256 — проверяем и мигрируем
        if self.password_hash == self._legacy_hash(password):
            self.password_hash = self.hash_password(password)
            return True
        return False


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
    referrer_id = Column(Integer, ForeignKey('referrers.id'), nullable=True)
    referrer = relationship("Referrer", back_populates="referred_clients", foreign_keys=[referrer_id])
    deals = relationship("Deal", back_populates="client")

    def to_dict(self):
        return {'id': self.id, 'name': self.name, 'telegram': self.telegram, 'phone': self.phone,
                'total_deals': self.total_deals, 'total_volume_usdt': self.total_volume_usdt,
                'referrer_id': self.referrer_id,
                'referrer_name': self.referrer.name if self.referrer else None}

class Partner(Base):
    """Партнёр (риелтор) — доступ к персональному калькулятору по ссылке"""
    __tablename__ = 'partners'
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    token = Column(String(32), unique=True, nullable=False, index=True)
    markup_percent = Column(Float, default=1.4)  # Наценка сверх Binance
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id, 'name': self.name, 'token': self.token,
            'markup_percent': self.markup_percent, 'active': self.active,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class Referrer(Base):
    """Реферер — B2C клиент, который приводит новых клиентов за комиссию"""
    __tablename__ = 'referrers'
    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey('clients.id'), nullable=True)
    name = Column(String(100), nullable=False)
    code = Column(String(20), unique=True, nullable=False, index=True)
    token = Column(String(32), unique=True, nullable=False, index=True)
    telegram = Column(String(50))
    default_percent = Column(Float, default=10.0)
    payout_currency = Column(String(10), default='USDT')  # USDT или THB
    active = Column(Boolean, default=True)
    total_referred_clients = Column(Integer, default=0)
    total_deals = Column(Integer, default=0)
    total_earned_usdt = Column(Float, default=0)
    total_paid_usdt = Column(Float, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    notes = Column(Text)

    referred_clients = relationship("Client", back_populates="referrer", foreign_keys="Client.referrer_id")

    def to_dict(self):
        return {
            'id': self.id, 'client_id': self.client_id,
            'name': self.name, 'code': self.code, 'token': self.token,
            'telegram': self.telegram, 'default_percent': self.default_percent,
            'payout_currency': self.payout_currency or 'USDT',
            'active': self.active,
            'total_referred_clients': self.total_referred_clients,
            'total_deals': self.total_deals,
            'total_earned_usdt': self.total_earned_usdt,
            'total_paid_usdt': self.total_paid_usdt,
            'pending_usdt': round((self.total_earned_usdt or 0) - (self.total_paid_usdt or 0), 2),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'notes': self.notes,
            'referral_link': f'https://grusha.space/?ref={self.code}',
            'bot_link': f'https://t.me/exgreen_pro_bot?start=ref__{self.code.replace("-", "")}',
            'wa_link': f'https://api.whatsapp.com/send/?phone=66818429939&text=%D0%97%D0%B4%D1%80%D0%B0%D0%B2%D1%81%D1%82%D0%B2%D1%83%D0%B9%D1%82%D0%B5%21+%D0%A5%D0%BE%D1%87%D1%83+%D1%83%D1%82%D0%BE%D1%87%D0%BD%D0%B8%D1%82%D1%8C+%D0%B4%D0%B5%D1%82%D0%B0%D0%BB%D0%B8+%D0%BE%D0%B1%D0%BC%D0%B5%D0%BD%D0%B0.%0A%0A%28%D0%98%D1%81%D1%82%D0%BE%D1%87%D0%BD%D0%B8%D0%BA%3A+ref_{self.code.replace("-", "")}%29&type=phone_number&app_absent=0',
        }


class KycStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"

class KycRequest(Base):
    """Запрос на KYC-верификацию клиента"""
    __tablename__ = 'kyc_requests'
    id = Column(Integer, primary_key=True)
    token = Column(String(64), unique=True, nullable=False, index=True)
    client_id = Column(Integer, ForeignKey('clients.id'), nullable=True)
    client_name = Column(String(100))
    status = Column(String(20), default=KycStatus.PENDING)
    created_at = Column(DateTime, default=datetime.utcnow)
    reviewed_at = Column(DateTime, nullable=True)
    reviewed_by = Column(String(100), nullable=True)
    rejection_reason = Column(Text, nullable=True)
    doc_path = Column(String(500), nullable=True)
    selfie_path = Column(String(500), nullable=True)
    liveness_paths = Column(Text, nullable=True)  # JSON-массив путей

    client = relationship("Client", backref="kyc_requests")

    def to_dict(self):
        return {
            'id': self.id, 'token': self.token, 'client_id': self.client_id,
            'client_name': self.client_name, 'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'reviewed_at': self.reviewed_at.isoformat() if self.reviewed_at else None,
            'reviewed_by': self.reviewed_by, 'rejection_reason': self.rejection_reason,
            'has_doc': bool(self.doc_path), 'has_selfie': bool(self.selfie_path),
            'has_liveness': bool(self.liveness_paths)
        }

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
    tx_hash = Column(Text)  # Несколько хэшей через запятую
    tx_verified = Column(Boolean, default=False)
    notes = Column(Text)
    deals = relationship("Deal", back_populates="reimbursement")

    def to_dict(self):
        # tx_hashes — список для фронта
        hashes = [h.strip() for h in (self.tx_hash or '').split(',') if h.strip()]
        return {'id': self.id, 'founder_name': self.founder_name, 'amount_usdt': self.amount_usdt,
                'tx_hash': self.tx_hash, 'tx_hashes': hashes, 'tx_verified': self.tx_verified,
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
    is_monitored = Column(Boolean, default=True)  # Виден во вкладке Транзакции
    is_balance = Column(Boolean, default=False)   # Виден во вкладке Баланс (Binance)
    operations = relationship("WalletOperation", back_populates="wallet", cascade="all, delete-orphan")
    
    def to_dict(self, session=None):
        # Если передан session, считаем системный баланс
        system_balance = 0
        if session:
            ops = session.query(WalletOperation).filter(WalletOperation.wallet_id == self.id).all()
            for op in ops:
                if op.type == 'income':
                    system_balance += op.amount
                else:
                    system_balance -= op.amount
                    
        return {
            'id': self.id, 'address': self.address, 'blockchain': self.blockchain,
            'label': self.label, 'created_at': self.created_at.isoformat() if self.created_at else None,
            'active': self.active,
            'is_monitored': self.is_monitored,
            'is_balance': self.is_balance,
            'system_balance': round(system_balance, 2)
        }

class WalletOperation(Base):
    __tablename__ = 'wallet_operations'
    id = Column(Integer, primary_key=True)
    wallet_id = Column(Integer, ForeignKey('wallets.id'), nullable=False)
    type = Column(String(20), nullable=False)  # 'income' или 'expense'
    amount = Column(Float, nullable=False)
    description = Column(String(255))
    tx_hash = Column(String(100))
    deal_id = Column(Integer, ForeignKey('deals.id'), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    wallet = relationship("Wallet", back_populates="operations")
    
    def to_dict(self):
        return {
            'id': self.id, 'wallet_id': self.wallet_id, 'type': self.type,
            'amount': self.amount, 'description': self.description,
            'tx_hash': self.tx_hash, 'deal_id': self.deal_id,
            'created_at': self.created_at.isoformat() if self.created_at else None
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
    payout_wallet_id = Column(Integer, ForeignKey('wallets.id'), nullable=True)
    payout_wallet = relationship("Wallet", foreign_keys=[payout_wallet_id])
    cash_batch_id = Column(Integer, ForeignKey('cash_batches.id'), nullable=True)
    cash_batch = relationship("CashBatch", back_populates="deals")
    cash_batch_rate = Column(Float)
    payout_founder_name = Column(String(100))
    reimbursement_id = Column(Integer, ForeignKey('reimbursements.id'), nullable=True)
    reimbursement = relationship("Reimbursement", back_populates="deals")
    profit_usdt = Column(Float)
    profit_percent = Column(Float)
    exchange_rate = Column(Float)
    referrer_id = Column(Integer, ForeignKey('referrers.id'), nullable=True)
    referrer_ref = relationship("Referrer", foreign_keys=[referrer_id])
    referrer_name = Column(String(100))
    referrer_percent = Column(Float)
    referrer_fixed_usdt = Column(Float)
    referrer_payout_usdt = Column(Float)
    referrer_paid = Column(Boolean, default=False)
    net_profit_usdt = Column(Float)
    needs_reimbursement = Column(Boolean, default=True)
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
            'payout_wallet_id': self.payout_wallet_id,
            'cash_batch_rate': self.cash_batch_rate,
            'payout_founder_name': self.payout_founder_name,
            'profit_usdt': self.profit_usdt,
            'profit_percent': self.profit_percent,
            'net_profit_usdt': self.net_profit_usdt,
            'referrer_id': self.referrer_id,
            'referrer_name': self.referrer_name,
            'referrer_percent': self.referrer_percent,
            'referrer_payout_usdt': self.referrer_payout_usdt,
            'referrer_paid': self.referrer_paid,
            'is_custom': self.is_custom,
            'custom_payin_currency': self.custom_payin_currency,
            'custom_payin_amount': self.custom_payin_amount,
            'custom_payin_rate': self.custom_payin_rate,
            'custom_payout_currency': self.custom_payout_currency,
            'custom_payout_amount': self.custom_payout_amount,
            'custom_payout_rate': self.custom_payout_rate,
            'notes': self.notes,
            'reimbursement_id': self.reimbursement_id,
            'reimbursement': self.reimbursement.to_dict() if self.reimbursement else None,
            'needs_reimbursement': self.needs_reimbursement if self.needs_reimbursement is not None else True,
            'is_reimbursed': self.reimbursement_id is not None or not (self.needs_reimbursement if self.needs_reimbursement is not None else True)
        }

# Создание таблиц
Base.metadata.create_all(bind=engine)

# Миграция: добавляем колонки если их нет
try:
    with engine.connect() as conn:
        from sqlalchemy import text
        # Для PostgreSQL
        if 'postgresql' in DATABASE_URL:
            conn.execute(text("SET lock_timeout = '3s'"))  # не ждать лок дольше 3 сек
            conn.execute(text("ALTER TABLE deals ADD COLUMN IF NOT EXISTS payout_wallet_id INTEGER REFERENCES wallets(id)"))
            conn.execute(text("ALTER TABLE wallets ADD COLUMN IF NOT EXISTS is_monitored BOOLEAN DEFAULT TRUE"))
            conn.execute(text("ALTER TABLE wallets ADD COLUMN IF NOT EXISTS is_balance BOOLEAN DEFAULT FALSE"))
            conn.execute(text("ALTER TABLE deals ADD COLUMN IF NOT EXISTS needs_reimbursement BOOLEAN DEFAULT TRUE"))
        # Для SQLite
        else:
            try: conn.execute(text("ALTER TABLE deals ADD COLUMN payout_wallet_id INTEGER"))
            except: pass
            try: conn.execute(text("ALTER TABLE wallets ADD COLUMN is_monitored BOOLEAN DEFAULT TRUE"))
            except: pass
            try: conn.execute(text("ALTER TABLE wallets ADD COLUMN is_balance BOOLEAN DEFAULT FALSE"))
            except: pass
            try: conn.execute(text("ALTER TABLE deals ADD COLUMN needs_reimbursement BOOLEAN DEFAULT 1"))
            except: pass
        # Реферальная система
        if 'postgresql' in DATABASE_URL:
            conn.execute(text("ALTER TABLE clients ADD COLUMN IF NOT EXISTS referrer_id INTEGER REFERENCES referrers(id)"))
            conn.execute(text("ALTER TABLE deals ADD COLUMN IF NOT EXISTS referrer_id INTEGER REFERENCES referrers(id)"))
            conn.execute(text("ALTER TABLE referrers ADD COLUMN IF NOT EXISTS payout_currency VARCHAR(10) DEFAULT 'USDT'"))
        else:
            try: conn.execute(text("ALTER TABLE clients ADD COLUMN referrer_id INTEGER"))
            except: pass
            try: conn.execute(text("ALTER TABLE deals ADD COLUMN referrer_id INTEGER"))
            except: pass
            try: conn.execute(text("ALTER TABLE referrers ADD COLUMN payout_currency VARCHAR(10) DEFAULT 'USDT'"))
            except: pass
        conn.commit()
    print("✅ Database migration successful")
except Exception as e:
    print(f"ℹ️ Migration info: {e}")

print("✅ Database initialized")

# ==================== WEBHOOK CONFIG ====================
WEBHOOK_URL = os.environ.get('CRM_WEBHOOK_URL', '')

# ==================== GOOGLE SHEETS SYNC ====================
GSHEET_ID = '1aW84o8JmiIOPpCaSyGQuWCmf_h7H6uPWBCloq7_WDOY'
GSHEET_WORKSHEET = 'общая сделка'
GOOGLE_SA_JSON = os.environ.get('GOOGLE_SA_JSON', '')  # JSON строка service account
# OAuth user-credentials (для доступа к файлам в закрытых папках Workspace)
GOOGLE_OAUTH_CLIENT_ID = os.environ.get('GOOGLE_OAUTH_CLIENT_ID', '')
GOOGLE_OAUTH_CLIENT_SECRET = os.environ.get('GOOGLE_OAUTH_CLIENT_SECRET', '')
GOOGLE_OAUTH_REFRESH_TOKEN = os.environ.get('GOOGLE_OAUTH_REFRESH_TOKEN', '')


def get_gsheet_client():
    """Возвращает авторизованный gspread клиент.
    Приоритет: OAuth user-credentials > Service Account > локальный SA файл."""
    # 1. OAuth user-credentials — работает с закрытыми папками Workspace
    if GOOGLE_OAUTH_REFRESH_TOKEN and GOOGLE_OAUTH_CLIENT_ID:
        from google.oauth2.credentials import Credentials
        creds = Credentials(
            token=None,
            refresh_token=GOOGLE_OAUTH_REFRESH_TOKEN,
            client_id=GOOGLE_OAUTH_CLIENT_ID,
            client_secret=GOOGLE_OAUTH_CLIENT_SECRET,
            token_uri='https://oauth2.googleapis.com/token',
            scopes=['https://www.googleapis.com/auth/spreadsheets'],
        )
        print('[GSheet] Using OAuth user-credentials', flush=True)
        return gspread.authorize(creds)

    # 2. Service Account из env (Railway)
    if GOOGLE_SA_JSON:
        import json as _json
        sa_info = _json.loads(GOOGLE_SA_JSON)
        creds = GoogleCredentials.from_service_account_info(
            sa_info, scopes=['https://www.googleapis.com/auth/spreadsheets']
        )
        return gspread.authorize(creds)

    # 3. Локально — SA из файла
    sa_path = os.path.join(os.path.dirname(__file__), 'google_sa.json')
    if not os.path.exists(sa_path):
        return None
    creds = GoogleCredentials.from_service_account_file(
        sa_path, scopes=['https://www.googleapis.com/auth/spreadsheets']
    )
    return gspread.authorize(creds)


def sync_deals_to_gsheet(deals):
    """Добавляет завершённые сделки в Google Sheet 'общая сделка'.
    Возвращает dict {ok: bool, inserted: int, error: str|None} для диагностики."""
    try:
        gc = get_gsheet_client()
        if not gc:
            print('[GSheet] No credentials, skipping sync')
            return {'ok': False, 'inserted': 0, 'error': 'no_credentials'}

        sh = gc.open_by_key(GSHEET_ID)
        ws = sh.worksheet(GSHEET_WORKSHEET)
        all_rows = ws.get_all_values()

        # Находим последнюю строку с данными или заголовком недели
        insert_row = len(all_rows) + 1
        for i in range(len(all_rows) - 1, -1, -1):
            row = all_rows[i]
            if (row[0] and str(row[0]).strip().isdigit()) or \
               (row[1] and 'неделя' in str(row[1]).lower()):
                insert_row = i + 2  # после этой строки (1-indexed + 1)
                break

        # Последний номер сделки
        last_num = 0
        for row in reversed(all_rows):
            if row[0] and str(row[0]).strip().isdigit():
                last_num = int(row[0])
                break

        new_rows = []
        for deal in deals:
            last_num += 1

            # Маппинг payin_method → способ пополнения
            payin_map = {
                'spp_doverka': 'доверка',
                'crypto_direct': 'крипта',
                'partners_cash': 'наличные',
            }
            # Маппинг payout_method → способ выдачи
            payout_map = {
                'office': 'офис',
                'courier': 'курьер',
                'atm': 'банкомат',
                'transfer': 'перевод',
            }

            payin_method_str = payin_map.get(
                deal.payin_method.value if deal.payin_method else '', ''
            )
            payout_method_str = payout_map.get(
                deal.payout_method.value if deal.payout_method else '', ''
            )

            # Валюта пополнения (кастомные сделки используют custom_* поля)
            if deal.is_custom:
                currency_in = (deal.custom_payin_currency or '').lower()
                amount_in = deal.custom_payin_amount or 0
                amount_in_usdt = deal.payin_amount_usdt or deal.custom_payin_amount or 0
                payout_thb = deal.custom_payout_amount or deal.payout_amount_thb or 0
                payout_currency = (deal.custom_payout_currency or 'thb').lower()
            elif deal.payin_method == PayInMethod.CRYPTO_DIRECT:
                currency_in = 'usdt'
                amount_in = deal.payin_amount_usdt or 0
                amount_in_usdt = amount_in
                payout_thb = deal.custom_payout_amount or deal.payout_amount_thb or 0
                payout_currency = (deal.custom_payout_currency or 'thb').lower()
            else:
                currency_in = 'rub'
                amount_in = deal.payin_amount_rub or 0
                amount_in_usdt = deal.payin_amount_usdt or 0
                payout_thb = deal.custom_payout_amount or deal.payout_amount_thb or 0
                payout_currency = (deal.custom_payout_currency or 'thb').lower()

            # Значения как числа — Google Sheets сам отформатирует
            date_str = deal.created_at.strftime('%d.%m.%Y') if deal.created_at else ''
            payout_usdt = deal.payout_amount_usdt or 0
            tx_hash = deal.payin_tx_hash or ''

            row = [
                last_num,                              # A: номер
                (deal.client.name if deal.client else deal.client_name) or '',  # B: клиент
                '',                                    # C: пусто
                date_str,                              # D: дата
                f'{amount_in:,.2f}' if amount_in else '',  # E: сумма получения
                currency_in,                           # F: валюта
                f'${amount_in_usdt:,.2f}' if amount_in_usdt else '',  # G: получение в USDT
                int(payout_thb) if payout_thb else '',  # H: выдача клиенту
                payout_currency,                       # I: валюта выдачи
                f'${payout_usdt:,.2f}' if payout_usdt else '',  # J: выдача в USDT
                '',                                    # K: брокеру
                '',                                    # L: партнеру
                f'${deal.profit_usdt:,.2f}' if deal.profit_usdt else '',  # M: доходность
                payout_method_str,                     # N: способ выдачи
                payin_method_str if not deal.is_custom else 'кастом',  # O: способ пополнения
                tx_hash,                               # P: хеш
            ]
            new_rows.append(row)

        if new_rows:
            # Находим строку-образец для копирования формата (последняя строка с номером)
            template_row_idx = None
            for i in range(len(all_rows) - 1, -1, -1):
                if all_rows[i][0] and str(all_rows[i][0]).strip().isdigit():
                    template_row_idx = i  # 0-indexed
                    break

            ws.insert_rows(new_rows, row=insert_row, value_input_option='USER_ENTERED')
            print(f'[GSheet] Synced {len(new_rows)} deals to row {insert_row}')

            # Копируем форматирование (дропдауны, цвета, формат чисел) с образца
            if template_row_idx is not None:
                sheet_id = ws.id
                num_cols = max(len(r) for r in new_rows)
                for offset in range(len(new_rows)):
                    sh.batch_update({
                        'requests': [{
                            'copyPaste': {
                                'source': {
                                    'sheetId': sheet_id,
                                    'startRowIndex': template_row_idx,
                                    'endRowIndex': template_row_idx + 1,
                                    'startColumnIndex': 0,
                                    'endColumnIndex': num_cols,
                                },
                                'destination': {
                                    'sheetId': sheet_id,
                                    'startRowIndex': insert_row - 1 + offset,  # 0-indexed
                                    'endRowIndex': insert_row + offset,
                                    'startColumnIndex': 0,
                                    'endColumnIndex': num_cols,
                                },
                                'pasteType': 'PASTE_FORMAT',
                            }
                        }]
                    })
                print(f'[GSheet] Copied formatting from row {template_row_idx + 1}')

        return {'ok': True, 'inserted': len(new_rows), 'error': None}
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(f'[GSheet] Sync error: {e}', flush=True)
        print(f'[GSheet] Traceback: {tb}', flush=True)
        return {'ok': False, 'inserted': 0, 'error': f'{type(e).__name__}: {e}'}


def find_deal_row_in_gsheet(ws, all_rows, deal):
    """Находит строку сделки в Google Sheet по клиенту + дате.
    Возвращает 1-indexed номер строки или None."""
    deal_date = deal.created_at.strftime('%d.%m.%Y') if deal.created_at else ''
    deal_name = (deal.client_name or '').strip().lower()
    for i, row in enumerate(all_rows):
        if len(row) >= 4:
            row_name = str(row[1]).strip().lower()
            row_date = str(row[3]).strip()
            if row_name == deal_name and row_date == deal_date:
                return i + 1  # 1-indexed
    return None


def delete_deal_from_gsheet(deal):
    """Удаляет строку сделки из Google Sheet"""
    try:
        gc = get_gsheet_client()
        if not gc:
            return
        sh = gc.open_by_key(GSHEET_ID)
        ws = sh.worksheet(GSHEET_WORKSHEET)
        all_rows = ws.get_all_values()
        row_num = find_deal_row_in_gsheet(ws, all_rows, deal)
        if row_num:
            ws.delete_rows(row_num)
            print(f'[GSheet] Deleted row {row_num} ({deal.client_name})')
        else:
            print(f'[GSheet] Row not found for {deal.client_name}')
    except Exception as e:
        print(f'[GSheet] Delete error: {e}')


def update_deal_in_gsheet(deal):
    """Обновляет строку сделки в Google Sheet (только если возмещена)"""
    if deal.reimbursement_id is None:
        return
    try:
        gc = get_gsheet_client()
        if not gc:
            return
        sh = gc.open_by_key(GSHEET_ID)
        ws = sh.worksheet(GSHEET_WORKSHEET)
        all_rows = ws.get_all_values()
        row_num = find_deal_row_in_gsheet(ws, all_rows, deal)
        if not row_num:
            print(f'[GSheet] Row not found for update: {deal.client_name}')
            return

        # Маппинг
        payin_map = {'spp_doverka': 'доверка', 'crypto_direct': 'крипта', 'partners_cash': 'наличные'}
        payout_map = {'office': 'офис', 'courier': 'курьер', 'atm': 'банкомат', 'transfer': 'перевод'}
        payin_method_str = payin_map.get(deal.payin_method.value if deal.payin_method else '', '')
        payout_method_str = payout_map.get(deal.payout_method.value if deal.payout_method else '', '')

        # Кастомные сделки используют custom_* поля
        if deal.is_custom:
            currency_in = (deal.custom_payin_currency or '').lower()
            amount_in = deal.custom_payin_amount or 0
            amount_in_usdt = deal.payin_amount_usdt or deal.custom_payin_amount or 0
            payout_thb = deal.custom_payout_amount or deal.payout_amount_thb or 0
            payout_currency = (deal.custom_payout_currency or 'thb').lower()
        elif deal.payin_method == PayInMethod.CRYPTO_DIRECT:
            currency_in = 'usdt'
            amount_in = deal.payin_amount_usdt or 0
            amount_in_usdt = amount_in
            payout_thb = deal.custom_payout_amount or deal.payout_amount_thb or 0
            payout_currency = (deal.custom_payout_currency or 'thb').lower()
        else:
            currency_in = 'rub'
            amount_in = deal.payin_amount_rub or 0
            amount_in_usdt = deal.payin_amount_usdt or 0
            payout_thb = deal.custom_payout_amount or deal.payout_amount_thb or 0
            payout_currency = (deal.custom_payout_currency or 'thb').lower()

        date_str = deal.created_at.strftime('%d.%m.%Y') if deal.created_at else ''
        payout_usdt = deal.payout_amount_usdt or 0

        # Сохраняем номер из колонки A (не перезаписываем)
        existing_num = all_rows[row_num - 1][0] if len(all_rows[row_num - 1]) > 0 else ''

        row = [
            existing_num,
            (deal.client.name if deal.client else deal.client_name) or '',
            '',
            date_str,
            f'{amount_in:,.2f}' if amount_in else '',
            currency_in,
            f'${amount_in_usdt:,.2f}' if amount_in_usdt else '',
            int(payout_thb) if payout_thb else '',
            payout_currency,
            f'${payout_usdt:,.2f}' if payout_usdt else '',
            '',
            '',
            f'${deal.profit_usdt:,.2f}' if deal.profit_usdt else '',
            payout_method_str,
            payin_method_str if not deal.is_custom else 'кастом',
            deal.payin_tx_hash or '',
        ]

        ws.update(values=[row], range_name=f'A{row_num}:P{row_num}', value_input_option='USER_ENTERED')
        print(f'[GSheet] Updated row {row_num} ({(deal.client.name if deal.client else deal.client_name) or ""})')
    except Exception as e:
        print(f'[GSheet] Update error: {e}')


def _send_deal_telegram(deal):
    """Отправляет уведомление о сделке в Telegram"""
    date_str = deal.created_at.strftime('%d.%m.%Y') if deal.created_at else ''
    payout_usdt = deal.payout_amount_usdt or 0
    profit = deal.profit_usdt or 0

    if deal.is_custom:
        currency = (deal.custom_payin_currency or '').upper()
        amount_in = deal.custom_payin_amount or 0
        # USDT эквивалент: если payin уже в USDT — берём его, иначе payin_amount_usdt
        if (deal.custom_payin_currency or '').upper() == 'USDT':
            amount_in_usdt = deal.custom_payin_amount or 0
        else:
            amount_in_usdt = deal.payin_amount_usdt or 0
        # Payout: если payout в USDT — usdt эквивалент = custom_payout_amount
        payout_val = deal.custom_payout_amount or deal.payout_amount_thb or 0
        payout_cur = (deal.custom_payout_currency or 'THB').upper()
        if payout_cur == 'USDT':
            payout_usdt = deal.custom_payout_amount or 0
    else:
        pm = deal.payin_method.value if deal.payin_method else ''
        currency = 'usdt' if pm == 'crypto_direct' else 'rub'
        amount_in = deal.payin_amount_usdt if pm == 'crypto_direct' else (deal.payin_amount_rub or 0)
        amount_in_usdt = deal.payin_amount_usdt or 0
        if deal.custom_payout_currency:
            payout_val = deal.custom_payout_amount or deal.payout_amount_thb or 0
            payout_cur = deal.custom_payout_currency.upper()
            if payout_cur == 'USDT':
                payout_usdt = deal.custom_payout_amount or 0
        else:
            payout_val = int(deal.payout_amount_thb) if deal.payout_amount_thb else 0
            payout_cur = 'THB'

    msg = (
        f"✅ <b>Сделка {deal.id} — {(deal.client.name if deal.client else deal.client_name) or 'без имени'} — {date_str}</b>\n"
        f"Получено: {amount_in:,.2f} {currency} (${amount_in_usdt:,.2f})\n"
        f"Выдано: {payout_val:,} {payout_cur} (${payout_usdt:,.2f})\n"
        f"Прибыль: ${profit:,.2f}"
    )
    send_telegram_notification(msg)


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

# ==================== AUTH ====================

@app.route('/login', methods=['GET'])
def login_page():
    """Страница входа"""
    if flask_session.get('user_id'):
        return redirect('/crm')
    return send_from_directory('static/auth', 'login.html')

@app.route('/api/auth/login', methods=['POST'])
@limiter.limit("5/minute")
def auth_login():
    """Авторизация"""
    data = request.get_json() or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')

    if not username or not password:
        return jsonify({'success': False, 'error': 'Введите логин и пароль'}), 400

    db = get_session()
    try:
        user = db.query(AdminUser).filter_by(username=username).first()
        if not user or not user.check_password(password):
            return jsonify({'success': False, 'error': 'Неверный логин или пароль'}), 401

        # Сохраняем rehash если произошла миграция SHA-256 → bcrypt
        db.commit()

        flask_session['user_id'] = user.id
        flask_session['username'] = user.username
        flask_session['display_name'] = user.display_name or user.username
        flask_session.permanent = True

        return jsonify({'success': True, 'user': user.display_name or user.username})
    finally:
        db.close()

@app.route('/api/auth/logout', methods=['POST'])
def auth_logout():
    """Выход"""
    flask_session.clear()
    return jsonify({'success': True})

@app.route('/api/auth/me', methods=['GET'])
def auth_me():
    """Текущий пользователь"""
    if flask_session.get('user_id'):
        return jsonify({
            'success': True,
            'user': {
                'id': flask_session['user_id'],
                'username': flask_session.get('username'),
                'display_name': flask_session.get('display_name')
            }
        })
    return jsonify({'success': False}), 401

@app.route('/api/auth/setup', methods=['POST'])
@limiter.limit("3/minute")
def auth_setup():
    """Первоначальная настройка — создание админа (только если нет ни одного пользователя)"""
    if os.environ.get('SETUP_ENABLED') != 'true':
        return jsonify({'success': False, 'error': 'Setup отключён'}), 403
    db = get_session()
    try:
        existing = db.query(AdminUser).first()
        if existing:
            return jsonify({'success': False, 'error': 'Админ уже создан'}), 403

        data = request.get_json() or {}
        username = data.get('username', '').strip()
        password = data.get('password', '')
        display_name = data.get('display_name', '').strip()

        if not username or not password:
            return jsonify({'success': False, 'error': 'Укажите логин и пароль'}), 400

        if len(password) < 8:
            return jsonify({'success': False, 'error': 'Пароль минимум 8 символов'}), 400

        admin = AdminUser(
            username=username,
            password_hash=AdminUser.hash_password(password),
            display_name=display_name or username,
            role='admin'
        )
        db.add(admin)
        db.commit()

        flask_session['user_id'] = admin.id
        flask_session['username'] = admin.username
        flask_session['display_name'] = admin.display_name
        flask_session.permanent = True

        return jsonify({'success': True, 'user': admin.display_name})
    finally:
        db.close()

# ==================== PAGES ====================

@app.route('/')
def calculator_index():
    """Главная страница - Калькулятор (авторизация)"""
    if not flask_session.get('user_id'):
        return redirect('/login')
    return send_from_directory('static/calculator', 'index.html')

@app.route('/partner/<token>')
def partner_page(token):
    """Страница партнёрского калькулятора (публичная, по токену)"""
    return send_from_directory('static/partner', 'index.html')

@app.route('/partner/<token>/<path:filename>')
def partner_static(token, filename):
    """Статика партнёрского калькулятора"""
    return send_from_directory('static/partner', filename)

@app.route('/kyc/')
def kyc_index():
    """KYC страница для клиента (публичная)"""
    return send_from_directory('static/kyc', 'index.html')

@app.route('/kyc/<path:filename>')
def kyc_static(filename):
    """Статика KYC (CSS, изображения)"""
    return send_from_directory('static/kyc', filename)

@app.route('/crm')
def crm_index():
    """CRM страница (защищённая)"""
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
        usdt_thb = rates.get('usdt_thb')
        rub_usdt = rates.get('rub_usdt')
        errors = []
        if not usdt_thb:
            errors.append('USDT/THB недоступен (Binance)')
        if not rub_usdt:
            errors.append('RUB/USDT недоступен (Doverka)')
        return jsonify({
            'usdt_thb': usdt_thb,
            'rub_usdt': rub_usdt,
            'success': bool(usdt_thb and rub_usdt),
            'errors': errors
        })
    except Exception as e:
        app.logger.error(f'Rates error: {e}')
        return jsonify({'error': 'Ошибка получения курсов', 'usdt_thb': None, 'rub_usdt': None, 'success': False})

@app.route('/api/rates/precise', methods=['POST'])
def get_precise_rate():
    """
    ТОЧНЫЙ курс USDT-THB через Playwright парсинг Binance

    Вычисляет USDT сумму с учётом маржи для текущего сценария,
    затем парсит точный курс для этой суммы.

    POST /api/rates/precise
    {
        "scenario": "rub-to-thb",  # rub-to-thb | thb-to-rub | usdt-to-thb | thb-to-usdt
        "amount": 100000,          # Входная сумма
        "method": "doverka",       # doverka | broker
        "rub_usdt": 82.0,          # Курс RUB/USDT
        "profit_margin": 5.0       # Маржа %
    }

    Returns:
    {
        "success": true,
        "rate_used": 31.5152,  # Точный курс USDT-THB
        "time": 6.5
    }
    """
    try:
        print(f"🎯 Precise rate request received", flush=True)
        data = request.get_json()

        scenario = data.get('scenario', 'rub-to-thb')
        amount = float(data.get('amount', 0))
        direction = data.get('direction', 'amount')  # 'amount' (вношу) или 'target' (хочу получить)
        method = data.get('method', 'doverka')
        rub_usdt_raw = data.get('rub_usdt')
        rub_usdt = float(rub_usdt_raw) if rub_usdt_raw not in (None, '', 0) else 82.0
        pm_raw = data.get('profit_margin')
        profit_margin = float(pm_raw) if pm_raw not in (None, '') else 5.0

        if amount <= 0:
            return jsonify({'success': False, 'error': 'Invalid amount'}), 400

        print(f"🎯 Scenario: {scenario}, Direction: {direction}, Amount: {amount}, Margin: {profit_margin}%", flush=True)

        # Определяем что парсить на Binance с учётом direction
        # direction='amount' — клиент вводит сумму которую ВНОСИТ (исходная валюта)
        # direction='target' — клиент вводит сумму которую ХОЧЕТ ПОЛУЧИТЬ (целевая валюта)
        usdt_amount_for_parsing = None
        thb_amount_for_parsing = None
        playwright_direction = None

        usdt_comm_approx = (profit_margin / 100.0) / 2.0

        if scenario == 'rub-to-thb':
            if direction == 'target':
                # Хочу получить N THB → на странице USDT/THB вводим THB в Receive, читаем USDT из From
                thb_amount_for_parsing = round(amount)
                playwright_direction = 'usdt_to_thb_reverse'
                print(f"📊 Хочу {amount} THB → парсим USDT/THB reverse (вводим THB в Receive)", flush=True)
            else:
                # Вношу N RUB → пересчитать в USDT → парсим USDT→THB
                rub_usdt_sell = rub_usdt * (1 + usdt_comm_approx)
                usdt_amount_for_parsing = round(amount / rub_usdt_sell, 2)
                playwright_direction = 'usdt_to_thb'
                print(f"📊 {amount} RUB / {rub_usdt_sell:.2f} = {usdt_amount_for_parsing:.2f} USDT → парсим USDT→THB", flush=True)

        elif scenario == 'usdt-to-thb':
            if direction == 'target':
                # Хочу получить N THB → на странице USDT/THB вводим THB в Receive, читаем USDT из From
                thb_amount_for_parsing = round(amount)
                playwright_direction = 'usdt_to_thb_reverse'
                print(f"📊 Хочу {amount} THB → парсим USDT/THB reverse (вводим THB в Receive)", flush=True)
            else:
                # Вношу N USDT → парсим USDT→THB
                usdt_amount_for_parsing = round(amount, 2)
                playwright_direction = 'usdt_to_thb'
                print(f"📊 {amount} USDT → парсим USDT→THB", flush=True)

        elif scenario == 'thb-to-rub':
            # thb-to-rub всегда = "клиент хочет получить N THB" (target)
            # Парсим USDT→THB reverse: вводим THB в Receive, читаем USDT из From
            thb_amount_for_parsing = round(amount)
            playwright_direction = 'usdt_to_thb_reverse'
            print(f"📊 Хочу {amount} THB → парсим USDT/THB reverse (вводим THB в Receive)", flush=True)

        elif scenario == 'thb-to-usdt':
            if direction == 'target':
                # Хочу получить N USDT → на странице THB/USDT вводим USDT в Receive, читаем THB из From
                usdt_amount_for_parsing = round(amount, 2)
                playwright_direction = 'thb_to_usdt_reverse'
                print(f"📊 Хочу {amount} USDT → парсим THB/USDT reverse (вводим USDT в Receive)", flush=True)
            else:
                # Вношу N THB → парсим THB→USDT
                thb_amount_for_parsing = round(amount)
                playwright_direction = 'thb_to_usdt'
                print(f"📊 {amount} THB → парсим THB→USDT", flush=True)

        elif scenario == 'rub-to-usdt':
            if direction == 'target':
                # Хочу получить N USDT → парсим USDT→THB (для курса)
                usdt_amount_for_parsing = round(amount, 2)
                playwright_direction = 'usdt_to_thb'
                print(f"📊 Хочу {amount} USDT → парсим USDT→THB", flush=True)
            else:
                # Вношу N RUB → пересчитать в USDT → парсим USDT→THB
                rub_usdt_sell = rub_usdt * (1 + usdt_comm_approx)
                usdt_amount_for_parsing = round(amount / rub_usdt_sell, 2)
                playwright_direction = 'usdt_to_thb'
                print(f"📊 {amount} RUB / {rub_usdt_sell:.2f} = {usdt_amount_for_parsing} USDT → парсим USDT→THB", flush=True)

        else:
            usdt_amount_for_parsing = round(amount, 2)
            playwright_direction = 'usdt_to_thb'

        # Парсим точный курс
        playwright_result = asyncio.run(ExchangeRateProvider.get_precise_binance_rate(
            usdt_amount=usdt_amount_for_parsing,
            thb_amount=thb_amount_for_parsing,
            direction=playwright_direction
        ))

        if 'error' in playwright_result:
            # Playwright не сработал — фоллбэк на CoinGecko API
            print(f"⚠️ Playwright failed: {playwright_result['error']}. Falling back to CoinGecko.", flush=True)
            try:
                import aiohttp
                async def _get_coingecko_rate():
                    async with aiohttp.ClientSession() as session:
                        url = "https://api.coingecko.com/api/v3/simple/price"
                        params = {"ids": "tether", "vs_currencies": "thb"}
                        async with session.get(url, params=params, timeout=5) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                return float(data['tether']['thb'])
                    return None
                fallback_rate = asyncio.run(_get_coingecko_rate())
                if fallback_rate:
                    print(f"✅ CoinGecko fallback rate: {fallback_rate:.4f}", flush=True)
                    return jsonify({
                        'success': True,
                        'rate_used': round(fallback_rate, 4),
                        'time': playwright_result.get('time', 0),
                        'source': 'coingecko_fallback'
                    })
            except Exception as fe:
                print(f"❌ CoinGecko fallback error: {fe}", flush=True)
            return jsonify({'success': False, 'error': playwright_result['error']}), 500

        rate_used = playwright_result['rate']
        print(f"✅ Точный курс USDT-THB: {rate_used:.4f}", flush=True)

        return jsonify({
            'success': True,
            'rate_used': round(rate_used, 4),
            'time': playwright_result['time']
        })

    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"❌ Exception in /api/rates/precise: {e}", flush=True)
        print(f"❌ Traceback: {error_trace}", flush=True)
        app.logger.error(f'Server error: {e}')
        return jsonify({'success': False, 'error': 'Внутренняя ошибка сервера'}), 500

# Удалён старый код THB → RUB, USDT → THB, THB → USDT (теперь обработано выше)

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

        # Если передан точный курс USDT-THB (от Playwright), используем его
        custom_usdt_thb = data.get('custom_usdt_thb')
        if custom_usdt_thb:
            rates['usdt_thb'] = float(custom_usdt_thb)
            print(f"🎯 Использую точный курс USDT-THB: {rates['usdt_thb']:.4f}", flush=True)

        if method == 'broker':
            from broker_detailed import BrokerCalculatorDetailed
            custom_rub_usdt_raw = data.get('custom_rub_usdt')
            custom_rub_usdt = float(custom_rub_usdt_raw) if custom_rub_usdt_raw not in (None, '', 0) else 80.9
            pm_raw = data.get('profit_margin')
            profit_margin = float(pm_raw) if pm_raw not in (None, '') else 4.0
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
        
        # CalcCRM — внутренний инструмент за авторизацией, отдаём всю кухню
        # (profit_usdt, комиссии, incoming/outgoing, bonus_usdt, курсы).
        # Фильтр PUBLIC_FIELDS применяем только в api_server.py на VPS.
        return jsonify(result)
    except Exception as e:
        app.logger.error(f'Webhook error: {e}')
        return jsonify({'error': 'Внутренняя ошибка'}), 500

# ==================== CRM API - DEALS ====================

@app.route('/api/deals', methods=['GET'])
def get_deals():
    from sqlalchemy.orm import joinedload
    session = get_session()
    try:
        query = session.query(Deal).options(
            joinedload(Deal.client), joinedload(Deal.reimbursement)
        ).order_by(Deal.created_at.desc(), Deal.id.desc())
        status = request.args.get('status')
        if status:
            query = query.filter(Deal.status == DealStatus(status))
        manager = request.args.get('manager')
        if manager:
            query = query.filter(Deal.manager_name.ilike(f'%{manager}%'))
        date_from = request.args.get('date_from')
        if date_from:
            query = query.filter(Deal.created_at >= datetime.strptime(date_from, '%Y-%m-%d'))
        date_to = request.args.get('date_to')
        if date_to:
            # Включаем весь день date_to
            query = query.filter(Deal.created_at < datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1))
        # Пагинация
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 50))
        total = query.count()
        deals = query.offset((page - 1) * per_page).limit(per_page).all()
        return jsonify({
            'success': True,
            'count': len(deals),
            'total': total,
            'page': page,
            'per_page': per_page,
            'total_pages': (total + per_page - 1) // per_page,
            'deals': [d.to_dict() for d in deals]
        })
    finally:
        session.close()

@app.route('/api/deals/<int:deal_id>', methods=['GET'])
def get_deal(deal_id):
    session = get_session()
    try:
        from sqlalchemy.orm import joinedload
        deal = session.query(Deal).options(joinedload(Deal.reimbursement)).filter(Deal.id == deal_id).first()
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
        
        # Парсим дату если передана
        created_at = None
        if data.get('created_at'):
            try:
                date_str = data['created_at']
                if 'T' in date_str:
                    created_at = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                else:
                    created_at = datetime.strptime(date_str, '%Y-%m-%d')
            except:
                created_at = datetime.now()
        else:
            created_at = datetime.now()
        
        # Автоматически создаём клиента если указано имя и такого клиента ещё нет
        client_id = data.get('client_id')
        client_name = data.get('client_name')
        
        if not client_id and client_name:
            existing_client = session.query(Client).filter(Client.name == client_name).first()
            if not existing_client:
                new_client = Client(name=client_name)
                session.add(new_client)
                session.flush()
                client_id = new_client.id
            else:
                client_id = existing_client.id
        elif client_id and not client_name:
            client = session.query(Client).get(client_id)
            if client:
                client_name = client.name

        # Авто-заполнение реферера: если у клиента есть привязанный реферер
        ref_name = data.get('referrer_name')
        ref_percent = data.get('referrer_percent')
        ref_id = data.get('referrer_id')
        if client_id and not ref_name:
            client_obj = session.query(Client).get(client_id)
            if client_obj and client_obj.referrer_id:
                referrer = session.query(Referrer).get(client_obj.referrer_id)
                if referrer and referrer.active:
                    ref_id = referrer.id
                    ref_name = referrer.name
                    ref_percent = referrer.default_percent

        deal = Deal(
            created_at=created_at,
            manager_name=data.get('manager_name'),
            deal_type=DealType(data.get('deal_type', 'pay_in')),
            status=DealStatus(data.get('status', 'pending')),
            client_id=client_id,
            client_name=client_name,
            payin_method=PayInMethod(data['payin_method']) if data.get('payin_method') else None,
            payin_amount_rub=data.get('payin_amount_rub'),
            payin_amount_usdt=data.get('payin_amount_usdt'),
            payin_rate_rub_usdt=data.get('payin_rate_rub_usdt'),
            payin_tx_hash=data.get('payin_tx_hash'),
            doverka_transaction_id=data.get('doverka_transaction_id'),
            payout_method=PayOutMethod(data['payout_method']) if data.get('payout_method') else None,
            payout_source=PayOutSource(data['payout_source']) if data.get('payout_source') else None,
            payout_wallet_id=data.get('payout_wallet_id'),
            payout_amount_thb=data.get('payout_amount_thb'),
            payout_amount_usdt=data.get('payout_amount_usdt'),
            payout_tx_hash=data.get('payout_tx_hash'),
            payout_founder_name=data.get('payout_founder_name'),
            referrer_id=ref_id,
            referrer_name=ref_name,
            referrer_percent=ref_percent,
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
        session.flush()

        # Автоматическое списание с кошелька при создании
        if deal.payout_source == PayOutSource.BINANCE and deal.payout_wallet_id and deal.payout_amount_usdt:
            op = WalletOperation(
                wallet_id=deal.payout_wallet_id,
                type='expense',
                amount=deal.payout_amount_usdt,
                description=f"Сделка #{deal.id} ({deal.client_name or 'без имени'})",
                tx_hash=deal.payout_tx_hash,
                deal_id=deal.id
            )
            session.add(op)

        session.commit()
        
        # Если сделка создана сразу со статусом completed (skip_sync — для импорта исторических сделок)
        skip_sync = data.get('skip_sync', False)
        if deal.status == DealStatus.COMPLETED and not skip_sync:
            send_deal_completed_webhook(deal)
            # GSheet + Telegram для завершённых сделок с рассчитанной прибылью
            if deal.profit_usdt is not None:
                try:
                    sync_deals_to_gsheet([deal])
                except Exception as e:
                    print(f'[GSheet] Sync error on create: {e}')
                try:
                    _send_deal_telegram(deal)
                except Exception as e:
                    print(f'[Telegram] Error on create: {e}')

        return jsonify({'success': True, 'deal': deal.to_dict()}), 201
    except Exception as e:
        session.rollback()
        app.logger.error(f'Request error: {e}')
        return jsonify({'success': False, 'error': 'Ошибка обработки запроса'}), 400
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
                      'payout_tx_hash', 'profit_usdt', 'profit_percent', 'net_profit_usdt',
                      'referrer_id', 'referrer_name',
                      'referrer_percent', 'referrer_payout_usdt', 'referrer_fixed_usdt',
                      'referrer_paid', 'notes', 'client_id',
                      'payout_founder_name', 'payout_wallet_id',
                      'is_custom', 'custom_payin_currency', 'custom_payin_amount', 'custom_payin_rate',
                      'custom_payout_currency', 'custom_payout_amount', 'custom_payout_rate',
                      'needs_reimbursement']:
            if field in data:
                setattr(deal, field, data[field])
        
        # Обновляем Enum поля
        if 'payin_method' in data:
            deal.payin_method = PayInMethod(data['payin_method']) if data['payin_method'] else None
        if 'payout_method' in data:
            deal.payout_method = PayOutMethod(data['payout_method']) if data['payout_method'] else None
        if 'payout_source' in data:
            deal.payout_source = PayOutSource(data['payout_source']) if data['payout_source'] else None

        # Управление списанием с Binance кошелька при сохранении/завершении
        if deal.payout_source == PayOutSource.BINANCE and deal.payout_wallet_id and deal.payout_amount_usdt:
            # Ищем существующую операцию для этой сделки
            existing_op = session.query(WalletOperation).filter(
                WalletOperation.deal_id == deal.id,
                WalletOperation.type == 'expense'
            ).first()
            
            if not existing_op:
                op = WalletOperation(
                    wallet_id=deal.payout_wallet_id,
                    type='expense',
                    amount=deal.payout_amount_usdt,
                    description=f"Сделка #{deal.id} ({deal.client_name or 'без имени'})",
                    tx_hash=deal.payout_tx_hash,
                    deal_id=deal.id
                )
                session.add(op)
            else:
                # Обновляем существующую
                existing_op.wallet_id = deal.payout_wallet_id
                existing_op.amount = deal.payout_amount_usdt
                existing_op.tx_hash = deal.payout_tx_hash
                existing_op.description = f"Сделка #{deal.id} ({deal.client_name or 'без имени'})"

        # Если имя клиента изменилось и есть привязанный клиент - обновляем и его имя
        # Если имя клиента передано и оно не пустое, и есть привязанный клиент - обновляем имя клиента в базе
        client_name_val = data.get('client_name')
        if client_name_val and str(client_name_val).strip() != "" and deal.client_id:
            client = session.query(Client).filter(Client.id == deal.client_id).first()
            if client:
                client.name = str(client_name_val)
                # Синхронизируем client_name во всех сделках этого клиента
                session.query(Deal).filter(Deal.client_id == deal.client_id).update(
                    {"client_name": str(client_name_val)}, synchronize_session=False
                )
        
        # Если пришел новый client_id, просто привязываем
        if 'client_id' in data:
            deal.client_id = data['client_id']
        
        if 'status' in data:
            deal.status = DealStatus(data['status'])

        # Автоматический пересчёт прибыли при изменении сумм
        if deal.payin_amount_usdt and deal.payout_amount_usdt:
            deal.profit_usdt = round(deal.payin_amount_usdt - deal.payout_amount_usdt, 2)
            deal.profit_percent = round((deal.profit_usdt / deal.payout_amount_usdt * 100), 2) if deal.payout_amount_usdt > 0 else 0
            # Авто-расчёт выплаты рефереру из profit * percent
            if deal.referrer_percent and not data.get('referrer_payout_usdt'):
                deal.referrer_payout_usdt = round(deal.profit_usdt * deal.referrer_percent / 100, 2)
            referrer_payout = deal.referrer_payout_usdt or 0
            deal.net_profit_usdt = round(deal.profit_usdt - referrer_payout, 2)

        session.commit()
        
        # Обновление агрегатов реферера при завершении сделки
        if deal.status == DealStatus.COMPLETED and old_status != DealStatus.COMPLETED:
            if deal.referrer_id:
                referrer = session.query(Referrer).get(deal.referrer_id)
                if referrer:
                    referrer.total_deals = (referrer.total_deals or 0) + 1
                    referrer.total_earned_usdt = round(
                        (referrer.total_earned_usdt or 0) + (deal.referrer_payout_usdt or 0), 2
                    )
                    session.commit()

        # Webhook при завершении
        if deal.status == DealStatus.COMPLETED and old_status != DealStatus.COMPLETED:
            send_deal_completed_webhook(deal)
            # GSheet + Telegram только если сделка ещё НЕ была возмещена
            # (возмещение уже отправило уведомления при create_reimbursement)
            if deal.profit_usdt is not None and deal.reimbursement_id is None:
                try:
                    sync_deals_to_gsheet([deal])
                except Exception as e:
                    print(f'[GSheet] Sync error on complete: {e}')
                try:
                    _send_deal_telegram(deal)
                except Exception as e:
                    print(f'[Telegram] Error on complete: {e}')

        # Обновление строки в Google Sheet (если сделка возмещена — обновляем статус)
        if deal.reimbursement_id is not None:
            try:
                update_deal_in_gsheet(deal)
            except Exception as e:
                print(f'[GSheet] Update error: {e}')

        return jsonify({'success': True, 'deal': deal.to_dict()})
    except Exception as e:
        session.rollback()
        app.logger.error(f'Request error: {e}')
        return jsonify({'success': False, 'error': 'Ошибка обработки запроса'}), 400
    finally:
        session.close()

@app.route('/api/deals/<int:deal_id>', methods=['DELETE'])
def delete_deal(deal_id):
    session = get_session()
    try:

        deal = session.query(Deal).filter(Deal.id == deal_id).first()
        if not deal:
            return jsonify({'success': False, 'error': 'Сделка не найдена'}), 404
        
        # Запоминаем данные до удаления для Google Sheet
        reimbursement_id = deal.reimbursement_id
        was_reimbursed = deal.reimbursement_id is not None
        was_completed = deal.status == DealStatus.COMPLETED
        deal_client_name = deal.client_name
        deal_created_at = deal.created_at

        # Удаляем связанные операции по кошелькам (Binance списания)
        session.query(WalletOperation).filter(WalletOperation.deal_id == deal_id).delete()

        session.delete(deal)
        session.flush()

        # Удаляем пустые возмещения (без сделок)
        if reimbursement_id:
            remaining_deals = session.query(Deal).filter(Deal.reimbursement_id == reimbursement_id).count()
            if remaining_deals == 0:
                reimbursement = session.query(Reimbursement).filter(Reimbursement.id == reimbursement_id).first()
                if reimbursement:
                    session.delete(reimbursement)

        session.commit()

        # Удаляем из Google Sheet (если сделка была завершена — она могла попасть в таблицу)
        if was_completed or was_reimbursed:
            class _DealStub:
                pass
            stub = _DealStub()
            stub.client_name = deal_client_name
            stub.created_at = deal_created_at
            delete_deal_from_gsheet(stub)

        return jsonify({'success': True})
    except Exception as e:
        session.rollback()
        # Error logged internally
        app.logger.error(f'Request error: {e}')
        return jsonify({'success': False, 'error': 'Ошибка обработки запроса'}), 400
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

        # Валидация: сумма должна быть больше нуля
        if amount_thb <= 0 or cost_usdt <= 0:
            return jsonify({'success': False, 'error': 'Сумма должна быть больше нуля'}), 400

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
        app.logger.error(f'Request error: {e}')
        return jsonify({'success': False, 'error': 'Ошибка обработки запроса'}), 400
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
        app.logger.error(f'Request error: {e}')
        return jsonify({'success': False, 'error': 'Ошибка обработки запроса'}), 400
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
        app.logger.error(f'Server error: {e}')
        return jsonify({'success': False, 'error': 'Внутренняя ошибка сервера'}), 500
    finally:
        session.close()

# ==================== CRM API - WALLETS ====================

@app.route('/api/wallets', methods=['GET'])
def get_wallets():
    session = get_session()
    try:
        force_refresh = request.args.get('force_refresh', 'false').lower() == 'true'
        current_time = time.time()
        
        # Возвращаем только те, что для мониторинга
        wallets = session.query(Wallet).filter(Wallet.active == True, Wallet.is_monitored == True).order_by(Wallet.created_at.desc()).all()
        wallets_with_balance = []
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Apple) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        for wallet in wallets:
            wallet_data = wallet.to_dict()
            
            # Проверяем кэш для данного кошелька
            cache_entry = TRONSCAN_CACHE['balances'].get(wallet.address)
            if not force_refresh and cache_entry and (current_time - cache_entry['timestamp'] < CACHE_TTL):
                wallet_data['usdt_balance'] = cache_entry['usdt']
                wallet_data['trx_balance'] = cache_entry['trx']
                wallet_data['cached'] = True
                wallets_with_balance.append(wallet_data)
                continue

            wallet_data['usdt_balance'] = 0
            wallet_data['trx_balance'] = 0
            
            # Получаем баланс с TronScan
            try:
                balance_url = f'https://apilist.tronscanapi.com/api/account?address={wallet.address}'
                balance_resp = requests.get(balance_url, headers=headers, timeout=5)
                if balance_resp.status_code == 200:
                    balance_data = balance_resp.json()
                    wallet_data['trx_balance'] = float(balance_data.get('balance', 0)) / 1_000_000
                    for token in balance_data.get('trc20token_balances', []):
                        if token.get('tokenId') == 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t':
                            wallet_data['usdt_balance'] = float(token.get('balance', 0)) / 1_000_000
                            break
                    
                    # Обновляем кэш
                    TRONSCAN_CACHE['balances'][wallet.address] = {
                        'usdt': wallet_data['usdt_balance'],
                        'trx': wallet_data['trx_balance'],
                        'timestamp': current_time
                    }
                else:
                    # Если ошибка, попробуем альтернативный эндпоинт баланса
                    alt_url = f'https://apilist.tronscanapi.com/api/account/tokens?address={wallet.address}'
                    alt_resp = requests.get(alt_url, headers=headers, timeout=5)
                    if alt_resp.status_code == 200:
                        alt_data = alt_resp.json()
                        for token in alt_data.get('data', []):
                            if token.get('tokenId') == 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t':
                                wallet_data['usdt_balance'] = float(token.get('balance', 0)) / 1_000_000
                                break
                        
                        # Обновляем кэш (даже если TRX не нашли тут)
                        TRONSCAN_CACHE['balances'][wallet.address] = {
                            'usdt': wallet_data['usdt_balance'],
                            'trx': wallet_data['trx_balance'],
                            'timestamp': current_time
                        }
                # Небольшая пауза между кошельками
                time.sleep(0.3)
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
            # Если уже есть, просто включаем нужный флаг
            if data.get('is_monitored'): existing.is_monitored = True
            if data.get('is_balance'): existing.is_balance = True
            if data.get('label'): existing.label = data['label']
            session.commit()
            return jsonify({'success': True, 'wallet': existing.to_dict()})
        
        wallet = Wallet(
            address=address,
            blockchain=data.get('blockchain', 'TRON'),
            label=data.get('label', ''),
            is_monitored=data.get('is_monitored', True),
            is_balance=data.get('is_balance', False)
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
        app.logger.error(f'Server error: {e}')
        return jsonify({'success': False, 'error': 'Внутренняя ошибка сервера'}), 500
    finally:
        session.close()

@app.route('/api/wallets/<int:wallet_id>', methods=['DELETE'])
def delete_wallet(wallet_id):
    session = get_session()
    try:
        wallet = session.query(Wallet).filter(Wallet.id == wallet_id).first()
        if not wallet:
            return jsonify({'success': False, 'error': 'Кошелёк не найден'}), 404
        

        # Отвязываем кошелек от всех сделок перед удалением
        session.query(Deal).filter(Deal.payout_wallet_id == wallet_id).update({Deal.payout_wallet_id: None})
        
        session.delete(wallet)
        session.commit()
        return jsonify({'success': True})
    except Exception as e:
        session.rollback()
        app.logger.error(f'Server error: {e}')
        return jsonify({'success': False, 'error': 'Внутренняя ошибка сервера'}), 500
    finally:
        session.close()

def get_used_transaction_hashes(session):
    """Собрать все хэши транзакций, которые уже используются в системе"""
    used_hashes = set()
    
    # 1. Из таблицы Transaction
    db_txs = session.query(Transaction.tx_hash).filter(Transaction.deal_id != None).all()
    for tx in db_txs: used_hashes.add(tx[0])
    
    # 2. Из полей payin_tx_hash в Deal
    deals_payin = session.query(Deal.payin_tx_hash).filter(Deal.payin_tx_hash != None).all()
    for d in deals_payin: used_hashes.add(d[0])
    
    # 3. Из полей doverka_payout_hash в Deal
    deals_doverka = session.query(Deal.doverka_payout_hash).filter(Deal.doverka_payout_hash != None).all()
    for d in deals_doverka: used_hashes.add(d[0])
    
    # 4. Из полей tx_hash в Reimbursement
    reimb_txs = session.query(Reimbursement.tx_hash).filter(Reimbursement.tx_hash != None).all()
    for r in reimb_txs: used_hashes.add(r[0])
    
    # 5. Из таблицы WalletOperation
    wallet_ops = session.query(WalletOperation.tx_hash).filter(WalletOperation.tx_hash != None).all()
    for op in wallet_ops: used_hashes.add(op[0])
    
    return used_hashes

@app.route('/api/transactions/incoming', methods=['GET'])
def get_incoming_transactions():
    """Получить входящие USDT транзакции по всем кошелькам"""
    session = get_session()
    try:
        # Получаем фильтры
        wallet_filter = request.args.get('wallet')
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')
        
        start_ts = None
        if start_date_str:
            try:
                start_ts = int(datetime.strptime(start_date_str, '%Y-%m-%d').timestamp() * 1000)
            except: pass
            
        end_ts = None
        if end_date_str:
            try:
                end_ts = int((datetime.strptime(end_date_str, '%Y-%m-%d') + timedelta(days=1)).timestamp() * 1000)
            except: pass
        
        if wallet_filter:
            wallets = session.query(Wallet).filter(Wallet.address == wallet_filter, Wallet.active == True).all()
        else:
            wallets = session.query(Wallet).filter(Wallet.active == True, Wallet.is_monitored == True).all()
        
        # Проверяем кэш
        force_refresh = request.args.get('force_refresh', 'false').lower() == 'true'
        cache_key = wallet_filter or 'all'
        current_time = time.time()
        
        # Если не форсируем и есть свежий кэш
        if not force_refresh and TRONSCAN_CACHE['incoming']['data'] and (current_time - TRONSCAN_CACHE['incoming']['timestamp'] < CACHE_TTL):
            # Фильтруем кэшированные данные по кошельку, если нужно
            cached_data = TRONSCAN_CACHE['incoming']['data']
            if wallet_filter:
                cached_data = [tx for tx in cached_data if tx['to_address'] == wallet_filter]
            
            # Получаем актуальные использованные хэши
            used_hashes = get_used_transaction_hashes(session)
            
            available = [tx for tx in cached_data if tx['tx_hash'] not in used_hashes and tx.get('is_incoming')]
            used = [tx for tx in cached_data if tx['tx_hash'] in used_hashes]
            
            return jsonify({
                'success': True,
                'available': available[:1000],
                'used': used[:200],
                'cached': True,
                'cache_time': TRONSCAN_CACHE['incoming']['timestamp']
            })

        all_incoming = []
        wallets_checked = []
        wallets_errors = []

        usdt_contract = 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t'
        headers = {
            'User-Agent': 'Mozilla/5.0 (Apple) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }

        for wallet_idx, wallet in enumerate(wallets):
            wallet_tx_count = 0
            wallets_checked.append(wallet.address)

            # Пауза между кошельками чтобы не словить 429 от TronScan
            if wallet_idx > 0:
                time.sleep(1.5)

            try:
                for page in range(2):  # 2 страницы по 50 = 100 транзакций на кошелек
                    url = f'https://apilist.tronscanapi.com/api/token_trc20/transfers'
                    params = {
                        'relatedAddress': wallet.address,
                        'contract_address': usdt_contract,
                        'limit': 50,
                        'start': page * 50,
                        't': int(time.time())
                    }

                    # Retry при 429 (rate limit)
                    for attempt in range(3):
                        response = requests.get(url, params=params, headers=headers, timeout=10)
                        if response.status_code == 429:
                            wait_time = 2 * (attempt + 1)
                            print(f"[DEBUG] TronScan 429 for {wallet.address[:10]}..., waiting {wait_time}s (attempt {attempt+1})")
                            time.sleep(wait_time)
                            continue
                        break

                    if response.status_code == 200:
                        data = response.json()
                        transfers = data.get('token_transfers', [])
                        if not transfers:
                            break

                        reached_start_ts = False
                        for tx in transfers:
                            tx_ts = tx.get('block_ts', 0)

                            # Фильтр по дате (если задан)
                            if start_ts and tx_ts < start_ts:
                                reached_start_ts = True
                                continue
                            if end_ts and tx_ts > end_ts:
                                continue

                            amount = float(tx.get('quant', 0)) / 1_000_000

                            all_incoming.append({
                                'tx_hash': tx.get('transaction_id'),
                                'from_address': tx.get('from_address'),
                                'to_address': tx.get('to_address'),
                                'amount_usdt': amount,
                                'timestamp': datetime.fromtimestamp(tx_ts / 1000).isoformat(),
                                'confirmed': tx.get('confirmed', False),
                                'is_incoming': tx.get('to_address', '').lower() == wallet.address.lower()
                            })
                            wallet_tx_count += 1

                        if reached_start_ts:
                            break
                        # Пауза между страницами
                        time.sleep(1)
                    else:
                        error_msg = f"HTTP {response.status_code}"
                        wallets_errors.append({'address': wallet.address, 'error': error_msg})
                        print(f"[DEBUG] TronScan HTTP error for {wallet.address}: {error_msg}")
                        break
            except Exception as e:
                wallets_errors.append({'address': wallet.address, 'error': str(e)})
                print(f"[DEBUG] TronScan request error for {wallet.address}: {e}")

            print(f"[DEBUG] Wallet {wallet.address[:10]}... fetched {wallet_tx_count} transfers")
        
        # Сортируем все транзакции по времени
        all_incoming.sort(key=lambda x: x['timestamp'], reverse=True)
        
        # Обновляем кэш
        if not wallet_filter: # Кэшируем только общий список
            TRONSCAN_CACHE['incoming']['data'] = all_incoming
            TRONSCAN_CACHE['incoming']['timestamp'] = current_time
        
        used_hashes = get_used_transaction_hashes(session)
        
        # Фильтруем: available = входящие и не использованные
        available = [tx for tx in all_incoming if tx['tx_hash'] not in used_hashes and tx.get('is_incoming')]
        used = [tx for tx in all_incoming if tx['tx_hash'] in used_hashes]
        
        return jsonify({
            'success': True,
            'available': available[:1000],
            'used': used[:200],
            'wallets_checked': wallets_checked,
            'wallets_errors': wallets_errors,
            'total_fetched': len(all_incoming),
            'cached': False
        })
    except Exception as e:
        print(f"[DEBUG] get_incoming_transactions error: {e}")
        app.logger.error(f'Server error: {e}')
        return jsonify({'success': False, 'error': 'Внутренняя ошибка сервера'}), 500
    finally:
        session.close()

@app.route('/api/transactions/outgoing', methods=['GET'])
def get_outgoing_transactions():
    """Получить исходящие USDT транзакции по всем кошелькам"""
    session = get_session()
    try:
        # Получаем фильтры
        wallet_filter = request.args.get('wallet')
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')
        result_limit = request.args.get('limit', type=int)  # Ограничить кол-во результатов
        
        start_ts = None
        if start_date_str:
            try:
                start_ts = int(datetime.strptime(start_date_str, '%Y-%m-%d').timestamp() * 1000)
            except: pass
            
        end_ts = None
        if end_date_str:
            try:
                end_ts = int((datetime.strptime(end_date_str, '%Y-%m-%d') + timedelta(days=1)).timestamp() * 1000)
            except: pass

        # Проверяем кэш
        force_refresh = request.args.get('force_refresh', 'false').lower() == 'true'
        current_time = time.time()
        
        if not force_refresh and TRONSCAN_CACHE['outgoing']['data'] and (current_time - TRONSCAN_CACHE['outgoing']['timestamp'] < CACHE_TTL):
            cached_data = TRONSCAN_CACHE['outgoing']['data']
            if wallet_filter:
                cached_data = [tx for tx in cached_data if tx['from_address'] == wallet_filter]
            
            return jsonify({
                'success': True,
                'available': cached_data[:result_limit or 1000],
                'cached': True,
                'cache_time': TRONSCAN_CACHE['outgoing']['timestamp']
            })

        if wallet_filter:
            wallets = session.query(Wallet).filter(Wallet.address == wallet_filter, Wallet.active == True).all()
        else:
            wallets = session.query(Wallet).filter(Wallet.active == True, Wallet.is_monitored == True).all()

        if not wallets:
            return jsonify({'success': True, 'available': []})

        all_outgoing = []
        usdt_contract = 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t'
        headers = {
            'User-Agent': 'Mozilla/5.0 (Apple) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }

        # Только monitored-кошельки — для фильтрации внутренних переводов между своими.
        # Balance-кошельки (is_monitored=False) НЕ считаются внутренними: переводы туда
        # — легитимные исходящие (например, возмещения фаундеру на его balance-адрес),
        # и их нужно видеть в дропдауне возмещений.
        internal_wallet_addresses = set(w.address for w in session.query(Wallet).filter(Wallet.active == True, Wallet.is_monitored == True).all())

        for wallet_idx, wallet in enumerate(wallets):
            # Пауза между кошельками чтобы не словить 429 от TronScan
            if wallet_idx > 0:
                time.sleep(1.5)

            try:
                # При наличии limit — 1 страница с меньшим кол-вом, иначе 2 по 50
                api_limit = min(result_limit or 50, 50)
                max_pages = 1 if result_limit else 2
                for page in range(max_pages):
                    url = 'https://apilist.tronscanapi.com/api/token_trc20/transfers'
                    params = {
                        'relatedAddress': wallet.address,
                        'contract_address': usdt_contract,
                        'limit': api_limit,
                        'start': page * api_limit,
                        't': int(time.time())
                    }

                    # Retry при 429 (rate limit)
                    for attempt in range(3):
                        response = requests.get(url, params=params, headers=headers, timeout=10)
                        if response.status_code == 429:
                            wait_time = 2 * (attempt + 1)
                            print(f"[DEBUG] TronScan outgoing 429 for {wallet.address[:10]}..., waiting {wait_time}s")
                            time.sleep(wait_time)
                            continue
                        break

                    if response.status_code == 200:
                        data = response.json()
                        transfers = data.get('token_transfers', [])
                        if not transfers:
                            break

                        reached_start_ts = False
                        for tx in transfers:
                            tx_ts = tx.get('block_ts', 0)

                            if start_ts and tx_ts < start_ts:
                                reached_start_ts = True
                                continue
                            if end_ts and tx_ts > end_ts:
                                continue

                            # Только исходящие (from_address == наш кошелёк), исключая внутренние переводы между monitored-кошельками
                            if tx.get('from_address') == wallet.address and tx.get('to_address') not in internal_wallet_addresses:
                                amount = float(tx.get('quant', 0)) / 1_000_000
                                all_outgoing.append({
                                    'tx_hash': tx.get('transaction_id'),
                                    'from_address': tx.get('from_address'),
                                    'to_address': tx.get('to_address'),
                                    'amount_usdt': amount,
                                    'timestamp': datetime.fromtimestamp(tx_ts / 1000).isoformat(),
                                    'confirmed': tx.get('confirmed', False)
                                })

                        if reached_start_ts:
                            break
                        time.sleep(1)
                    else:
                        print(f"[DEBUG] TronScan outgoing HTTP {response.status_code} for {wallet.address[:10]}...")
                        break
            except Exception as e:
                print(f"[DEBUG] TronScan outgoing error for {wallet.address}: {e}")
        
        all_outgoing.sort(key=lambda x: x['timestamp'], reverse=True)

        # Дедупликация цепочек переводов: кошелёк → посредник → конечный
        # TronScan relatedAddress показывает обе ноги. Оставляем одну по amount+время (±15мин)
        deduped = []
        seen = set()
        for tx in all_outgoing:
            # Округляем время до 15 минут для группировки
            from datetime import datetime as dt
            ts = dt.fromisoformat(tx['timestamp'])
            bucket = (round(tx['amount_usdt'], 2), ts.strftime('%Y-%m-%d'), ts.hour, ts.minute // 15)
            if bucket in seen:
                continue
            seen.add(bucket)
            deduped.append(tx)
        all_outgoing = deduped

        # Обновляем кэш (полный набор, без limit-фильтра)
        if not wallet_filter and not result_limit:
            TRONSCAN_CACHE['outgoing']['data'] = all_outgoing
            TRONSCAN_CACHE['outgoing']['timestamp'] = current_time

        final_limit = result_limit or 1000
        return jsonify({
            'success': True,
            'available': all_outgoing[:final_limit],
            'cached': False
        })
    except Exception as e:
        app.logger.error(f'Server error: {e}')
        return jsonify({'success': False, 'error': 'Внутренняя ошибка сервера'}), 500
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
        app.logger.error(f'Server error: {e}')
        return jsonify({'success': False, 'error': 'Внутренняя ошибка сервера'}), 500

# ==================== CRM API - CLIENTS ====================

@app.route('/api/clients', methods=['GET'])
def get_clients():
    session = get_session()
    try:
        query = session.query(Client)
        search = request.args.get('search', '').strip()
        if search:
            query = query.filter(Client.name.ilike(f'%{search}%'))
        clients = query.order_by(Client.name).all()
        return jsonify({'success': True, 'clients': [c.to_dict() for c in clients]})
    except Exception as e:
        session.rollback()
        app.logger.error(f'Request error: {e}')
        return jsonify({'success': False, 'error': 'Ошибка обработки запроса'}), 400
    finally:
        session.close()

@app.route('/api/clients/<int:client_id>', methods=['DELETE'])
def delete_client(client_id):
    """Удаление клиента (только если нет сделок)."""
    session = get_session()
    try:
        client = session.query(Client).filter(Client.id == client_id).first()
        if not client:
            return jsonify({'success': False, 'error': 'Клиент не найден'}), 404
        deals_count = session.query(Deal).filter(Deal.client_id == client_id).count()
        if deals_count > 0:
            return jsonify({'success': False, 'error': f'У клиента {deals_count} сделок. Сначала удалите или переназначьте сделки.'}), 400
        session.delete(client)
        session.commit()
        return jsonify({'success': True})
    except Exception as e:
        session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        session.close()

# ==================== WALLET OPERATIONS API ====================

@app.route('/api/wallets/<int:wallet_id>/operations', methods=['GET'])
def get_wallet_operations(wallet_id):
    session = get_session()
    try:
        ops = session.query(WalletOperation).filter(WalletOperation.wallet_id == wallet_id).order_by(WalletOperation.created_at.desc()).all()
        return jsonify({'success': True, 'operations': [op.to_dict() for op in ops]})
    finally:
        session.close()

@app.route('/api/wallets/<int:wallet_id>/operations', methods=['POST'])
def create_wallet_operation(wallet_id):
    session = get_session()
    try:
        data = request.get_json()
        

        op = WalletOperation(
            wallet_id=wallet_id,
            type=data['type'],  # 'income' or 'expense'
            amount=float(data['amount']),
            description=data.get('description'),
            tx_hash=data.get('tx_hash')
        )
        session.add(op)
        session.commit()


        return jsonify({'success': True, 'operation': op.to_dict()})
    except Exception as e:
        session.rollback()
        app.logger.error(f'Request error: {e}')
        return jsonify({'success': False, 'error': 'Ошибка обработки запроса'}), 400
    finally:
        session.close()

@app.route('/api/wallets/operations/<int:op_id>', methods=['DELETE'])
def delete_wallet_operation(op_id):
    session = get_session()
    try:
        op = session.query(WalletOperation).filter(WalletOperation.id == op_id).first()
        if not op:
            return jsonify({'success': False, 'error': 'Операция не найдена'}), 404
        session.delete(op)
        session.commit()
        return jsonify({'success': True})
    except Exception as e:
        session.rollback()
        app.logger.error(f'Request error: {e}')
        return jsonify({'success': False, 'error': 'Ошибка обработки запроса'}), 400
    finally:
        session.close()

@app.route('/api/wallets/summary', methods=['GET'])
def get_wallets_summary():
    session = get_session()
    try:
        # Возвращаем только те, что для баланса
        wallets = session.query(Wallet).filter(Wallet.active == True, Wallet.is_balance == True).all()
        

        return jsonify({
            'success': True, 
            'wallets': [w.to_dict(session) for w in wallets]
        })
    finally:
        session.close()

# ==================== BANK CARDS API ====================

@app.route('/api/cards', methods=['GET'])
def get_cards():
    session = get_session()
    try:
        cards = session.query(BankCard).all()
        total_remaining = sum(c.balance_thb for c in cards if c.status == CashBatchStatus.ACTIVE)
        return jsonify({
            'success': True,
            'cards': [c.to_dict() for c in cards],
            'total_remaining_thb': total_remaining
        })
    finally:
        session.close()

@app.route('/api/cards', methods=['POST'])
def create_card():
    session = get_session()
    try:
        data = request.get_json()
        card = BankCard(
            bank_name=data['bank_name'],
            card_name=data.get('card_name'),
            holder_name=data.get('holder_name'),
            balance_thb=0
        )
        session.add(card)
        session.commit()
        return jsonify({'success': True, 'card': card.to_dict()})
    except Exception as e:
        session.rollback()
        app.logger.error(f'Request error: {e}')
        return jsonify({'success': False, 'error': 'Ошибка обработки запроса'}), 400
    finally:
        session.close()

@app.route('/api/cards/<int:card_id>', methods=['DELETE'])
def delete_card(card_id):
    session = get_session()
    try:
        card = session.query(BankCard).filter(BankCard.id == card_id).first()
        if not card:
            return jsonify({'success': False, 'error': 'Карта не найдена'}), 404
        
        # Только если нет пополнений
        if card.topups:
            return jsonify({'success': False, 'error': 'Нельзя удалить карту с историей пополнений'}), 400
            
        session.delete(card)
        session.commit()
        return jsonify({'success': True})
    except Exception as e:
        session.rollback()
        app.logger.error(f'Request error: {e}')
        return jsonify({'success': False, 'error': 'Ошибка обработки запроса'}), 400
    finally:
        session.close()

@app.route('/api/cards/balance', methods=['GET'])
def get_cards_balance():
    """Получить баланс всех активных карт для dropdown'а"""
    session = get_session()
    try:
        cards = session.query(BankCard).filter(
            BankCard.status == CashBatchStatus.ACTIVE,
            BankCard.balance_thb > 0
        ).order_by(BankCard.bank_name).all()

        result = []
        for c in cards:
            # Рассчитываем средневзвешенный курс закупки
            total_thb = sum(t.amount_thb for t in c.topups) if c.topups else 0
            total_usdt = sum(t.cost_usdt for t in c.topups) if c.topups else 0
            avg_rate = total_thb / total_usdt if total_usdt > 0 else 0

            result.append({
                'id': c.id,
                'bank_name': c.bank_name,
                'card_name': c.card_name,
                'holder_name': c.holder_name,
                'balance_thb': c.balance_thb,
                'avg_rate': round(avg_rate, 4) if avg_rate else 0
            })

        return jsonify({
            'success': True,
            'cards': result,
            'total_thb': sum(c.balance_thb for c in cards)
        })
    finally:
        session.close()

@app.route('/api/cards/<int:card_id>/topup', methods=['POST'])
def topup_card(card_id):
    session = get_session()
    try:
        data = request.get_json()
        card = session.query(BankCard).filter(BankCard.id == card_id).first()
        if not card:
            return jsonify({'success': False, 'error': 'Карта не найдена'}), 404

        amount_thb = float(data['amount_thb'])
        source_type = data['source_type'] # 'cash_batch' or 'separate'
        
        cost_usdt = 0
        purchase_rate = 0
        source_batch_id = None
        
        if source_type == 'cash_batch':
            batch_id = int(data['source_batch_id'])
            batch = session.query(CashBatch).filter(CashBatch.id == batch_id).first()
            if not batch or batch.remaining_thb < amount_thb:
                return jsonify({'success': False, 'error': 'Недостаточно средств в партии'}), 400
            
            source_batch_id = batch.id
            purchase_rate = batch.purchase_rate
            cost_usdt = amount_thb / purchase_rate
            
            # Списываем из партии
            batch.remaining_thb -= amount_thb
            if batch.remaining_thb < 0.1:
                batch.status = CashBatchStatus.DEPLETED
        else:
            # Отдельная закупка
            cost_usdt = float(data['cost_usdt'])
            purchase_rate = amount_thb / cost_usdt
            
        topup = CardTopup(
            card_id=card.id,
            amount_thb=amount_thb,
            cost_usdt=cost_usdt,
            purchase_rate=purchase_rate,
            source_type=source_type,
            source_batch_id=source_batch_id
        )
        
        card.balance_thb += amount_thb
        session.add(topup)
        session.commit()
        
        return jsonify({'success': True, 'topup': topup.to_dict()})
    except Exception as e:
        session.rollback()
        app.logger.error(f'Request error: {e}')
        return jsonify({'success': False, 'error': 'Ошибка обработки запроса'}), 400
    finally:
        session.close()

@app.route('/api/cards/<int:card_id>/history', methods=['GET'])
def get_card_history(card_id):
    """Получить историю пополнений карты"""
    session = get_session()
    try:
        card = session.query(BankCard).filter(BankCard.id == card_id).first()
        if not card:
            return jsonify({'success': False, 'error': 'Карта не найдена'}), 404

        topups = session.query(CardTopup).filter(
            CardTopup.card_id == card_id
        ).order_by(CardTopup.created_at.desc()).all()

        result = []
        for t in topups:
            topup_data = {
                'id': t.id,
                'created_at': t.created_at.isoformat() if t.created_at else None,
                'amount_thb': t.amount_thb,
                'cost_usdt': t.cost_usdt,
                'purchase_rate': t.purchase_rate,
                'source_type': t.source_type,
                'source_batch_id': t.source_batch_id
            }
            result.append(topup_data)

        return jsonify({
            'success': True,
            'card': {
                'id': card.id,
                'bank_name': card.bank_name,
                'card_name': card.card_name,
                'balance_thb': card.balance_thb
            },
            'topups': result,
            'total_topups': len(result)
        })
    finally:
        session.close()

@app.route('/api/cards/<int:card_id>/topup/<int:topup_id>', methods=['DELETE'])
def delete_card_topup(card_id, topup_id):
    session = get_session()
    try:
        topup = session.query(CardTopup).filter(CardTopup.id == topup_id, CardTopup.card_id == card_id).first()
        if not topup:
            return jsonify({'success': False, 'error': 'Пополнение не найдено'}), 404
            
        card = session.query(BankCard).filter(BankCard.id == card_id).first()
        
        returned_to_batch = None
        if topup.source_type == 'cash_batch' and topup.source_batch_id:
            batch = session.query(CashBatch).filter(CashBatch.id == topup.source_batch_id).first()
            if batch:
                batch.remaining_thb += topup.amount_thb
                batch.status = CashBatchStatus.ACTIVE
                returned_to_batch = batch.id
        
        card.balance_thb -= topup.amount_thb
        session.delete(topup)
        session.commit()
        
        return jsonify({'success': True, 'returned_to_batch': returned_to_batch, 'amount_returned': topup.amount_thb})
    except Exception as e:
        session.rollback()
        app.logger.error(f'Request error: {e}')
        return jsonify({'success': False, 'error': 'Ошибка обработки запроса'}), 400
    finally:
        session.close()

@app.route('/api/analytics/dashboard', methods=['GET'])
def get_dashboard():
    session = get_session()
    try:
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        week_ago = today - timedelta(days=7)

        # Период для графиков
        period = request.args.get('period', '30d')
        if period == 'today':
            chart_start = today
        elif period == 'week':
            chart_start = week_ago
        elif period == 'month':
            chart_start = today.replace(day=1)
        elif period == 'all':
            chart_start = datetime(2024, 1, 1)
        else:  # 30d
            chart_start = today - timedelta(days=30)

        cash_batches = session.query(CashBatch).filter(CashBatch.status == CashBatchStatus.ACTIVE).all()
        pending_deals = session.query(Deal).filter(Deal.status == DealStatus.PENDING).all()

        # Невозмещенные
        unreimbursed = session.query(Deal).filter(
            Deal.payout_source == PayOutSource.FOUNDER_PERSONAL,
            Deal.reimbursement_id == None
        ).all()

        # Метрики за выбранный период (chart_start)
        period_deals = session.query(Deal).filter(Deal.created_at >= chart_start).all()
        period_with_margin = [d for d in period_deals if d.profit_percent and d.profit_percent > 0]
        period_avg_margin = round(sum(d.profit_percent for d in period_with_margin) / len(period_with_margin), 1) if period_with_margin else 0
        period_with_payin = [d for d in period_deals if d.payin_amount_usdt and d.payin_amount_usdt > 0]
        period_avg_check = round(sum(d.payin_amount_usdt for d in period_with_payin) / len(period_with_payin), 2) if period_with_payin else 0
        period_profit = round(sum(d.net_profit_usdt or d.profit_usdt or 0 for d in period_deals), 2)
        period_volume = round(sum(d.payin_amount_usdt or 0 for d in period_deals), 2)

        # График: прибыль и объём по дням за выбранный период
        month_deals = session.query(Deal).filter(Deal.created_at >= chart_start).all()
        daily_data = {}
        for d in month_deals:
            day_key = d.created_at.strftime('%d.%m') if d.created_at else None
            if not day_key:
                continue
            if day_key not in daily_data:
                daily_data[day_key] = {'profit': 0, 'volume': 0, 'count': 0}
            daily_data[day_key]['profit'] += d.net_profit_usdt or d.profit_usdt or 0
            daily_data[day_key]['volume'] += d.payin_amount_usdt or 0
            daily_data[day_key]['count'] += 1

        # Сортируем по дате
        chart_days = []
        num_days = (today - chart_start).days
        for i in range(num_days, -1, -1):
            day = today - timedelta(days=i)
            key = day.strftime('%d.%m')
            entry = daily_data.get(key, {'profit': 0, 'volume': 0, 'count': 0})
            chart_days.append({
                'date': key,
                'profit': round(entry['profit'], 2),
                'volume': round(entry['volume'], 2),
                'count': entry['count']
            })

        # Распределение по методам Pay-In
        method_stats = {}
        for d in month_deals:
            method = d.payin_method.value if d.payin_method else 'unknown'
            if method not in method_stats:
                method_stats[method] = {'count': 0, 'volume': 0}
            method_stats[method]['count'] += 1
            method_stats[method]['volume'] += d.payin_amount_usdt or 0

        # New vs Old buyers за выбранный период
        period_client_ids = {d.client_id for d in period_deals if d.client_id}
        new_buyers = 0
        for cid in period_client_ids:
            first = session.query(Deal).filter(Deal.client_id == cid).order_by(Deal.created_at).first()
            if first and first.created_at and first.created_at >= chart_start:
                new_buyers += 1
        old_buyers = len(period_client_ids) - new_buyers

        return jsonify({
            'success': True,
            'dashboard': {
                'period': {
                    'deals_count': len(period_deals),
                    'profit_usdt': period_profit,
                    'volume_usdt': period_volume,
                    'avg_margin': period_avg_margin,
                    'avg_check': period_avg_check
                },
                'attention': {
                    'pending_deals': len(pending_deals),
                    'unreimbursed_founders': len(unreimbursed),
                    'unreimbursed_total_usdt': round(sum(d.payout_amount_usdt or 0 for d in unreimbursed), 2)
                },
                'charts': {
                    'daily': chart_days,
                    'methods': method_stats,
                    'buyers': {'new': new_buyers, 'old': old_buyers, 'total': len(period_client_ids)}
                }
            }
        })
    finally:
        session.close()

# ==================== REIMBURSEMENTS API ====================

@app.route('/api/reimbursements/pending', methods=['GET'])
def get_pending_reimbursements():
    """Get deals awaiting reimbursement, grouped by founder"""
    from sqlalchemy.orm import joinedload
    session = get_session()
    try:
        # Find deals with founder_personal source that haven't been reimbursed
        deals = session.query(Deal).options(joinedload(Deal.client)).filter(
            Deal.payout_source == PayOutSource.FOUNDER_PERSONAL,
            Deal.reimbursement_id == None,
            Deal.payout_founder_name != None,
            Deal.needs_reimbursement != False
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
    from sqlalchemy.orm import joinedload
    session = get_session()
    try:
        reimbursements = session.query(Reimbursement).options(
            joinedload(Reimbursement.deals)
        ).order_by(Reimbursement.created_at.desc()).all()
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
        tx_hash = data.get('tx_hash', '')
        # Поддержка массива хэшей (фронт может передать tx_hashes[] или tx_hash строкой)
        tx_hashes = data.get('tx_hashes', [])
        if tx_hashes:
            tx_hash = ', '.join(h.strip() for h in tx_hashes if h.strip())

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
        # Для пропорционального распределения USDT учитываем custom_payout_amount
        total_payout = sum((d.payout_amount_thb or d.custom_payout_amount or 0) for d in deals)
        for deal in deals:
            deal.reimbursement_id = reimbursement.id
            deal_payout = deal.payout_amount_thb or deal.custom_payout_amount or 0
            deal.payout_amount_usdt = amount_usdt * (deal_payout / total_payout) if deal_payout and total_payout else 0
            total_thb += deal_payout
            
            # Recalculate profit now that we know payout USDT
            if deal.payin_amount_usdt and deal.payout_amount_usdt:
                deal.profit_usdt = deal.payin_amount_usdt - deal.payout_amount_usdt
                deal.profit_percent = (deal.profit_usdt / deal.payout_amount_usdt * 100) if deal.payout_amount_usdt > 0 else 0

                # Recalculate net profit
                referrer_payout = deal.referrer_payout_usdt or 0
                deal.net_profit_usdt = deal.profit_usdt - referrer_payout

            # Возмещение = автозавершение сделки. Прибыль посчитана, деньги
            # фаундеру вернули — pending на этом этапе уже некорректен.
            if deal.status == DealStatus.PENDING:
                deal.status = DealStatus.COMPLETED

        session.commit()

        # Синк в Google Sheets после возмещения
        try:
            sync_deals_to_gsheet(deals)
        except Exception as gsheet_err:
            import traceback
            print(f'[GSheet] Error after reimbursement: {gsheet_err}', flush=True)
            print(f'[GSheet] Traceback: {traceback.format_exc()}', flush=True)

        # Уведомление в Telegram
        try:
            for deal in deals:
                _send_deal_telegram(deal)
        except Exception as tg_err:
            print(f'[Telegram] Error on reimbursement: {tg_err}')

        return jsonify({
            'success': True,
            'reimbursement': reimbursement.to_dict(),
            'deals_updated': len(deals),
            'total_thb': total_thb
        })
    except Exception as e:
        session.rollback()
        app.logger.error(f'Request error: {e}')
        return jsonify({'success': False, 'error': 'Ошибка обработки запроса'}), 400
    finally:
        session.close()

@app.route('/api/reimbursements/<int:reimbursement_id>', methods=['DELETE'])
def delete_reimbursement(reimbursement_id):
    """Delete a reimbursement"""
    session = get_session()
    try:
        reimbursement = session.query(Reimbursement).filter(Reimbursement.id == reimbursement_id).first()
        if not reimbursement:
            return jsonify({'success': False, 'error': 'Возмещение не найдено'}), 404
        
        # Unlink deals from this reimbursement
        deals = session.query(Deal).filter(Deal.reimbursement_id == reimbursement_id).all()
        for deal in deals:
            deal.reimbursement_id = None
        
        session.delete(reimbursement)
        session.commit()
        return jsonify({'success': True})
    except Exception as e:
        session.rollback()
        app.logger.error(f'Request error: {e}')
        return jsonify({'success': False, 'error': 'Ошибка обработки запроса'}), 400
    finally:
        session.close()

# ==================== MANUAL SYNC ====================

@app.route('/api/deals/sync-gsheet', methods=['POST'])
def manual_sync_gsheet():
    """Ручной синк сделок в Google Sheet по списку ID"""
    session = get_session()
    try:
        data = request.get_json()
        deal_ids = data.get('deal_ids', [])
        deals = session.query(Deal).filter(Deal.id.in_(deal_ids)).all()
        if not deals:
            return jsonify({'success': False, 'error': 'Сделки не найдены'}), 404
        result = sync_deals_to_gsheet(deals) or {}
        if not result.get('ok'):
            return jsonify({
                'success': False,
                'error': result.get('error', 'sync_failed'),
                'found_deals': len(deals),
            }), 500
        return jsonify({
            'success': True,
            'synced': len(deals),
            'inserted': result.get('inserted', 0),
        })
    except Exception as e:
        app.logger.error(f'Request error: {e}')
        return jsonify({'success': False, 'error': 'Ошибка обработки запроса'}), 400
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
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    chat_id = os.environ.get('TELEGRAM_CHAT_ID', '-1002274229486').strip()
    thread_id = os.environ.get('TELEGRAM_THREAD_ID', '2108').strip()
    if not token or not chat_id:
        print(f'[Telegram] Skip: token={bool(token)} chat_id={bool(chat_id)}')
        return False
    try:
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        if thread_id:
            payload["message_thread_id"] = int(thread_id)
        response = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                                json=payload, timeout=10)
        print(f'[Telegram] Sent: {response.status_code}')
        return response.status_code == 200
    except Exception as e:
        print(f'[Telegram] Error: {e}')
        return False

@app.route('/api/doverka/payments', methods=['GET'])
def doverka_payments_history():
    """Прокси для получения истории платежей Доверки"""
    from calculator import ExchangeRateProvider
    key = ExchangeRateProvider.DOVERKA_API_KEY
    if not key:
        return jsonify({'success': False, 'error': 'No Doverka API key'}), 500
    params = {k: v for k, v in request.args.items()}
    resp = requests.get(
        'https://api.doverkapay.com/v1/payments',
        headers={'Authorization': f'Bearer {key}', 'accept': 'application/json'},
        params=params, timeout=15
    )
    return jsonify(resp.json()), resp.status_code


@app.route('/api/proxy/create-payment', methods=['POST'])
def proxy_create_payment():
    """Прокси для создания платежа. Сначала grushab-2-b.ru, fallback на Doverka API."""
    data = request.get_json()
    provider = data.pop('provider', 'grusha')  # 'grusha' или 'doverka'

    if provider == 'grusha':
        # Пробуем grushab-2-b.ru (персонализированная страница)
        try:
            response = requests.post(
                'https://grushab-2-b.ru/api/payments',
                json=data,
                headers={'Content-Type': 'application/json', 'X-Provider-Name': 'doverkapay'},
                timeout=8
            )
            try:
                return jsonify(response.json()), response.status_code
            except Exception:
                return jsonify({'success': False, 'message': f'Grusha HTTP {response.status_code}', 'grusha_down': True}), 502
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            return jsonify({'success': False, 'message': 'grushab-2-b.ru не отвечает', 'grusha_down': True}), 503

    elif provider == 'doverka':
        # Прямой Doverka Partner API
        from calculator import ExchangeRateProvider
        key = ExchangeRateProvider.DOVERKA_API_KEY
        if not key:
            return jsonify({'success': False, 'message': 'No Doverka API key'}), 500
        try:
            # Получаем currency_id для USD (кэшируем)
            if not hasattr(proxy_create_payment, '_currency_id'):
                cur_resp = requests.get(
                    'https://api.doverkapay.com/v1/currencies',
                    headers={'Authorization': f'Bearer {key}', 'accept': 'application/json'},
                    timeout=10
                )
                if cur_resp.status_code == 200:
                    for c in cur_resp.json():
                        if c.get('symbol', '').upper() in ('USD', 'USDT'):
                            proxy_create_payment._currency_id = c.get('currency_id') or c.get('id')
                            break
                if not hasattr(proxy_create_payment, '_currency_id'):
                    return jsonify({'success': False, 'message': 'Не удалось получить currency_id'}), 500

            doverka_payload = {
                'currency_id': proxy_create_payment._currency_id,
                'amount_rub': data.get('amount'),
                'order_transaction_id': data.get('order_id', f'GR-{int(__import__("time").time() * 1000)}'),
                'order_title': data.get('description', 'Grusha Exchange'),
            }
            webhook_url = os.environ.get('DOVERKA_WEBHOOK_URL')
            if webhook_url:
                doverka_payload['callback_url'] = webhook_url

            response = requests.post(
                'https://api.doverkapay.com/v1/payments',
                json=doverka_payload,
                headers={
                    'Authorization': f'Bearer {key}',
                    'Content-Type': 'application/json',
                    'accept': 'application/json',
                },
                timeout=15
            )
            try:
                return jsonify(response.json()), response.status_code
            except Exception:
                return jsonify({'success': False, 'message': f'Doverka HTTP {response.status_code}: {response.text[:300]}'}), 502
        except Exception as e:
            app.logger.error(f'Doverka create-payment error: {e}')
            return jsonify({'success': False, 'message': f'Ошибка: {e}'}), 502


@app.route('/api/doverka/currencies', methods=['GET'])
def doverka_currencies():
    """Прокси для получения валют Доверки (нужен currency_id для создания платежа)"""
    from calculator import ExchangeRateProvider
    key = ExchangeRateProvider.DOVERKA_API_KEY
    if not key:
        return jsonify({'success': False, 'error': 'No Doverka API key'}), 500
    resp = requests.get(
        'https://api.doverkapay.com/v1/currencies',
        headers={'Authorization': f'Bearer {key}', 'accept': 'application/json'},
        timeout=15
    )
    return jsonify(resp.json()), resp.status_code

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
        app.logger.error(f'Webhook error: {e}')
        return jsonify({'error': 'Внутренняя ошибка'}), 500

@app.route('/api/doverka/confirm/<int:deal_id>', methods=['POST'])
def confirm_doverka(deal_id):
    """Подтвердить получение выплаты от Доверки вручную"""
    session = get_session()
    try:
        data = request.get_json()
        payout_hash = data.get('payout_hash')
        
        deal = session.query(Deal).filter(Deal.id == deal_id).first()
        if not deal:
            return jsonify({'success': False, 'error': 'Сделка не найдена'}), 404
            
        deal.doverka_status = DoverkaStatus.CONFIRMED
        deal.doverka_payout_hash = payout_hash
        deal.doverka_confirmed_at = datetime.utcnow()
        
        # Если сделка была в ожидании, переводим в завершенные
        if deal.status == DealStatus.PENDING:
            deal.status = DealStatus.COMPLETED
            
        # Автоматическое списание с кошелька при подтверждении (если выбрано)
        if deal.payout_source == PayOutSource.BINANCE and deal.payout_wallet_id and deal.payout_amount_usdt:
            # Ищем существующую операцию
            existing_op = session.query(WalletOperation).filter(
                WalletOperation.deal_id == deal.id,
                WalletOperation.type == 'expense'
            ).first()
            
            if not existing_op:
                op = WalletOperation(
                    wallet_id=deal.payout_wallet_id,
                    type='expense',
                    amount=deal.payout_amount_usdt,
                    description=f"Сделка #{deal.id} ({deal.client_name or 'без имени'})",
                    tx_hash=deal.payout_tx_hash,
                    deal_id=deal.id
                )
                session.add(op)

        session.commit()
        
        return jsonify({'success': True, 'deal': deal.to_dict()})
    except Exception as e:
        session.rollback()
        app.logger.error(f'Request error: {e}')
        return jsonify({'success': False, 'error': 'Ошибка обработки запроса'}), 400
    finally:
        session.close()

# ==================== KYC API ====================

import secrets
import shutil
from werkzeug.utils import secure_filename

# Папка для временного хранения KYC-файлов
KYC_UPLOAD_DIR = os.path.join(os.path.dirname(__file__), 'kyc_uploads')
os.makedirs(KYC_UPLOAD_DIR, exist_ok=True)

@app.route('/api/kyc/generate', methods=['POST'])
def kyc_generate_token():
    """Менеджер генерирует ссылку для клиента"""
    session = get_session()
    try:
        data = request.json or {}
        client_id = data.get('client_id')
        client_name = data.get('client_name', '')

        # Проверяем, нет ли уже активного KYC для клиента
        if client_id:
            existing = session.query(KycRequest).filter(
                KycRequest.client_id == client_id,
                KycRequest.status == KycStatus.PENDING
            ).first()
            if existing:
                return jsonify({'success': True, 'token': existing.token, 'existing': True})

        token = secrets.token_urlsafe(16)
        kyc = KycRequest(
            token=token,
            client_id=client_id,
            client_name=client_name
        )
        session.add(kyc)
        session.commit()
        return jsonify({'success': True, 'token': token})
    except Exception as e:
        session.rollback()
        app.logger.error(f'Request error: {e}')
        return jsonify({'success': False, 'error': 'Ошибка обработки запроса'}), 400
    finally:
        session.close()

@app.route('/api/kyc/status/<token>', methods=['GET'])
def kyc_status(token):
    """Клиент проверяет статус своей верификации"""
    session = get_session()
    try:
        kyc = session.query(KycRequest).filter(KycRequest.token == token).first()
        if not kyc:
            return jsonify({'success': False, 'error': 'invalid_token'}), 404

        result = {'success': True, 'status': kyc.status}
        if kyc.client_name:
            result['client_name'] = kyc.client_name
        if kyc.status == KycStatus.REJECTED:
            result['rejection_reason'] = kyc.rejection_reason
        return jsonify(result)
    finally:
        session.close()

@app.route('/api/kyc/submit', methods=['POST'])
def kyc_submit():
    """Клиент загружает файлы верификации"""
    token = request.form.get('token')
    if not token:
        return jsonify({'success': False, 'error': 'missing_token'}), 400

    session = get_session()
    try:
        kyc = session.query(KycRequest).filter(KycRequest.token == token).first()
        if not kyc:
            return jsonify({'success': False, 'error': 'invalid_token'}), 404

        if kyc.status == KycStatus.APPROVED:
            return jsonify({'success': False, 'error': 'already_verified'}), 400

        # Создаём папку для этого запроса
        upload_dir = os.path.join(KYC_UPLOAD_DIR, token)
        os.makedirs(upload_dir, exist_ok=True)

        # Сохраняем документ
        doc = request.files.get('document')
        if doc:
            doc_filename = f"doc_{secure_filename(doc.filename)}"
            doc_path = os.path.join(upload_dir, doc_filename)
            doc.save(doc_path)
            kyc.doc_path = doc_path

        # Сохраняем селфи
        selfie = request.files.get('selfie')
        if selfie:
            selfie_filename = f"selfie_{secure_filename(selfie.filename)}"
            selfie_path = os.path.join(upload_dir, selfie_filename)
            selfie.save(selfie_path)
            kyc.selfie_path = selfie_path

        # Сохраняем liveness-кадры
        liveness_files = request.files.getlist('liveness')
        if liveness_files:
            liveness_paths = []
            for i, f in enumerate(liveness_files):
                liveness_filename = f"liveness_{i}.jpg"
                liveness_path = os.path.join(upload_dir, liveness_filename)
                f.save(liveness_path)
                liveness_paths.append(liveness_path)
            kyc.liveness_paths = json.dumps(liveness_paths)

        # Сбрасываем статус на pending если клиент перезагружает после отклонения
        kyc.status = KycStatus.PENDING
        kyc.rejection_reason = None
        kyc.reviewed_at = None
        kyc.reviewed_by = None

        session.commit()
        return jsonify({'success': True, 'status': 'pending'})
    except Exception as e:
        session.rollback()
        app.logger.error(f'Server error: {e}')
        return jsonify({'success': False, 'error': 'Внутренняя ошибка сервера'}), 500
    finally:
        session.close()

@app.route('/api/kyc/list', methods=['GET'])
def kyc_list():
    """CRM: список всех KYC-запросов"""
    session = get_session()
    try:
        status_filter = request.args.get('status')
        query = session.query(KycRequest).order_by(KycRequest.created_at.desc())
        if status_filter:
            query = query.filter(KycRequest.status == status_filter)
        kycs = query.limit(100).all()
        return jsonify({'success': True, 'kyc_requests': [k.to_dict() for k in kycs]})
    finally:
        session.close()

@app.route('/api/kyc/review/<token>', methods=['GET'])
def kyc_review(token):
    """CRM: получить детали KYC для проверки"""
    session = get_session()
    try:
        kyc = session.query(KycRequest).filter(KycRequest.token == token).first()
        if not kyc:
            return jsonify({'success': False, 'error': 'not_found'}), 404
        return jsonify({'success': True, 'kyc': kyc.to_dict()})
    finally:
        session.close()

@app.route('/api/kyc/photo/<token>/<photo_type>', methods=['GET'])
def kyc_photo(token, photo_type):
    """CRM: получить фото для просмотра (doc, selfie, liveness_0..4)"""
    if not flask_session.get('user_id'):
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    session = get_session()
    try:
        kyc = session.query(KycRequest).filter(KycRequest.token == token).first()
        if not kyc:
            return '', 404

        if photo_type == 'doc' and kyc.doc_path and os.path.exists(kyc.doc_path):
            directory = os.path.dirname(kyc.doc_path)
            filename = os.path.basename(kyc.doc_path)
            return send_from_directory(directory, filename)
        elif photo_type == 'selfie' and kyc.selfie_path and os.path.exists(kyc.selfie_path):
            directory = os.path.dirname(kyc.selfie_path)
            filename = os.path.basename(kyc.selfie_path)
            return send_from_directory(directory, filename)
        elif photo_type.startswith('liveness_') and kyc.liveness_paths:
            idx = int(photo_type.split('_')[1])
            paths = json.loads(kyc.liveness_paths)
            if idx < len(paths) and os.path.exists(paths[idx]):
                directory = os.path.dirname(paths[idx])
                filename = os.path.basename(paths[idx])
                return send_from_directory(directory, filename)

        return '', 404
    finally:
        session.close()

@app.route('/api/kyc/approve/<token>', methods=['POST'])
def kyc_approve(token):
    """CRM: одобрить KYC"""
    session = get_session()
    try:
        data = request.json or {}
        kyc = session.query(KycRequest).filter(KycRequest.token == token).first()
        if not kyc:
            return jsonify({'success': False, 'error': 'not_found'}), 404

        kyc.status = KycStatus.APPROVED
        kyc.reviewed_at = datetime.utcnow()
        kyc.reviewed_by = data.get('manager', 'unknown')
        session.commit()

        # Удаляем файлы после одобрения — хранить не нужно
        _delete_kyc_files(token)

        return jsonify({'success': True, 'status': 'approved'})
    except Exception as e:
        session.rollback()
        app.logger.error(f'Server error: {e}')
        return jsonify({'success': False, 'error': 'Внутренняя ошибка сервера'}), 500
    finally:
        session.close()

@app.route('/api/kyc/reject/<token>', methods=['POST'])
def kyc_reject(token):
    """CRM: отклонить KYC"""
    session = get_session()
    try:
        data = request.json or {}
        kyc = session.query(KycRequest).filter(KycRequest.token == token).first()
        if not kyc:
            return jsonify({'success': False, 'error': 'not_found'}), 404

        kyc.status = KycStatus.REJECTED
        kyc.reviewed_at = datetime.utcnow()
        kyc.reviewed_by = data.get('manager', 'unknown')
        kyc.rejection_reason = data.get('reason', 'Фото не соответствует требованиям')
        session.commit()

        # Удаляем старые файлы — клиент загрузит новые
        _delete_kyc_files(token)

        return jsonify({'success': True, 'status': 'rejected'})
    except Exception as e:
        session.rollback()
        app.logger.error(f'Server error: {e}')
        return jsonify({'success': False, 'error': 'Внутренняя ошибка сервера'}), 500
    finally:
        session.close()

@app.route('/api/kyc/<token>', methods=['DELETE'])
def kyc_cancel(token):
    """CRM: отменить/удалить KYC-запрос"""
    session = get_session()
    try:
        kyc = session.query(KycRequest).filter(KycRequest.token == token).first()
        if not kyc:
            return jsonify({'success': False, 'error': 'not_found'}), 404

        # Удаляем файлы если есть
        _delete_kyc_files(token)

        # Удаляем запись из БД
        session.delete(kyc)
        session.commit()
        return jsonify({'success': True})
    except Exception as e:
        session.rollback()
        app.logger.error(f'Server error: {e}')
        return jsonify({'success': False, 'error': 'Внутренняя ошибка сервера'}), 500
    finally:
        session.close()

def _delete_kyc_files(token):
    """Удалить загруженные файлы KYC"""
    upload_dir = os.path.join(KYC_UPLOAD_DIR, token)
    if os.path.exists(upload_dir):
        shutil.rmtree(upload_dir, ignore_errors=True)

# ==================== REFERRAL SYSTEM ====================

@app.route('/ref/<token>')
def referrer_page(token):
    """Страница статистики реферера (публичная, по токену)"""
    return send_from_directory('static/referrer', 'index.html')


@app.route('/api/ref/<token>/stats', methods=['GET'])
def referrer_stats(token):
    """Публичная статистика реферера"""
    db = get_session()
    try:
        referrer = db.query(Referrer).filter(Referrer.token == token, Referrer.active == True).first()
        if not referrer:
            return jsonify({'success': False, 'error': 'Реферер не найден'}), 404

        # Последние сделки (без имён клиентов — конфиденциальность)
        deals = db.query(Deal).filter(
            Deal.referrer_id == referrer.id,
            Deal.status == DealStatus.COMPLETED
        ).order_by(Deal.created_at.desc()).limit(20).all()

        recent_deals = [{
            'date': d.created_at.strftime('%d.%m.%Y') if d.created_at else None,
            'volume_usdt': d.payout_amount_usdt,
            'commission_usdt': d.referrer_payout_usdt,
            'paid': d.referrer_paid or False,
        } for d in deals]

        # Считаем из реальных данных (не из кэшированных агрегатов)
        total_earned = sum(d.referrer_payout_usdt or 0 for d in deals)
        total_paid = sum((d.referrer_payout_usdt or 0) for d in deals if d.referrer_paid)
        referred_clients = db.query(Client).filter(Client.referrer_id == referrer.id).count()

        return jsonify({
            'success': True,
            'name': referrer.name,
            'code': referrer.code,
            'referral_link': f'https://grusha.space/?ref={referrer.code}',
            'bot_link': f'https://t.me/exgreen_pro_bot?start=ref__{referrer.code.replace("-", "")}',
            'wa_link': f'https://api.whatsapp.com/send/?phone=66818429939&text=%D0%97%D0%B4%D1%80%D0%B0%D0%B2%D1%81%D1%82%D0%B2%D1%83%D0%B9%D1%82%D0%B5%21+%D0%A5%D0%BE%D1%87%D1%83+%D1%83%D1%82%D0%BE%D1%87%D0%BD%D0%B8%D1%82%D1%8C+%D0%B4%D0%B5%D1%82%D0%B0%D0%BB%D0%B8+%D0%BE%D0%B1%D0%BC%D0%B5%D0%BD%D0%B0.%0A%0A%28%D0%98%D1%81%D1%82%D0%BE%D1%87%D0%BD%D0%B8%D0%BA%3A+ref_{referrer.code.replace("-", "")}%29&type=phone_number&app_absent=0',
            'payout_currency': referrer.payout_currency or 'USDT',
            'default_percent': referrer.default_percent,
            'total_referred_clients': referred_clients,
            'total_deals': len(deals),
            'total_earned_usdt': round(total_earned, 2),
            'total_paid_usdt': round(total_paid, 2),
            'pending_usdt': round(total_earned - total_paid, 2),
            'recent_deals': recent_deals,
        })
    finally:
        db.close()


@app.route('/api/referrers', methods=['GET'])
def get_referrers():
    """Список рефереров (для CRM) — данные из реальных сделок, не из кэша."""
    db = get_session()
    try:
        referrers = db.query(Referrer).order_by(Referrer.created_at.desc()).all()
        result = []
        for r in referrers:
            d = r.to_dict()
            # Пересчитываем из реальных сделок (кэш может рассинхронизироваться)
            deals = db.query(Deal).filter(
                Deal.referrer_id == r.id, Deal.status == DealStatus.COMPLETED
            ).all()
            d['total_deals'] = len(deals)
            d['total_earned_usdt'] = round(sum(dl.referrer_payout_usdt or 0 for dl in deals), 2)
            d['total_paid_usdt'] = round(sum((dl.referrer_payout_usdt or 0) for dl in deals if dl.referrer_paid), 2)
            d['pending_usdt'] = round(d['total_earned_usdt'] - d['total_paid_usdt'], 2)
            d['total_referred_clients'] = db.query(Client).filter(Client.referrer_id == r.id).count()
            result.append(d)
        return jsonify({'success': True, 'referrers': result})
    finally:
        db.close()


@app.route('/api/referrers', methods=['POST'])
def create_referrer():
    """Создать реферера"""
    import secrets
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    code = data.get('code', '').strip().upper()
    default_percent = data.get('default_percent', 10.0)
    payout_currency = data.get('payout_currency', 'USDT').upper()
    if payout_currency not in ('USDT', 'THB'):
        payout_currency = 'USDT'
    telegram = data.get('telegram', '').strip()

    if not name:
        return jsonify({'success': False, 'error': 'Укажите имя'}), 400

    db = get_session()
    try:
        # Генерируем код если не задан
        if not code:
            # GR-ИМЯ (транслит первых 5 букв)
            import re
            slug = re.sub(r'[^A-Za-z0-9]', '', name.upper())[:6]
            code = f'GR-{slug}' if slug else f'GR-{secrets.token_hex(3).upper()}'

        # Проверяем уникальность кода
        existing = db.query(Referrer).filter(Referrer.code == code).first()
        if existing:
            return jsonify({'success': False, 'error': f'Код {code} уже занят'}), 400

        token = secrets.token_hex(16)  # 32 символа
        referrer = Referrer(
            name=name, code=code, token=token,
            telegram=telegram,
            default_percent=float(default_percent),
            payout_currency=payout_currency,
            client_id=data.get('client_id'),
        )
        db.add(referrer)
        db.commit()
        return jsonify({'success': True, 'referrer': referrer.to_dict()})
    finally:
        db.close()


@app.route('/api/referrers/<int:referrer_id>', methods=['PUT'])
def update_referrer(referrer_id):
    """Обновить реферера"""
    data = request.get_json() or {}
    db = get_session()
    try:
        referrer = db.query(Referrer).get(referrer_id)
        if not referrer:
            return jsonify({'success': False, 'error': 'Реферер не найден'}), 404

        if 'name' in data:
            referrer.name = data['name'].strip()
        if 'default_percent' in data:
            referrer.default_percent = float(data['default_percent'])
        if 'active' in data:
            referrer.active = bool(data['active'])
        if 'telegram' in data:
            referrer.telegram = data['telegram'].strip()
        if 'payout_currency' in data:
            pc = data['payout_currency'].upper()
            if pc in ('USDT', 'THB'):
                referrer.payout_currency = pc
        if 'notes' in data:
            referrer.notes = data['notes']
        if 'total_paid_usdt' in data:
            referrer.total_paid_usdt = float(data['total_paid_usdt'])

        db.commit()
        return jsonify({'success': True, 'referrer': referrer.to_dict()})
    finally:
        db.close()


@app.route('/api/referrers/<int:referrer_id>', methods=['DELETE'])
def delete_referrer(referrer_id):
    """Деактивировать реферера (не удаляем — мягкое удаление)"""
    db = get_session()
    try:
        referrer = db.query(Referrer).get(referrer_id)
        if not referrer:
            return jsonify({'success': False, 'error': 'Реферер не найден'}), 404
        referrer.active = False
        db.commit()
        return jsonify({'success': True})
    finally:
        db.close()


@app.route('/api/referrers/lookup', methods=['GET'])
def lookup_referrer():
    """Найти реферера по коду (для DealCloser и CRM).
    Нормализует код: GR-ED и GRED находят одного реферера.
    """
    import re
    code = request.args.get('code', '').strip().upper()
    if not code:
        return jsonify({'success': False, 'error': 'Укажите код'}), 400

    db = get_session()
    try:
        # Точный поиск
        referrer = db.query(Referrer).filter(Referrer.code == code, Referrer.active == True).first()
        # Нормализованный поиск (без дефисов/подчёркиваний) — для start-параметра TG
        if not referrer:
            normalized = re.sub(r'[^A-Z0-9]', '', code)
            for r in db.query(Referrer).filter(Referrer.active == True).all():
                if re.sub(r'[^A-Z0-9]', '', r.code) == normalized:
                    referrer = r
                    break
        if not referrer:
            return jsonify({'success': False, 'error': 'Реферер не найден'}), 404
        return jsonify({'success': True, 'referrer': referrer.to_dict()})
    finally:
        db.close()


@app.route('/api/clients/<int:client_id>/set-referrer', methods=['POST'])
def set_client_referrer(client_id):
    """Привязать клиента к рефереру по коду"""
    data = request.get_json() or {}
    code = data.get('code', '').strip().upper()
    referrer_id = data.get('referrer_id')

    db = get_session()
    try:
        client = db.query(Client).get(client_id)
        if not client:
            return jsonify({'success': False, 'error': 'Клиент не найден'}), 404

        if code:
            import re
            referrer = db.query(Referrer).filter(Referrer.code == code, Referrer.active == True).first()
            # Нормализованный поиск (GRED → GR-ED)
            if not referrer:
                normalized = re.sub(r'[^A-Z0-9]', '', code)
                for r in db.query(Referrer).filter(Referrer.active == True).all():
                    if re.sub(r'[^A-Z0-9]', '', r.code) == normalized:
                        referrer = r
                        break
        elif referrer_id:
            referrer = db.query(Referrer).get(referrer_id)
        else:
            return jsonify({'success': False, 'error': 'Укажите code или referrer_id'}), 400

        if not referrer:
            return jsonify({'success': False, 'error': 'Реферер не найден'}), 404

        # Привязываем (первая привязка, lifetime)
        if client.referrer_id and client.referrer_id != referrer.id:
            return jsonify({'success': False, 'error': f'Клиент уже привязан к рефереру {client.referrer.name}'}), 400

        if not client.referrer_id:
            client.referrer_id = referrer.id
            referrer.total_referred_clients = (referrer.total_referred_clients or 0) + 1

        db.commit()
        return jsonify({'success': True, 'client': client.to_dict(), 'referrer': referrer.to_dict()})
    finally:
        db.close()


@app.route('/api/referrers/<int:referrer_id>/pay', methods=['POST'])
def pay_referrer(referrer_id):
    """Отметить выплату рефереру (все неоплаченные сделки)"""
    db = get_session()
    try:
        referrer = db.query(Referrer).get(referrer_id)
        if not referrer:
            return jsonify({'success': False, 'error': 'Реферер не найден'}), 404

        # Находим все завершённые неоплаченные сделки
        unpaid_deals = db.query(Deal).filter(
            Deal.referrer_id == referrer.id,
            Deal.status == DealStatus.COMPLETED,
            Deal.referrer_paid == False,
            Deal.referrer_payout_usdt > 0,
        ).all()

        total_paid = 0
        for deal in unpaid_deals:
            deal.referrer_paid = True
            total_paid += deal.referrer_payout_usdt or 0

        referrer.total_paid_usdt = round((referrer.total_paid_usdt or 0) + total_paid, 2)
        db.commit()

        return jsonify({
            'success': True,
            'deals_paid': len(unpaid_deals),
            'amount_usdt': round(total_paid, 2),
            'referrer': referrer.to_dict(),
        })
    finally:
        db.close()


# ==================== PARTNER CALCULATOR ====================

@app.route('/api/partner/<token>/calculate', methods=['GET'])
def partner_calculate(token):
    """Расчёт курса для партнёра — публичный, по токену"""
    db = get_session()
    try:
        partner = db.query(Partner).filter_by(token=token, active=True).first()
        if not partner:
            return jsonify({'success': False, 'error': 'Недействительная ссылка'}), 404

        amount = request.args.get('amount', type=float)
        direction = request.args.get('direction', 'usdt-to-thb')  # usdt-to-thb | thb-to-usdt

        if not amount or amount <= 0:
            return jsonify({'success': False, 'error': 'Укажите сумму'}), 400

        # Получаем курс Binance
        rates = asyncio.run(ExchangeRateProvider.get_all_rates())
        binance_rate = rates.get('usdt_thb')
        if not binance_rate:
            return jsonify({'success': False, 'error': 'Курс временно недоступен'}), 503

        # Наценка зависит от направления:
        # USDT→THB: курс ниже рынка (клиент получает меньше THB)
        # THB→USDT: курс выше рынка (клиенту нужно больше THB за 1 USDT → получает меньше USDT)
        if direction == 'usdt-to-thb':
            partner_rate = binance_rate * (1 - partner.markup_percent / 100)
            result_amount = round(amount * partner_rate, 2)
            return jsonify({
                'success': True,
                'rate': round(partner_rate, 4),
                'usdt': amount,
                'thb': result_amount
            })
        else:  # thb-to-usdt
            partner_rate = binance_rate * (1 + partner.markup_percent / 100)
            result_amount = round(amount / partner_rate, 2)
            return jsonify({
                'success': True,
                'rate': round(partner_rate, 4),
                'thb': amount,
                'usdt': result_amount
            })
    finally:
        db.close()


@app.route('/api/partner/<token>/info', methods=['GET'])
def partner_info(token):
    """Проверка токена партнёра — имя + текущий курс"""
    db = get_session()
    try:
        partner = db.query(Partner).filter_by(token=token, active=True).first()
        if not partner:
            return jsonify({'success': False}), 404

        rates = asyncio.run(ExchangeRateProvider.get_all_rates())
        binance_rate = rates.get('usdt_thb')

        return jsonify({
            'success': True,
            'name': partner.name,
            'rate_buy': round(binance_rate * (1 - partner.markup_percent / 100), 4) if binance_rate else None,
            'rate_sell': round(binance_rate * (1 + partner.markup_percent / 100), 4) if binance_rate else None,
        })
    finally:
        db.close()


@app.route('/api/partner/<token>/precise', methods=['POST'])
def partner_precise_rate(token):
    """Точный курс через Playwright для партнёра"""
    db = get_session()
    try:
        partner = db.query(Partner).filter_by(token=token, active=True).first()
        if not partner:
            return jsonify({'success': False, 'error': 'Invalid link'}), 404

        data = request.get_json() or {}
        usdt_amount = data.get('usdt_amount')
        thb_amount = data.get('thb_amount')

        if not usdt_amount and not thb_amount:
            return jsonify({'success': False, 'error': 'Specify amount'}), 400

        # Безопасные суммы для ретрая при превышении лимита Binance
        SAFE_USDT = 50000
        SAFE_THB = 1600000

        # Определяем направление парсинга
        if usdt_amount:
            playwright_result = asyncio.run(ExchangeRateProvider.get_precise_binance_rate(
                usdt_amount=round(float(usdt_amount), 2),
                direction='usdt_to_thb'
            ))
            # Если упал — ретрай с безопасной суммой
            if 'error' in playwright_result:
                print(f"⚠️ Playwright failed for {usdt_amount} USDT, retrying with {SAFE_USDT}", flush=True)
                playwright_result = asyncio.run(ExchangeRateProvider.get_precise_binance_rate(
                    usdt_amount=SAFE_USDT,
                    direction='usdt_to_thb'
                ))
        else:
            playwright_result = asyncio.run(ExchangeRateProvider.get_precise_binance_rate(
                thb_amount=round(float(thb_amount)),
                direction='usdt_to_thb_reverse'
            ))
            if 'error' in playwright_result:
                print(f"⚠️ Playwright failed for {thb_amount} THB, retrying with {SAFE_THB}", flush=True)
                playwright_result = asyncio.run(ExchangeRateProvider.get_precise_binance_rate(
                    thb_amount=SAFE_THB,
                    direction='usdt_to_thb_reverse'
                ))

        if 'error' in playwright_result:
            return jsonify({'success': False, 'error': 'Rate temporarily unavailable'}), 503

        binance_rate = playwright_result['rate']
        markup = partner.markup_percent

        return jsonify({
            'success': True,
            'rate_buy': round(binance_rate * (1 - markup / 100), 4),
            'rate_sell': round(binance_rate * (1 + markup / 100), 4),
            'time': playwright_result['time']
        })
    finally:
        db.close()


# ==================== PARTNER ADMIN (CRM) ====================

@app.route('/api/partners', methods=['GET'])
def get_partners():
    """Список партнёров (для CRM)"""
    db = get_session()
    try:
        partners = db.query(Partner).order_by(Partner.created_at.desc()).all()
        return jsonify({'success': True, 'partners': [p.to_dict() for p in partners]})
    finally:
        db.close()


@app.route('/api/partners', methods=['POST'])
def create_partner():
    """Создать партнёра"""
    import secrets
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    markup = data.get('markup_percent', 1.4)

    if not name:
        return jsonify({'success': False, 'error': 'Укажите имя'}), 400

    db = get_session()
    try:
        token = secrets.token_hex(12)  # 24 символа
        partner = Partner(name=name, token=token, markup_percent=float(markup))
        db.add(partner)
        db.commit()
        return jsonify({'success': True, 'partner': partner.to_dict()})
    finally:
        db.close()


@app.route('/api/partners/<int:partner_id>', methods=['PUT'])
def update_partner(partner_id):
    """Обновить партнёра (наценку, имя, активность)"""
    data = request.get_json() or {}
    db = get_session()
    try:
        partner = db.query(Partner).get(partner_id)
        if not partner:
            return jsonify({'success': False, 'error': 'Партнёр не найден'}), 404

        if 'name' in data:
            partner.name = data['name'].strip()
        if 'markup_percent' in data:
            partner.markup_percent = float(data['markup_percent'])
        if 'active' in data:
            partner.active = bool(data['active'])

        db.commit()
        return jsonify({'success': True, 'partner': partner.to_dict()})
    finally:
        db.close()


@app.route('/api/partners/<int:partner_id>', methods=['DELETE'])
def delete_partner(partner_id):
    """Удалить партнёра"""
    db = get_session()
    try:
        partner = db.query(Partner).get(partner_id)
        if not partner:
            return jsonify({'success': False, 'error': 'Партнёр не найден'}), 404
        db.delete(partner)
        db.commit()
        return jsonify({'success': True})
    finally:
        db.close()


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

@app.route('/docs/<path:filename>')
def docs_static(filename):
    """Статические документы (инструкции)"""
    return send_from_directory('static/docs', filename)

@app.route('/calculator/<path:filename>')
def calculator_static(filename):
    if not flask_session.get('user_id'):
        return redirect('/login')
    return send_from_directory('static/calculator', filename)

@app.route('/auth/<path:filename>')
def auth_static(filename):
    """Статика страницы логина (публичная)"""
    return send_from_directory('static/auth', filename)

@app.route('/crm/<path:filename>')
def crm_static(filename):
    if not flask_session.get('user_id'):
        return redirect('/login')
    return send_from_directory('static/crm', filename)

@app.route('/<path:filename>')
def static_files(filename):
    if filename.startswith('api'):
        return '', 404
    allowed = ['.css', '.js', '.png', '.jpg', '.svg', '.ico']
    if any(filename.endswith(ext) for ext in allowed):
        if not flask_session.get('user_id'):
            return '', 401
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
