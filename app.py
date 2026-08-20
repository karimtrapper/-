"""
Unified Service: Calculator + CRM
Объединённый сервис калькулятора и CRM для Railway
"""

from flask import Flask, jsonify, request, send_from_directory, send_file, redirect, session as flask_session
from flask_cors import CORS
from datetime import datetime, timedelta, date
import os
import sys
import requests
import threading
import asyncio
import time
import json
import re
import math
import hashlib
import hmac
import secrets
import bcrypt
import logging
import gspread
from google.oauth2.service_account import Credentials as GoogleCredentials

# ==================== FLASK APP ====================
from werkzeug.middleware.proxy_fix import ProxyFix
# Расчётное ядро конвертаций вынесено в отдельный модуль (чистые функции, без
# Flask/БД/сети): формулы лежали россыпью между строками 2400 и 5800, и одна
# и та же успела разойтись по четырём местам. Имена с подчёркиванием сохранены —
# их зовёт остальной код и тесты, менять вызовы ради переезда лишний риск.
from conversions_core import (conversion_shares as _conversion_shares,
                              match_wl_deal as _match_wl_deal,
                              parse_sent_at as _parse_sent_at)
app = Flask(__name__, static_folder='static')
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)  # Railway proxy
app.secret_key = os.environ['SECRET_KEY']  # Без fallback — crash если не задан
# Дефолт — актуальный прод-домен (старый proud-renewal-… умер 16.06.2026).
# На проде переопределяется через env CORS_ORIGINS.
cors_origins = os.environ.get('CORS_ORIGINS', 'https://grusha.up.railway.app').split(',')
CORS(app, origins=cors_origins, supports_credentials=True)
# 30MB: KYC-сабмит везёт паспорт + селфи + 5 liveness-кадров + видео-заявление
# одним multipart-запросом. Пофайловые лимиты жёстче и проверяются в kyc_submit.
app.config['MAX_CONTENT_LENGTH'] = 30 * 1024 * 1024  # макс размер загрузки
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
    '/api/tg/',                                # Webhook бота-логина (защищён secret_token)
    '/api/health',                             # Health check
    '/api/auth/',                              # Авторизация
    '/api/webhook/doverka',                    # Вебхук Doverka (защищён HMAC-подписью)
    '/api/sber-incomes/ingest',                # Пуш приходов Сбера с VPS (защищён X-Api-Key)
    '/api/webhook/payment-link',               # Коннектор сообщает об оплате ссылки (защищён ключом в URL)
]

# Что открывает read-only ключ (SERVICE_API_KEY_RO) — Claude Code фаундера.
# Белый список, а не «любой GET»: снаружи остаются персональные данные клиентов
# (/api/kyc/photo отдаёт паспорта и селфи) и платные вызовы модели
# (/api/bitrix/deals/<id>/analyze гоняет LLM по чату на каждый запрос).
READONLY_PATHS = [
    '/api/deals',                 # сделки: список, карточка, кандидаты LOSE
    '/api/clients', '/api/managers',
    '/api/referrers',             # рефереры, их неоплаченные сделки, заявки
    '/api/payout-requests',       # заявки рефереров на вывод
    '/api/reimbursements',        # возмещения, в т.ч. /pending — что не возмещено
    '/api/wallets', '/api/cards', '/api/cash/',
    '/api/transactions/',         # приходы и расходы по кошелькам
    '/api/sber-incomes', '/api/wl-transactions',
    '/api/analytics/',            # дашборд, юнит-экономика, конверсия
    '/api/reestr/',
    '/api/health',
]

# Read-only ключи: имя env-переменной → его белый список путей. У каждого
# интеграционного ключа свой скоуп — внешним не открывается ни финансы сделок,
# ни KYC. Отзыв ключа = убрать переменную из env, остальные ключи не замечают.
READONLY_KEY_SCOPES = {
    'SERVICE_API_KEY_RO': READONLY_PATHS,   # ключ фаундера — всё чтение
    'SERVICE_API_KEY_RO_LEADS': [           # внешняя интеграция «лиды/мерчанты»
        '/api/clients',                     # лиды = клиенты CRM
        '/api/reestr/',                     # мерчанты WL-реестра (view merchants в /all)
        '/api/health',
    ],
}


def _api_key_matches(expected: str) -> bool:
    """Сравнивает заголовок X-Api-Key с ключом из env.

    Сравнение по байтам, а не по строкам: `secrets.compare_digest` на non-ASCII
    строке кидает TypeError — заголовок с кириллицей ронял запрос в 500 вместо
    честного 401.
    """
    if not expected:
        return False
    return secrets.compare_digest(
        request.headers.get('X-Api-Key', '').encode('utf-8'),
        expected.encode('utf-8'),
    )


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

    # Локальный стенд без логина: только при явном флаге И только на sqlite.
    # На проде DATABASE_URL — Postgres, поэтому обход невозможен даже если
    # переменную выставят по ошибке.
    if os.environ.get('LOCAL_NO_AUTH') == '1' and 'postgresql' not in DATABASE_URL:
        return None

    # Сервисный доступ для ботов (DealCloser, SberNotifier) — непротухающий API-ключ.
    # Иммунитет к ротации человеческого пароля админа: ключ живёт в env, не в БД.
    if _api_key_matches(os.environ.get('SERVICE_API_KEY', '')):
        return None

    # Read-only ключи — только GET и только пути из скоупа конкретного ключа
    # (READONLY_KEY_SCOPES). Боты на основном ключе этой ветки не видят.
    for ro_env, ro_scope in READONLY_KEY_SCOPES.items():
        if not _api_key_matches(os.environ.get(ro_env, '')):
            continue
        if request.method != 'GET':
            return jsonify({'success': False, 'error': 'read_only_key',
                            'detail': 'Ключ только для чтения — запись через CRM'}), 403
        if not any(path.startswith(p) for p in ro_scope):
            return jsonify({'success': False, 'error': 'read_only_key_scope',
                            'detail': f'Путь {path} закрыт для read-only ключа'}), 403
        app.logger.info(f'RO-ключ {ro_env}: GET {path}')
        return None

    # Проверяем сессию
    uid = flask_session.get('user_id')
    if not uid:
        if path.startswith('/api/'):
            return jsonify({'success': False, 'error': 'unauthorized'}), 401
        return redirect('/login')

    # Серверная ревалидация: сессия жива только пока админ существует в БД.
    # Удаление админа из whitelist → мгновенный разлог (cookie сам по себе не даёт доступ).
    db = get_session()
    try:
        still_admin = db.query(AdminUser.id).filter(AdminUser.id == uid).first() is not None
    finally:
        db.close()
    if not still_admin:
        flask_session.clear()
        if path.startswith('/api/'):
            return jsonify({'success': False, 'error': 'unauthorized'}), 401
        return redirect('/login')

# ==================== DATABASE ====================
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session

# Автоматически выбираем PostgreSQL для прода или SQLite для локальной разработки
DATABASE_URL = os.environ.get('DATABASE_URL', '')
if DATABASE_URL.startswith('sqlite'):
    # Отдельный sqlite-файл: демо-стенд не должен жить в одной базе с тестами —
    # они чистят deals/clients/admins и стирают всё, что там завели руками
    engine = create_engine(DATABASE_URL, echo=False, connect_args={'check_same_thread': False})
elif DATABASE_URL:
    # Railway PostgreSQL (иногда начинается с postgres://, нужно postgresql://)
    if DATABASE_URL.startswith('postgres://'):
        DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
    engine = create_engine(DATABASE_URL, echo=False, connect_args={'connect_timeout': 10})
else:
    # Локальная SQLite по умолчанию
    DATABASE_PATH = os.path.join(os.path.dirname(__file__), 'local.db')
    DATABASE_URL = f'sqlite:///{DATABASE_PATH}'
    engine = create_engine(DATABASE_URL, echo=False, connect_args={'check_same_thread': False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
Session = scoped_session(SessionLocal)

def get_session():
    return Session()


def parse_float(value, default=0.0):
    """Безопасный парсинг числа из формы: '', None, пробелы и запятая-разделитель
    (RU-локаль) больше не роняют ручку в 500 через ValueError."""
    if value is None:
        return default
    if isinstance(value, str):
        value = value.strip().replace(' ', '').replace(',', '.')
        if not value:
            return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default

# ==================== TRONSCAN CACHE ====================
TRONSCAN_CACHE = {
    'incoming': {'data': None, 'timestamp': 0},
    'outgoing': {'data': None, 'timestamp': 0},
    'balances': {} # address -> {'data': data, 'timestamp': 0}
}
CACHE_TTL = 300 # 5 минут

# ==================== MODELS ====================
from sqlalchemy import Column, Integer, BigInteger, String, Float, DateTime, Boolean, Text, LargeBinary, ForeignKey, Enum as SQLEnum, or_, and_, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, deferred
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
    telegram = Column(String(50))            # @username из whitelist
    telegram_user_id = Column(BigInteger)     # привязанный TG id (trust-on-first-login)

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

    def to_dict(self):
        return {
            'id': self.id, 'username': self.username,
            'display_name': self.display_name or self.username,
            'telegram': self.telegram, 'bound': bool(self.telegram_user_id),
            'role': self.role or 'admin',
        }


class DealType(str, Enum):
    PAY_IN = "pay_in"
    PAY_OUT = "pay_out"

class PayInMethod(str, Enum):
    SPP_DOVERKA = "spp_doverka"
    PARTNERS_CASH = "partners_cash"
    CRYPTO_DIRECT = "crypto_direct"
    SBER_WL = "sber_wl"
    SBER_REQS = "sber_reqs"


PAYIN_METHOD_LABELS = {
    # sber_wl — живой СБП-рельс: ссылка WL-бота → QR НСПК → эквайринг Сбера.
    # spp_doverka — тот же СБП, но через умершего провайдера Доверку; значение
    # оставлено ради истории (68 сделок янв–апр) и помечено, чтобы не путать.
    'spp_doverka': 'СБП (Доверка)',
    'crypto_direct': 'крипта',
    'partners_cash': 'наличные',
    'sber_wl': 'СБП',
    'sber_reqs': 'сбер реквизиты',
}

PAYOUT_METHOD_LABELS = {
    'office': 'офис',
    'courier': 'курьер',
    'atm': 'банкомат',
    'transfer': 'перевод',
}

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
    LOSE = "lose"  # несостоявшаяся сделка (из DealCloser) — только для конверсии, не деньги
    # Не обращение: клиент написал случайно или дописал что-то по уже закрытой
    # сделке. Это не лид — ни в победы, ни в отказы, из конверсии исключено совсем.
    NOT_LEAD = "not_lead"

# Записи без денег: клиента не заводим, финансы и агентов не считаем
NON_DEAL_STATUSES = (DealStatus.LOSE, DealStatus.NOT_LEAD)

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
    # Демо-клиент тестового реферера: не показываем в CRM (см. Deal.is_test)
    is_test = Column(Boolean, default=False)
    referrer = relationship("Referrer", back_populates="referred_clients", foreign_keys=[referrer_id])
    deals = relationship("Deal", back_populates="client")

    def to_dict(self):
        return {'id': self.id, 'name': self.name, 'telegram': self.telegram, 'phone': self.phone,
                'total_deals': self.total_deals, 'total_volume_usdt': self.total_volume_usdt,
                'referrer_id': self.referrer_id,
                'is_test': bool(self.is_test),
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


def referral_links(code, lang='ru'):
    """Реферальные ссылки партнёра. Предзаполненный текст WhatsApp — на языке партнёра:
    англоязычный застройщик пересылает ссылку своему клиенту, русский текст там мусор."""
    from urllib.parse import quote as _q
    flat = (code or '').replace('-', '')
    wa_text = ('Здравствуйте! Хочу уточнить детали обмена.\n\n(Источник: ref_%s)' % flat
               if (lang or 'ru') != 'en'
               else 'Hello! I would like to check the exchange details.\n\n(Source: ref_%s)' % flat)
    return {
        'referral_link': f'https://grusha.space/?ref={code}',
        'bot_link': f'https://t.me/Grushath_bot?start=ref__{flat}',
        'wa_link': ('https://api.whatsapp.com/send/?phone=66818429939&text='
                    + _q(wa_text, safe='') + '&type=phone_number&app_absent=0'),
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
    # Модель вознаграждения: 'revshare' (% от прибыли) или 'markup' (+% к курсу клиента)
    comp_model = Column(String(20), default='revshare')
    markup_percent = Column(Float, default=0.0)
    # ── Платёжные ссылки (продукт на рельсах Rapira+Bitazza, см. partner_rates.py) ──
    # Отдельные поля, а не comp_model/markup_percent: там связка Доверки со своей
    # лестницей комиссий, смешивать экономику двух разных рельсов нельзя.
    can_create_links = Column(Boolean, default=False)      # доступ к созданию ссылок
    link_base_markup_percent = Column(Float)               # наша наценка, % (NULL → глобальная 3.5)
    link_markup_percent = Column(Float, default=0.0)       # наценка партнёра СВЕРХУ нашей (платит клиент)
    link_revshare_percent = Column(Float, default=0.0)     # доля партнёра от нашей прибыли, %
    link_logo_url = Column(String(512))                    # логотип на странице оплаты (white label)
    link_description = Column(String(200))                 # подпись клиенту на странице оплаты
    lang = Column(String(5), default='ru')                  # язык кабинета и уведомлений: 'ru' | 'en'
    active = Column(Boolean, default=True)
    is_test = Column(Boolean, default=False)  # Тестовый реферер: не слать TG-уведомления о заявках
    auth_mode = Column(String(20), default='link')       # 'link' | 'telegram'
    telegram_user_id = Column(BigInteger)                  # привязанный TG id (>2^31)
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
            'comp_model': self.comp_model or 'revshare',
            'markup_percent': self.markup_percent or 0.0,
            'can_create_links': bool(self.can_create_links),
            'link_base_markup_percent': self.link_base_markup_percent,
            'link_markup_percent': self.link_markup_percent or 0.0,
            'link_revshare_percent': self.link_revshare_percent or 0.0,
            'link_logo_url': self.link_logo_url,
            'link_description': self.link_description,
            'active': self.active,
            'lang': self.lang or 'ru',
            'auth_mode': self.auth_mode or 'link',
            'telegram_user_id': self.telegram_user_id,
            'total_referred_clients': self.total_referred_clients,
            'total_deals': self.total_deals,
            'total_earned_usdt': self.total_earned_usdt,
            'total_paid_usdt': self.total_paid_usdt,
            'pending_usdt': round((self.total_earned_usdt or 0) - (self.total_paid_usdt or 0), 2),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'notes': self.notes,
            **referral_links(self.code, self.lang or 'ru'),
        }


class LoginNonce(Base):
    """Одноразовый код входа через бота (@grusha_lk_bot /start login_<nonce>).
    Браузер генерит nonce → юзер открывает бота в приложении Telegram (сам выбирает
    аккаунт) → webhook матчит whitelist и пишет admin_id → браузер поллит и получает сессию.
    Обходит кэш-сессию oauth.telegram.org полностью."""
    __tablename__ = 'login_nonces'
    nonce = Column(String(64), primary_key=True)
    admin_id = Column(Integer)                       # заполняется webhook'ом при матче (админ-вход)
    referrer_id = Column(Integer)                    # nonce для входа в кабинет реферера
    tg_id = Column(BigInteger)                       # подтвердивший TG id (для ref_auth сессии)
    denied = Column(Boolean, default=False)          # аккаунт не прошёл проверку
    used = Column(Boolean, default=False)            # сессия уже выдана
    created_at = Column(DateTime, default=datetime.utcnow)


class PayoutRequest(Base):
    """Заявка реферера на выплату накопленного баланса."""
    __tablename__ = 'payout_requests'
    id = Column(Integer, primary_key=True)
    referrer_id = Column(Integer, ForeignKey('referrers.id'), nullable=False, index=True)
    # Снапшот суммы к выплате на момент заявки
    amount_usdt = Column(Float, default=0)
    wallet = Column(String(200), nullable=False)
    # 'telegram' | 'whatsapp'
    contact_method = Column(String(20), nullable=False)
    # @username, телефон или ник — то, что указал реферер
    contact_value = Column(String(100), nullable=False)
    notes = Column(Text)
    # 'new' | 'in_progress' | 'paid' | 'cancelled'
    status = Column(String(20), default='new', index=True)
    tx_hash = Column(String(120))  # Хеш транзакции при статусе 'paid'
    # JSON-список deal_id, зафиксированных при создании заявки.
    # При статусе paid помечаются оплаченными ТОЛЬКО эти сделки — сделки,
    # закрытые после создания заявки, остаются к выводу (не сгорают).
    deal_ids = Column(Text)
    # ── Выплата в батах ──
    # 'usdt' | 'thb'. Курсы — снапшот на момент заявки (фиксируем при запросе:
    # наша задача успеть откупить, клиенту платим по зафиксированному).
    payout_method = Column(String(10), default='usdt')
    bitazza_rate = Column(Float)      # VWAP Bitazza на объём — по нему откупаем
    client_rate = Column(Float)       # курс клиенту = VWAP × (1 − 0.25%)
    thb_amount = Column(Float)        # сумма к выплате, ฿ (уже с −20฿)
    bank_name = Column(String(100))
    account_name = Column(String(150))
    account_number = Column(String(60))
    receipt_tg_file_id = Column(String(200))  # чек выплаты (file_id в Telegram)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    processed_at = Column(DateTime, nullable=True)

    referrer = relationship("Referrer", foreign_keys=[referrer_id])

    def to_dict(self, with_referrer=False):
        d = {
            'id': self.id,
            'referrer_id': self.referrer_id,
            'amount_usdt': self.amount_usdt,
            'wallet': self.wallet,
            'contact_method': self.contact_method,
            'contact_value': self.contact_value,
            'notes': self.notes,
            'status': self.status,
            'tx_hash': self.tx_hash,
            'payout_method': self.payout_method or 'usdt',
            'bitazza_rate': self.bitazza_rate,
            'client_rate': self.client_rate,
            'thb_amount': self.thb_amount,
            'bank_name': self.bank_name,
            'account_name': self.account_name,
            'account_number': self.account_number,
            'has_receipt': bool(self.receipt_tg_file_id),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'processed_at': self.processed_at.isoformat() if self.processed_at else None,
        }
        if with_referrer and self.referrer:
            d['referrer_name'] = self.referrer.name
            d['referrer_code'] = self.referrer.code
        return d


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
    # Legacy-колонки эпохи файлов на диске. Не пишутся с 2026-08-16, оставлены
    # чтобы не ронять старые строки; сами файлы по ним давно недостижимы —
    # контейнер Railway эфемерный, kyc_uploads/ обнулялся каждым деплоем.
    doc_path = Column(String(500), nullable=True)
    selfie_path = Column(String(500), nullable=True)
    liveness_paths = Column(Text, nullable=True)  # JSON-массив путей

    # Видео-заявление: клиент вслух читает текст, заданный менеджером
    statement_required = Column(Boolean, default=False)
    statement_text = Column(Text, nullable=True)
    # Когда ретенция стёрла файлы (сама запись KYC живёт дальше)
    files_purged_at = Column(DateTime, nullable=True)

    client = relationship("Client", backref="kyc_requests")
    files = relationship("KycFile", backref="kyc", cascade="all, delete-orphan",
                         lazy="selectin", order_by="KycFile.idx")

    def to_dict(self):
        kinds = {f.kind for f in self.files}
        return {
            'id': self.id, 'token': self.token, 'client_id': self.client_id,
            'client_name': self.client_name, 'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'reviewed_at': self.reviewed_at.isoformat() if self.reviewed_at else None,
            'reviewed_by': self.reviewed_by, 'rejection_reason': self.rejection_reason,
            'has_doc': 'doc' in kinds, 'has_selfie': 'selfie' in kinds,
            'has_liveness': 'liveness' in kinds,
            'liveness_count': sum(1 for f in self.files if f.kind == 'liveness'),
            'has_statement': 'statement' in kinds,
            'statement_required': bool(self.statement_required),
            'statement_text': self.statement_text,
            'files_purged_at': self.files_purged_at.isoformat() if self.files_purged_at else None,
            'files_total_bytes': sum(f.size or 0 for f in self.files),
        }


class KycFile(Base):
    """Файл KYC внутри БД: паспорт, селфи, liveness-кадр, видео-заявление.

    Хранится в Postgres, а не на диске сервиса: файловая система контейнера
    Railway эфемерная, тома у сервиса нет — папка с документами исчезала при
    каждом деплое. Файлы живут до ретенции (KYC_RETENTION_DAYS), менеджер
    может открыть и скачать их из CRM в любой момент до этого срока.
    """
    __tablename__ = 'kyc_files'
    id = Column(Integer, primary_key=True)
    kyc_id = Column(Integer, ForeignKey('kyc_requests.id'), nullable=False, index=True)
    kind = Column(String(20), nullable=False)   # doc | selfie | liveness | statement
    idx = Column(Integer, default=0)            # порядок liveness-кадров
    mime = Column(String(60), nullable=False)
    ext = Column(String(10), nullable=False)
    size = Column(Integer, nullable=False)
    # deferred: список KYC в CRM тянет по 100 записей с файлами — без этого
    # каждый ответ /api/kyc/list поднимал бы в память все паспорта и видео.
    data = deferred(Column(LargeBinary, nullable=False))
    created_at = Column(DateTime, default=datetime.utcnow)

    @property
    def slot(self):
        """Имя слота в API: doc, selfie, statement, liveness_0…"""
        return f'liveness_{self.idx}' if self.kind == 'liveness' else self.kind

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
        avg_rate = _card_avg_rate(self)
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
    # Чем подтверждается пополнение: хэш TRON, если заводили криптой, либо
    # банковский референс (у IPPS это строка вида IDTT260723564098)
    reference = Column(String(120))
    notes = Column(Text)
    card = relationship("BankCard", back_populates="topups")

    def to_dict(self):
        return {'id': self.id, 'card_id': self.card_id, 'amount_thb': self.amount_thb,
                'cost_usdt': self.cost_usdt, 'purchase_rate': self.purchase_rate,
                'source_type': self.source_type, 'source_batch_id': self.source_batch_id,
                'reference': self.reference, 'notes': self.notes,
                'created_at': self.created_at.isoformat() if self.created_at else None}

class ChannelTraffic(Base):
    """Дневной трафик/расход по каналам привлечения из внешних источников.

    Пишет фоновая джоба _channel_traffic_loop (Яндекс.Метрика; Meta — когда
    появится токен). Ключ upsert: (date, channel, provider).
    """
    __tablename__ = 'channel_traffic'
    id = Column(Integer, primary_key=True)
    date = Column(DateTime, nullable=False)          # день (00:00)
    channel = Column(String(50), nullable=False)     # utm_source ('insta', 'site'…)
    provider = Column(String(20), nullable=False)    # 'metrika' | 'meta'
    visits = Column(Integer, default=0)
    users = Column(Integer, default=0)               # уникальные посетители = UA
    spend_usd = Column(Float, default=0.0)           # расход канала (рекламные кабинеты)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'date': self.date.strftime('%Y-%m-%d') if self.date else None,
            'channel': self.channel, 'provider': self.provider,
            'visits': self.visits, 'users': self.users, 'spend_usd': self.spend_usd,
        }


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
    tx_uses = relationship('ReimbursementTxUse', back_populates='reimbursement',
                           cascade='all, delete-orphan')

    def to_dict(self):
        # tx_hashes — список для фронта
        hashes = [h.strip() for h in (self.tx_hash or '').split(',') if h.strip()]
        # Состав возмещения: одним переводом закрываем несколько сделок, и по
        # карточке одной сделки было не понять, что ещё вошло в тот же хэш и
        # осталось ли нераспределённое. Без этого один перевод легко «возместить»
        # дважды. НЕ вызываем deal.to_dict() — Deal.to_dict сам зовёт этот метод.
        breakdown = []
        allocated = 0.0
        for d in (self.deals or []):
            share = d.payout_amount_usdt or 0
            allocated += share
            breakdown.append({
                'deal_id': d.id,
                'client_name': (d.client.name if d.client else d.client_name) or '',
                'payout_thb': d.payout_amount_thb,
                'share_usdt': round(share, 2),
            })
        total = self.amount_usdt or 0
        # Переводы, из которых сложилось возмещение, с остатком по каждому.
        # По ним видно «запас»: сколько из перевода ещё не разобрано по сделкам.
        tx_uses = []
        for u in (self.tx_uses or []):
            tx = u.tx
            tx_uses.append({
                'tx_hash': tx.tx_hash if tx else '',
                'tx_amount_usdt': round((tx.amount_usdt or 0) if tx else 0, 2),
                'taken_usdt': round(u.amount_usdt or 0, 2),
                'free_usdt': tx.free_usdt() if tx else 0,
                'source': tx.source if tx else '',
            })
        return {'id': self.id, 'founder_name': self.founder_name, 'amount_usdt': total,
                'tx_hash': self.tx_hash, 'tx_hashes': hashes, 'tx_verified': self.tx_verified,
                'created_at': self.created_at.isoformat() if self.created_at else None,
                'deals_breakdown': breakdown,
                'deals_count': len(breakdown),
                'allocated_usdt': round(allocated, 2),
                'unallocated_usdt': round(total - allocated, 2),
                'tx_uses': tx_uses,
                'tx_free_total': round(sum(t['free_usdt'] for t in tx_uses), 2)}

class ReimbursementTx(Base):
    """Перевод фаундеру — одна запись на хэш транзакции.

    Раньше хэши жили строкой в `Reimbursement.tx_hash`, и «сколько из перевода уже
    разобрано» система не знала: один и тот же перевод можно было провести дважды,
    и обе сделки выглядели возмещёнными. Теперь перевод — сущность с суммой,
    а возмещения берут из него доли (см. ReimbursementTxUse).
    """
    __tablename__ = 'reimbursement_txs'
    id = Column(Integer, primary_key=True)
    tx_hash = Column(String(120), nullable=False, unique=True, index=True)
    founder_name = Column(String(100))
    amount_usdt = Column(Float, nullable=False, default=0)
    source = Column(String(20), default='tronscan')   # tronscan | manual
    created_at = Column(DateTime, default=datetime.utcnow)
    notes = Column(Text)
    uses = relationship('ReimbursementTxUse', back_populates='tx',
                        cascade='all, delete-orphan')

    def used_usdt(self):
        """Сколько из перевода уже разобрано по возмещениям.

        Считаем запросом, а не по `self.uses`: в рамках одного запроса
        использования добавляются и читаются тут же, а коллекция в памяти
        к этому моменту ещё не перечитана — остаток показывался бы старый.
        """
        from sqlalchemy import func as _f
        from sqlalchemy.orm import object_session
        s = object_session(self)
        if s is not None and self.id:
            # no_autoflush обязателен: to_dict вызывается в середине запроса,
            # и автофлаш здесь выталкивал незавершённые изменения чужой логики
            # (ловилось падениями реферальных тестов на общем прогоне).
            with s.no_autoflush:
                val = s.query(_f.sum(ReimbursementTxUse.amount_usdt)).filter(
                    ReimbursementTxUse.tx_id == self.id).scalar()
            return round(val or 0, 2)
        return round(sum(u.amount_usdt or 0 for u in (self.uses or [])), 2)

    def free_usdt(self):
        """Незадействованный остаток перевода — тот самый «запас»."""
        return round((self.amount_usdt or 0) - self.used_usdt(), 2)

    def to_dict(self):
        return {'id': self.id, 'tx_hash': self.tx_hash, 'founder_name': self.founder_name,
                'amount_usdt': round(self.amount_usdt or 0, 2), 'source': self.source,
                'used_usdt': self.used_usdt(), 'free_usdt': self.free_usdt(),
                'created_at': self.created_at.isoformat() if self.created_at else None}


class ReimbursementTxUse(Base):
    """Сколько из конкретного перевода ушло в конкретное возмещение."""
    __tablename__ = 'reimbursement_tx_uses'
    id = Column(Integer, primary_key=True)
    tx_id = Column(Integer, ForeignKey('reimbursement_txs.id'), nullable=False, index=True)
    reimbursement_id = Column(Integer, ForeignKey('reimbursements.id'), nullable=False, index=True)
    amount_usdt = Column(Float, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    tx = relationship('ReimbursementTx', back_populates='uses')
    reimbursement = relationship('Reimbursement', back_populates='tx_uses')

class PayinTx(Base):
    """Входящий USDT-перевод — одна запись на хэш.

    Зеркало ReimbursementTx для приходов. Клиент платит рублями несколько раз,
    а обмениваем мы один раз и получаем ОДИН перевод на несколько сделок. Раньше
    хэш считался занятым целиком: во второй сделке он не показывался, а вбитый
    руками давал двойной приход — одна и та же сумма попадала в обе сделки.
    Теперь перевод это сущность с суммой, а сделки берут из него доли (PayinTxUse).
    """
    __tablename__ = 'payin_txs'
    id = Column(Integer, primary_key=True)
    tx_hash = Column(String(120), nullable=False, unique=True, index=True)
    amount_usdt = Column(Float, nullable=False, default=0)
    source = Column(String(20), default='manual')     # tronscan | manual
    tx_time = Column(DateTime, nullable=True)
    # Кошелёк-получатель: в сводке по конвертации нужно «сколько пришло,
    # хеш, какого кошелька». Берём из сети, а не с рук
    to_address = Column(String(100), nullable=True)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    uses = relationship('PayinTxUse', back_populates='tx', cascade='all, delete-orphan')

    def used_usdt(self):
        """Сколько из перевода уже разобрано по сделкам.

        Считаем запросом, а не по self.uses: в рамках одного запроса доли
        добавляются и читаются тут же, коллекция в памяти к этому моменту
        не перечитана — остаток показывался бы старый (см. ReimbursementTx).
        """
        from sqlalchemy import func as _f
        from sqlalchemy.orm import object_session
        s = object_session(self)
        if s is not None and self.id:
            with s.no_autoflush:
                val = s.query(_f.sum(PayinTxUse.amount_usdt)).filter(
                    PayinTxUse.tx_id == self.id).scalar()
            return round(val or 0, 2)
        return round(sum(u.amount_usdt or 0 for u in (self.uses or [])), 2)

    def free_usdt(self):
        """Нераспределённый остаток перевода."""
        return round((self.amount_usdt or 0) - self.used_usdt(), 2)

    def to_dict(self):
        return {'id': self.id, 'tx_hash': self.tx_hash, 'to_address': self.to_address,
                'amount_usdt': round(self.amount_usdt or 0, 2), 'source': self.source,
                'used_usdt': self.used_usdt(), 'free_usdt': self.free_usdt(),
                'deal_ids': sorted({u.deal_id for u in (self.uses or []) if u.deal_id}),
                'tx_time': self.tx_time.isoformat() if self.tx_time else None,
                'notes': self.notes,
                'created_at': self.created_at.isoformat() if self.created_at else None}


class PayinTxUse(Base):
    """Сколько из конкретного входящего перевода отнесено на конкретную сделку."""
    __tablename__ = 'payin_tx_uses'
    __table_args__ = (UniqueConstraint('tx_id', 'deal_id', name='uq_payin_tx_use'),)
    id = Column(Integer, primary_key=True)
    tx_id = Column(Integer, ForeignKey('payin_txs.id'), nullable=False, index=True)
    deal_id = Column(Integer, ForeignKey('deals.id'), nullable=False, index=True)
    amount_usdt = Column(Float, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    tx = relationship('PayinTx', back_populates='uses')


class ConversionStatus(str, Enum):
    DRAFT = 'draft'          # состав собираем, рубли ещё не ушли
    SENT = 'sent'            # рубли ушли брокеру, ждём USDT
    RECEIVED = 'received'    # USDT пришёл, доли разнесены
    CANCELLED = 'cancelled'  # не состоялась — поступления вернулись в свободные


class Conversion(Base):
    """Пачка конвертации: рублёвые поступления → рубли брокеру → USDT на кошелёк.

    Зеркало Reimbursement, только на входе: возмещение раздаёт исходящий перевод
    по сделкам, конвертация собирает входящие рубли и раздаёт полученный USDT.

    Без неё связь «эти рубли → этот приход USDT» жила только в голове операциониста.
    Доли PayinTxUse вбивались руками, и один перевод дважды съедал остаток: 1733 USDT
    записались целиком на #469 (её доля 330,28), реестр решил, что перевод разобран,
    и спрятал хеш; следом #481 забрала остаток 1402,72 вместо своих 416,02.
    """
    __tablename__ = 'conversions'
    id = Column(Integer, primary_key=True)
    broker = Column(String(100))
    request_no = Column(String(60))            # «заявка №46», «поруч. 67»
    sent_at = Column(DateTime)
    # Удержание — наша комиссия с конвертации (налоги + вознаграждение реферала,
    # который провёл сделку), а НЕ расход. Внутрь здесь не раскладываем.
    # Ставка правится: по факту выписки сверх фикса выходило и 0,2006 % (11.08),
    # и 0,4005 % (13.08), формулой это не выводится.
    held_percent = Column(Float, default=0.3)
    held_fixed_rub = Column(Float, default=40.0)
    amount_rub_sent = Column(Float)            # факт из выписки; пусто → считаем по ставке
    rate_rub_usdt = Column(Float)
    wallet_id = Column(Integer, ForeignKey('wallets.id'), nullable=True)
    status = Column(SQLEnum(ConversionStatus), default=ConversionStatus.DRAFT)
    notes = Column(Text)
    created_by = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)
    received_at = Column(DateTime)
    sources = relationship('ConversionSource', back_populates='conversion',
                           cascade='all, delete-orphan')
    txs = relationship('ConversionTx', back_populates='conversion',
                       cascade='all, delete-orphan')
    debits = relationship('ConversionDebit', back_populates='conversion',
                          cascade='all, delete-orphan')

    @property
    def display_name(self):
        return f'CNV-{self.id:04d}' if self.id else 'CNV-новая'

    def sources_rub(self):
        """Σ привязанных поступлений (G)."""
        return round(sum(s.amount_rub or 0 for s in (self.sources or [])), 2)

    def _debits_by_kind(self, kind):
        """Σ привязанных списаний нужного вида. Вид берём у самого платежа."""
        total = 0.0
        for link in (self.debits or []):
            deb = link.debit
            if deb is not None and (deb.kind or 'broker') == kind:
                total += link.amount_rub or 0
        return round(total, 2)

    def has_debits(self):
        return bool(self.debits)

    def held_rub(self):
        """Удержано нами: Σ списаний-комиссий из выписки.

        Пока списания не привязаны — падаем на расчёт по ставке (дефолт 0,3 % + 40)
        или на разницу, если отправка задана вручную.
        """
        if self.has_debits():
            return self._debits_by_kind('fee')
        g = self.sources_rub()
        if not g:
            return 0.0   # пустая пачка: фикс без состава давал «отправлено −40 ₽»
        if self.amount_rub_sent:
            return round(g - self.amount_rub_sent, 2)
        return round(g * (self.held_percent or 0) / 100 + (self.held_fixed_rub or 0), 2)

    def sent_rub(self):
        """Отправлено брокеру (S). Факт выписки главнее любого расчёта."""
        if self.has_debits():
            return self._debits_by_kind('broker')
        if self.amount_rub_sent:
            return round(self.amount_rub_sent, 2)
        return round(self.sources_rub() - self.held_rub(), 2)

    def debits_delta_rub(self):
        """Приходы минус всё, что ушло со счёта. Должно сходиться в ноль."""
        if not self.has_debits():
            return 0.0
        spent = round(sum(l.amount_rub or 0 for l in self.debits), 2)
        return round(self.sources_rub() - spent, 2)

    def expected_usdt(self):
        rate = self.rate_rub_usdt or 0
        return round(self.sent_rub() / rate, 4) if rate else 0.0

    def received_usdt(self):
        """Σ привязанных приходов USDT (R)."""
        return round(sum(t.amount_usdt or 0 for t in (self.txs or [])), 4)

    def delta_usdt(self):
        return round(self.received_usdt() - self.expected_usdt(), 4)

    def to_dict(self):
        return {
            'id': self.id, 'display_name': self.display_name,
            'broker': self.broker, 'request_no': self.request_no,
            'sent_at': self.sent_at.isoformat() if self.sent_at else None,
            'held_percent': self.held_percent, 'held_fixed_rub': self.held_fixed_rub,
            'held_rub': self.held_rub(),
            'sources_rub': self.sources_rub(), 'sent_rub': self.sent_rub(),
            # Отдаём отдельно: по нему фронт понимает, что удержание — факт
            # выписки, а не расчёт по ставке
            'amount_rub_sent': self.amount_rub_sent,
            'has_debits': self.has_debits(),
            'debits_delta_rub': self.debits_delta_rub(),
            'rate_rub_usdt': self.rate_rub_usdt,
            'expected_usdt': self.expected_usdt(),
            'received_usdt': self.received_usdt(),
            'delta_usdt': self.delta_usdt(),
            'wallet_id': self.wallet_id,
            'status': self.status.value if self.status else None,
            'notes': self.notes, 'created_by': self.created_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'received_at': self.received_at.isoformat() if self.received_at else None,
        }


class ConversionSource(Base):
    """Какой долей рублёвое поступление вошло в пачку.

    Долями, а не целиком: 200 000 от Имайкиной закрывали часть сделки на 800 000,
    а 14.08 конвертировали больше, чем пришло, добирая из буфера счёта.
    """
    __tablename__ = 'conversion_sources'
    __table_args__ = (UniqueConstraint('conversion_id', 'sber_income_id',
                                       name='uq_conversion_source'),)
    id = Column(Integer, primary_key=True)
    conversion_id = Column(Integer, ForeignKey('conversions.id'), nullable=False, index=True)
    sber_income_id = Column(Integer, ForeignKey('sber_incomes.id'), nullable=False, index=True)
    amount_rub = Column(Float, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    conversion = relationship('Conversion', back_populates='sources')


class ConversionTx(Base):
    """Каким приходом USDT закрыта пачка. Брокер может дробить выдачу на несколько."""
    __tablename__ = 'conversion_txs'
    __table_args__ = (UniqueConstraint('conversion_id', 'payin_tx_id',
                                       name='uq_conversion_tx'),)
    id = Column(Integer, primary_key=True)
    conversion_id = Column(Integer, ForeignKey('conversions.id'), nullable=False, index=True)
    payin_tx_id = Column(Integer, ForeignKey('payin_txs.id'), nullable=False, index=True)
    amount_usdt = Column(Float, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    conversion = relationship('Conversion', back_populates='txs')


class ConversionDebit(Base):
    """Какие списания со счёта относятся к этой пачке.

    Расход приходит частями: отправка брокеру, комиссия процентом, фикс —
    три отдельные строки выписки. Плюс саму отправку могут дробить на несколько
    платежей. Поэтому связь «многие ко многим» долями, а не одно поле.
    """
    __tablename__ = 'conversion_debits'
    __table_args__ = (UniqueConstraint('conversion_id', 'sber_debit_id',
                                       name='uq_conversion_debit'),)
    id = Column(Integer, primary_key=True)
    conversion_id = Column(Integer, ForeignKey('conversions.id'), nullable=False, index=True)
    sber_debit_id = Column(Integer, ForeignKey('sber_debits.id'), nullable=False, index=True)
    amount_rub = Column(Float, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    conversion = relationship('Conversion', back_populates='debits')
    debit = relationship('SberDebit')


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

    def to_dict(self):
        return {
            'id': self.id, 'deal_id': self.deal_id, 'card_id': self.card_id,
            'amount_thb': self.amount_thb, 'cost_usdt': self.cost_usdt,
            'card_rate': self.card_rate,
            'client_name': self.deal.client_name if self.deal else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

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
    # CR-05: defense-in-depth — partial UNIQUE(deal_id, type) WHERE deal_id IS NOT NULL
    # создаётся миграцией ниже (uq_wallet_operations_deal_type).
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
    # Демо-сделка тестового реферера: живёт только в реферальном кабинете.
    # В CRM (список сделок, клиенты, аналитика), в GSheet и в TG-уведомления
    # НЕ попадает — витрина для показа партнёру, а не реальные деньги.
    is_test = Column(Boolean, default=False)
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
    # Приход частями: JSON [{hash, amount_usdt}]. payin_tx_hash = первый хэш (легаси-отображения)
    payin_tx_hashes = Column(Text, nullable=True)
    # Фактическая отправка в MF Corp: JSON [{hash, amount_usdt, to_address, date}].
    # Расчётная себестоимость — модель; эти переводы — то, что реально ушло
    payout_tx_hashes = Column(Text, nullable=True)
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
    # С какой карты (THB-счёта) выдали баты. Курс закупки карты — база
    # себестоимости выдачи; сама аллокация лежит в card_allocations.
    bank_card_id = Column(Integer, ForeignKey('bank_cards.id'), nullable=True)
    bank_card = relationship("BankCard", foreign_keys=[bank_card_id])
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
    referrer_paid_at = Column(DateTime, nullable=True)  # когда выплачено партнёру
    # Снапшот модели реферера на момент сделки (изменения настроек не ломают историю)
    referrer_comp_model = Column(String(20))  # 'revshare' | 'markup'
    referrer_markup_percent = Column(Float)
    net_profit_usdt = Column(Float)
    needs_reimbursement = Column(Boolean, default=True)
    # Части прихода (метод sber_reqs, оплата частями): JSON-список
    # [{uuid|null, amount_rub, payer, date, note}]. uuid → приход из пула sber_incomes.
    payin_parts = Column(Text, nullable=True)
    # Дополнительные приходы сверх основного: JSON-список
    # [{method, amount_rub, rate_rub_usdt, amount_usdt, partner_name,
    #   tx_hashes, sber_uuids, note}]
    # Основной приход остаётся в плоских payin_* — часть 1 это он. После
    # сохранения плоские поля хранят АГРЕГАТЫ (итог USDT, сумма рублей,
    # средневзвешенный курс), поэтому весь остальной код читает их как раньше.
    payin_extra = Column(Text, nullable=True)
    # LOSE-сделки и revive-логика (конверсия по Красинскому)
    lose_reason = Column(String(300), nullable=True)         # причина отказа из LLM-анализа DealCloser
    bitrix_deal_id = Column(Integer, nullable=True, index=True)  # id сделки Bitrix (дедуп + трейсинг)
    # Канал привлечения из /start-парама бота: 'insta', 'site', 'ref:GR-XXX'…
    # Пишет DealCloser (utm_source__/ref__ из первого сообщения Bitrix-чата)
    source_channel = Column(String(50), nullable=True)
    revived_by_deal_id = Column(Integer, ForeignKey('deals.id'), nullable=True)  # WON, забравший этот LOSE
    # ── Недвижимость через MF Corporation (leasehold) ────────────────────────
    # Спека: docs/specs/2026-08-04-mf-corp-leasehold.md
    # Деньги расходятся по ДВУМ карманам: комиссия оседает в батах на счёте тайской
    # компании, остаток остаётся в USDT на кошельке. Чистый доход = сумма обоих.
    deal_kind = Column(String(20), nullable=True)      # None/'exchange' — обычная, 'mf_realty' — через MF Corp
    realty_purpose = Column(String(200))               # назначение: проект / юнит / номер инвойса
    invoice_amount_thb = Column(Float)                 # сколько должен получить застройщик
    sell_rate_thb_usdt = Column(Float)                 # курс продажи (клиенту)
    buy_rate_thb_usdt = Column(Float)                  # курс покупки (наш) — база себестоимости
    company_percent = Column(Float)                    # комиссия компании, % от суммы инвойса (кастомная)
    company_sent_thb = Column(Float)                   # фактически отправлено в MF Corp
    company_fee_thb = Column(Float)                    # комиссия компании в батах
    company_fee_usdt = Column(Float)                   # она же в USDT (по курсу покупки)
    crypto_remainder_usdt = Column(Float)              # остаток на кошельке после комиссии и партнёров
    katika_fee_thb = Column(Float)                     # выплата номиналу, баты
    katika_fee_usdt = Column(Float)                    # она же в USDT
    client_spread_percent = Column(Float)              # спред клиенту: курс продажи = курс покупки − спред
    # ── Недвижимость фрихолд (оплата застройщику SWIFT-ом из-за рубежа) ──────
    # Спека: docs/specs/2026-08-06-mf-freehold.md. Карман ОДИН: тайская компания
    # не участвует, банк съедает комиссию ИЗ отправленной суммы, вся прибыль
    # остаётся в USDT. Приход заводится так же, как у лизхолда.
    invoice_amount_usd = Column(Float)                 # сколько должен получить застройщик
    transfer_sent_usd = Column(Float)                  # сколько ушло с нашей стороны
    transfer_fee_percent = Column(Float)               # комиссия за перевод, % от отправки
    transfer_fee_fixed_usd = Column(Float)             # фикс за платёж, $
    transfer_fee_usd = Column(Float)                   # производная: вся комиссия за перевод
    transfer_arrive_usd = Column(Float)                # производная: дойдёт до застройщика
    doc_invoice_url = Column(String(500))
    doc_contract_url = Column(String(500))
    doc_payment_url = Column(String(500))
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
    agents = relationship("DealAgent", backref="deal", cascade="all, delete-orphan",
                          order_by="DealAgent.tier")

    def to_dict(self):
        return {
            'id': self.id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'manager_name': self.manager_name,
            'deal_type': self.deal_type.value if self.deal_type else None,
            'status': self.status.value if self.status else None,
            'is_test': bool(self.is_test),
            'client_id': self.client_id,
            'client_name': self.client.name if self.client else self.client_name,
            'client': self.client.to_dict() if self.client else None,
            'payin_method': self.payin_method.value if self.payin_method else None,
            'payin_amount_rub': self.payin_amount_rub,
            'payin_amount_usdt': self.payin_amount_usdt,
            'payin_rate_rub_usdt': self.payin_rate_rub_usdt,
            'payin_tx_hash': self.payin_tx_hash,
            'payin_tx_hashes': json.loads(self.payin_tx_hashes) if self.payin_tx_hashes else None,
            'payout_tx_hashes': json.loads(self.payout_tx_hashes) if self.payout_tx_hashes else None,
            'payin_tx_verified': self.payin_tx_verified,
            'deal_kind': self.deal_kind or 'exchange',
            'realty_purpose': self.realty_purpose,
            'invoice_amount_thb': self.invoice_amount_thb,
            'sell_rate_thb_usdt': self.sell_rate_thb_usdt,
            'buy_rate_thb_usdt': self.buy_rate_thb_usdt,
            'company_percent': self.company_percent,
            'company_sent_thb': self.company_sent_thb,
            'company_fee_thb': self.company_fee_thb,
            'company_fee_usdt': self.company_fee_usdt,
            'crypto_remainder_usdt': self.crypto_remainder_usdt,
            'katika_fee_thb': self.katika_fee_thb,
            'katika_fee_usdt': self.katika_fee_usdt,
            'client_spread_percent': self.client_spread_percent,
            'invoice_amount_usd': self.invoice_amount_usd,
            'transfer_sent_usd': self.transfer_sent_usd,
            'transfer_fee_percent': self.transfer_fee_percent,
            'transfer_fee_fixed_usd': self.transfer_fee_fixed_usd,
            'transfer_fee_usd': self.transfer_fee_usd,
            'transfer_arrive_usd': self.transfer_arrive_usd,
            'doc_invoice_url': self.doc_invoice_url,
            'doc_contract_url': self.doc_contract_url,
            'doc_payment_url': self.doc_payment_url,
            'payin_partner_name': self.payin_partner_name,
            'payin_parts': json.loads(self.payin_parts) if self.payin_parts else None,
            'payin_extra': json.loads(self.payin_extra) if self.payin_extra else None,
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
            'bank_card_id': self.bank_card_id,
            'payout_founder_name': self.payout_founder_name,
            'profit_usdt': self.profit_usdt,
            'profit_percent': self.profit_percent,
            'net_profit_usdt': self.net_profit_usdt,
            'referrer_id': self.referrer_id,
            'referrer_name': self.referrer_name,
            'referrer_percent': self.referrer_percent,
            'referrer_payout_usdt': self.referrer_payout_usdt,
            'referrer_paid': self.referrer_paid,
            'referrer_paid_at': self.referrer_paid_at.isoformat() if self.referrer_paid_at else None,
            'referrer_comp_model': self.referrer_comp_model,
            'referrer_markup_percent': self.referrer_markup_percent,
            'referrer_fixed_usdt': self.referrer_fixed_usdt,
            'is_custom': self.is_custom,
            'custom_payin_currency': self.custom_payin_currency,
            'custom_payin_amount': self.custom_payin_amount,
            'custom_payin_rate': self.custom_payin_rate,
            'custom_payout_currency': self.custom_payout_currency,
            'custom_payout_amount': self.custom_payout_amount,
            'custom_payout_rate': self.custom_payout_rate,
            'notes': self.notes,
            'lose_reason': self.lose_reason,
            'bitrix_deal_id': self.bitrix_deal_id,
            'source_channel': self.source_channel,
            'revived_by_deal_id': self.revived_by_deal_id,
            'reimbursement_id': self.reimbursement_id,
            'reimbursement': self.reimbursement.to_dict() if self.reimbursement else None,
            'needs_reimbursement': self.needs_reimbursement if self.needs_reimbursement is not None else True,
            'is_reimbursed': self.reimbursement_id is not None or not (self.needs_reimbursement if self.needs_reimbursement is not None else True),
            'agents': [a.to_dict() for a in sorted(self.agents, key=lambda x: (x.tier or 1, x.id or 0))] if self.agents else []
        }


class DealAgent(Base):
    """Участие одного агента в сделке. N строк на сделку — мультиагенты (каскад / «в долю»).

    tier — уровень: одинаковый tier у нескольких = делят от ОДНОЙ базы («в долю»),
    разные tier = каскад (каждый следующий считает от остатка предыдущего).
    """
    __tablename__ = 'deal_agents'
    id = Column(Integer, primary_key=True)
    deal_id = Column(Integer, ForeignKey('deals.id', ondelete='CASCADE'), nullable=False, index=True)
    referrer_id = Column(Integer, ForeignKey('referrers.id'), nullable=True)
    name = Column(String(100))                            # снапшот имени агента
    tier = Column(Integer, default=1)                     # уровень 1,2,3…
    comp_model = Column(String(20), default='revshare')   # revshare | markup | fixed
    percent = Column(Float, default=0.0)                  # % (revshare/markup)
    fixed_usdt = Column(Float, default=0.0)               # сумма $ (fixed)
    payout_usdt = Column(Float)                           # посчитанная выплата
    base_usdt = Column(Float)                             # база расчёта (для аудита)
    paid = Column(Boolean, default=False)
    paid_at = Column(DateTime, nullable=True)
    paid_note = Column(String(255), nullable=True)        # чем выплачено: хэш / «по SCB» и т.п.
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id, 'deal_id': self.deal_id, 'referrer_id': self.referrer_id,
            'name': self.name, 'tier': self.tier or 1,
            'comp_model': self.comp_model or 'revshare',
            'percent': self.percent or 0.0, 'fixed_usdt': self.fixed_usdt or 0.0,
            'payout_usdt': self.payout_usdt, 'base_usdt': self.base_usdt,
            'paid': self.paid or False,
            'paid_at': self.paid_at.isoformat() if self.paid_at else None,
            'paid_note': self.paid_note,
        }


def compute_agent_cascade(profit_usdt, volume_usdt, agents, crypto_base_usdt=None):
    """Считает выплаты агентам каскадом по уровням.

    agents — список dict с ключами comp_model, percent, fixed_usdt, tier.
    На одном уровне (tier) все берут от ОДНОЙ базы; база уменьшается на сумму
    выплат уровня перед переходом на следующий. Возвращает (agents_out, net_profit),
    где у каждого агента проставлены '_payout' и '_base'.

    Модели вознаграждения:
      markup       — % от объёма сделки;
      fixed        — фиксированная сумма;
      revshare     — % от прибыли (база уменьшается каскадом);
      crypto_share — % от того, что осталось НА КОШЕЛЬКЕ (сделки через MF Corp:
                     часть прибыли заперта в батах на счёте компании, делить её
                     с партнёром нельзя). База — crypto_base_usdt, тоже каскадная.

    Отрицательных выплат не бывает: партнёр не доплачивает нам. Если база ушла
    в минус (например, прибыль ещё не известна — сделка ждёт возмещения, а агент
    ур.1 уже взял markup), выплата уровня ниже = 0, а не отрицательное число.
    """
    profit = profit_usdt or 0
    volume = volume_usdt or 0
    by_tier = {}
    for a in agents:
        by_tier.setdefault(int(a.get('tier') or 1), []).append(a)
    base = profit
    crypto_base = crypto_base_usdt if crypto_base_usdt is not None else profit
    out = []
    for t in sorted(by_tier):
        tier_total = 0.0
        for a in by_tier[t]:
            model = (a.get('comp_model') or 'revshare').lower()
            pct = float(a.get('percent') or 0) / 100
            if model == 'markup':
                pay = volume * pct
                shown_base = base
            elif model == 'fixed':
                pay = float(a.get('fixed_usdt') or 0)
                shown_base = base
            elif model == 'crypto_share':
                pay = max(crypto_base, 0) * pct
                shown_base = crypto_base
            else:  # revshare
                pay = max(base, 0) * pct
                shown_base = base
            pay = round(pay, 2)
            a['_payout'] = pay
            a['_base'] = round(shown_base, 2)
            tier_total += pay
            out.append(a)
        base -= tier_total
        crypto_base -= tier_total
    return out, round(base, 2)


MF_REALTY_KIND = 'mf_realty'      # недвижимость через тайскую компанию (лизхолд)
MF_FREEHOLD_KIND = 'mf_freehold'  # недвижимость фрихолд: оплата SWIFT-ом из-за рубежа
# Оба типа недвижимости: своя математика, возмещение не нужно, выгрузка в
# «Cделки недвижимость», свой шаблон Telegram. Общая ветка кода — по этому кортежу.
REALTY_KINDS = (MF_REALTY_KIND, MF_FREEHOLD_KIND)


def compute_mf_realty(invoice_thb, buy_rate, payin_usdt, sell_rate=None,
                      company_percent=None, company_sent_thb=None, agents=None,
                      actual_cost_usdt=None):
    """Расчёт сделки по недвижимости через MF Corporation (leasehold).

    Спека: docs/specs/2026-08-04-mf-corp-leasehold.md. Формулы сверены по строкам
    таблицы «Cделки недвижимость» за май–июль.

    Клиент платит по курсу продажи, баты покупаем по курсу покупки (он выше) —
    разница и есть заработок. Баты уходят в MF Corp, там оседает комиссия,
    остальное остаётся в USDT на кошельке.

    Комиссию задают с одной из двух сторон, вторая считается:
      company_percent  → сколько батов отправить в компанию;
      company_sent_thb → какой процент вышел по факту.
    Если заданы обе — фактическая сумма приоритетнее (процент пересчитываем из неё).

    Возвращает dict со всеми производными величинами и разложенными выплатами
    партнёрам. Ничего не пишет в БД — чистая функция, её же зовёт форма для превью.
    """
    invoice_thb = float(invoice_thb or 0)
    buy_rate = float(buy_rate or 0)
    sell_rate = float(sell_rate or 0)

    # Комиссия компании — от суммы инвойса в батах
    if company_sent_thb not in (None, ''):
        sent_thb = float(company_sent_thb)
        fee_thb = sent_thb - invoice_thb
        percent = (fee_thb / invoice_thb * 100) if invoice_thb else 0
    else:
        percent = float(company_percent or 0)
        fee_thb = invoice_thb * percent / 100
        sent_thb = invoice_thb + fee_thb
    fee_usdt = fee_thb / buy_rate if buy_rate else 0

    # Приход: либо известен фактически, либо выводится из курса продажи
    payin = float(payin_usdt or 0)
    if not payin and invoice_thb and sell_rate:
        payin = invoice_thb / sell_rate

    # Себестоимость = ВСЯ отправляемая в компанию сумма: баты покупаем вместе
    # с комиссией, с кошелька уходит именно столько. Отдельно держим стоимость
    # самого инвойса — по ней видно общий заработок до расщепления на карманы.
    computed_cost_usdt = sent_thb / buy_rate if buy_rate else 0
    # Если переводы в компанию отмечены — себестоимость берём по факту, а не по
    # курсу: разница (комиссии сети, округление) должна быть видна, а не растворяться
    cost_usdt = float(actual_cost_usdt) if actual_cost_usdt else computed_cost_usdt
    invoice_cost_usdt = invoice_thb / buy_rate if buy_rate else 0
    crypto_profit = payin - cost_usdt          # осталось в крипте до выплат партнёрам
    gross_profit = payin - invoice_cost_usdt   # общий заработок (крипта + комиссия)

    # Партнёрам платим из крипты, поэтому база crypto_share — именно крипта
    volume = max(payin, cost_usdt)
    computed, _ = compute_agent_cascade(gross_profit, volume,
                                        [dict(a) for a in (agents or [])],
                                        crypto_base_usdt=crypto_profit)
    agents_total = sum(a.get('_payout') or 0 for a in computed)

    wallet_remainder = crypto_profit - agents_total     # осталось на кошельке
    net_profit = wallet_remainder + fee_usdt            # чистый доход = оба кармана

    return {
        'payin_usdt': round(payin, 2),
        'cost_usdt': round(cost_usdt, 2),
        'computed_cost_usdt': round(computed_cost_usdt, 2),
        # Расхождение факта с расчётом: комиссии сети, округление курса
        'cost_diff_usdt': round(cost_usdt - computed_cost_usdt, 2) if actual_cost_usdt else 0,
        'invoice_cost_usdt': round(invoice_cost_usdt, 2),
        'crypto_profit_usdt': round(crypto_profit, 2),
        'gross_profit_usdt': round(gross_profit, 2),
        'company_percent': round(percent, 4),
        'company_fee_thb': round(fee_thb, 2),
        'company_fee_usdt': round(fee_usdt, 2),
        'company_sent_thb': round(sent_thb, 2),
        'agents': computed,
        'agents_total_usdt': round(agents_total, 2),
        'crypto_remainder_usdt': round(wallet_remainder, 2),
        'net_profit_usdt': round(net_profit, 2),
        # Хватает ли крипты на выплаты партнёрам. Минус = придётся конвертировать
        # баты обратно или платить из кармана (кейс SID + Валера, спека §3.6).
        'crypto_shortfall_usdt': round(min(wallet_remainder, 0), 2),
    }


def client_sell_rate(buy_rate, spread_percent):
    """Курс клиенту = наш курс минус спред: 33.20 − 1.5% = 32.702."""
    return round(float(buy_rate or 0) * (1 - float(spread_percent or 0) / 100), 6)


def suggest_company_percent(invoice_thb, buy_rate, payin_usdt, agents=None,
                            sell_rate=None, keep_usdt=0.0):
    """Максимальный процент компании, при котором крипты хватает на выплаты партнёрам.

    Ровно та арифметика, которую сейчас делают в уме («поставлю 0.9, потому что
    Валере ещё платить»). keep_usdt — сколько дополнительно оставить на кошельке.
    Возвращает процент, округлённый вниз до сотых, не больше 100 и не меньше 0.
    """
    invoice_thb = float(invoice_thb or 0)
    buy_rate = float(buy_rate or 0)
    if not invoice_thb or not buy_rate:
        return 0.0

    # Выплаты партнёрам зависят от процента (crypto_share), поэтому идём итерациями:
    # 3 прохода сходятся с запасом — база меняется монотонно и слабо.
    percent = 0.0
    for _ in range(3):
        r = compute_mf_realty(invoice_thb, buy_rate, payin_usdt, sell_rate=sell_rate,
                              company_percent=percent, agents=agents)
        # Свободные деньги = валовый доход − выплаты − что просили оставить
        free_usdt = r['gross_profit_usdt'] - r['agents_total_usdt'] - float(keep_usdt or 0)
        percent = max(0.0, free_usdt * buy_rate / invoice_thb * 100)
    return min(round(math.floor(percent * 100) / 100, 2), 100.0)


def compute_mf_freehold(payin_usdt, invoice_usd=None, sent_usd=None,
                        fee_percent=None, fee_fixed_usd=None, agents=None):
    """Расчёт сделки по недвижимости во фрихолде (оплата застройщику SWIFT-ом).

    Спека: docs/specs/2026-08-06-mf-freehold.md. Отличие от лизхолда — карман
    ОДИН: тайская компания в платеже не участвует, деньги уходят в USD со счёта
    за пределами Таиланда, поэтому вся прибыль остаётся в USDT.

    Комиссия провайдера считается ОТ СУММЫ ПЛАТЕЖА (инвойса), а не от того, что
    ушло с кошелька, и добавляется сверху:
      должно дойти X   → отправить S = X·(1+p) + F
      отправили S      → дойдёт  X = (S − F)/(1+p)
    До 10.08 здесь стоял gross-up `(X + F)/(1−p)` — предположение, что процент
    удерживают из отправки. Оно разошлось с фактом: на сделках Радимира
    (#477/#478) CRM насчитал 74 083,34, а реальный транш был 74 078,195 =
    73 440,67·1,008 + 50, совпадение до тысячных. Так же считали и #464 (03.08),
    где сумму вбивали руками. Расхождение малое (p·комиссия, тут $5,14), но
    систематическое.

    Себестоимость сделки = вся отправленная сумма: комиссия уже внутри неё,
    отдельной строкой её вычитать нельзя — получилось бы двойное списание.
    Поэтому валовый доход = приход − отправка УЖЕ учитывает все расходы, и это
    же число — база выплат агентам (решение Карима 06.08).

    Ничего не пишет в БД — чистая функция, её же зовёт форма для превью.
    """
    payin = float(payin_usdt or 0)
    invoice = float(invoice_usd or 0)
    p = float(fee_percent or 0) / 100
    fixed = float(fee_fixed_usd or 0)

    if sent_usd not in (None, ''):
        sent = float(sent_usd)
        arrive = (sent - fixed) / (1 + p)
    elif invoice:
        arrive = invoice
        sent = invoice * (1 + p) + fixed
    else:
        sent = arrive = 0.0
    arrive = max(arrive, 0.0)
    fee = max(sent - arrive, 0.0) if sent else 0.0

    gross_profit = payin - sent          # уже после всех расходов: комиссия внутри отправки
    volume = max(payin, sent)
    computed, _ = compute_agent_cascade(gross_profit, volume,
                                        [dict(a) for a in (agents or [])],
                                        crypto_base_usdt=gross_profit)
    agents_total = sum(a.get('_payout') or 0 for a in computed)
    net_profit = gross_profit - agents_total

    return {
        'payin_usdt': round(payin, 2),
        'invoice_usd': round(invoice, 2),
        'sent_usd': round(sent, 2),
        'arrive_usd': round(arrive, 2),
        'fee_usd': round(fee, 2),
        'fee_percent': round(p * 100, 4),
        'fee_fixed_usd': round(fixed, 2),
        # Фактическая доля комиссии в отправке — видно, во сколько обошёлся перевод
        'effective_fee_percent': round(fee / sent * 100, 4) if sent else 0,
        # Меньше нуля = застройщику дойдёт меньше инвойса, надо доотправить
        'invoice_gap_usd': round(arrive - invoice, 2) if invoice else 0,
        'gross_profit_usdt': round(gross_profit, 2),
        'profit_percent': round(gross_profit / sent * 100, 2) if sent else 0,
        'agents': computed,
        'agents_total_usdt': round(agents_total, 2),
        'net_profit_usdt': round(net_profit, 2),
        # Минус = выплаты агентам больше заработка сделки
        'net_shortfall_usdt': round(min(net_profit, 0), 2),
    }


class ReestrSnapshot(Base):
    """Снапшот данных реестра обменников (WL-бот). Фаза 1 — засев из reestr_seed.json,
    Фаза 2 — фоновый синк перезаписывает payload. Просмотры читают только отсюда → без лага."""
    __tablename__ = 'reestr_snapshots'
    id = Column(Integer, primary_key=True)
    view = Column(String(40), unique=True, nullable=False)  # deals|brokers|requests|merchants|wallets
    payload = Column(Text, nullable=False)                  # JSON-массив
    updated_at = Column(DateTime, default=datetime.utcnow)


class ReestrInflow(Base):
    """Приход брокера, заведённый вручную поштучно (закрытие дня).
    Маржа = разница (получено − Σ к выплате по покрытым сделкам), разнесённая
    пропорционально по сделкам. composition хранит снимок состава на момент ввода."""
    __tablename__ = 'reestr_inflows'
    id = Column(Integer, primary_key=True)
    broker = Column(String(100))
    wallet = Column(String(120))
    txhashes = Column(Text)               # хеши через запятую
    received_usdt = Column(Float)         # сколько реально прислал брокер
    expected_usdt = Column(Float)         # Σ к выплате по покрытым сделкам
    delta = Column(Float)                 # received − expected (наша маржа/корректировка)
    period = Column(String(60))
    composition = Column(Text)            # JSON: [{wl,m,rub,client,margin,mPct,st}]
    dop = Column(Text)                    # JSON: [{id,назн,usdt}] — доп.расходы (недвижка/предоплата), вычитаются из прихода
    created_at = Column(DateTime, default=datetime.utcnow)


_ACQ_FEE_RE = re.compile(r'Комиссия\s+([0-9][0-9\s ]*(?:[.,]\d{1,2})?)', re.IGNORECASE)
_ACQ_MERCHANT_RE = re.compile(r'Мерчант\s*№\s*(\d+)')


def parse_sber_acquiring(purpose):
    """Разбор назначения прихода Сбера: эквайринг (СБП) или перевод по реквизитам.

    В выписку приходят оба потока, и в пуле они были неразличимы. Отличие —
    в назначении: у СБП-платежа (ссылка WL-бота → QR НСПК) банк пишет
    «Зачисление средств по операциям эквайринга. Мерчант №781003872118.
    Комиссия 700.00.», плательщик — «Московский банк Сбербанка России».
    У перевода по реквизитам плательщик — ФИО клиента, назначение произвольное.

    Главное: эквайринг зачисляется УЖЕ ЗА ВЫЧЕТОМ комиссии, а клиент заплатил
    больше — 99 300 ₽ на счёте при 100 000 ₽ от клиента. В сделку должен идти
    gross = зачислено + комиссия, иначе курс клиента и объём занижены.
    Ставку не хардкодим: у разных мерчантов она разная (видели 0.7% и 2.4%).
    """
    text_ = purpose or ''
    low = text_.lower()
    if 'эквайринг' not in low and 'мерчант' not in low:
        return {'kind': 'transfer', 'merchant': None, 'fee_rub': 0.0}
    fee = 0.0
    m = _ACQ_FEE_RE.search(text_)
    if m:
        raw = m.group(1).replace(' ', '').replace(' ', '').replace(',', '.')
        try:
            fee = float(raw)
        except ValueError:
            fee = 0.0
    mer = _ACQ_MERCHANT_RE.search(text_)
    return {'kind': 'acquiring', 'merchant': mer.group(1) if mer else None, 'fee_rub': fee}


# Учёт конвертаций запущен 19.08.2026. Сделки, закрытые раньше, менялись вне
# системы: пачек по ним нет и не будет, и предупреждение «пачка не оформлена»
# на них — шум, из-за которого не видно настоящих пропусков после запуска.
# Через env можно сдвинуть, если разбор истории пойдёт глубже.
CONVERSIONS_LAUNCH_DATE = os.environ.get('CONVERSIONS_LAUNCH_DATE', '2026-08-19')


class SberIncome(Base):
    """Приход на счёт Сбера (реквизиты). Пушится SberNotifier'ом с VPS
    (POST /api/sber-incomes/ingest, идемпотентный upsert по uuid выписки).
    Пул с защитой от двойного учёта: claimed_deal_id — в какой сделке сумма
    забрана; забранные приходы исчезают из доступных в пикере."""
    __tablename__ = 'sber_incomes'
    id = Column(Integer, primary_key=True)
    uuid = Column(String(64), unique=True, nullable=False, index=True)
    # Индекс: списки всегда сортируются по дате, а отсечка истории фильтрует по ней
    operation_date = Column(String(40), index=True)   # ISO-дата операции из выписки Сбера
    amount_rub = Column(Float, nullable=False)
    payer = Column(String(255))             # плательщик (rurTransfer.payerName)
    purpose = Column(Text)                  # назначение платежа
    doc_number = Column(String(40))
    claimed_deal_id = Column(Integer, ForeignKey('deals.id'), nullable=True, index=True)
    claimed_at = Column(DateTime, nullable=True)
    # Приход, который к конвертации отношения не имеет: арбитраж, обменная сделка,
    # либо всё, что конвертировали до запуска учёта. Из «не сконвертировано»
    # такие исключаются, иначе экран показывает сотни миллионов и не читается
    excluded = Column(Boolean, default=False)
    note = Column(Text)
    # Откуда пришли деньги: WL-обменник, инвойс, обмен, арбитраж. Проставляется
    # руками либо подсказывается по привязанной сделке
    source_tag = Column(String(30))
    # Исключение из отсечки истории: приход старый, но деньги реально лежат
    # на счёте и ждут конвертации. Без него единственный способ вернуть такой
    # приход в работу — двигать дату запуска учёта, а это ломает все остальные
    keep_active = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    def converted_rub(self, agg=None):
        """Сколько из прихода уже ушло в конвертации (отменённые не считаются).

        `agg` — заранее посчитанная карта {income_id: сумма}. Без неё метод делает
        свой запрос, и на списке это превращалось в запрос на строку: 300 приходов
        давали 601 обращение к БД и 2,7 с на живом экране. Списки обязаны
        передавать agg (см. `_converted_by_income`), одиночные карточки — могут не.

        Запросом, а не по коллекции: доли добавляются и читаются в рамках одного
        запроса, коллекция в памяти к этому моменту не перечитана — остаток
        показывался бы старый (та же причина, что в ReimbursementTx.used_usdt).
        """
        if agg is not None:
            return round(agg.get(self.id, 0) or 0, 2)
        from sqlalchemy import func as _f
        from sqlalchemy.orm import object_session
        s = object_session(self)
        if s is not None and self.id:
            with s.no_autoflush:
                val = s.query(_f.sum(ConversionSource.amount_rub)).join(
                    Conversion, ConversionSource.conversion_id == Conversion.id
                ).filter(ConversionSource.sber_income_id == self.id,
                         Conversion.status != ConversionStatus.CANCELLED).scalar()
            return round(val or 0, 2)
        return 0.0

    def free_rub(self, agg=None):
        """Не сконвертировано по этому приходу."""
        return round((self.amount_rub or 0) - self.converted_rub(agg), 2)

    def to_dict(self, agg=None):
        acq = parse_sber_acquiring(self.purpose)
        net = self.amount_rub or 0
        return {
            'id': self.id, 'uuid': self.uuid,
            'operation_date': self.operation_date,
            'amount_rub': self.amount_rub,           # зачислено на счёт (net)
            'payer': self.payer, 'purpose': self.purpose,
            'doc_number': self.doc_number,
            'claimed_deal_id': self.claimed_deal_id,
            'claimed_at': self.claimed_at.isoformat() if self.claimed_at else None,
            # Разметка потока: 'acquiring' — СБП через эквайринг, 'transfer' — реквизиты
            'kind': acq['kind'],
            'merchant': acq['merchant'],
            # Сколько из прихода уже сконвертировано и сколько ещё лежит на счёте
            'converted_rub': self.converted_rub(agg),
            'free_rub': self.free_rub(agg),
            'excluded': bool(self.excluded),
            'keep_active': bool(self.keep_active),
            'note': self.note,
            'source_tag': self.source_tag,
            'fee_rub': round(acq['fee_rub'], 2),
            # Сколько заплатил клиент: у реквизитов = зачислено, у СБП = +комиссия
            'gross_rub': round(net + acq['fee_rub'], 2),
        }


_FEE_PURPOSE_RE = re.compile(r'комисси', re.IGNORECASE)


def parse_sber_debit_kind(purpose, payee=None):
    """Что это за списание: отправка брокеру или удержанная нами комиссия.

    Расход по конвертации уходит со счёта ТРЕМЯ строками — сама сумма брокеру,
    комиссия процентом и фиксированная. Проверено на выписке: 11.08
    144 435,47 + 290,46 + 40 = 144 765,93 (ровно зачисленное), 13.08
    232 681 + 935,79 + 40 = 233 656,79. Поэтому «удержание» не считается
    формулой — оно лежит в выписке отдельными платежами.

    Комиссии узнаём по слову «комисси» в назначении; вид правится руками.
    """
    if _FEE_PURPOSE_RE.search(purpose or ''):
        return 'fee'
    return 'broker'


class SberDebit(Base):
    """Списание со счёта Сбера. Зеркало SberIncome для расходной стороны.

    SberNotifier читает выписку с полем direction и уже шлёт расходы в Telegram,
    но в CalcCRM отдавал только CREDIT. Между тем в DEBIT есть всё, что оператор
    иначе вбивает руками: сумма, получатель (БРАЙТУМ, Кей Ту Эй), ИНН, назначение
    и номер платёжного поручения («поруч. 67»).
    """
    __tablename__ = 'sber_debits'
    id = Column(Integer, primary_key=True)
    uuid = Column(String(64), unique=True, nullable=False, index=True)
    operation_date = Column(String(40), index=True)
    amount_rub = Column(Float, nullable=False)
    payee = Column(String(255))             # получатель (rurTransfer.payeeName)
    payee_inn = Column(String(20))
    purpose = Column(Text)
    doc_number = Column(String(40))         # номер платёжного поручения
    kind = Column(String(20), default='broker')   # broker | fee
    created_at = Column(DateTime, default=datetime.utcnow)

    def __init__(self, **kw):
        # Вид определяем сразу по назначению, если его не задали явно:
        # иначе каждый потребитель должен помнить про парсер
        if not kw.get('kind'):
            kw['kind'] = parse_sber_debit_kind(kw.get('purpose'), kw.get('payee'))
        super().__init__(**kw)

    def used_rub(self):
        """Сколько из списания уже отнесено на конвертации (кроме отменённых)."""
        from sqlalchemy import func as _f
        from sqlalchemy.orm import object_session
        s = object_session(self)
        if s is not None and self.id:
            with s.no_autoflush:
                val = s.query(_f.sum(ConversionDebit.amount_rub)).join(
                    Conversion, ConversionDebit.conversion_id == Conversion.id
                ).filter(ConversionDebit.sber_debit_id == self.id,
                         Conversion.status != ConversionStatus.CANCELLED).scalar()
            return round(val or 0, 2)
        return 0.0

    def free_rub(self):
        """Не привязано к пачкам — защита от двойного учёта расхода."""
        return round((self.amount_rub or 0) - self.used_rub(), 2)

    def to_dict(self):
        return {
            'id': self.id, 'uuid': self.uuid,
            'operation_date': self.operation_date,
            'amount_rub': self.amount_rub,
            'payee': self.payee, 'payee_inn': self.payee_inn,
            'purpose': self.purpose, 'doc_number': self.doc_number,
            'kind': self.kind,
            'used_rub': self.used_rub(), 'free_rub': self.free_rub(),
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class PaymentLinkOrder(Base):
    """Платёжная ссылка Grusha Exchange (рельс grushab-2-b.ru).

    Вебхук коннектора об оплате теряется (кейс 2026-08-17: клиент оплатил,
    вебхук не пришёл, команда узнала от клиента), поэтому статус дополнительно
    поллится фоном (_payment_link_poll_loop). Строка в БД переживает деплои —
    раньше ссылки жили только в памяти процесса и терялись при каждом рестарте.
    """
    __tablename__ = 'payment_link_orders'
    id = Column(Integer, primary_key=True)
    order_id = Column(String(64), unique=True, index=True, nullable=False)
    payment_id = Column(String(64))          # uuid платежа в коннекторе (для GET-статуса)
    amount = Column(Float, default=0)        # ₽
    thb = Column(Float)                      # ฿ по курсу на момент выставления
    comment = Column(String(256), default='')
    link = Column(String(512), default='')
    status = Column(String(16), default='PENDING', index=True)  # PENDING/PAID/EXPIRED/FAILED
    created_at = Column(DateTime, default=datetime.utcnow)
    paid_at = Column(DateTime)


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
            conn.execute(text("ALTER TABLE payin_txs ADD COLUMN IF NOT EXISTS to_address VARCHAR(100)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_sber_incomes_operation_date ON sber_incomes (operation_date)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_sber_debits_operation_date ON sber_debits (operation_date)"))
            conn.execute(text("ALTER TABLE sber_incomes ADD COLUMN IF NOT EXISTS excluded BOOLEAN DEFAULT FALSE"))
            conn.execute(text("ALTER TABLE sber_incomes ADD COLUMN IF NOT EXISTS note TEXT"))
            conn.execute(text("ALTER TABLE sber_incomes ADD COLUMN IF NOT EXISTS source_tag VARCHAR(30)"))
            conn.execute(text("ALTER TABLE sber_incomes ADD COLUMN IF NOT EXISTS keep_active BOOLEAN DEFAULT FALSE"))
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
            for _sql in ("CREATE INDEX IF NOT EXISTS ix_sber_incomes_operation_date ON sber_incomes (operation_date)",
                         "CREATE INDEX IF NOT EXISTS ix_sber_debits_operation_date ON sber_debits (operation_date)",
                         "ALTER TABLE payin_txs ADD COLUMN to_address VARCHAR(100)",
                         "ALTER TABLE sber_incomes ADD COLUMN excluded BOOLEAN DEFAULT 0",
                         "ALTER TABLE sber_incomes ADD COLUMN note TEXT",
                         "ALTER TABLE sber_incomes ADD COLUMN source_tag VARCHAR(30)",
                         "ALTER TABLE sber_incomes ADD COLUMN keep_active BOOLEAN DEFAULT 0"):
                try: conn.execute(text(_sql))
                except: pass
        # Выдача с карты (THB-счёта): какой картой закрыли сделку
        if 'postgresql' in DATABASE_URL:
            conn.execute(text("ALTER TABLE deals ADD COLUMN IF NOT EXISTS bank_card_id INTEGER REFERENCES bank_cards(id)"))
            conn.execute(text("ALTER TABLE card_topups ADD COLUMN IF NOT EXISTS reference VARCHAR(120)"))
        else:
            try: conn.execute(text("ALTER TABLE deals ADD COLUMN bank_card_id INTEGER"))
            except: pass
            try: conn.execute(text("ALTER TABLE card_topups ADD COLUMN reference VARCHAR(120)"))
            except: pass
        # Реферальная система
        if 'postgresql' in DATABASE_URL:
            conn.execute(text("ALTER TABLE clients ADD COLUMN IF NOT EXISTS referrer_id INTEGER REFERENCES referrers(id)"))
            conn.execute(text("ALTER TABLE deals ADD COLUMN IF NOT EXISTS referrer_id INTEGER REFERENCES referrers(id)"))
            conn.execute(text("ALTER TABLE referrers ADD COLUMN IF NOT EXISTS payout_currency VARCHAR(10) DEFAULT 'USDT'"))
            # Две модели вознаграждения реферера: revshare (default) + markup
            conn.execute(text("ALTER TABLE referrers ADD COLUMN IF NOT EXISTS comp_model VARCHAR(20) DEFAULT 'revshare'"))
            conn.execute(text("ALTER TABLE referrers ADD COLUMN IF NOT EXISTS markup_percent FLOAT DEFAULT 0"))
            # Снапшот модели на сделке
            conn.execute(text("ALTER TABLE deals ADD COLUMN IF NOT EXISTS referrer_comp_model VARCHAR(20)"))
            conn.execute(text("ALTER TABLE deals ADD COLUMN IF NOT EXISTS referrer_markup_percent FLOAT"))
            conn.execute(text("ALTER TABLE deals ADD COLUMN IF NOT EXISTS referrer_paid_at TIMESTAMP"))
            # Платёжные ссылки партнёра: доступ выключен у всех, прод не меняется
            conn.execute(text("ALTER TABLE referrers ADD COLUMN IF NOT EXISTS can_create_links BOOLEAN DEFAULT FALSE"))
            conn.execute(text("ALTER TABLE referrers ADD COLUMN IF NOT EXISTS link_base_markup_percent FLOAT"))
            conn.execute(text("ALTER TABLE referrers ADD COLUMN IF NOT EXISTS link_markup_percent FLOAT DEFAULT 0"))
            conn.execute(text("ALTER TABLE referrers ADD COLUMN IF NOT EXISTS link_revshare_percent FLOAT DEFAULT 0"))
            conn.execute(text("ALTER TABLE referrers ADD COLUMN IF NOT EXISTS link_logo_url VARCHAR(512)"))
            conn.execute(text("ALTER TABLE referrers ADD COLUMN IF NOT EXISTS link_description VARCHAR(200)"))
            # Язык кабинета партнёра (англоязычные застройщики)
            conn.execute(text("ALTER TABLE referrers ADD COLUMN IF NOT EXISTS lang VARCHAR(5) DEFAULT 'ru'"))
        else:
            try: conn.execute(text("ALTER TABLE clients ADD COLUMN referrer_id INTEGER"))
            except: pass
            try: conn.execute(text("ALTER TABLE deals ADD COLUMN referrer_id INTEGER"))
            except: pass
            try: conn.execute(text("ALTER TABLE referrers ADD COLUMN payout_currency VARCHAR(10) DEFAULT 'USDT'"))
            except: pass
            try: conn.execute(text("ALTER TABLE referrers ADD COLUMN comp_model VARCHAR(20) DEFAULT 'revshare'"))
            except: pass
            try: conn.execute(text("ALTER TABLE referrers ADD COLUMN markup_percent FLOAT DEFAULT 0"))
            except: pass
            try: conn.execute(text("ALTER TABLE deals ADD COLUMN referrer_comp_model VARCHAR(20)"))
            except: pass
            try: conn.execute(text("ALTER TABLE deals ADD COLUMN referrer_markup_percent FLOAT"))
            except: pass
            try: conn.execute(text("ALTER TABLE deals ADD COLUMN referrer_paid_at TIMESTAMP"))
            except: pass
            try: conn.execute(text("ALTER TABLE referrers ADD COLUMN can_create_links BOOLEAN DEFAULT 0"))
            except: pass
            try: conn.execute(text("ALTER TABLE referrers ADD COLUMN link_base_markup_percent FLOAT"))
            except: pass
            try: conn.execute(text("ALTER TABLE referrers ADD COLUMN link_markup_percent FLOAT DEFAULT 0"))
            except: pass
            try: conn.execute(text("ALTER TABLE referrers ADD COLUMN link_revshare_percent FLOAT DEFAULT 0"))
            except: pass
            try: conn.execute(text("ALTER TABLE referrers ADD COLUMN link_logo_url VARCHAR(512)"))
            except: pass
            try: conn.execute(text("ALTER TABLE referrers ADD COLUMN link_description VARCHAR(200)"))
            except: pass
            try: conn.execute(text("ALTER TABLE referrers ADD COLUMN lang VARCHAR(5) DEFAULT 'ru'"))
            except: pass
        # Бэкфилл мультиагентов: старый одиночный реферал → строка deal_agents (ур.1).
        # Идемпотентно (NOT EXISTS) — безопасно выполнять при каждом старте.
        try:
            if 'postgresql' in DATABASE_URL:
                conn.execute(text("""
                    INSERT INTO deal_agents (deal_id, referrer_id, name, tier, comp_model,
                                             percent, fixed_usdt, payout_usdt, base_usdt, paid, paid_at, created_at)
                    SELECT d.id, d.referrer_id, d.referrer_name, 1,
                           COALESCE(d.referrer_comp_model, 'revshare'),
                           COALESCE(d.referrer_percent, 0), COALESCE(d.referrer_fixed_usdt, 0),
                           d.referrer_payout_usdt, d.profit_usdt,
                           COALESCE(d.referrer_paid, false), d.referrer_paid_at,
                           COALESCE(d.created_at, now())
                    FROM deals d
                    WHERE (d.referrer_id IS NOT NULL OR d.referrer_payout_usdt IS NOT NULL)
                      AND NOT EXISTS (SELECT 1 FROM deal_agents da WHERE da.deal_id = d.id)
                """))
            else:
                conn.execute(text("""
                    INSERT INTO deal_agents (deal_id, referrer_id, name, tier, comp_model,
                                             percent, fixed_usdt, payout_usdt, base_usdt, paid, paid_at, created_at)
                    SELECT d.id, d.referrer_id, d.referrer_name, 1,
                           COALESCE(d.referrer_comp_model, 'revshare'),
                           COALESCE(d.referrer_percent, 0), COALESCE(d.referrer_fixed_usdt, 0),
                           d.referrer_payout_usdt, d.profit_usdt,
                           COALESCE(d.referrer_paid, 0), d.referrer_paid_at,
                           COALESCE(d.created_at, CURRENT_TIMESTAMP)
                    FROM deals d
                    WHERE (d.referrer_id IS NOT NULL OR d.referrer_payout_usdt IS NOT NULL)
                      AND NOT EXISTS (SELECT 1 FROM deal_agents da WHERE da.deal_id = d.id)
                """))
        except Exception as e:
            print(f"ℹ️ backfill deal_agents: {e}", flush=True)
        # is_test флаг для тестовых рефереров (пропуск TG-нотификаций)
        if 'postgresql' in DATABASE_URL:
            try:
                conn.execute(text("ALTER TABLE referrers ADD COLUMN IF NOT EXISTS is_test BOOLEAN DEFAULT FALSE"))
            except Exception as e:
                print(f"ℹ️ referrers.is_test: {e}")
        else:
            try: conn.execute(text("ALTER TABLE referrers ADD COLUMN is_test BOOLEAN DEFAULT 0"))
            except: pass
        # is_test на сделках и клиентах — демо-данные тестового реферера.
        # Видны только в реферальном кабинете, из CRM/аналитики/GSheet исключены.
        if 'postgresql' in DATABASE_URL:
            try:
                conn.execute(text("ALTER TABLE deals ADD COLUMN IF NOT EXISTS is_test BOOLEAN DEFAULT FALSE"))
                conn.execute(text("ALTER TABLE clients ADD COLUMN IF NOT EXISTS is_test BOOLEAN DEFAULT FALSE"))
            except Exception as e:
                print(f"ℹ️ deals/clients.is_test: {e}")
        else:
            try: conn.execute(text("ALTER TABLE deals ADD COLUMN is_test BOOLEAN DEFAULT 0"))
            except: pass
            try: conn.execute(text("ALTER TABLE clients ADD COLUMN is_test BOOLEAN DEFAULT 0"))
            except: pass
        # Вход в кабинет: режим + привязанный TG id
        if 'postgresql' in DATABASE_URL:
            try:
                conn.execute(text("ALTER TABLE referrers ADD COLUMN IF NOT EXISTS auth_mode VARCHAR(20) DEFAULT 'link'"))
                conn.execute(text("ALTER TABLE referrers ADD COLUMN IF NOT EXISTS telegram_user_id BIGINT"))
            except Exception as e:
                print(f"ℹ️ referrers.auth_mode: {e}")
        else:
            try: conn.execute(text("ALTER TABLE referrers ADD COLUMN auth_mode VARCHAR(20) DEFAULT 'link'"))
            except: pass
            try: conn.execute(text("ALTER TABLE referrers ADD COLUMN telegram_user_id BIGINT"))
            except: pass
        # Admin: Telegram-вход
        if 'postgresql' in DATABASE_URL:
            try:
                conn.execute(text("ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS telegram VARCHAR(50)"))
                conn.execute(text("ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS telegram_user_id BIGINT"))
            except Exception as e:
                print(f"ℹ️ admin_users.telegram: {e}")
        else:
            try: conn.execute(text("ALTER TABLE admin_users ADD COLUMN telegram VARCHAR(50)"))
            except: pass
            try: conn.execute(text("ALTER TABLE admin_users ADD COLUMN telegram_user_id BIGINT"))
            except: pass
        # login_nonces: вход через бота для рефереров (nonce привязан к кабинету)
        if 'postgresql' in DATABASE_URL:
            try:
                conn.execute(text("ALTER TABLE login_nonces ADD COLUMN IF NOT EXISTS referrer_id INTEGER"))
                conn.execute(text("ALTER TABLE login_nonces ADD COLUMN IF NOT EXISTS tg_id BIGINT"))
            except Exception as e:
                print(f"ℹ️ login_nonces.referrer_id: {e}")
        else:
            try: conn.execute(text("ALTER TABLE login_nonces ADD COLUMN referrer_id INTEGER"))
            except: pass
            try: conn.execute(text("ALTER TABLE login_nonces ADD COLUMN tg_id BIGINT"))
            except: pass
        # payout_requests: снапшот сделок заявки (paid помечает только их)
        if 'postgresql' in DATABASE_URL:
            try:
                conn.execute(text("ALTER TABLE payout_requests ADD COLUMN IF NOT EXISTS deal_ids TEXT"))
            except Exception as e:
                print(f"ℹ️ payout_requests.deal_ids: {e}")
        else:
            try: conn.execute(text("ALTER TABLE payout_requests ADD COLUMN deal_ids TEXT"))
            except: pass
        # payout_requests: индекс по статусу + колонка tx_hash
        if 'postgresql' in DATABASE_URL:
            try:
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_payout_requests_status "
                    "ON payout_requests(status)"
                ))
                conn.execute(text("ALTER TABLE payout_requests ADD COLUMN IF NOT EXISTS tx_hash VARCHAR(120)"))
            except Exception as e:
                print(f"ℹ️ payout_requests migration: {e}")
        else:
            try: conn.execute(text("ALTER TABLE payout_requests ADD COLUMN tx_hash VARCHAR(120)"))
            except: pass
        # payout_requests: выплата в батах (метод, снапшот курсов, реквизиты банка, чек)
        _thb_cols = [
            ("payout_method", "VARCHAR(10) DEFAULT 'usdt'"),
            ("bitazza_rate", "FLOAT"),
            ("client_rate", "FLOAT"),
            ("thb_amount", "FLOAT"),
            ("bank_name", "VARCHAR(100)"),
            ("account_name", "VARCHAR(150)"),
            ("account_number", "VARCHAR(60)"),
            ("receipt_tg_file_id", "VARCHAR(200)"),
        ]
        for _col, _type in _thb_cols:
            if 'postgresql' in DATABASE_URL:
                try:
                    conn.execute(text(f"ALTER TABLE payout_requests ADD COLUMN IF NOT EXISTS {_col} {_type}"))
                except Exception as e:
                    print(f"ℹ️ payout_requests.{_col}: {e}")
            else:
                try: conn.execute(text(f"ALTER TABLE payout_requests ADD COLUMN {_col} {_type}"))
                except: pass
        # CR-05: partial UNIQUE на wallet_operations(deal_id, type) для защиты от дублей
        # при гонках. Пред-проверка дублей: если есть — лог и пропуск, иначе создание.
        dup_count = conn.execute(text(
            "SELECT COUNT(*) FROM (SELECT deal_id, type FROM wallet_operations "
            "WHERE deal_id IS NOT NULL GROUP BY deal_id, type HAVING COUNT(*) > 1) AS d"
        )).scalar() or 0
        if dup_count > 0:
            print(f"⚠️ CR-05 migration skipped: {dup_count} duplicate (deal_id,type) rows. Clean up first.")
        else:
            try:
                conn.execute(text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_wallet_operations_deal_type "
                    "ON wallet_operations(deal_id, type) WHERE deal_id IS NOT NULL"
                ))
                print("✅ CR-05 migration applied: UNIQUE(deal_id, type) on wallet_operations")
            except Exception as e:
                print(f"⚠️ CR-05 migration failed: {e}")
        # Доп.расходы на приходе реестра (недвижка/предоплата)
        if 'postgresql' in DATABASE_URL:
            try: conn.execute(text("ALTER TABLE reestr_inflows ADD COLUMN IF NOT EXISTS dop TEXT"))
            except Exception as e: print(f"ℹ️ reestr_inflows.dop: {e}")
        else:
            try: conn.execute(text("ALTER TABLE reestr_inflows ADD COLUMN dop TEXT"))
            except: pass
        conn.commit()
    print("✅ Database migration successful")
except Exception as e:
    print(f"ℹ️ Migration info: {e}")

print("✅ Database initialized")

# Засев реестра обменников из reestr_seed.json (только если таблица пуста).
# Фаза 1: снапшот демо/реальных данных. Фаза 2: фоновый синк перезапишет.
try:
    _rs = get_session()
    if _rs.query(ReestrSnapshot).count() == 0:
        _seed_path = os.path.join(os.path.dirname(__file__), 'reestr_seed.json')
        if os.path.exists(_seed_path):
            with open(_seed_path, 'r', encoding='utf-8') as _f:
                _seed = json.load(_f)
            for _view, _arr in _seed.items():
                _rs.add(ReestrSnapshot(view=_view, payload=json.dumps(_arr, ensure_ascii=False)))
            _rs.commit()
            print(f"✅ Reestr seeded: {', '.join(f'{k}={len(v)}' for k,v in _seed.items())}")
    _rs.close()
except Exception as e:
    print(f"ℹ️ Reestr seed: {e}", flush=True)

# ALTER TYPE ADD VALUE нельзя запускать внутри транзакции — отдельный autocommit
if 'postgresql' in DATABASE_URL:
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as ac:
            ac.execute(text("ALTER TYPE payinmethod ADD VALUE IF NOT EXISTS 'SBER_WL'"))
            ac.execute(text("ALTER TYPE payinmethod ADD VALUE IF NOT EXISTS 'SBER_REQS'"))
        print("✅ SBER_WL/SBER_REQS enum values added")
    except Exception as e:
        print(f"ℹ️ SBER_WL enum: {e}")
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as ac:
            ac.execute(text("ALTER TYPE dealstatus ADD VALUE IF NOT EXISTS 'LOSE'"))
            ac.execute(text("ALTER TYPE dealstatus ADD VALUE IF NOT EXISTS 'NOT_LEAD'"))
        print("✅ LOSE/NOT_LEAD enum values added")
    except Exception as e:
        print(f"ℹ️ LOSE enum: {e}")

# LOSE-сделки: причина, id Bitrix, revive-привязка к WON
try:
    with engine.connect() as conn:
        if 'postgresql' in DATABASE_URL:
            conn.execute(text("ALTER TABLE deals ADD COLUMN IF NOT EXISTS lose_reason VARCHAR(300)"))
            conn.execute(text("ALTER TABLE deals ADD COLUMN IF NOT EXISTS bitrix_deal_id INTEGER"))
            conn.execute(text("ALTER TABLE deals ADD COLUMN IF NOT EXISTS revived_by_deal_id INTEGER REFERENCES deals(id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_deals_bitrix_deal_id ON deals (bitrix_deal_id)"))
        else:
            for ddl in ("ALTER TABLE deals ADD COLUMN lose_reason VARCHAR(300)",
                        "ALTER TABLE deals ADD COLUMN bitrix_deal_id INTEGER",
                        "ALTER TABLE deals ADD COLUMN revived_by_deal_id INTEGER REFERENCES deals(id)"):
                try: conn.execute(text(ddl))
                except: pass
        conn.commit()
except Exception as e:
    print(f"ℹ️ lose fields migration: {e}")

# Канал привлечения на сделке (utm_source__/ref__ из start-парама бота)
try:
    with engine.connect() as conn:
        if 'postgresql' in DATABASE_URL:
            conn.execute(text("ALTER TABLE deals ADD COLUMN IF NOT EXISTS source_channel VARCHAR(50)"))
        else:
            try: conn.execute(text("ALTER TABLE deals ADD COLUMN source_channel VARCHAR(50)"))
            except: pass
        conn.commit()
except Exception as e:
    print(f"ℹ️ source_channel migration: {e}")

# Части прихода (sber_reqs): JSON-список частичных оплат на сделке
try:
    with engine.connect() as conn:
        if 'postgresql' in DATABASE_URL:
            conn.execute(text("ALTER TABLE deals ADD COLUMN IF NOT EXISTS payin_parts TEXT"))
            conn.execute(text("ALTER TABLE deal_agents ADD COLUMN IF NOT EXISTS paid_note VARCHAR(255)"))
        else:
            try: conn.execute(text("ALTER TABLE deals ADD COLUMN payin_parts TEXT"))
            except: pass
            try: conn.execute(text("ALTER TABLE deal_agents ADD COLUMN paid_note VARCHAR(255)"))
            except: pass
        conn.commit()
except Exception as e:
    print(f"ℹ️ payin_parts migration: {e}")

# Приход крипты частями: JSON-список хэшей с суммами
try:
    with engine.connect() as conn:
        if 'postgresql' in DATABASE_URL:
            conn.execute(text("ALTER TABLE deals ADD COLUMN IF NOT EXISTS payin_tx_hashes TEXT"))
        else:
            try: conn.execute(text("ALTER TABLE deals ADD COLUMN payin_tx_hashes TEXT"))
            except: pass
        conn.commit()
except Exception as e:
    print(f"ℹ️ payin_tx_hashes migration: {e}")

# Реестр входящих переводов: один хэш может обслуживать несколько сделок
try:
    Base.metadata.create_all(engine, tables=[PayinTx.__table__, PayinTxUse.__table__])
except Exception as e:
    print(f"ℹ️ payin_txs migration: {e}")

# Бэкфилл реестра: существующие хэши прихода становятся переводами с долями.
# Без него старый хэш не найдётся в реестре и будет считаться занятым целиком —
# то есть поведение до реестра, но уже без возможности добрать остаток.
# Сумма перевода = сумма долей: сеть тут не опрашиваем (сотни запросов на старте),
# помечаем source='manual', сверить можно вручную из экрана реестра.
try:
    with SessionLocal() as _s:
        if _s.query(PayinTx).count() == 0:
            claims = {}
            for _d in _s.query(Deal).filter(Deal.payin_tx_hashes != None).all():
                try:
                    for _p in json.loads(_d.payin_tx_hashes) or []:
                        if _p.get('hash'):
                            claims.setdefault(_p['hash'], []).append(
                                (_d.id, float(_p.get('amount_usdt') or 0)))
                except (ValueError, TypeError, AttributeError):
                    continue
            for _d in _s.query(Deal).filter(Deal.payin_tx_hash != None).all():
                if _d.payin_tx_hash not in claims:
                    claims[_d.payin_tx_hash] = [(_d.id, float(_d.payin_amount_usdt or 0))]
            for _hash, _uses in claims.items():
                _tx = PayinTx(tx_hash=_hash, source='manual',
                              amount_usdt=round(sum(a for _, a in _uses), 2),
                              notes='бэкфилл: сумма из CRM, с сетью не сверена')
                _s.add(_tx)
                _s.flush()
                for _deal_id, _amt in _uses:
                    _s.add(PayinTxUse(tx_id=_tx.id, deal_id=_deal_id, amount_usdt=_amt))
            _s.commit()
            if claims:
                print(f'✅ Бэкфилл реестра приходов: {len(claims)} переводов')
except Exception as e:
    print(f"ℹ️ payin_txs backfill: {e}")

# Дополнительные приходы: несколько способов Pay-In в одной сделке
try:
    with engine.connect() as conn:
        if 'postgresql' in DATABASE_URL:
            conn.execute(text("ALTER TABLE deals ADD COLUMN IF NOT EXISTS payin_extra TEXT"))
        else:
            try: conn.execute(text("ALTER TABLE deals ADD COLUMN payin_extra TEXT"))
            except: pass
        conn.commit()
except Exception as e:
    print(f"ℹ️ payin_extra migration: {e}")

# reimbursements.tx_hash хранит несколько хэшей через запятую, но в БД остался
# VARCHAR(100) от первой версии — возмещение с 2+ хэшами падало на INSERT
# (StringDataRightTruncation). В модели уже Text, тип в БД догоняем здесь.
try:
    with engine.connect() as conn:
        if 'postgresql' in DATABASE_URL:
            conn.execute(text("ALTER TABLE reimbursements ALTER COLUMN tx_hash TYPE TEXT"))
        conn.commit()
except Exception as e:
    print(f"ℹ️ reimbursements.tx_hash migration: {e}")

# Сделки по недвижимости через MF Corporation (leasehold)
_MF_REALTY_COLUMNS = [
    ('deal_kind', 'VARCHAR(20)'), ('realty_purpose', 'VARCHAR(200)'),
    ('invoice_amount_thb', 'DOUBLE PRECISION'), ('sell_rate_thb_usdt', 'DOUBLE PRECISION'),
    ('buy_rate_thb_usdt', 'DOUBLE PRECISION'), ('company_percent', 'DOUBLE PRECISION'),
    ('company_sent_thb', 'DOUBLE PRECISION'), ('company_fee_thb', 'DOUBLE PRECISION'),
    ('company_fee_usdt', 'DOUBLE PRECISION'), ('crypto_remainder_usdt', 'DOUBLE PRECISION'),
    ('katika_fee_thb', 'DOUBLE PRECISION'), ('katika_fee_usdt', 'DOUBLE PRECISION'),
    ('client_spread_percent', 'DOUBLE PRECISION'), ('payout_tx_hashes', 'TEXT'),
    ('doc_invoice_url', 'VARCHAR(500)'), ('doc_contract_url', 'VARCHAR(500)'),
    ('doc_payment_url', 'VARCHAR(500)'),
    # Фрихолд (оплата SWIFT-ом, один карман)
    ('invoice_amount_usd', 'DOUBLE PRECISION'), ('transfer_sent_usd', 'DOUBLE PRECISION'),
    ('transfer_fee_percent', 'DOUBLE PRECISION'), ('transfer_fee_fixed_usd', 'DOUBLE PRECISION'),
    ('transfer_fee_usd', 'DOUBLE PRECISION'), ('transfer_arrive_usd', 'DOUBLE PRECISION'),
]
try:
    with engine.connect() as conn:
        is_pg = 'postgresql' in DATABASE_URL
        for col, coltype in _MF_REALTY_COLUMNS:
            sql_type = coltype if is_pg else coltype.replace('DOUBLE PRECISION', 'FLOAT')
            if is_pg:
                conn.execute(text(f"ALTER TABLE deals ADD COLUMN IF NOT EXISTS {col} {sql_type}"))
            else:
                try: conn.execute(text(f"ALTER TABLE deals ADD COLUMN {col} {sql_type}"))
                except: pass
        conn.commit()
except Exception as e:
    print(f"ℹ️ mf_realty migration: {e}")

# KYC: файлы переехали с диска в БД + видео-заявление клиента
try:
    Base.metadata.create_all(engine, tables=[KycFile.__table__])
    with engine.connect() as conn:
        if 'postgresql' in DATABASE_URL:
            conn.execute(text("ALTER TABLE kyc_requests ADD COLUMN IF NOT EXISTS statement_required BOOLEAN DEFAULT FALSE"))
            conn.execute(text("ALTER TABLE kyc_requests ADD COLUMN IF NOT EXISTS statement_text TEXT"))
            conn.execute(text("ALTER TABLE kyc_requests ADD COLUMN IF NOT EXISTS files_purged_at TIMESTAMP"))
        else:
            for ddl in ("ALTER TABLE kyc_requests ADD COLUMN statement_required BOOLEAN DEFAULT 0",
                        "ALTER TABLE kyc_requests ADD COLUMN statement_text TEXT",
                        "ALTER TABLE kyc_requests ADD COLUMN files_purged_at TIMESTAMP"):
                try: conn.execute(text(ddl))
                except: pass
        conn.commit()
except Exception as e:
    print(f"ℹ️ kyc_files migration: {e}")

# ==================== WEBHOOK CONFIG ====================
WEBHOOK_URL = os.environ.get('CRM_WEBHOOK_URL', '')

# ==================== WL BOT ====================
WL_BOT_URL = os.environ.get('WL_BOT_URL', 'http://wl.grusha.agency')
WL_BOT_API_KEY = os.environ.get('WL_BOT_API_KEY', '')


# ==================== РЕЕСТР ОБМЕННИКОВ ====================
def _conversions_by_wl(session, wl_deals):
    """Карта «WL-сделка → её конвертация» для реестра обменников.

    Реестр знает только про ручные приходы брокера и потому показывает сделку
    необеспеченной, хотя рубли по ней уже конвертированы. Мост тот же, что во
    вкладке «Поступления»: приход на счёт ↔ WL-сделка по сумме и дате.
    """
    if not wl_deals:
        return {}
    from sqlalchemy.orm import selectinload
    rows = session.query(ConversionSource, Conversion, SberIncome).join(
        Conversion, ConversionSource.conversion_id == Conversion.id).join(
        SberIncome, ConversionSource.sber_income_id == SberIncome.id).options(
        selectinload(Conversion.sources), selectinload(Conversion.txs)).filter(
        Conversion.status != ConversionStatus.CANCELLED).all()
    out = {}
    shares_cache = {}
    for src, conv, inc in rows:
        deal = _match_wl_deal(inc.to_dict(agg={}), wl_deals)
        if not deal:
            continue
        usdt = None
        if conv.status == ConversionStatus.RECEIVED:
            if conv.id not in shares_cache:
                shares_cache[conv.id] = conversion_shares_for(conv)
            usdt = shares_cache[conv.id].get(inc.id)
        out[deal['wl']] = {
            'id': conv.id, 'display_name': conv.display_name, 'broker': conv.broker,
            'request_no': conv.request_no, 'rate_rub_usdt': conv.rate_rub_usdt,
            'status': conv.status.value if conv.status else None,
            'sent_at': conv.sent_at.isoformat() if conv.sent_at else None,
            'amount_rub': round(src.amount_rub or 0, 2), 'usdt': usdt,
        }
    return out


@app.route('/api/reestr/all', methods=['GET'])
def get_reestr_all():
    """Все данные реестра одним чтением из Postgres CalcCRM (без внешних вызовов → без лага).
    Фронт-вкладка «Обменники» рендерит из этого ответа все под-вкладки."""
    session = get_session()
    try:
        out = {'deals': [], 'brokers': [], 'requests': [], 'merchants': [], 'wallets': [], 'updated_at': None}
        for snap in session.query(ReestrSnapshot).all():
            try:
                out[snap.view] = json.loads(snap.payload)
            except Exception:
                out[snap.view] = []
            if snap.updated_at and (out['updated_at'] is None or snap.updated_at.isoformat() > out['updated_at']):
                out['updated_at'] = snap.updated_at.isoformat()

        # Приходы = только заведённые вручную (поштучно). Авто-приходы из таблицы
        # не показываем — Карим ведёт список сам. Маржа/покрытие из ручных приходов.
        brokers = []
        for inf in session.query(ReestrInflow).order_by(ReestrInflow.created_at.desc()).all():
            comp = json.loads(inf.composition or '[]')
            brokers.append({
                'n': '#' + str(inf.id), 'd': inf.period or (inf.created_at.strftime('%d.%m') if inf.created_at else ''),
                'br': inf.broker or '', 'w': inf.wallet or '', 'h': inf.txhashes or '—',
                'got': inf.received_usdt or 0, 'delta': f"{(inf.delta or 0):.2f}", 'st': 'received',
                'items': comp, 'dop': json.loads(inf.dop or '[]'), 'dealsText': ', '.join(c.get('wl', '') for c in comp),
                'k': '', 'manual': True,
            })
        out['brokers'] = brokers
        # покрытие из приходов (какой приход обеспечил сделку). Маржа/финансы — НЕ отсюда,
        # а из синка (таблица «Иструмент карим»). Приход влияет только на СТАТУС + сверку.
        inflow_by_wl = {}
        for b in brokers:
            h0 = (b.get('h') or '').split(',')[0].strip()
            for it in (b.get('items') or []):
                wl = it.get('wl')
                if wl and not str(wl).startswith('#'):
                    inflow_by_wl[wl] = {'n': b.get('n'), 'h': h0, 'w': b.get('w', ''), 'br': b.get('br', '')}
        # Конвертации из «Поступлений»: сделка, чьи рубли ушли брокеру и вернулись
        # в USDT, обеспечена — даже если ручной приход по ней не заводили
        conv_by_wl = _conversions_by_wl(session, out['deals'])
        covered_wls = set(inflow_by_wl.keys())
        for d in out['deals']:
            conv = conv_by_wl.get(d['wl'])
            d['conversion'] = conv
            cov = d['wl'] in covered_wls or bool(conv and conv['status'] == 'received')
            d['covered'] = cov
            # маржа/получили/отдали — остаются из синка (таблица). Статус — по покрытию.
            base = d.get('status')
            if base == 'closed':
                d['status'] = 'closed' if cov else 'advance'
            elif base == 'paid':
                d['status'] = 'covered' if cov else 'paid'
            # 'requested' и пр. — без изменения (ещё не выплачено)
        for r in out['requests']:
            cov = 0
            txs = r.get('txs', [])
            for t in txs:
                src = inflow_by_wl.get(t['wl'])
                conv = conv_by_wl.get(t['wl'])
                t['conversion'] = conv
                if src:
                    t['broker'] = src
                    cov += 1
                elif conv and conv['status'] == 'received':
                    cov += 1
            n = len(txs)
            all_cov = bool(n) and cov == n
            if all_cov:
                r['reco'] = f"✅ Сверка: {cov}/{n} сделок обеспечены приходами · суммы бьются"
            elif cov:
                r['reco'] = f"⚠️ Обеспечено {cov}/{n} · остальные ждут прихода"
            # выплаченная заявка без полного покрытия = аванс (брокер ещё должен)
            if r.get('status') == 'closed' and not all_cov:
                r['status'] = 'advance'
        return jsonify(out)
    finally:
        session.close()


def _reestr_inflow_composition(received, deal_wls, deals_by_wl):
    """Состав прихода + пропорциональное распределение разницы по сделкам.
    margin сделки = доля_сделки × (received − Σ к выплате). Возвращает (items, expected, delta)."""
    picked = [deals_by_wl[w] for w in deal_wls if w in deals_by_wl]
    expected = sum(float(d.get('usdt') or 0) for d in picked)
    delta = float(received or 0) - expected
    items = []
    for d in picked:
        usdt = float(d.get('usdt') or 0)
        share = (usdt / expected * delta) if expected else 0.0
        items.append({
            'wl': d['wl'], 'm': d.get('merchant', ''), 'rub': d.get('rub', 0),
            'client': usdt, 'margin': round(share, 2),
            'mPct': (f"{share / usdt * 100:.2f}%" if usdt else ''),
            'st': d.get('status', 'closed'),
        })
    return items, round(expected, 2), round(delta, 2)


@app.route('/api/reestr/inflows', methods=['POST'])
def post_reestr_inflow():
    """Завести приход вручную: {broker, wallet, period, received, txhashes[], deals:[wl..]}.
    Считает разницу (received − Σ к выплате) и разносит её пропорционально → маржа сделок."""
    data = request.get_json(force=True, silent=True) or {}
    received = float(data.get('received') or 0)
    deal_wls = data.get('deals') or []
    txhashes = data.get('txhashes') or []
    if isinstance(txhashes, str):
        txhashes = [h.strip() for h in txhashes.replace(',', '\n').split('\n') if h.strip()]
    if not deal_wls:
        return jsonify({'ok': False, 'error': 'не выбраны сделки'}), 400
    session = get_session()
    try:
        snap = session.query(ReestrSnapshot).filter_by(view='deals').first()
        deals = json.loads(snap.payload) if snap else []
        by_wl = {d['wl']: d for d in deals}
        items, expected, delta = _reestr_inflow_composition(received, deal_wls, by_wl)
        inf = ReestrInflow(
            broker=data.get('broker', ''), wallet=data.get('wallet', ''),
            txhashes=', '.join(txhashes), received_usdt=received,
            expected_usdt=expected, delta=delta, period=data.get('period', ''),
            composition=json.dumps(items, ensure_ascii=False),
        )
        session.add(inf)
        session.commit()
        return jsonify({'ok': True, 'id': inf.id, 'expected': expected, 'delta': delta})
    finally:
        session.close()


@app.route('/api/reestr/inflows/<int:inflow_id>', methods=['DELETE'])
def delete_reestr_inflow(inflow_id):
    """Удалить ручной приход (сделки снова станут необеспеченными)."""
    session = get_session()
    try:
        inf = session.get(ReestrInflow, inflow_id)
        if inf:
            session.delete(inf)
            session.commit()
        return jsonify({'ok': True})
    finally:
        session.close()


@app.route('/api/reestr/inflows/<int:inflow_id>', methods=['PATCH'])
def patch_reestr_inflow(inflow_id):
    """Переименовать брокера / поправить кошелёк / период у ручного прихода."""
    data = request.get_json(force=True, silent=True) or {}
    session = get_session()
    try:
        inf = session.get(ReestrInflow, inflow_id)
        if not inf:
            return jsonify({'ok': False, 'error': 'не найдено'}), 404
        if 'broker' in data:
            inf.broker = (data['broker'] or '').strip()
        if 'wallet' in data:
            inf.wallet = (data['wallet'] or '').strip()
        if 'period' in data:
            inf.period = (data['period'] or '').strip()
        session.commit()
        return jsonify({'ok': True})
    finally:
        session.close()


@app.route('/api/reestr/inflows/<int:inflow_id>/dop', methods=['POST'])
def add_reestr_dop(inflow_id):
    """Доп.расход на приходе (недвижка/предоплата — не за транзакцию): {назн, usdt}.
    Вычитается из остатка прихода и из нашей прибыли при рендере."""
    data = request.get_json(force=True, silent=True) or {}
    naz = (data.get('назн') or data.get('nazn') or 'Доп оплата').strip()
    usdt = float(data.get('usdt') or 0)
    if usdt <= 0:
        return jsonify({'ok': False, 'error': 'сумма должна быть > 0'}), 400
    session = get_session()
    try:
        inf = session.get(ReestrInflow, inflow_id)
        if not inf:
            return jsonify({'ok': False, 'error': 'приход не найден'}), 404
        items = json.loads(inf.dop or '[]')
        new_id = (max((d.get('id', 0) for d in items), default=0) + 1)
        items.append({'id': new_id, 'назн': naz, 'usdt': round(usdt, 2)})
        inf.dop = json.dumps(items, ensure_ascii=False)
        session.commit()
        return jsonify({'ok': True, 'id': new_id})
    finally:
        session.close()


@app.route('/api/reestr/inflows/<int:inflow_id>/dop/<int:dop_id>', methods=['DELETE'])
def delete_reestr_dop(inflow_id, dop_id):
    """Удалить доп.расход с прихода."""
    session = get_session()
    try:
        inf = session.get(ReestrInflow, inflow_id)
        if not inf:
            return jsonify({'ok': False, 'error': 'приход не найден'}), 404
        items = [d for d in json.loads(inf.dop or '[]') if d.get('id') != dop_id]
        inf.dop = json.dumps(items, ensure_ascii=False)
        session.commit()
        return jsonify({'ok': True})
    finally:
        session.close()


@app.route('/api/reestr/tx-sum', methods=['POST'])
def reestr_tx_sum():
    """Сумма USDT по списку TxHash из TronScan (1 хеш → его сумма; 2+ → сумма транзакций).
    Используется формой прихода для авто-подстановки «сколько прислал брокер»."""
    data = request.get_json(force=True, silent=True) or {}
    raw = data.get('hashes') or []
    if isinstance(raw, str):
        raw = [h.strip() for h in raw.replace(',', '\n').split('\n') if h.strip()]
    # Лимит: каждый хеш — синхронный запрос к TronScan с timeout=10с. Без лимита
    # POST со 100+ хешами блокирует воркер на ~1000с (DoS одним запросом).
    raw = raw[:20]
    items, total, to_addr, dates = [], 0.0, None, []
    for h in raw:
        try:
            r = requests.get(f'https://apilist.tronscanapi.com/api/transaction-info?hash={h}', timeout=10)
            info = r.json() if r.status_code == 200 else {}
            trc = info.get('trc20TransferInfo') or []
            tr = trc[0] if trc else {}
            amt = float(tr.get('amount_str', 0)) / 1_000_000 if tr else 0.0
            if tr.get('to_address') and not to_addr:
                to_addr = tr.get('to_address')
            # дата транзакции из TronScan → BKK (UTC+7), как в реестре
            ts = info.get('timestamp')
            dstr = None
            if ts:
                d = datetime.utcfromtimestamp(int(ts) / 1000) + timedelta(hours=7)
                dates.append(d)
                dstr = d.strftime('%d.%m %H:%M')
            items.append({'hash': h, 'amount': round(amt, 6), 'ok': amt > 0,
                          'to': tr.get('to_address'), 'from': tr.get('from_address'), 'date': dstr})
            total += amt
        except Exception as e:
            items.append({'hash': h, 'amount': 0, 'ok': False, 'error': str(e)})
    # дата/период прихода: одна дата или диапазон
    date_str = ''
    if dates:
        ds = sorted(dates)
        a, b = ds[0].strftime('%d.%m'), ds[-1].strftime('%d.%m')
        date_str = a if a == b else f'{a}–{b}'
    # определяем брокера по кошельку получения (мэтч с таблицей «Приходы от брокера»)
    broker, wallet = '', to_addr or ''
    if to_addr:
        session = get_session()
        try:
            snap = session.query(ReestrSnapshot).filter_by(view='brokers').first()
            for b in (json.loads(snap.payload) if snap else []):
                if (b.get('w') or '') == to_addr:
                    broker = b.get('br', '')
                    break
        finally:
            session.close()
    return jsonify({'ok': True, 'total': round(total, 6), 'items': items,
                    'wallet': wallet, 'broker': broker, 'date': date_str})


# Сериализует ВСЕ обращения к листу «общая сделка»: read (get_all_values) и
# mutate (insert/update/delete) должны идти атомарно, иначе два параллельных
# завершения сделки (вебхук + ручное) читают один снапшот и дублируют/затирают
# строки. Gunicorn запущен в 1 воркер (см. Procfile) → threading.Lock достаточно.
_gsheet_lock = threading.RLock()

# --- онлайн-синк реестра из WL-бота ---
_reestr_sync_lock = threading.Lock()
REESTR_SYNC_INTERVAL = int(os.environ.get('REESTR_SYNC_INTERVAL', '300'))  # сек


def _reestr_upsert(session, view, arr):
    """Перезаписывает один view снапшота (idempotent)."""
    payload = json.dumps(arr, ensure_ascii=False)
    snap = session.query(ReestrSnapshot).filter_by(view=view).first()
    if snap:
        snap.payload = payload
        snap.updated_at = datetime.utcnow()
    else:
        session.add(ReestrSnapshot(view=view, payload=payload, updated_at=datetime.utcnow()))


def sync_reestr_from_wl():
    """Онлайн-синк: тянет снапшот из WL-бота → пишет в reestr_snapshots (deals/requests/merchants).
    brokers/wallets НЕ трогает (они из seed/Google Sheet). Бросает requests-исключение при сетевой ошибке.
    Просмотры реестра всегда читают из БД CalcCRM → синк не влияет на скорость UI (без лага)."""
    headers = {}
    if WL_BOT_API_KEY:
        headers['Authorization'] = f'Bearer {WL_BOT_API_KEY}'
    resp = requests.get(f'{WL_BOT_URL}/api/reestr/snapshot', headers=headers, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    session = get_session()
    try:
        counts = {}
        for view in ('merchants', 'deals', 'requests', 'brokers'):
            arr = data.get(view, [])
            # пустой brokers (лист недоступен) не затираем — оставляем прошлый снапшот/seed
            if view == 'brokers' and not arr:
                continue
            _reestr_upsert(session, view, arr)
            counts[view] = len(arr)
        session.commit()
        return counts
    finally:
        session.close()


@app.route('/api/reestr/sync', methods=['POST'])
def post_reestr_sync():
    """Ручной форс-синк (кнопка «🔄 Обновить»). Сериализован локом."""
    with _reestr_sync_lock:
        try:
            counts = sync_reestr_from_wl()
            return jsonify({'ok': True, 'synced': counts})
        except requests.exceptions.RequestException as e:
            return jsonify({'ok': False, 'error': f'WL Bot недоступен: {e}'}), 502
        except Exception as e:
            return jsonify({'ok': False, 'error': str(e)}), 500


def _reestr_sync_loop():
    """Фоновый рефрешер: раз в REESTR_SYNC_INTERVAL тянет онлайн-данные. Ошибки глушит
    (старый снапшот остаётся, UI не падает). Не запускает Chromium → не конфликтует с Playwright по RAM."""
    while True:
        time.sleep(REESTR_SYNC_INTERVAL)
        try:
            with _reestr_sync_lock:
                sync_reestr_from_wl()
        except Exception as e:
            print(f"ℹ️ reestr sync loop: {e}", flush=True)


if os.environ.get('REESTR_SYNC_ENABLED', '1') == '1' and WL_BOT_URL:
    threading.Thread(target=_reestr_sync_loop, daemon=True, name='reestr-sync').start()

# ==================== GOOGLE SHEETS SYNC ====================
GSHEET_ID = '1aW84o8JmiIOPpCaSyGQuWCmf_h7H6uPWBCloq7_WDOY'
GSHEET_WORKSHEET = 'общая сделка'
GSHEET_REFERRERS_WORKSHEET = 'рефереры'
# Заголовки листа «рефереры» (создаются автоматически, если листа ещё нет)
GSHEET_REFERRERS_HEADERS = [
    '№', 'Дата', 'ID сделки', 'Реферер', 'Код', 'Модель', '%',
    'Объём USDT', 'Profit USDT', 'Reward USDT', 'Выплачено',
]
# ── Таблица «Cделки недвижимость» (сделки через MF Corp) ─────────────────
# Отдельный файл от «общей сделки»: помесячные листы «<месяц> leasehold».
# Лист создаётся лениво — при первой сделке месяца, из шаблона колонок ниже.
GSHEET_REALTY_ID = os.environ.get(
    'GSHEET_REALTY_ID', '1OhcHOoAI3_EMplg-VaP3lI8FjhOahA3jY7f62T3pkg4')
GSHEET_REALTY_ALL = 'все сделки'   # сводный лист: каждая строка независимо от месяца
# Колонки один в один с листами май–июль (включая опечатки в шапке — иначе
# существующие листы пришлось бы переписывать). CRM ID добавлен последним:
# это якорь для upsert, без него правка сделки плодила бы дубли строк.
GSHEET_REALTY_HEADERS = [
    'Назанчение', 'дата', 'направление', 'сумма руб', 'курс от брокера rub-usdt',
    'от кого', 'сумма thb', 'курс продажи', 'курс покупкт', 'приход usdt ',
    'cколько потратили на инвойс', 'доход Тайской компании usdt',
    'процент на тайскую компанию', 'отправлено на компанию в thb',
    'Доход в бата тайской компании', 'доход Катики в батах ', 'доход Катики в usdt ',
    'доход', 'выплата агенту', 'доход в usdt на кошельке', 'чистый доход',
    'инвойс', 'договор', 'оплата', 'хеш транзакции', 'CRM ID', 'часть',
]
# Фрихолд — свой набор колонок: карман один, зато есть расход на перевод и
# сумма, которая реально дойдёт до застройщика. Лист «<месяц> freehold».
GSHEET_FREEHOLD_ALL = 'все сделки freehold'
GSHEET_FREEHOLD_HEADERS = [
    'Назначение', 'дата', 'направление', 'сумма руб', 'курс от брокера rub-usdt',
    'от кого', 'приход usdt', 'инвойс застройщику usd', 'отправлено usd',
    'комиссия за перевод %', 'фикс за перевод usd', 'комиссия за перевод usd',
    'дойдёт застройщику usd', 'доход', 'выплата агенту', 'чистый доход',
    'инвойс', 'договор', 'оплата', 'хеш транзакции', 'CRM ID', 'часть',
]
# CRM ID больше не последняя колонка — позицию берём по имени, а не по длине
GSHEET_REALTY_ID_COL = GSHEET_REALTY_HEADERS.index('CRM ID') + 1
GSHEET_FREEHOLD_ID_COL = GSHEET_FREEHOLD_HEADERS.index('CRM ID') + 1
GSHEET_REALTY_MONTHS = [
    'январь', 'февраль', 'март', 'апрель', 'май', 'июнь',
    'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь',
]

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


def realty_month_sheet_name(deal_date):
    """Имя листа месяца: «июль leasehold». Месяц берём из ДАТЫ СДЕЛКИ, не из
    «сегодня» — иначе правка июльской сделки в августе создаёт лишний лист."""
    return f'{GSHEET_REALTY_MONTHS[deal_date.month - 1]} leasehold'


def freehold_month_sheet_name(deal_date):
    """Имя листа месяца для фрихолда: «август freehold» (в таблице уже есть «май freehold»)."""
    return f'{GSHEET_REALTY_MONTHS[deal_date.month - 1]} freehold'


def _find_month_worksheet(sh, name, keywords):
    """Ищет лист месяца по ключевым словам, а не по полной строке.

    Допуск на опечатки в существующих названиях («май leeshold» на проде):
    сверяем месяц из начала имени + любое из keywords в заголовке.
    """
    month = name.split()[0]
    for ws in sh.worksheets():
        title = ws.title.strip().lower()
        if title.startswith(month) and any(k in title for k in keywords):
            return ws
    return None


def _realty_find_month_worksheet(sh, name):
    """Лист месяца для лизхолда («июль leasehold», «май leeshold»)."""
    return _find_month_worksheet(sh, name, ('leasehold', 'leeshold'))


def build_realty_rows(deal):
    """Строки выгрузки сделки через MF Corp — по строке на часть Pay-In.

    Порядок колонок — как в GSHEET_REALTY_HEADERS. Делится всё, что
    пропорционально приходу; инвойс, курсы, процент компании и ссылки на
    документы описывают одну отправку и стоят только в первой строке.
    В остальных строках эти колонки помечаются прочерком «—»: пустая ячейка
    читается как «данные не подставились», прочерк — как «намеренно пусто».
    """
    d = deal
    parts = _payin_all_parts(d)
    amounts = [p['amount_usdt'] for p in parts]
    n = len(parts)

    agent_names = ', '.join(
        a.name for a in sorted(d.agents, key=lambda x: (x.tier or 1, x.id or 0)) if a.name
    ) if d.agents else ''
    date_str = d.created_at.strftime('%d.%m.%Y') if d.created_at else ''

    invoice_cost = (round((d.invoice_amount_thb or 0) / d.buy_rate_thb_usdt, 2)
                    if d.buy_rate_thb_usdt else 0)
    income = (round((d.payin_amount_usdt or 0) - invoice_cost, 2)
              if d.buy_rate_thb_usdt else 0)

    # Колонка хэша сверяет ОТПРАВКУ: если переводы в компанию отмечены — их хэши.
    # Отправка одна на сделку, поэтому они стоят в первой строке; остальные части
    # показывают свои хэши прихода.
    payout_hashes = _payout_hash_list(d)

    cost_split = split_by_payin_share(invoice_cost, amounts)
    fee_usdt_split = split_by_payin_share(d.company_fee_usdt or 0, amounts)
    sent_thb_split = split_by_payin_share(d.company_sent_thb or 0, amounts)
    fee_thb_split = split_by_payin_share(d.company_fee_thb or 0, amounts)
    katika_thb_split = split_by_payin_share(d.katika_fee_thb or 0, amounts)
    katika_usdt_split = split_by_payin_share(d.katika_fee_usdt or 0, amounts)
    income_split = split_by_payin_share(income, amounts)
    agent_split = split_by_payin_share(d.referrer_payout_usdt or 0, amounts)
    wallet_split = split_by_payin_share(d.crypto_remainder_usdt or 0, amounts)
    net_split = split_by_payin_share(d.net_profit_usdt or 0, amounts)

    rows = []
    for i, p in enumerate(parts):
        first = (i == 0)
        rows.append([
            d.realty_purpose or '',                                       # 0 Назначение
            date_str,                                                     # 1 дата
            'usdt-thb' if p['method'] == 'crypto_direct' else 'rub-thb',  # 2 направление
            p['amount_rub'] or '',                                        # 3 сумма руб части
            p['rate_rub_usdt'] or '',                                     # 4 курс ЧАСТИ
            agent_names,                                                  # 5 от кого
            (d.invoice_amount_thb or '') if first else '—',               # 6 сумма thb
            (d.sell_rate_thb_usdt or '') if first else '—',               # 7 курс продажи
            (d.buy_rate_thb_usdt or '') if first else '—',                # 8 курс покупкт
            p['amount_usdt'] or '',                                       # 9 приход usdt части
            cost_split[i] or '',                                          # 10 потратили на инвойс
            fee_usdt_split[i] or '',                                      # 11 доход компании usdt
            ((d.company_percent / 100) if d.company_percent else '') if first else '—',  # 12
            sent_thb_split[i] or '',                                      # 13 отправлено thb
            fee_thb_split[i] or '',                                       # 14 доход в батах
            katika_thb_split[i] or '',                                    # 15 Катика баты
            katika_usdt_split[i] or '',                                   # 16 Катика usdt
            income_split[i] or '',                                        # 17 доход
            agent_split[i] or '',                                         # 18 выплата агенту
            wallet_split[i] or '',                                        # 19 на кошельке
            net_split[i] or '',                                           # 20 чистый доход
            (d.doc_invoice_url or '') if first else '',                   # 21 инвойс
            (d.doc_contract_url or '') if first else '',                  # 22 договор
            (d.doc_payment_url or '') if first else '',                   # 23 оплата
            (', '.join(payout_hashes) if (first and payout_hashes)
             else ', '.join(h['hash'] for h in p['tx_hashes'])),          # 24 хеш
            d.id,                                                         # 25 CRM ID
            f'{i + 1}/{n}',                                               # 26 часть
        ])
    return rows


def build_freehold_rows(deal):
    """Строки выгрузки сделки во фрихолде — по строке на часть Pay-In.

    Делятся приход и всё, что от него пропорционально: отправка, доход, выплата
    агенту, чистый доход. Инвойс, комиссия за перевод, «дойдёт застройщику» и
    ссылки на документы описывают один SWIFT — стоят только в первой строке,
    делить их значило бы придумать переводы, которых не было. В остальных
    строках эти колонки помечаются прочерком «—»: пустая ячейка читается как
    «данные не подставились», прочерк — как «намеренно пусто, см. строку ч.1».
    """
    d = deal
    parts = _payin_all_parts(d)
    amounts = [p['amount_usdt'] for p in parts]
    n = len(parts)

    agent_names = ', '.join(
        a.name for a in sorted(d.agents, key=lambda x: (x.tier or 1, x.id or 0)) if a.name
    ) if d.agents else ''
    date_str = d.created_at.strftime('%d.%m.%Y') if d.created_at else ''

    # Как у лизхолда: сверяют отправку, поэтому хэши переводов — в первой строке
    payout_hashes = _payout_hash_list(d)

    sent_split = split_by_payin_share(d.transfer_sent_usd or 0, amounts)
    profit_split = split_by_payin_share(d.profit_usdt or 0, amounts)
    agent_split = split_by_payin_share(d.referrer_payout_usdt or 0, amounts)
    net_split = split_by_payin_share(d.net_profit_usdt or 0, amounts)

    rows = []
    for i, p in enumerate(parts):
        first = (i == 0)
        rows.append([
            d.realty_purpose or '',                                       # 0 Назначение
            date_str,                                                     # 1 дата
            'usdt-usd' if p['method'] == 'crypto_direct' else 'rub-usd',  # 2 направление
            p['amount_rub'] or '',                                        # 3 сумма руб части
            p['rate_rub_usdt'] or '',                                     # 4 курс ЧАСТИ
            agent_names,                                                  # 5 от кого
            p['amount_usdt'] or '',                                       # 6 приход usdt части
            (d.invoice_amount_usd or '') if first else '—',               # 7 инвойс
            sent_split[i] or '',                                          # 8 отправлено — доля
            (d.transfer_fee_percent or '') if first else '—',             # 9 комиссия %
            (d.transfer_fee_fixed_usd or '') if first else '—',           # 10 фикс
            (d.transfer_fee_usd or '') if first else '—',                 # 11 комиссия usd
            (d.transfer_arrive_usd or '') if first else '—',              # 12 дойдёт
            profit_split[i] or '',                                        # 13 доход — доля
            agent_split[i] or '',                                         # 14 выплата агенту
            net_split[i] or '',                                           # 15 чистый доход
            (d.doc_invoice_url or '') if first else '',                   # 16 инвойс url
            (d.doc_contract_url or '') if first else '',                  # 17 договор
            (d.doc_payment_url or '') if first else '',                   # 18 оплата
            (', '.join(payout_hashes) if (first and payout_hashes)
             else ', '.join(h['hash'] for h in p['tx_hashes'])),          # 19 хеш
            d.id,                                                         # 20 CRM ID
            f'{i + 1}/{n}',                                               # 21 часть
        ])
    return rows


def sync_realty_deal_to_gsheet(deal):
    """Выгрузка сделки через MF Corp в таблицу «Cделки недвижимость».

    Лист месяца создаётся лениво из шаблона колонок; строка ищется по CRM ID
    и перезаписывается (upsert), иначе дописывается. Та же строка дублируется
    в сводный лист «все сделки» — чтобы считать год без склейки вкладок.
    Никогда не роняет вызывающего: возвращает dict с диагностикой.
    """
    with _gsheet_lock:
        return _sync_realty_deal_impl(deal)


def _realty_upsert(ws, rows, deal_id, id_col=None):
    """Перезаписывает блок строк сделки по CRM ID либо дописывает. True = вставка.

    Число частей могло измениться с прошлой выгрузки: лишние строки удаляются
    снизу вверх (сверху вниз номера ниже съезжают), недостающие вставляются.
    Без выравнивания update затёр бы соседнюю сделку.
    """
    id_col = id_col or GSHEET_REALTY_ID_COL
    width = len(rows[0])
    ids = ws.col_values(id_col)
    hits = [idx for idx, val in enumerate(ids, start=1)
            if val and str(val).strip() == str(deal_id)]
    if not hits:
        for row in rows:
            ws.append_row(row, value_input_option='USER_ENTERED')
        return True

    while len(hits) > len(rows):
        ws.delete_rows(hits.pop())
    while len(hits) < len(rows):
        ws.insert_rows([[''] * width], row=hits[-1] + 1)
        hits.append(hits[-1] + 1)

    end = gspread.utils.rowcol_to_a1(hits[-1], width)
    ws.update(f'A{hits[0]}:{end}', rows, value_input_option='USER_ENTERED')
    return False


def _realty_get_or_create_ws(sh, title, rows=200, headers=None):
    """Лист по имени, создаётся с шапкой если его нет."""
    headers = headers or GSHEET_REALTY_HEADERS
    try:
        return sh.worksheet(title)
    except Exception:
        ws = sh.add_worksheet(title=title, rows=rows, cols=len(headers))
        ws.append_row(headers, value_input_option='USER_ENTERED')
        return ws


def _sheet_header(ws):
    """Первая строка листа, пустой список если недоступна."""
    try:
        return [str(x).strip() for x in (ws.row_values(1) or [])]
    except Exception:
        return []


def _sync_freehold_impl(sh, deal, when):
    """Фрихолд: лист «<месяц> freehold», свои колонки.

    Лист «май freehold» в таблице заполнен руками и по другой разметке —
    дописать туда наши колонки значило бы разъехаться с шапкой. Поэтому при
    несовпадении заголовка пишем в «<месяц> freehold CRM», а ручной лист
    оставляем как есть.
    """
    title = freehold_month_sheet_name(when)
    ws = _find_month_worksheet(sh, title, ('freehold',))
    created = False
    if ws is None:
        ws = _realty_get_or_create_ws(sh, title, headers=GSHEET_FREEHOLD_HEADERS)
        created = True
    else:
        header = _sheet_header(ws)
        if not any(header):
            # Лист завели руками и не заполнили — без шапки строка читалась бы заголовком
            ws.append_row(GSHEET_FREEHOLD_HEADERS, value_input_option='USER_ENTERED')
        elif GSHEET_FREEHOLD_HEADERS[:len(header)] != header:
            title = f'{title} CRM'
            ws = _realty_get_or_create_ws(sh, title, headers=GSHEET_FREEHOLD_HEADERS)
            created = True
    rows = build_freehold_rows(deal)
    inserted = _realty_upsert(ws, rows, deal.id, id_col=GSHEET_FREEHOLD_ID_COL)
    try:
        _realty_upsert(
            _realty_get_or_create_ws(sh, GSHEET_FREEHOLD_ALL, rows=2000,
                                     headers=GSHEET_FREEHOLD_HEADERS),
            rows, deal.id, id_col=GSHEET_FREEHOLD_ID_COL)
    except Exception as e:
        print(f'[GSheet freehold] сводный лист: {e}', flush=True)
    return {'ok': True, 'sheet': ws.title, 'sheet_created': created, 'inserted': inserted}


def _sync_realty_deal_impl(deal):
    try:
        gc = get_gsheet_client()
        if not gc:
            return {'ok': False, 'error': 'no_credentials'}
        sh = gc.open_by_key(GSHEET_REALTY_ID)
        when = deal.created_at or datetime.utcnow()
        if deal.deal_kind == MF_FREEHOLD_KIND:
            return _sync_freehold_impl(sh, deal, when)
        month_name = realty_month_sheet_name(when)
        ws = _realty_find_month_worksheet(sh, month_name)
        created = False
        if ws is None:
            ws = _realty_get_or_create_ws(sh, month_name)
            created = True
        elif not ws.col_values(1):
            # Лист месяца есть, но пустой (завели руками и не заполнили) —
            # без шапки строка легла бы в первую строку и читалась как заголовок
            ws.append_row(GSHEET_REALTY_HEADERS, value_input_option='USER_ENTERED')
        rows = build_realty_rows(deal)
        inserted = _realty_upsert(ws, rows, deal.id)
        # Сводный лист — тот же upsert, чтобы правка не плодила дубли
        try:
            _realty_upsert(_realty_get_or_create_ws(sh, GSHEET_REALTY_ALL, rows=2000),
                           rows, deal.id)
        except Exception as e:
            print(f'[GSheet realty] сводный лист: {e}', flush=True)
        return {'ok': True, 'sheet': ws.title, 'sheet_created': created,
                'inserted': inserted}
    except Exception as e:
        print(f'[GSheet realty] {e}', flush=True)
        return {'ok': False, 'error': str(e)}


def sync_deals_to_gsheet(deals):
    """Тонкий враппер: сериализует доступ к листу через _gsheet_lock."""
    deals = [d for d in deals if not getattr(d, 'is_test', False)]  # демо не льём в таблицу
    if not deals:
        return
    with _gsheet_lock:
        return _sync_deals_to_gsheet_impl(deals)


def build_deal_rows(deal, start_num):
    """Строки листа «общая сделка» для одной сделки — по строке на часть Pay-In.

    Колонки A–R как раньше, S — «часть» (`1/2`, `2/2`; у одноканальной `1/1`).
    Номер первой строки обычный, дальше `.2`, `.3` — так видно, что строки
    принадлежат одной сделке, и счётчик остаётся счётчиком сделок.

    Делится всё, что пропорционально приходу: выдача клиенту, выдача в USDT,
    выплата партнёру, чистая доходность. Приход, метод и хэши идут построчно
    от самой части. Остальное дублируется.

    У сделки с одним каналом строка получается ровно такой же, как до
    появления частей, — плюс «1/1» в новой колонке.
    """
    parts = _payin_all_parts(deal)
    amounts = [p['amount_usdt'] for p in parts]
    n = len(parts)
    single = (n == 1)

    date_str = deal.created_at.strftime('%d.%m.%Y') if deal.created_at else ''
    payout_method_str = PAYOUT_METHOD_LABELS.get(
        deal.payout_method.value if deal.payout_method else '', '')
    net_profit = (deal.net_profit_usdt
                  if (deal.referrer_payout_usdt and deal.net_profit_usdt is not None)
                  else deal.profit_usdt)

    payout_thb = deal.custom_payout_amount or deal.payout_amount_thb or 0
    payout_currency = (deal.custom_payout_currency or 'thb').lower()
    payout_usdt = deal.payout_amount_usdt or 0

    thb_split = split_by_payin_share(payout_thb, amounts, digits=0)
    usdt_split = split_by_payin_share(payout_usdt, amounts)
    ref_split = split_by_payin_share(deal.referrer_payout_usdt or 0, amounts)
    net_split = split_by_payin_share(net_profit or 0, amounts)

    rows = []
    for i, p in enumerate(parts):
        # Кастомная одночастная сделка сохраняет прежний вид: приход в своей
        # валюте из custom_*, а не восстановленный из плоских полей
        if deal.is_custom and single:
            currency_in = (deal.custom_payin_currency or '').lower()
            amount_in = deal.custom_payin_amount or 0
            amount_in_usdt = deal.payin_amount_usdt or deal.custom_payin_amount or 0
        elif p['amount_rub']:
            currency_in, amount_in = 'rub', p['amount_rub']
            amount_in_usdt = p['amount_usdt']
        else:
            currency_in, amount_in = 'usdt', p['amount_usdt']
            amount_in_usdt = p['amount_usdt']

        method_str = ('кастом' if deal.is_custom
                      else PAYIN_METHOD_LABELS.get(p['method'], ''))

        rows.append([
            start_num if i == 0 else f'{start_num}.{i + 1}',       # A: номер
            (deal.client.name if deal.client else deal.client_name) or '',  # B: клиент
            '',                                                    # C: пусто
            date_str,                                              # D: дата
            f'{amount_in:,.2f}' if amount_in else '',              # E: сумма части
            currency_in,                                           # F: валюта
            f'${amount_in_usdt:,.2f}' if amount_in_usdt else '',   # G: USDT части
            int(thb_split[i]) if thb_split[i] else '',             # H: доля выдачи
            payout_currency,                                       # I: валюта выдачи
            f'${usdt_split[i]:,.2f}' if usdt_split[i] else '',     # J: доля выдачи USDT
            '',                                                    # K: брокеру
            deal.referrer_name or '',                              # L: реферал
            f'${ref_split[i]:,.2f}' if ref_split[i] else '',       # M: доля партнёру
            f'${net_split[i]:,.2f}' if net_profit is not None else '',  # N: доля чистой
            payout_method_str,                                     # O: способ выдачи
            method_str,                                            # P: метод ЧАСТИ
            ', '.join(h['hash'] for h in p['tx_hashes']),          # Q: хэши части
            str(deal.id) if deal.id else '',                       # R: якорь upsert
            f'{i + 1}/{n}',                                        # S: часть
        ])
    return rows


def _sync_deals_to_gsheet_impl(deals):
    """Добавляет завершённые сделки в Google Sheet 'общая сделка'.
    Идемпотентно: если строка для сделки уже есть (по deal.id в колонке R,
    иначе по client_name + date) — обновляет её через _force_update_deal_row_in_gsheet.
    Возвращает dict {ok: bool, inserted: int, error: str|None} для диагностики."""
    try:
        gc = get_gsheet_client()
        if not gc:
            print('[GSheet] No credentials, skipping sync')
            return {'ok': False, 'inserted': 0, 'error': 'no_credentials'}

        sh = gc.open_by_key(GSHEET_ID)
        ws = sh.worksheet(GSHEET_WORKSHEET)
        all_rows = ws.get_all_values()

        # Идемпотентность: разделяем сделки на «уже есть» и «новые».
        # Существующие — апдейтим, новые — append'им.
        existing_to_update = []
        deals = list(deals)
        new_deals = []
        for d in deals:
            # Тем же поиском, что и перезапись: у многочастной сделки без якоря
            # он вернёт пусто, и она пойдёт на вставку, а не затрёт чужую строку
            existing_row_num = find_deal_rows_in_gsheet(all_rows, d)
            if existing_row_num:
                existing_to_update.append(d)
            else:
                new_deals.append(d)
        # Обновляем существующие
        for d in existing_to_update:
            try:
                _force_update_deal_row_in_gsheet(ws, all_rows, d)
            except Exception as e:
                print(f'[GSheet] update existing row error for deal #{getattr(d, "id", "?")}: {e}')
        if not new_deals:
            return {'ok': True, 'inserted': 0, 'updated': len(existing_to_update), 'error': None}
        deals = new_deals

        # Находим последнюю строку данных: пронумерованную сделку, строку-итог
        # «ИТОГ <месяц>» или заголовок недели. Новые сделки вставляются ПОСЛЕ неё.
        # Важно учитывать строку «ИТОГ <месяц>»: иначе сделки нового месяца садятся
        # ВЫШЕ уже закрытого итога предыдущего месяца (баг: июньские сделки оказались
        # над «ИТОГ МАЙ 2026» → визуально «июня нет»). Теперь они уходят под итог.
        insert_row = len(all_rows) + 1
        for i in range(len(all_rows) - 1, -1, -1):
            row = all_rows[i]
            a = str(row[0]).strip() if row[0] else ''
            b = str(row[1]).strip().lower() if len(row) > 1 and row[1] else ''
            if a.isdigit() or a.upper().startswith('ИТОГ') or 'неделя' in b:
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
            # Номер инкрементируется на СДЕЛКУ, а не на строку: части получают
            # тот же номер с суффиксом (187, 187.2), счётчик остаётся счётчиком сделок
            last_num += 1
            new_rows.extend(build_deal_rows(deal, last_num))

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
    """Находит строку сделки в Google Sheet.
    0) По deal.id в служебной колонке R (надёжно, без коллизий) — для сделок,
       записанных после внедрения id-колонки.
    1) По клиенту + дате (точное совпадение) — легаси-строки без id.
    2) Fallback: по дате + сумме USDT (если имя клиента было изменено
       в CRM, но строка в Sheet с прежним именем).
    Возвращает 1-indexed номер строки или None."""
    deal_date = deal.created_at.strftime('%d.%m.%Y') if deal.created_at else ''
    deal_name = (deal.client_name or '').strip().lower()
    deal_usdt = deal.payin_amount_usdt or 0
    # Попытка 0: по deal.id в колонке R (индекс 17). Уникальный ключ — два
    # обмена одного клиента в один день больше не схлопываются в одну строку.
    deal_id_str = str(deal.id) if getattr(deal, 'id', None) else ''
    if deal_id_str:
        for i, row in enumerate(all_rows):
            if len(row) >= 18 and str(row[17]).strip() == deal_id_str:
                return i + 1
    # Попытка 1: имя + дата
    for i, row in enumerate(all_rows):
        if len(row) >= 4:
            row_name = str(row[1]).strip().lower()
            row_date = str(row[3]).strip()
            if row_name == deal_name and row_date == deal_date:
                return i + 1
    # Попытка 2: дата + сумма USDT (колонка G). Нормализуем: убираем $ и запятые,
    # сравниваем как float — формат в Sheet может быть как "$39,241.00" так и "39,241.00".
    if deal_date and deal_usdt > 0:
        for i, row in enumerate(all_rows):
            if len(row) >= 7:
                row_date = str(row[3]).strip()
                if row_date != deal_date:
                    continue
                raw = str(row[6]).strip().replace('$', '').replace(',', '').replace(' ', '')
                try:
                    if abs(float(raw) - deal_usdt) < 0.01:
                        return i + 1
                except ValueError:
                    pass
    return None


def find_deal_rows_in_gsheet(all_rows, deal):
    """Номера ВСЕХ строк сделки (1-indexed), по порядку сверху вниз.

    Основной путь — `deal.id` в колонке R. Фолбэки по «имя + дата» и
    «дата + сумма USDT» оставлены только для сделок с ОДНОЙ частью: у
    многочастной в колонке G лежат суммы частей, а фолбэк сравнивает с итогом —
    своё он не найдёт никогда, зато может совпасть чужая сделка с близкой суммой
    в тот же день, и снесётся она.
    """
    deal_id_str = str(deal.id) if getattr(deal, 'id', None) else ''
    if deal_id_str:
        hits = [i + 1 for i, row in enumerate(all_rows)
                if len(row) >= 18 and str(row[17]).strip() == deal_id_str]
        if hits:
            return hits

    if len(_payin_all_parts(deal)) > 1:
        return []          # вслепую многочастную не ищем

    row_num = find_deal_row_in_gsheet(None, all_rows, deal)
    return [row_num] if row_num else []


def delete_deal_from_gsheet(deal):
    """Тонкий враппер: сериализует доступ к листу через _gsheet_lock."""
    if getattr(deal, 'is_test', False):
        return
    with _gsheet_lock:
        return _delete_deal_from_gsheet_impl(deal)


def _delete_deal_from_gsheet_impl(deal):
    """Удаляет ВСЕ строки сделки из листа «общая сделка».

    Снизу вверх: после первого delete_rows номера строк ниже съезжают на
    единицу, и удаление сверху вниз снесло бы соседнюю сделку.
    """
    try:
        gc = get_gsheet_client()
        if not gc:
            return
        sh = gc.open_by_key(GSHEET_ID)
        ws = sh.worksheet(GSHEET_WORKSHEET)
        all_rows = ws.get_all_values()
        row_nums = find_deal_rows_in_gsheet(all_rows, deal)
        if not row_nums:
            print(f'[GSheet] Rows not found for deal #{deal.id} ({deal.client_name})')
            return
        for row_num in sorted(row_nums, reverse=True):
            ws.delete_rows(row_num)
        print(f'[GSheet] Deleted {len(row_nums)} row(s) for deal #{deal.id}')
    except Exception as e:
        print(f'[GSheet] Delete error: {e}')


def _force_update_deal_row_in_gsheet(ws, all_rows, deal):
    """Перезаписывает блок строк сделки в листе «общая сделка» без проверки
    reimbursement_id. Используется sync_deals_to_gsheet для идемпотентности.

    Число частей могло измениться с прошлой выгрузки, поэтому блок сначала
    выравнивается по длине: лишние строки удаляются снизу вверх, недостающие
    вставляются. Без этого ws.update затёр бы соседнюю сделку.
    """
    row_nums = find_deal_rows_in_gsheet(all_rows, deal)
    if not row_nums:
        return False
    existing_num = all_rows[row_nums[0] - 1][0] if all_rows[row_nums[0] - 1] else ''
    rows = build_deal_rows(deal, existing_num or (deal.id or ''))

    while len(row_nums) > len(rows):
        ws.delete_rows(row_nums.pop())
    while len(row_nums) < len(rows):
        ws.insert_rows([[''] * len(rows[0])], row=row_nums[-1] + 1)
        row_nums.append(row_nums[-1] + 1)

    ws.update(values=rows, range_name=f'A{row_nums[0]}:S{row_nums[-1]}',
              value_input_option='USER_ENTERED')
    print(f'[GSheet] Force-updated {len(rows)} row(s) for deal #{deal.id}')
    return True


def update_deal_in_gsheet(deal):
    """Тонкий враппер: сериализует доступ к листу через _gsheet_lock."""
    if getattr(deal, 'is_test', False):
        return
    with _gsheet_lock:
        return _update_deal_in_gsheet_impl(deal)


def _update_deal_in_gsheet_impl(deal):
    """Обновляет строки сделки в Google Sheet (только если возмещена).

    Сборка строк — общая с _force_update_deal_row_in_gsheet: раньше здесь
    лежала её копия, и любая правка формата требовала синхронной правки в двух
    местах. Заодно отсюда приезжает выравнивание блока по числу частей.
    """
    if deal.reimbursement_id is None:
        return
    try:
        gc = get_gsheet_client()
        if not gc:
            return
        sh = gc.open_by_key(GSHEET_ID)
        ws = sh.worksheet(GSHEET_WORKSHEET)
        all_rows = ws.get_all_values()
        if not _force_update_deal_row_in_gsheet(ws, all_rows, deal):
            print(f'[GSheet] Row not found for update: {deal.client_name}')
    except Exception as e:
        print(f'[GSheet] Update error: {e}')


def _get_or_create_referrers_worksheet(sh):
    """Возвращает worksheet 'рефереры'. Создаёт с заголовками если нет."""
    try:
        return sh.worksheet(GSHEET_REFERRERS_WORKSHEET)
    except Exception:
        ws = sh.add_worksheet(title=GSHEET_REFERRERS_WORKSHEET, rows=200, cols=len(GSHEET_REFERRERS_HEADERS))
        ws.update(values=[GSHEET_REFERRERS_HEADERS], range_name='A1', value_input_option='USER_ENTERED')
        # Заголовок — жирный
        try:
            ws.format(f'A1:{chr(ord("A") + len(GSHEET_REFERRERS_HEADERS) - 1)}1', {
                'textFormat': {'bold': True},
                'backgroundColor': {'red': 0.93, 'green': 0.95, 'blue': 1.0},
            })
        except Exception:
            pass
        print(f'[GSheet] Created sheet "{GSHEET_REFERRERS_WORKSHEET}"')
        return ws


def sync_referrer_reward_to_gsheet(deal):
    """Добавляет строку выплаты рефереру в лист 'рефереры'."""
    if getattr(deal, 'is_test', False):
        return
    if not deal.referrer_id or not deal.referrer_payout_usdt:
        return
    try:
        gc = get_gsheet_client()
        if not gc:
            return
        sh = gc.open_by_key(GSHEET_ID)
        ws = _get_or_create_referrers_worksheet(sh)
        all_rows = ws.get_all_values()

        # Идемпотентность: если строка с этой сделкой уже есть — не дублируем
        for row in all_rows[1:]:  # пропускаем заголовок
            if len(row) >= 3 and str(row[2]).strip() == str(deal.id):
                return

        # Найти реферера для кода
        ref_code = ''
        try:
            from sqlalchemy.orm import object_session
            sess = object_session(deal) or get_session()
            ref = sess.query(Referrer).get(deal.referrer_id)
            if ref:
                ref_code = ref.code or ''
        except Exception:
            pass

        date_str = deal.created_at.strftime('%d.%m.%Y') if deal.created_at else ''
        model = deal.referrer_comp_model or 'revshare'
        if model == 'markup':
            pct = deal.referrer_markup_percent or 0
            pct_str = f'+{pct}% к курсу'
        elif model == 'fixed':
            pct = deal.referrer_fixed_usdt or 0
            pct_str = f'fixed ${pct}'
        else:
            pct = deal.referrer_percent or 0
            pct_str = f'{pct}% от прибыли'
        volume_usdt = deal.payout_amount_usdt or deal.payin_amount_usdt or 0

        # Номер строки = последний номер + 1 (по колонке A)
        last_num = 0
        for r in reversed(all_rows[1:]):
            if r and str(r[0]).strip().isdigit():
                last_num = int(r[0]); break

        paid_str = (deal.referrer_paid_at.strftime('%d.%m.%Y')
                    if deal.referrer_paid and deal.referrer_paid_at
                    else ('да' if deal.referrer_paid else 'нет'))
        row = [
            last_num + 1,
            date_str,
            deal.id,
            deal.referrer_name or '',
            ref_code,
            model,
            pct_str,
            f'${volume_usdt:,.2f}' if volume_usdt else '',
            f'${deal.profit_usdt:,.2f}' if deal.profit_usdt is not None else '',
            f'${deal.referrer_payout_usdt:,.2f}' if deal.referrer_payout_usdt else '',
            paid_str,
        ]
        ws.append_row(row, value_input_option='USER_ENTERED')
        print(f'[GSheet] Referrers: added row for deal #{deal.id}')
    except Exception as e:
        print(f'[GSheet] Referrer sync error: {e}')


def mark_referrer_rewards_paid_in_gsheet(deal_ids, paid_at):
    """Обновляет колонку «Выплачено» в листе «рефереры» для указанных сделок."""
    if not deal_ids:
        return
    try:
        gc = get_gsheet_client()
        if not gc:
            return
        sh = gc.open_by_key(GSHEET_ID)
        try:
            ws = sh.worksheet(GSHEET_REFERRERS_WORKSHEET)
        except Exception:
            return
        all_rows = ws.get_all_values()
        date_str = paid_at.strftime('%d.%m.%Y') if paid_at else 'да'
        ids_str = {str(x) for x in deal_ids}
        # Колонка «Выплачено» = K (11-я, 1-indexed)
        paid_col_idx = len(GSHEET_REFERRERS_HEADERS)  # 11
        updates = []
        for i, row in enumerate(all_rows[1:], start=2):
            if len(row) >= 3 and str(row[2]).strip() in ids_str:
                cell = f'{chr(ord("A") + paid_col_idx - 1)}{i}'
                updates.append({'range': cell, 'values': [[date_str]]})
        if updates:
            ws.batch_update(updates, value_input_option='USER_ENTERED')
            print(f'[GSheet] Referrers: marked {len(updates)} rows paid ({date_str})')
    except Exception as e:
        print(f'[GSheet] mark paid sync error: {e}')


def delete_referrer_reward_from_gsheet(deal):
    """Удаляет строку выплаты рефереру по ID сделки."""
    if not deal.referrer_id:
        return
    try:
        gc = get_gsheet_client()
        if not gc:
            return
        sh = gc.open_by_key(GSHEET_ID)
        try:
            ws = sh.worksheet(GSHEET_REFERRERS_WORKSHEET)
        except Exception:
            return
        all_rows = ws.get_all_values()
        for i, row in enumerate(all_rows[1:], start=2):  # 2 = 1-indexed после заголовка
            if len(row) >= 3 and str(row[2]).strip() == str(deal.id):
                ws.delete_rows(i)
                print(f'[GSheet] Referrers: deleted row {i} (deal #{deal.id})')
                return
    except Exception as e:
        print(f'[GSheet] Referrer delete error: {e}')


def _payin_parts_block(deal):
    """Блок «— Приход —» для уведомлений. Пусто у сделки с одним каналом.

    Один и тот же во всех трёх шаблонах: получатель должен видеть, откуда
    сложился приход, независимо от типа сделки.
    """
    parts = _payin_all_parts(deal)
    if len(parts) < 2:
        return ''
    out = f"\n— Приход ({len(parts)}) —"
    for p in parts:
        name = PAYIN_METHOD_LABELS.get(p['method'], p['method'] or '—')
        if p['partner_name']:
            name += f" {p['partner_name']}"
        if p['amount_rub'] and p['rate_rub_usdt']:
            out += (f"\n• {name} · {p['amount_rub']:,.0f} ₽ @ {p['rate_rub_usdt']:.4f}"
                    f" → ${p['amount_usdt']:,.2f}")
        else:
            out += f"\n• {name} → ${p['amount_usdt']:,.2f}"
    return out


def _mf_realty_telegram_text(deal):
    """Текст уведомления по сделке через MF Corp.

    У обычной сделки один карман, здесь два — поэтому общий шаблон не подходит:
    он показал бы «Выдано: 0 THB» (инвойс лежит в другом поле) и «чистую нашу»
    без указания, что часть суммы заперта в батах на счёте компании.
    """
    date_str = deal.created_at.strftime('%d.%m.%Y') if deal.created_at else ''
    client = (deal.client.name if deal.client else deal.client_name) or 'без имени'
    fee_usdt = deal.company_fee_usdt or 0
    crypto = deal.crypto_remainder_usdt or 0
    msg = (
        f"🏠 <b>Недвижимость {deal.id} — {client} — {date_str}</b>\n"
        f"{deal.realty_purpose or ''}\n"
        f"Приход: ${deal.payin_amount_usdt or 0:,.2f}"
        f"{_payin_parts_block(deal)}\n"
        f"Отправлено в MF Corp: {deal.company_sent_thb or 0:,.0f} ฿ "
        f"(${deal.payout_amount_usdt or 0:,.2f})\n"
        f"— инвойс застройщику: {deal.invoice_amount_thb or 0:,.0f} ฿\n"
        f"— комиссия компании: {deal.company_fee_thb or 0:,.0f} ฿ "
        f"(${fee_usdt:,.2f}, {deal.company_percent or 0:.2f}%)"
    )
    # Куда и сколько реально ушло — чтобы отправку можно было сверить, не заходя в CRM
    payout_parts = []
    if deal.payout_tx_hashes:
        try:
            payout_parts = json.loads(deal.payout_tx_hashes)
        except (ValueError, TypeError):
            payout_parts = []
    if payout_parts:
        msg += f"\n— Переводы ({len(payout_parts)}) —"
        for pt in payout_parts:
            addr = (pt.get('to_address') or '')[:10]
            msg += f"\n• ${float(pt.get('amount_usdt') or 0):,.2f}"
            if addr:
                msg += f" → {addr}…"
            if pt.get('date'):
                msg += f" · {pt['date']}"
        total_sent = sum(float(pt.get('amount_usdt') or 0) for pt in payout_parts)
        msg += f"\nИтого ушло: ${total_sent:,.2f}"
    agents = sorted(deal.agents, key=lambda x: (x.tier or 1, x.id or 0)) if deal.agents else []
    if agents:
        labels = {'markup': 'от курса', 'fixed': 'фикс',
                  'revshare': 'от прибыли', 'crypto_share': 'от прибыли в крипте'}
        msg += "\n— Партнёры —"
        for a in agents:
            lbl = labels.get(a.comp_model, a.comp_model or '')
            pct = f"{a.percent or 0}% " if a.comp_model != 'fixed' else ''
            msg += f"\n• Ур.{a.tier or 1} {a.name or '-'} · {pct}{lbl} → ${a.payout_usdt or 0:,.2f}"
        msg += f"\nВыплаты партнёрам: ${deal.referrer_payout_usdt or 0:,.2f}"
    # Доход компании — в батах: именно баты лежат на счёте MF Corp, доллар тут
    # только пересчёт для сводной цифры (иначе кажется, что всё в крипте)
    msg += (
        f"\n\n💰 <b>Чистый доход: ${deal.net_profit_usdt or 0:,.2f}</b>\n"
        f"   на кошельке ${crypto:,.2f} · в компании {deal.company_fee_thb or 0:,.0f} ฿ (${fee_usdt:,.2f})"
    )
    return msg


def _mf_freehold_telegram_text(deal):
    """Текст уведомления по сделке во фрихолде.

    Главное, чего нет в общем шаблоне: сколько съел перевод и сколько РЕАЛЬНО
    дойдёт до застройщика. Прибыль здесь тонкая (сотни долларов на десятки
    тысяч), поэтому расход показываем строкой, а не прячем в себестоимость.
    """
    date_str = deal.created_at.strftime('%d.%m.%Y') if deal.created_at else ''
    client = (deal.client.name if deal.client else deal.client_name) or 'без имени'
    sent = deal.transfer_sent_usd or 0
    arrive = deal.transfer_arrive_usd or 0
    fee = deal.transfer_fee_usd or 0
    invoice = deal.invoice_amount_usd or 0
    msg = (
        f"🏠 <b>Фрихолд {deal.id} — {client} — {date_str}</b>\n"
        f"{deal.realty_purpose or ''}\n"
        f"Приход: ${deal.payin_amount_usdt or 0:,.2f}"
        f"{_payin_parts_block(deal)}\n"
        f"Отправлено: ${sent:,.2f}\n"
        f"— комиссия за перевод: ${fee:,.2f} "
        f"({deal.transfer_fee_percent or 0:.2f}% + ${deal.transfer_fee_fixed_usd or 0:,.0f})\n"
        f"— дойдёт застройщику: ${arrive:,.2f}"
    )
    gap = round(arrive - invoice, 2) if invoice else 0
    if gap < -0.01:
        msg += f"\n⚠️ Инвойс ${invoice:,.2f} — не хватает ${-gap:,.2f}"
    # Куда и сколько реально ушло — отправку сверяют по этим переводам
    payout_parts = []
    if deal.payout_tx_hashes:
        try:
            payout_parts = json.loads(deal.payout_tx_hashes)
        except (ValueError, TypeError):
            payout_parts = []
    if payout_parts:
        msg += f"\n— Переводы ({len(payout_parts)}) —"
        for pt in payout_parts:
            addr = (pt.get('to_address') or '')[:10]
            msg += f"\n• ${float(pt.get('amount_usdt') or 0):,.2f}"
            if addr:
                msg += f" → {addr}…"
            if pt.get('date'):
                msg += f" · {pt['date']}"
    agents = sorted(deal.agents, key=lambda x: (x.tier or 1, x.id or 0)) if deal.agents else []
    if agents:
        labels = {'markup': 'от курса', 'fixed': 'фикс',
                  'revshare': 'от прибыли', 'crypto_share': 'от прибыли в крипте'}
        msg += "\n— Партнёры —"
        for a in agents:
            lbl = labels.get(a.comp_model, a.comp_model or '')
            pct = f"{a.percent or 0}% " if a.comp_model != 'fixed' else ''
            msg += f"\n• Ур.{a.tier or 1} {a.name or '-'} · {pct}{lbl} → ${a.payout_usdt or 0:,.2f}"
        msg += f"\nВыплаты партнёрам: ${deal.referrer_payout_usdt or 0:,.2f}"
    msg += (
        f"\n\n💰 <b>Чистый доход: ${deal.net_profit_usdt or 0:,.2f}</b>\n"
        f"   прибыль до выплат ${deal.profit_usdt or 0:,.2f} (после расходов на перевод)"
    )
    return msg


def _send_deal_telegram(deal):
    """Отправляет уведомление о сделке в Telegram"""
    if getattr(deal, 'is_test', False):
        print(f'[TG] Skip notify: deal #{deal.id} is test')
        return
    if deal.deal_kind == MF_REALTY_KIND:
        return send_telegram_notification(_mf_realty_telegram_text(deal))
    if deal.deal_kind == MF_FREEHOLD_KIND:
        return send_telegram_notification(_mf_freehold_telegram_text(deal))
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

    # Откуда выдали: без этого «Выдано 19 652 THB» не говорит, чьи это баты —
    # карта уже откуплена, а наличные фаундера ещё ждут возмещения
    source_note = ''
    if deal.payout_source == PayOutSource.BANK_CARD and deal.bank_card:
        source_note = f" · с карты {deal.bank_card.bank_name}"
    elif deal.payout_source == PayOutSource.FOUNDER_PERSONAL and deal.payout_founder_name:
        source_note = f" · личные {deal.payout_founder_name}"
    elif deal.payout_source == PayOutSource.CASH_BATCH:
        source_note = ' · из кассы'

    # При смешанных валютах частей строка «Получено» в рублях занижает — у
    # крипто-части рублей нет. Тогда печатаем итог в USDT, разбивка идёт ниже.
    _parts = _payin_all_parts(deal)
    _mixed = len(_parts) > 1 and any(
        bool(p['amount_rub']) != bool(_parts[0]['amount_rub']) for p in _parts)
    received_line = (f"Получено: ${amount_in_usdt:,.2f} (несколько каналов)"
                     if _mixed
                     else f"Получено: {amount_in:,.2f} {currency} (${amount_in_usdt:,.2f})")

    msg = (
        f"✅ <b>Сделка {deal.id} — {(deal.client.name if deal.client else deal.client_name) or 'без имени'} — {date_str}</b>\n"
        f"{received_line}"
        f"{_payin_parts_block(deal)}\n"
        f"Выдано: {payout_val:,} {payout_cur} (${payout_usdt:,.2f}){source_note}\n"
        f"Прибыль: ${profit:,.2f}"
    )
    # Блок агентов (мультиагенты) + чистая прибыль
    agents = sorted(deal.agents, key=lambda x: (x.tier or 1, x.id or 0)) if deal.agents else []
    if agents:
        msg += "\n— Агенты —"
        for a in agents:
            if a.comp_model == 'markup':
                lbl = f"markup +{a.percent or 0}%"
            elif a.comp_model == 'fixed':
                lbl = f"fixed ${a.fixed_usdt or 0:,.2f}"
            else:
                lbl = f"revshare {a.percent or 0}%"
            msg += f"\n• Ур.{a.tier or 1} {a.name or '-'} · {lbl} → ${a.payout_usdt or 0:,.2f}"
        total_agents = sum(a.payout_usdt or 0 for a in agents)
        net = deal.net_profit_usdt if deal.net_profit_usdt is not None else round(profit - total_agents, 2)
        msg += (
            f"\nВыплаты агентам: ${total_agents:,.2f}\n"
            f"💰 <b>Чистая наша: ${net:,.2f}</b>"
        )
    elif deal.referrer_id:
        if deal.referrer_comp_model == 'markup':
            ref_label = f"markup +{deal.referrer_markup_percent or 0}%"
            ref_payout = deal.referrer_payout_usdt or round((max(deal.payin_amount_usdt or 0, payout_usdt)) * ((deal.referrer_markup_percent or 0) / 100), 2)
        elif deal.referrer_comp_model == 'fixed':
            ref_label = f"fixed ${deal.referrer_fixed_usdt or 0}"
            ref_payout = deal.referrer_payout_usdt or deal.referrer_fixed_usdt or 0
        else:
            ref_label = f"revshare {deal.referrer_percent or 0}%"
            ref_payout = deal.referrer_payout_usdt or round(profit * (deal.referrer_percent or 0) / 100, 2)
        net = deal.net_profit_usdt if deal.net_profit_usdt is not None else round(profit - ref_payout, 2)
        msg += (
            f"\nРеферер: {deal.referrer_name or '-'} · {ref_label}\n"
            f"К выплате рефереру: ${ref_payout:,.2f}\n"
            f"💰 <b>Чистая наша: ${net:,.2f}</b>"
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
    if not WEBHOOK_URL or getattr(deal, 'is_test', False):
        return
    data = {
        'event': 'deal_completed',
        'timestamp': datetime.now().isoformat(),
        'deal': deal.to_dict()
    }
    send_webhook_async(WEBHOOK_URL, data)

# ==================== CALCULATOR IMPORTS ====================
from calculator import (ExchangeRateProvider, ExchangeCalculator, playwright_queue,
                        WITHDRAWAL_PCT_BINANCE, WITHDRAWAL_PCT_BITAZZA, WITHDRAWAL_FIXED_THB)
# Курс партнёрских ссылок — другие рельсы (Rapira + Bitazza), не путать с calculator
import partner_rates

# ==================== AUTH ====================

@app.route('/login', methods=['GET'])
def login_page():
    """Страница входа"""
    # Локальный стенд без логина — форма входа там только мешает
    if os.environ.get('LOCAL_NO_AUTH') == '1' and 'postgresql' not in DATABASE_URL:
        return redirect('/crm')
    if flask_session.get('user_id'):
        return redirect('/crm')
    return send_from_directory('static/auth', 'login.html')


def _match_admin_by_tg(db, tg_id, tg_username):
    """Находит админа по привязанному id, иначе по @username (trust-on-first-login → бинд id)."""
    tg_id = int(tg_id)
    admin = db.query(AdminUser).filter(AdminUser.telegram_user_id == tg_id).first()
    if admin:
        return admin
    uname = (tg_username or '').lstrip('@').strip().lower()
    if not uname:
        return None
    for a in db.query(AdminUser).filter(AdminUser.telegram_user_id.is_(None)).all():
        if (a.telegram or '').lstrip('@').strip().lower() == uname:
            a.telegram_user_id = tg_id
            db.commit()
            return a
    return None


@app.route('/api/auth/tg-config', methods=['GET'])
def auth_tg_config():
    """Публичный: bot_id/username для виджета входа на /login."""
    return jsonify({'bot_id': get_login_bot_id(), 'bot_username': get_bot_username()})


@app.route('/api/auth/tg-login', methods=['POST'])
@limiter.limit("10/minute")
def auth_tg_login():
    """Passwordless вход админа через Telegram Login Widget."""
    data = request.get_json(silent=True) or {}
    if not verify_telegram_auth(data, get_login_bot_token()):
        return jsonify({'success': False, 'error': 'Подпись Telegram недействительна или устарела'}), 403
    db = get_session()
    try:
        admin = _match_admin_by_tg(db, data.get('id'), data.get('username'))
        if not admin:
            return jsonify({'success': False, 'error': 'Этот Telegram не в списке администраторов'}), 403
        flask_session['user_id'] = admin.id
        flask_session['username'] = admin.username
        flask_session['display_name'] = admin.display_name or admin.username
        flask_session.permanent = True
        return jsonify({'success': True, 'user': admin.display_name or admin.username})
    finally:
        db.close()


LOGIN_NONCE_TTL_SEC = 300  # 5 минут на подтверждение входа через бота


@app.route('/api/auth/tg-start', methods=['POST'])
@limiter.limit("10/minute")
def auth_tg_start():
    """Вход через бота: генерит одноразовый nonce и deep-link на @grusha_lk_bot.
    Юзер открывает бота в приложении Telegram (сам выбирает аккаунт) и жмёт Start."""
    import secrets as _secrets
    nonce = _secrets.token_urlsafe(24)
    db = get_session()
    try:
        # Чистим протухшие, чтобы таблица не росла
        cutoff = datetime.utcnow() - timedelta(seconds=LOGIN_NONCE_TTL_SEC * 2)
        db.query(LoginNonce).filter(LoginNonce.created_at < cutoff).delete()
        db.add(LoginNonce(nonce=nonce))
        db.commit()
    finally:
        db.close()
    bot = get_bot_username()
    if not bot:
        return jsonify({'success': False, 'error': 'Бот недоступен'}), 503
    return jsonify({'success': True, 'nonce': nonce,
                    'link': f'https://t.me/{bot}?start=login_{nonce}'})


@app.route('/api/auth/tg-poll', methods=['GET'])
@limiter.limit("60/minute")
def auth_tg_poll():
    """Поллинг браузером: бот подтвердил вход? Выдаёт сессию один раз."""
    nonce = (request.args.get('nonce') or '').strip()
    if not nonce:
        return jsonify({'success': False, 'error': 'nonce required'}), 400
    db = get_session()
    try:
        ln = db.query(LoginNonce).get(nonce)
        if not ln or ln.used:
            return jsonify({'success': False, 'status': 'invalid'}), 404
        if (datetime.utcnow() - (ln.created_at or datetime.utcnow())).total_seconds() > LOGIN_NONCE_TTL_SEC:
            return jsonify({'success': False, 'status': 'expired'})
        if ln.denied:
            return jsonify({'success': False, 'status': 'denied',
                            'error': 'Этот Telegram не в списке администраторов'})
        if not ln.admin_id:
            return jsonify({'success': False, 'status': 'pending'})
        admin = db.query(AdminUser).get(ln.admin_id)
        if not admin:
            return jsonify({'success': False, 'status': 'denied'})
        ln.used = True
        db.commit()
        flask_session['user_id'] = admin.id
        flask_session['username'] = admin.username
        flask_session['display_name'] = admin.display_name or admin.username
        flask_session.permanent = True
        return jsonify({'success': True, 'status': 'ok',
                        'user': admin.display_name or admin.username})
    finally:
        db.close()


@app.route('/api/admins', methods=['GET'])
def list_admins():
    """Список админов (whitelist Telegram-входа)"""
    db = get_session()
    try:
        return jsonify({'success': True, 'admins': [a.to_dict() for a in db.query(AdminUser).order_by(AdminUser.id).all()]})
    finally:
        db.close()


@app.route('/api/admins', methods=['POST'])
def create_admin():
    """Добавление нового админа в whitelist (пароль случайный — вход только через Telegram)"""
    import secrets, re
    data = request.get_json() or {}
    display_name = (data.get('display_name') or '').strip()
    telegram = (data.get('telegram') or '').strip()
    if not display_name:
        return jsonify({'success': False, 'error': 'Укажите имя'}), 400
    if not telegram:
        return jsonify({'success': False, 'error': 'Укажите Telegram (@username)'}), 400
    db = get_session()
    try:
        base = re.sub(r'[^A-Za-z0-9_]', '', telegram.lstrip('@')) or f'admin{secrets.token_hex(2)}'
        username = base; i = 1
        while db.query(AdminUser).filter_by(username=username).first():
            i += 1; username = f'{base}{i}'
        admin = AdminUser(
            username=username, display_name=display_name,
            password_hash=AdminUser.hash_password(secrets.token_hex(16)),  # случайный — пароль-вход отключён
            telegram=telegram,
        )
        db.add(admin); db.commit()
        return jsonify({'success': True, 'admin': admin.to_dict()})
    finally:
        db.close()


@app.route('/api/admins/<int:admin_id>', methods=['PUT'])
def update_admin(admin_id):
    """Правка имени/telegram админа. Смена telegram сбрасывает привязку id — перепривязка при следующем входе."""
    data = request.get_json() or {}
    db = get_session()
    try:
        admin = db.query(AdminUser).get(admin_id)
        if not admin:
            return jsonify({'success': False, 'error': 'Админ не найден'}), 404
        if 'display_name' in data:
            admin.display_name = (data['display_name'] or '').strip()
        if 'telegram' in data:
            admin.telegram = (data['telegram'] or '').strip()
            admin.telegram_user_id = None  # смена username → перепривязка при следующем входе
        db.commit()
        return jsonify({'success': True, 'admin': admin.to_dict()})
    finally:
        db.close()


@app.route('/api/admins/<int:admin_id>', methods=['DELETE'])
def delete_admin(admin_id):
    """Удаление админа из whitelist. Нельзя удалить последнего — иначе никто не сможет войти."""
    db = get_session()
    try:
        if db.query(AdminUser).count() <= 1:
            return jsonify({'success': False, 'error': 'Нельзя удалить последнего админа'}), 400
        admin = db.query(AdminUser).get(admin_id)
        if not admin:
            return jsonify({'success': False, 'error': 'Админ не найден'}), 404
        db.delete(admin); db.commit()
        return jsonify({'success': True})
    finally:
        db.close()


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
    """Первоначальная настройка — создание админа (только если нет ни одного пользователя).

    CR-08: защита от race-условия. Раньше два параллельных запроса в окне < 100мс
    могли оба пройти проверку `existing = first()` и создать двух админов.
    Защита:
      1. Postgres advisory lock на время транзакции (no-op на SQLite, где
         writes сериализуются engine'ом).
      2. Повторная проверка count() ПОСЛЕ блокировки.
      3. UNIQUE(username) на admin_users (есть в модели) — defense-in-depth.
    """
    if os.environ.get('SETUP_ENABLED') != 'true':
        return jsonify({'success': False, 'error': 'Setup отключён'}), 403
    db = get_session()
    try:
        # 1) Advisory lock (только на Postgres). Любой setup-запрос ждёт, пока
        # предыдущий завершится. Произвольный 64-битный ключ.
        from sqlalchemy import text as _sql_text
        try:
            if db.bind and db.bind.dialect.name == 'postgresql':
                db.execute(_sql_text('SELECT pg_advisory_xact_lock(:k)'), {'k': 7423891234567890})
        except Exception as e:
            app.logger.warning(f'auth_setup: advisory lock failed (продолжаем без него): {e}')

        # 2) Проверка под локом — теперь между check и insert никто не вклинится
        if db.query(AdminUser).count() > 0:
            return jsonify({'success': False, 'error': 'Админ уже создан'}), 403

        data = request.get_json() or {}
        username = data.get('username', '').strip()
        password = data.get('password', '')
        display_name = data.get('display_name', '').strip()

        if not username or not password:
            return jsonify({'success': False, 'error': 'Укажите логин и пароль'}), 400

        # CR-08: подняли минимальную длину до 12 (раньше — 8). admin/test1234
        # был как раз на границе; новые пароли — длиннее.
        if len(password) < 12:
            return jsonify({'success': False, 'error': 'Пароль минимум 12 символов'}), 400

        admin = AdminUser(
            username=username,
            password_hash=AdminUser.hash_password(password),
            display_name=display_name or username,
            role='admin'
        )
        db.add(admin)
        try:
            db.commit()
        except Exception as e:
            # 3) Defense-in-depth: если по какой-то причине гонка прорвалась
            # сквозь advisory lock (например, lock не сработал) — UNIQUE(username)
            # отлавливает дубликат на уровне БД.
            db.rollback()
            app.logger.warning(f'auth_setup: commit failed (возможно race): {e}')
            return jsonify({'success': False, 'error': 'Setup race detected'}), 409

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

# Комиссии Bitazza для калькулятора (позже переедут в настройки CRM)
CALC_BITAZZA_FEE_PCT = 0.0015     # 0.15% комиссия биржи
CALC_BITAZZA_FEE_FIXED_THB = 20   # фикс за вывод, ฿ (разово со сделки)
CALC_BITAZZA_QUOTE_VOLUME = 1000  # номинальный объём USDT для карточки курса


def _estimate_usdt_volume(scenario, direction, amount, rates):
    """Прикидка объёма сделки в USDT — на неё считаем VWAP стакана Bitazza.

    `amount` в разных сценариях приходит в разной валюте, поэтому сначала
    определяем единицу, потом переводим в USDT по текущим курсам. Точность
    тут не критична: нужен порядок величины, чтобы взять реальную глубину
    стакана, а не номинальную 1000 USDT.
    """
    ut = rates.get('usdt_thb') or 0
    ru = rates.get('rub_usdt') or 0
    unit = {
        ('rub-to-thb', 'amount'): 'RUB', ('rub-to-thb', 'target'): 'THB',
        ('rub-to-usdt', 'amount'): 'RUB', ('rub-to-usdt', 'target'): 'USDT',
        ('usdt-to-thb', 'amount'): 'USDT', ('usdt-to-thb', 'target'): 'THB',
        ('thb-to-usdt', 'amount'): 'THB', ('thb-to-usdt', 'target'): 'USDT',
    }.get((scenario, direction), 'USDT')
    try:
        if unit == 'USDT':
            vol = float(amount)
        elif unit == 'RUB':
            vol = float(amount) / ru if ru else 0
        else:  # THB
            vol = float(amount) / ut if ut else 0
    except (TypeError, ValueError, ZeroDivisionError):
        vol = 0
    return vol if vol > 0 else CALC_BITAZZA_QUOTE_VOLUME


def _bitazza_calc_quote(usdt_amount=CALC_BITAZZA_QUOTE_VOLUME):
    """Курс Bitazza для калькулятора: VWAP по bids на объём × (1 − 0.15%).

    Фикс 20฿ здесь НЕ вычитается — он разовый на сделку, применяется в расчёте.
    None — стакан недоступен или объём не покрыт.
    """
    bids = _bitazza_bids()
    if not bids or not usdt_amount or usdt_amount <= 0:
        return None
    remaining, thb = usdt_amount, 0.0
    for price, qty in bids:
        take = min(remaining, qty)
        thb += take * price
        remaining -= take
        if remaining <= 0:
            break
    if remaining > 0:
        return None
    vwap = thb / usdt_amount
    return {'raw_vwap': round(vwap, 4),
            'effective': round(vwap * (1 - CALC_BITAZZA_FEE_PCT), 4)}


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
        # Bitazza — второй источник USDT/THB; его недоступность не роняет ответ
        bz = None
        try:
            bz = _bitazza_calc_quote()
        except Exception as e:
            app.logger.warning(f'Bitazza rate error: {e}')
        return jsonify({
            'usdt_thb': usdt_thb,
            'rub_usdt': rub_usdt,
            'bitazza_usdt_thb': bz['effective'] if bz else None,
            'bitazza_raw': bz['raw_vwap'] if bz else None,
            'bitazza_fee_percent': CALC_BITAZZA_FEE_PCT * 100,
            'bitazza_fee_fixed_thb': CALC_BITAZZA_FEE_FIXED_THB,
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

        # Парсим точный курс — через приоритетную очередь (priority=1 → CRM)
        playwright_result = playwright_queue.submit(
            lambda: ExchangeRateProvider.get_precise_binance_rate(
                usdt_amount=usdt_amount_for_parsing,
                thb_amount=thb_amount_for_parsing,
                direction=playwright_direction
            ),
            priority=1,
            timeout=60
        )

        if playwright_result.get('error') == 'queue_timeout':
            print(f"⚠️ Playwright queue timeout (60s) — отказ клиенту", flush=True)
            return jsonify({'success': False, 'error': 'queue_timeout'}), 503

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

        # Источник курса USDT-THB: bitazza (стакан по API) | binance | custom (ручной).
        # От него зависит и комиссия площадки за выдачу: Bitazza 0.15%, Binance 0.25%.
        rate_source = str(data.get('rate_source') or 'binance').lower()
        withdrawal_pct = WITHDRAWAL_PCT_BINANCE

        # Если передан точный курс USDT-THB (от Playwright), используем его
        custom_usdt_thb = data.get('custom_usdt_thb')
        if custom_usdt_thb:
            rates['usdt_thb'] = float(custom_usdt_thb)
            print(f"🎯 Использую точный курс USDT-THB: {rates['usdt_thb']:.4f}", flush=True)

        if rate_source == 'bitazza':
            # VWAP считаем на реальный объём сделки — на крупных суммах стакан «съедается»
            # и курс отличается от номинальной карточки.
            bz = _bitazza_calc_quote(_estimate_usdt_volume(scenario, direction, amount, rates))
            if bz:
                # raw VWAP: комиссию биржи 0.15% вычитаем ниже как комиссию за выдачу,
                # иначе она удержится дважды.
                rates['usdt_thb'] = bz['raw_vwap']
                withdrawal_pct = WITHDRAWAL_PCT_BITAZZA
            else:
                # Стакан недоступен — честно откатываемся на Binance вместе с его комиссией
                rate_source = 'binance'

        # Мягкая деградация: если биржа недоступна, курс = None → не роняем расчёт
        # в 500, а честно отвечаем 503. USDT-THB нужен всем сценариям.
        if rates.get('usdt_thb') is None:
            return jsonify({'error': 'Курс USDT-THB временно недоступен, попробуйте позже'}), 503
        # RUB-USDT нужен только стандартному калькулятору в RUB-сценариях
        # (брокер использует custom_rub_usdt с дефолтом).
        if method != 'broker' and scenario in ('rub-to-thb', 'rub-to-usdt') and rates.get('rub_usdt') is None:
            return jsonify({'error': 'Курс RUB-USDT временно недоступен, попробуйте позже'}), 503

        if method == 'broker':
            from broker_detailed import BrokerCalculatorDetailed
            custom_rub_usdt_raw = data.get('custom_rub_usdt')
            custom_rub_usdt = float(custom_rub_usdt_raw) if custom_rub_usdt_raw not in (None, '', 0) else 80.9
            pm_raw = data.get('profit_margin')
            profit_margin = float(pm_raw) if pm_raw not in (None, '') else 4.0
            broker_calc = BrokerCalculatorDetailed(rates['usdt_thb'], custom_rub_usdt, profit_margin,
                                                   withdrawal_percent=withdrawal_pct,
                                                   withdrawal_fixed=WITHDRAWAL_FIXED_THB)
            
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
            calculator = ExchangeCalculator(rates['usdt_thb'], rates['rub_usdt'],
                                            withdrawal_percent=withdrawal_pct,
                                            withdrawal_fixed=WITHDRAWAL_FIXED_THB)
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
        
        # Floor-guard: при слишком малой сумме выдача уходит в 0/минус, а
        # safe_rate возвращает 0 или курс становится отрицательным. Не отдаём
        # менеджеру бессмысленный расчёт — возвращаем понятную ошибку.
        if result.get('final_rate', 0) <= 0:
            return jsonify({'error': 'Сумма слишком мала для расчёта'}), 400

        # Откуда курс и по какой ставке считали выдачу — фронт подписывает этим
        # строку «Комиссия за выдачу (0,15%)» вместо захардкоженных 0,25%.
        result['rate_source'] = rate_source
        result['withdrawal_percent_rate'] = round(withdrawal_pct * 100, 3)

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
    from sqlalchemy.orm import joinedload, selectinload
    session = get_session()
    try:
        # selectinload(agents): to_dict сериализует agents — без предзагрузки
        # каждая сделка страницы делала отдельный SELECT (N+1, +50 запросов)
        query = session.query(Deal).options(
            joinedload(Deal.client), joinedload(Deal.reimbursement), selectinload(Deal.agents)
        ).order_by(Deal.created_at.desc(), Deal.id.desc())
        status = request.args.get('status')
        if status:
            query = query.filter(Deal.status == DealStatus(status))
        elif request.args.get('include_lose') != '1':
            # LOSE и «не обращение» — аналитические записи, в основном списке
            # сделок не показываем (достать можно фильтром по статусу)
            query = query.filter(Deal.status.notin_(NON_DEAL_STATUSES))
        # Демо-сделки тестового реферера в CRM не показываем (?include_test=1 — вернуть)
        if request.args.get('include_test') != '1':
            query = query.filter(Deal.is_test.isnot(True))
        manager = request.args.get('manager')
        if manager:
            query = query.filter(Deal.manager_name.ilike(f'%{manager}%'))
        referrer_id = request.args.get('referrer_id')
        if referrer_id:
            query = query.filter(Deal.referrer_id == int(referrer_id))
        date_from = request.args.get('date_from')
        if date_from:
            query = query.filter(Deal.created_at >= datetime.strptime(date_from, '%Y-%m-%d'))
        date_to = request.args.get('date_to')
        if date_to:
            # Включаем весь день date_to
            query = query.filter(Deal.created_at < datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1))
        # Поиск: номер сделки или кусок имени клиента / реферера / менеджера.
        # Без него «найди сделки Сергея» = выкачать все страницы и грепать локально.
        q = (request.args.get('q') or '').strip()
        if q:
            if q.isdigit():
                query = query.filter(Deal.id == int(q))
            elif session.bind.dialect.name == 'postgresql':
                like = f'%{q}%'
                query = query.filter(or_(
                    Deal.client_name.ilike(like),
                    Deal.referrer_name.ilike(like),
                    Deal.manager_name.ilike(like),
                ))
            else:
                # SQLite (локальный стенд, тесты): ilike не понижает кириллицу —
                # отбираем id в Python, чтобы поиск вёл себя как на проде.
                q_cf = q.casefold()
                rows = session.query(
                    Deal.id, Deal.client_name, Deal.referrer_name, Deal.manager_name
                ).all()
                matched = [r[0] for r in rows
                           if any(v and q_cf in v.casefold() for v in r[1:])]
                query = query.filter(Deal.id.in_(matched))
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

def _card_avg_rate(card):
    """Средневзвешенный курс закупки карты, THB за 1 USDT.

    Считается по всем её пополнениям: сколько бат завели и во что они обошлись.
    Это база себестоимости любой выдачи с этой карты.
    """
    total_thb = sum(t.amount_thb for t in card.topups) if card.topups else 0
    total_usdt = sum(t.cost_usdt for t in card.topups) if card.topups else 0
    return total_thb / total_usdt if total_usdt > 0 else 0


def _sync_card_allocation(session, deal):
    """Держит расход по карте в согласии со сделкой.

    Выдача с карты — единственное движение, которого карта раньше не видела:
    баланс рос от пополнений и не уменьшался никогда. Функция идемпотентна —
    зовётся и при создании, и при каждом обновлении: сначала возвращает деньги
    туда, откуда их сняли в прошлый раз, потом списывает заново по текущему
    состоянию сделки. Поэтому смена карты, суммы или уход сделки в LOSE
    отрабатывают сами, без отдельных веток.

    Возвращает текст предупреждения, если карте не хватило. В минус пускаем
    сознательно: остаток в CRM ведёт человек и он отстаёт от факта, а
    блокировать закрытие уже состоявшейся выдачи из-за этого нельзя.
    """
    for alloc in session.query(CardAllocation).filter(CardAllocation.deal_id == deal.id).all():
        card = session.query(BankCard).filter(BankCard.id == alloc.card_id).with_for_update().first()
        if card:
            card.balance_thb = round((card.balance_thb or 0) + alloc.amount_thb, 2)
        session.delete(alloc)
    session.flush()

    needs_allocation = (
        deal.payout_source == PayOutSource.BANK_CARD
        and deal.bank_card_id
        and (deal.payout_amount_thb or 0) > 0
        and deal.status not in NON_DEAL_STATUSES + (DealStatus.CANCELLED,)
    )
    if not needs_allocation:
        return None

    card = session.query(BankCard).filter(BankCard.id == deal.bank_card_id).with_for_update().first()
    if not card:
        return f'Карта #{deal.bank_card_id} не найдена — расход по сделке не списан'

    amount_thb = round(deal.payout_amount_thb, 2)
    rate = _card_avg_rate(card)
    # Курса нет только у карты без пополнений — тогда берём себестоимость,
    # посчитанную формой, чтобы не записать нулевую стоимость выдачи
    cost_usdt = round(amount_thb / rate, 2) if rate else round(deal.payout_amount_usdt or 0, 2)
    session.add(CardAllocation(
        deal_id=deal.id, card_id=card.id, amount_thb=amount_thb,
        cost_usdt=cost_usdt, card_rate=round(rate, 4),
    ))
    card.balance_thb = round((card.balance_thb or 0) - amount_thb, 2)
    # Себестоимость выдачи = курс карты. Форма её показывает, но не отправляет
    # (поле readonly и без name), из-за чего payout_amount_usdt оставался пустым:
    # карточка писала «Ожидает возмещения», а Telegram слал $0.00
    if rate:
        deal.payout_amount_usdt = cost_usdt
        deal.cash_batch_rate = round(rate, 4)
    if card.balance_thb < 0:
        return (f'Остаток карты «{card.bank_name}» ушёл в минус: '
                f'{card.balance_thb:,.2f} THB — проверьте пополнения')
    return None


def _clear_profit_if_payin_unknown(deal):
    """Приход ещё не пересчитан в USDT — прибыли не существует, а не «минус».

    Форма (и любой старый клиент из кэша) присылает profit_usdt = 0 − выдача:
    по #519 это −319.20, по #522 −700.96, оба с profit_percent −100. Выглядит
    как проваленная сделка, хотя неизвестна одна нога: рубли по СБП уходят
    в USDT позже. Держим пусто, пока приход не проставят — тогда
    _recalculate_deal_financials посчитает по-настоящему.
    """
    if deal.payout_amount_usdt and not deal.payin_amount_usdt:
        deal.profit_usdt = None
        deal.profit_percent = None
        deal.net_profit_usdt = None
        deal.referrer_payout_usdt = None


def _recalculate_deal_financials(deal, data):
    """Пересчитывает прибыль, выплату рефереру и чистую прибыль сделки.

    Используется и при создании, и при обновлении: гарантирует, что
    referrer_payout_usdt и net_profit_usdt всегда согласованы с моделью
    вознаграждения (revshare / markup / fixed), даже если фронт не передал
    их явно (например, реферер был привязан автоматически через клиента).

    Если data содержит явный referrer_payout_usdt — он сохраняется как есть.
    """
    if not (deal.payin_amount_usdt and deal.payout_amount_usdt):
        return
    deal.profit_usdt = round(deal.payin_amount_usdt - deal.payout_amount_usdt, 2)
    deal.profit_percent = round((deal.profit_usdt / deal.payout_amount_usdt * 100), 2) if deal.payout_amount_usdt > 0 else 0
    if not data.get('referrer_payout_usdt'):
        if deal.referrer_comp_model == 'markup' and deal.referrer_markup_percent:
            # markup: reward = markup% × объём USDT (макс из payin/payout USDT)
            volume_usdt = max(deal.payin_amount_usdt or 0, deal.payout_amount_usdt or 0)
            deal.referrer_payout_usdt = round(volume_usdt * (deal.referrer_markup_percent / 100), 2)
        elif deal.referrer_comp_model == 'fixed' and deal.referrer_fixed_usdt:
            # fixed: фиксированная выплата USDT
            deal.referrer_payout_usdt = round(deal.referrer_fixed_usdt, 2)
        elif deal.referrer_percent:
            deal.referrer_payout_usdt = round(deal.profit_usdt * deal.referrer_percent / 100, 2)
    referrer_payout = deal.referrer_payout_usdt or 0
    deal.net_profit_usdt = round(deal.profit_usdt - referrer_payout, 2)


def db_referrer_names(session, names_lower):
    """Активные рефереры, чьё имя совпало с одним из переданных (без учёта регистра)."""
    if not names_lower:
        return []
    rows = session.query(Referrer.id, Referrer.name).filter(Referrer.active == True).all()
    return [(rid, rname) for rid, rname in rows
            if rname and rname.strip().lower() in names_lower]


def _apply_deal_agents(session, deal, agents_data):
    """Сохраняет агентов сделки (мультиагенты) и пересчитывает выплаты каскадом.

    agents_data — список dict: {referrer_id, name, tier, comp_model, percent, fixed_usdt}.
    Обновляет deal.net_profit_usdt, deal.referrer_payout_usdt (СУММА всех агентов)
    и кэш ур.1 (referrer_id/name/percent/comp_model) для legacy-отображений.
    Статус paid сохраняется по совпадению referrer_id+tier.
    """
    # запоминаем кто уже выплачен (чтобы не сбросить при пересохранении)
    prev_paid = {(r.referrer_id, r.tier or 1): (r.paid or False, r.paid_at, r.paid_note) for r in deal.agents}
    deal.agents.clear()  # delete-orphan удалит старые строки на flush
    # Сделки через MF Corp: комиссия заперта в батах на счёте компании и в
    # profit_usdt уже не входит (там только крипта) — она и есть база crypto_share.
    # Фрихолд идёт обычной веткой: карман один, а profit_usdt там уже посчитан
    # после всех расходов на перевод — именно он и есть база выплат агентам.
    is_mf = deal.deal_kind == MF_REALTY_KIND
    crypto_base = (deal.profit_usdt or 0) if is_mf else None
    # revshare — «% от ПРИБЫЛИ», а прибыль MF-сделки лежит в двух карманах:
    # крипта (profit_usdt) + комиссия, осевшая в батах на счёте компании.
    # Считать revshare только от крипты нельзя: выплата партнёру начала бы
    # зависеть от того, сколько мы оставили компании. Для доли именно от крипты
    # есть отдельная модель crypto_share.
    profit_base = round((deal.profit_usdt or 0) + (deal.company_fee_usdt or 0), 2) if is_mf \
        else (deal.profit_usdt or 0)

    if not agents_data:
        deal.referrer_payout_usdt = None
        if is_mf:
            deal.crypto_remainder_usdt = round(crypto_base, 2)
            deal.net_profit_usdt = round(crypto_base + (deal.company_fee_usdt or 0), 2)
        else:
            deal.net_profit_usdt = round(deal.profit_usdt or 0, 2)
        return
    volume = max(deal.payin_amount_usdt or 0, deal.payout_amount_usdt or 0)
    computed, net = compute_agent_cascade(profit_base, volume,
                                          [dict(a) for a in agents_data],
                                          crypto_base_usdt=crypto_base)
    # Обратный случай: прислали только имя без referrer_id — связь с профилем
    # терялась молча, и сделка исчезала из кабинета партнёра (он видит свои
    # сделки по deal_agents.referrer_id). Находим по точному имени; если тёзок
    # несколько — не гадаем, оставляем как есть.
    nameless = [a for a in computed if not a.get('referrer_id') and (a.get('name') or '').strip()]
    if nameless:
        wanted = {(a['name'] or '').strip().lower() for a in nameless}
        by_name = {}
        for rid, rname in db_referrer_names(session, wanted):
            by_name.setdefault(rname.strip().lower(), []).append(rid)
        for a in nameless:
            found = by_name.get((a['name'] or '').strip().lower()) or []
            if len(found) == 1:
                a['referrer_id'] = found[0]

    # Имя не передали (скрипт/интеграция шлёт только referrer_id) — берём из профиля.
    # Иначе deal.referrer_name затирался в NULL и партнёр пропадал из списка сделок.
    missing_names = {a.get('referrer_id') for a in computed
                     if a.get('referrer_id') and not a.get('name')}
    if missing_names:
        names = dict(session.query(Referrer.id, Referrer.name)
                     .filter(Referrer.id.in_(missing_names)).all())
        for a in computed:
            if not a.get('name'):
                a['name'] = names.get(a.get('referrer_id'))
    total = 0.0
    for a in computed:
        tier = int(a.get('tier') or 1)
        rid = a.get('referrer_id') or None
        paid, paid_at, paid_note = prev_paid.get((rid, tier), (False, None, None))
        deal.agents.append(DealAgent(
            referrer_id=rid, name=a.get('name'), tier=tier,
            comp_model=(a.get('comp_model') or 'revshare'),
            percent=float(a.get('percent') or 0), fixed_usdt=float(a.get('fixed_usdt') or 0),
            payout_usdt=a.get('_payout'), base_usdt=a.get('_base'),
            paid=paid, paid_at=paid_at, paid_note=paid_note,
        ))
        total += a.get('_payout') or 0
    if is_mf:
        # Чистый доход = остаток на кошельке + комиссия, осевшая в компании
        deal.crypto_remainder_usdt = round(crypto_base - total, 2)
        deal.net_profit_usdt = round(deal.crypto_remainder_usdt + (deal.company_fee_usdt or 0), 2)
    else:
        deal.net_profit_usdt = net
    deal.referrer_payout_usdt = round(total, 2) if total else None
    # кэш агента ур.1 для старых отображений/выгрузок
    primary = min(computed, key=lambda x: int(x.get('tier') or 1))
    pm = (primary.get('comp_model') or 'revshare')
    deal.referrer_id = primary.get('referrer_id') or None
    deal.referrer_name = primary.get('name')
    deal.referrer_comp_model = pm
    deal.referrer_percent = float(primary.get('percent') or 0) if pm != 'markup' else None
    deal.referrer_markup_percent = float(primary.get('percent') or 0) if pm == 'markup' else None


def _mirror_legacy_agent(session, deal):
    """Зеркалит ОДИНОЧНОГО реферала сделки в одну строку deal_agents (ур.1) БЕЗ пересчёта:
    payout берётся из deal.referrer_payout_usdt как есть (учитывает ручной override).
    Нужен, чтобы кабинет единообразно читал deal_agents и для legacy-сделок без массива agents.
    Сохраняет статус paid; если реферала нет — удаляет строки."""
    prev = {(r.referrer_id, r.tier or 1): (r.paid or False, r.paid_at, r.paid_note) for r in deal.agents}
    deal.agents.clear()
    if not (deal.referrer_id or deal.referrer_payout_usdt):
        return
    model = deal.referrer_comp_model or 'revshare'
    pct = (deal.referrer_markup_percent if model == 'markup' else deal.referrer_percent) or 0
    paid, paid_at, paid_note = prev.get((deal.referrer_id, 1), (deal.referrer_paid or False, deal.referrer_paid_at, None))
    deal.agents.append(DealAgent(
        referrer_id=deal.referrer_id, name=deal.referrer_name, tier=1,
        comp_model=model, percent=pct, fixed_usdt=deal.referrer_fixed_usdt or 0,
        payout_usdt=deal.referrer_payout_usdt, base_usdt=deal.profit_usdt,
        paid=paid, paid_at=paid_at, paid_note=paid_note,
    ))


def _refresh_deal_agents(session, deal):
    """Единый источник истины: пересчитывает выплаты агентам от ТЕКУЩЕЙ прибыли
    сделки и синхронизирует deal_agents + net_profit_usdt + referrer_payout_usdt.

    Источник агентов — существующие строки deal.agents (мультиагенты) либо
    legacy-реферер сделки. Прогоняет всё через тот же каскад, что create/update,
    поэтому net и строки агентов НЕ МОГУТ разойтись. Статус paid сохраняется.

    Использовать там, где прибыль сделки меняется без нового массива agents с
    фронта (например, при возмещении, когда payout_amount_usdt появляется позже).
    """
    existing = sorted(deal.agents, key=lambda x: (x.tier or 1, x.id or 0)) if deal.agents else []
    if existing:
        agents_data = [{'referrer_id': r.referrer_id, 'name': r.name, 'tier': r.tier,
                        'comp_model': r.comp_model, 'percent': r.percent,
                        'fixed_usdt': r.fixed_usdt} for r in existing]
    elif deal.referrer_id or deal.referrer_payout_usdt:
        model = deal.referrer_comp_model or 'revshare'
        pct = (deal.referrer_markup_percent if model == 'markup' else deal.referrer_percent) or 0
        agents_data = [{'referrer_id': deal.referrer_id, 'name': deal.referrer_name, 'tier': 1,
                        'comp_model': model, 'percent': pct,
                        'fixed_usdt': deal.referrer_fixed_usdt or 0}]
    else:
        agents_data = []
    _apply_deal_agents(session, deal, agents_data)


# ==================== ПРИХОДЫ СБЕРА (реквизиты) ====================

@app.route('/api/sber-incomes/ingest', methods=['POST'])
def ingest_sber_incomes():
    """Приём приходов Сбера от SberNotifier (VPS). Идемпотентный upsert по uuid.
    Авторизация — X-Api-Key (env SBER_INGEST_KEY), путь в PUBLIC_PATHS."""
    key = os.environ.get('SBER_INGEST_KEY', '')
    if not key or request.headers.get('X-Api-Key') != key:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    data = request.get_json(silent=True) or {}
    incomes = data.get('incomes') or []
    # Расходы приходят тем же тиком нотификатора: списание на брокера и две
    # комиссии — это те самые цифры, которые иначе вбиваются в пачку руками
    debits = data.get('debits') or []
    if not isinstance(incomes, list) or len(incomes) > 500:
        return jsonify({'success': False, 'error': 'bad payload'}), 400
    if not isinstance(debits, list) or len(debits) > 500:
        return jsonify({'success': False, 'error': 'bad payload'}), 400
    db = get_session()
    try:
        created = 0
        for inc in incomes:
            uid = str(inc.get('uuid') or '').strip()
            amount = inc.get('amount_rub')
            if not uid or not amount:
                continue
            existing = db.query(SberIncome).filter(SberIncome.uuid == uid).first()
            if existing:
                continue  # приход неизменяем — обновлять нечего
            db.add(SberIncome(
                uuid=uid[:64],
                operation_date=str(inc.get('operation_date') or '')[:40],
                amount_rub=float(amount),
                payer=str(inc.get('payer') or '')[:255],
                purpose=str(inc.get('purpose') or '')[:1000],
                doc_number=str(inc.get('doc_number') or '')[:40],
            ))
            created += 1
        created_debits = 0
        for dbt in debits:
            uid = str(dbt.get('uuid') or '').strip()
            amount = dbt.get('amount_rub')
            if not uid or not amount:
                continue
            if db.query(SberDebit).filter(SberDebit.uuid == uid).first():
                continue  # списание неизменяемо — обновлять нечего
            db.add(SberDebit(
                uuid=uid[:64],
                operation_date=str(dbt.get('operation_date') or '')[:40],
                amount_rub=float(amount),
                payee=str(dbt.get('payee') or '')[:255],
                payee_inn=str(dbt.get('payee_inn') or '')[:20],
                purpose=str(dbt.get('purpose') or '')[:1000],
                doc_number=str(dbt.get('doc_number') or '')[:40],
            ))
            created_debits += 1
        db.commit()
        return jsonify({'success': True, 'created': created, 'received': len(incomes),
                        'created_debits': created_debits, 'received_debits': len(debits)})
    finally:
        db.close()


@app.route('/api/payin-txs', methods=['GET'])
def list_payin_txs():
    """Реестр входящих переводов: сколько пришло, сколько разобрано, остаток.

    ?unallocated=1 — только переводы с непустым остатком: это и есть ответ на
    «деньги обменяли или они ещё лежат». ?q= — поиск по хэшу.
    """
    session = get_session()
    try:
        q = session.query(PayinTx).order_by(PayinTx.created_at.desc(), PayinTx.id.desc())
        needle = (request.args.get('q') or '').strip()
        if needle:
            q = q.filter(PayinTx.tx_hash.ilike(f'%{needle}%'))
        rows = [t.to_dict() for t in q.limit(500).all()]
        if request.args.get('unallocated') == '1':
            rows = [r for r in rows if r['free_usdt'] > 0.01]
        return jsonify({'success': True, 'txs': rows[:300]})
    finally:
        session.close()


@app.route('/api/payin-txs/<tx_hash>', methods=['GET'])
def get_payin_tx(tx_hash):
    """Детали перевода и разбивка по сделкам — для карточки и формы."""
    session = get_session()
    try:
        tx = session.query(PayinTx).filter(PayinTx.tx_hash == tx_hash).first()
        if not tx:
            return jsonify({'success': False, 'error': 'not_found'}), 404
        uses = []
        for u in session.query(PayinTxUse).filter(PayinTxUse.tx_id == tx.id).all():
            deal = session.query(Deal).get(u.deal_id)
            uses.append({'deal_id': u.deal_id, 'amount_usdt': round(u.amount_usdt or 0, 2),
                         'client_name': (deal.client_name if deal else None),
                         'realty_purpose': (deal.realty_purpose if deal else None)})
        return jsonify({'success': True, 'tx': tx.to_dict(), 'uses': uses})
    finally:
        session.close()


# ── Конвертации рублёвых поступлений ────────────────────────────────────────

def _converted_by_income(session, income_ids):
    """Σ сконвертированного по приходам — одним запросом вместо запроса на строку.

    Ключевая функция бюджета запросов: см. tests/test_conversions_perf.py.
    """
    if not income_ids:
        return {}
    from sqlalchemy import func as _f
    rows = session.query(
        ConversionSource.sber_income_id, _f.sum(ConversionSource.amount_rub)
    ).join(Conversion, ConversionSource.conversion_id == Conversion.id).filter(
        ConversionSource.sber_income_id.in_(income_ids),
        Conversion.status != ConversionStatus.CANCELLED
    ).group_by(ConversionSource.sber_income_id).all()
    return {iid: round(val or 0, 2) for iid, val in rows}


def _attach_sources(db, conv, sources_req, force=False):
    """Привязать поступления к пачке долями. Бросает ValueError при переборе.

    Перебор над остатком счёта бывает осознанным — 14.08 конвертировали больше,
    чем пришло, добирая из буфера, — поэтому force снимает запрет. Но молча
    это не проходит: без флага пачка не создастся.
    """
    db.query(ConversionSource).filter(ConversionSource.conversion_id == conv.id).delete()
    db.flush()
    for item in sources_req or []:
        try:
            sid = int(item.get('sber_income_id'))
        except (TypeError, ValueError):
            raise ValueError('Некорректный id прихода')
        inc = db.query(SberIncome).filter(SberIncome.id == sid).with_for_update().first()
        if not inc:
            raise ValueError(f'Приход #{sid} не найден')
        if inc.excluded and not force:
            raise ValueError(
                f'Приход {inc.amount_rub:,.2f} ₽ ({inc.payer or sid}) исключён '
                f'из конвертаций{": " + inc.note if inc.note else ""}')
        try:
            take = round(float(item.get('amount_rub') or 0), 2)
        except (TypeError, ValueError):
            raise ValueError(f'Некорректная сумма по приходу #{sid}')
        free = inc.free_rub()
        if not take:
            # Сумму не задали — берём остаток. Если его нет, приход уже разнесён
            # целиком: молча привязать ноль значит потерять ошибку оператора
            take = free
            if take <= 0.01 and not force:
                raise ValueError(
                    f'Приход {inc.amount_rub:,.2f} ₽ ({inc.payer or sid}) '
                    f'уже сконвертирован полностью')
        if take > free + 0.01 and not force:
            raise ValueError(
                f'По приходу {inc.amount_rub:,.2f} ₽ ({inc.payer or sid}) '
                f'доступно {free:,.2f} ₽, запрошено {take:,.2f} ₽')
        db.add(ConversionSource(conversion_id=conv.id, sber_income_id=sid, amount_rub=take))
    db.flush()


def _clear_conversion_payin_uses(db, conv):
    """Снять доли PayinTxUse, проставленные этой пачкой (перед пересчётом/удалением)."""
    tx_ids = [t.payin_tx_id for t in conv.txs]
    if not tx_ids:
        return
    db.query(PayinTxUse).filter(PayinTxUse.tx_id.in_(tx_ids)).delete(synchronize_session=False)
    db.flush()


def conversion_shares_for(conv, expected_if_pending=False):
    """Доли USDT по приходам пачки: {sber_income_id: usdt}.

    Единственное место, где доля выводится из пачки. Раньше эти две строки были
    скопированы в четырёх местах (список приходов, карточка, разнос по сделкам,
    реестр обменников) — правка формулы в одном расходилась с остальными.

    expected_if_pending=True — для неполученной пачки вернуть ожидание по курсу
    (менеджер заводит сделку раньше, чем брокер отдаст USDT).
    """
    pairs = [(x.sber_income_id, x.amount_rub) for x in (conv.sources or [])]
    if conv.status == ConversionStatus.RECEIVED:
        return _conversion_shares(pairs, conv.received_usdt())
    if expected_if_pending:
        return _conversion_shares(pairs, conv.expected_usdt())
    return {}


def _apply_conversion_shares(db, conv):
    """Разнести полученный USDT по сделкам поступлений пачки.

    Одна сделка может забрать несколько поступлений — доли суммируются.
    Поступление без сделки пропускается: конвертировать приход, у которого сделки
    ещё нет, разрешено (порядок «приход → конвертация → USDT → сделка»).
    """
    _clear_conversion_payin_uses(db, conv)
    shares = _conversion_shares(
        [(src.sber_income_id, src.amount_rub) for src in conv.sources],
        conv.received_usdt())
    per_deal = {}
    for sid, usdt in shares.items():
        inc = db.query(SberIncome).get(sid)
        if not inc or not inc.claimed_deal_id:
            continue
        per_deal[inc.claimed_deal_id] = round(per_deal.get(inc.claimed_deal_id, 0) + usdt, 4)
    if not per_deal or not conv.txs:
        return
    # Доли вешаем на первый перевод пачки: брокер обычно шлёт одним, а при дроблении
    # разбивка по переводам роли не играет — важна сумма, пришедшаяся на сделку.
    tx_id = conv.txs[0].payin_tx_id
    for deal_id, amount in per_deal.items():
        db.add(PayinTxUse(tx_id=tx_id, deal_id=deal_id, amount_usdt=amount))
    db.flush()


@app.route('/api/conversions/<int:conv_id>/txs', methods=['POST'])
def attach_conversion_tx(conv_id):
    """Привязать приход USDT к пачке и разнести доли по сделкам.

    Это и есть то, ради чего сущность заводилась: доли PayinTxUse больше
    не вводятся руками, а выводятся из состава пачки.
    """
    db = get_session()
    try:
        conv = db.query(Conversion).get(conv_id)
        if not conv:
            return jsonify({'success': False, 'error': 'not_found'}), 404
        data = request.get_json(silent=True) or {}
        h = str(data.get('tx_hash') or '').strip()
        if not h:
            return jsonify({'success': False, 'error': 'Нужен хеш прихода'}), 400
        tx = db.query(PayinTx).filter(PayinTx.tx_hash == h).first()
        if tx is None:
            # Первый раз видим перевод — сумму берём из блокчейна, а не с рук
            onchain = _tron_tx_amount(h)
            try:
                manual = float(data.get('amount_usdt') or 0)
            except (TypeError, ValueError):
                return jsonify({'success': False, 'error': 'Некорректная сумма прихода'}), 400
            tx = PayinTx(tx_hash=h, amount_usdt=onchain if onchain is not None else manual,
                         source='tronscan' if onchain is not None else 'manual',
                         to_address=_tron_tx_to_address(h))
            db.add(tx)
            db.flush()
        try:
            take = round(float(data.get('amount_usdt') or tx.amount_usdt or 0), 4)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'Некорректная сумма прихода'}), 400
        existing = db.query(ConversionTx).filter(
            ConversionTx.conversion_id == conv.id,
            ConversionTx.payin_tx_id == tx.id).first()
        if existing:
            existing.amount_usdt = take
        else:
            db.add(ConversionTx(conversion_id=conv.id, payin_tx_id=tx.id, amount_usdt=take))
        db.flush()
        db.refresh(conv)
        conv.status = ConversionStatus.RECEIVED
        conv.received_at = datetime.utcnow()
        _apply_conversion_shares(db, conv)
        db.commit()
        db.refresh(conv)
        return jsonify({'success': True, 'conversion': conv.to_dict()})
    finally:
        db.close()


@app.route('/api/deals/<int:deal_id>/conversions', methods=['GET'])
def deal_conversions(deal_id):
    """Конвертации, через которые прошёл приход этой сделки.

    Отвечает на «эта сделка вообще сконвертирована?» прямо в карточке —
    и объясняет пустую прибыль, пока курс прихода неизвестен.
    """
    db = get_session()
    try:
        incs = db.query(SberIncome).filter(SberIncome.claimed_deal_id == deal_id).all()
        out = []
        for inc in incs:
            links = db.query(ConversionSource, Conversion).join(
                Conversion, ConversionSource.conversion_id == Conversion.id).filter(
                ConversionSource.sber_income_id == inc.id,
                Conversion.status != ConversionStatus.CANCELLED).all()
            for src, conv in links:
                shares = conversion_shares_for(conv)
                out.append({
                    'conversion_id': conv.id, 'display_name': conv.display_name,
                    'broker': conv.broker, 'rate_rub_usdt': conv.rate_rub_usdt,
                    'amount_rub': round(src.amount_rub or 0, 2),
                    'usdt': shares.get(inc.id, 0.0),
                    'status': conv.status.value if conv.status else None,
                })
        return jsonify({'success': True, 'conversions': out,
                        'has_incomes': bool(incs)})
    finally:
        db.close()


def _attach_debits(db, conv, debits_req, force=False):
    """Привязать списания со счёта к пачке. Бросает ValueError при двойном учёте.

    Расход приходит частями — отправка брокеру, комиссия процентом, фикс, —
    поэтому список, а не одно поле. Один платёж не должен закрывать две пачки:
    иначе расход учтётся дважды, как это было с приходами USDT.
    """
    db.query(ConversionDebit).filter(ConversionDebit.conversion_id == conv.id).delete()
    db.flush()
    for item in debits_req or []:
        try:
            did = int(item.get('sber_debit_id'))
        except (TypeError, ValueError):
            raise ValueError('Некорректный id списания')
        deb = db.query(SberDebit).filter(SberDebit.id == did).with_for_update().first()
        if not deb:
            raise ValueError(f'Списание #{did} не найдено')
        try:
            take = round(float(item.get('amount_rub') or 0), 2)
        except (TypeError, ValueError):
            raise ValueError(f'Некорректная сумма по списанию #{did}')
        free = deb.free_rub()
        if not take:
            take = free
            if take <= 0.01 and not force:
                raise ValueError(
                    f'Списание {deb.amount_rub:,.2f} ₽ ({deb.payee or did}) '
                    f'уже привязано к другой пачке')
        if take > free + 0.01 and not force:
            raise ValueError(
                f'Списание {deb.amount_rub:,.2f} ₽ ({deb.payee or did}) уже разнесено: '
                f'свободно {free:,.2f} ₽, запрошено {take:,.2f} ₽')
        db.add(ConversionDebit(conversion_id=conv.id, sber_debit_id=did, amount_rub=take))
    db.flush()


@app.route('/api/sber-debits', methods=['GET'])
def list_sber_debits():
    """Списания со счёта для привязки к пачке.

    По умолчанию — только с непривязанным остатком (?all=1 — все).
    ?kind=broker|fee — только отправки либо только комиссии.
    """
    db = get_session()
    try:
        q = db.query(SberDebit).order_by(SberDebit.operation_date.desc(), SberDebit.id.desc())
        rows = [d.to_dict() for d in q.limit(600).all()]
        if request.args.get('all') != '1':
            rows = [r for r in rows if r['free_rub'] > 0.01]
        kind = (request.args.get('kind') or '').strip()
        if kind in ('broker', 'fee'):
            rows = [r for r in rows if r['kind'] == kind]
        return jsonify({'success': True, 'debits': rows[:300]})
    finally:
        db.close()


@app.route('/api/sber-debits/<int:debit_id>', methods=['PUT'])
def update_sber_debit(debit_id):
    """Поправить вид списания: парсер по назначению угадывает не всегда."""
    db = get_session()
    try:
        deb = db.query(SberDebit).get(debit_id)
        if not deb:
            return jsonify({'success': False, 'error': 'not_found'}), 404
        kind = (request.get_json(silent=True) or {}).get('kind')
        if kind not in ('broker', 'fee'):
            return jsonify({'success': False, 'error': 'kind должен быть broker или fee'}), 400
        deb.kind = kind
        db.commit()
        return jsonify({'success': True, 'debit': deb.to_dict()})
    finally:
        db.close()


def payin_address_backfill_once(limit=20):
    """Один проход: проставить кошелёк-получатель переводам, где его нет.

    Вынесено из цикла, чтобы проверяться тестом без потока и таймеров.
    Возвращает, скольким переводам адрес проставлен.
    """
    db = get_session()
    try:
        rows = db.query(PayinTx).filter(PayinTx.to_address.is_(None)).limit(limit).all()
        done = 0
        for tx in rows:
            addr = _tron_tx_to_address(tx.tx_hash)
            if addr:
                tx.to_address = addr
                done += 1
        if done:
            db.commit()
        return done
    finally:
        db.close()


def _payin_address_backfill_loop():
    """Фоном проставляет кошелёк-получатель у переводов, где его нет.

    Раньше адрес дотягивался прямо в GET карточки — чтение зависело от чужого
    сервиса. Теперь это фоновая работа: экран открывается всегда, адрес
    появляется в течение минуты.
    """
    while True:
        time.sleep(PAYIN_ADDR_BACKFILL_INTERVAL)
        try:
            payin_address_backfill_once()
        except Exception as e:  # noqa: BLE001 — фон не должен ронять процесс
            app.logger.warning(f'payin address backfill: {str(e)[:120]}')


PAYIN_ADDR_BACKFILL_INTERVAL = int(os.environ.get('PAYIN_ADDR_BACKFILL_INTERVAL', '60'))
if os.environ.get('PAYIN_ADDR_BACKFILL', '1') == '1' and not app.config.get('TESTING'):
    threading.Thread(target=_payin_address_backfill_loop, daemon=True,
                     name='payin-addr-backfill').start()


@app.route('/api/conversions', methods=['GET'])
def list_conversions():
    """Список пачек конвертации, свежие сверху."""
    db = get_session()
    try:
        rows = db.query(Conversion).order_by(Conversion.id.desc()).limit(200).all()
        return jsonify({'success': True, 'conversions': [c.to_dict() for c in rows]})
    finally:
        db.close()


@app.route('/api/conversions/<int:conv_id>', methods=['GET'])
def get_conversion(conv_id):
    """Пачка с составом: какие поступления вошли, сколько USDT на каждое, чьи сделки."""
    db = get_session()
    try:
        conv = db.query(Conversion).get(conv_id)
        if not conv:
            return jsonify({'success': False, 'error': 'not_found'}), 404
        shares = conversion_shares_for(conv)
        # Сделки обменника: по пачке должно быть видно, чьи выплаты она обеспечивает
        wl_deals = []
        snap = db.query(ReestrSnapshot).filter(ReestrSnapshot.view == 'deals').first()
        if snap:
            try:
                wl_deals = json.loads(snap.payload) or []
            except (ValueError, TypeError):
                wl_deals = []
        composition = []
        for src in conv.sources:
            inc = db.query(SberIncome).get(src.sber_income_id)
            deal = (db.query(Deal).get(inc.claimed_deal_id)
                    if inc and inc.claimed_deal_id else None)
            wl = _match_wl_deal(inc.to_dict(), wl_deals) if inc else None
            composition.append({
                'sber_income_id': src.sber_income_id,
                'amount_rub': round(src.amount_rub or 0, 2),
                'usdt': shares.get(src.sber_income_id, 0.0),
                'payer': inc.payer if inc else None,
                'operation_date': inc.operation_date if inc else None,
                'deal_id': deal.id if deal else None,
                'client_name': (deal.client_name if deal else None),
                'wl': wl.get('wl') if wl else None,
                'merchant': wl.get('merchant') if wl else None,
                'author': wl.get('author') if wl else None,
            })
        txs = []
        wallet_labels = {w.address: w.label for w in db.query(Wallet).all()}
        for t in conv.txs:
            tx = db.query(PayinTx).get(t.payin_tx_id)
            # Адрес НЕ дотягиваем здесь: чтение не должно зависеть от доступности
            # TronScan — при его недоступности экран висел на таймауте чужого
            # сервиса. Хеши без адреса добирает фоновый _payin_address_backfill
            txs.append({'tx_hash': tx.tx_hash if tx else '',
                        'to_address': tx.to_address if tx else None,
                        'to_label': wallet_labels.get(tx.to_address) if tx else None,
                        'amount_usdt': round(t.amount_usdt or 0, 4),
                        'tx_total_usdt': round((tx.amount_usdt or 0) if tx else 0, 4),
                        'tx_free_usdt': tx.free_usdt() if tx else 0})
        return jsonify({'success': True, 'conversion': conv.to_dict(),
                        'composition': composition, 'txs': txs})
    finally:
        db.close()


@app.route('/api/conversions', methods=['POST'])
def create_conversion():
    """Создать пачку: брокер, курс, ставка удержания, состав поступлений."""
    db = get_session()
    try:
        data = request.get_json(silent=True) or {}
        try:
            conv = Conversion(
                broker=(data.get('broker') or '').strip()[:100] or None,
                request_no=(data.get('request_no') or '').strip()[:60] or None,
                rate_rub_usdt=float(data['rate_rub_usdt']) if data.get('rate_rub_usdt') else None,
                held_percent=float(data.get('held_percent') if data.get('held_percent') is not None else 0.3),
                held_fixed_rub=float(data.get('held_fixed_rub') if data.get('held_fixed_rub') is not None else 40.0),
                amount_rub_sent=float(data['amount_rub_sent']) if data.get('amount_rub_sent') else None,
                wallet_id=data.get('wallet_id') or None,
                notes=(data.get('notes') or '').strip() or None,
                created_by=flask_session.get('username'),
                status=ConversionStatus.SENT if data.get('sent_at') else ConversionStatus.DRAFT,
                sent_at=_parse_sent_at(data.get('sent_at')),
            )
        except (TypeError, ValueError) as e:
            return jsonify({'success': False, 'error': f'Некорректные данные пачки: {e}'}), 400
        db.add(conv)
        db.flush()
        try:
            _attach_sources(db, conv, data.get('sources'), force=bool(data.get('force')))
            _attach_debits(db, conv, data.get('debits'), force=bool(data.get('force')))
            # Списание из выписки знает дату платежа точно — она главнее введённой
            if conv.debits:
                dates = [d.debit.operation_date for d in conv.debits
                         if d.debit and d.debit.operation_date]
                if dates:
                    conv.sent_at = _parse_sent_at(min(dates))
        except ValueError as e:
            db.rollback()
            return jsonify({'success': False, 'error': str(e)}), 409
        db.commit()
        db.refresh(conv)
        return jsonify({'success': True, 'conversion': conv.to_dict()})
    finally:
        db.close()


@app.route('/api/conversions/<int:conv_id>', methods=['PUT'])
def update_conversion(conv_id):
    """Правка пачки: брокер, заявка, курс, дата, отправленная сумма, кошелёк.

    Состав не трогаем — для него есть отдельные ручки. Пересоздавать пачку
    из-за опечатки в курсе нельзя: удаление снимает доли USDT со сделок.
    """
    db = get_session()
    try:
        conv = db.query(Conversion).get(conv_id)
        if not conv:
            return jsonify({'success': False, 'error': 'not_found'}), 404
        data = request.get_json(silent=True) or {}
        try:
            if 'broker' in data:
                conv.broker = (data['broker'] or '').strip()[:100] or None
            if 'request_no' in data:
                conv.request_no = (data['request_no'] or '').strip()[:60] or None
            if 'rate_rub_usdt' in data:
                conv.rate_rub_usdt = float(data['rate_rub_usdt']) if data['rate_rub_usdt'] else None
            if 'amount_rub_sent' in data:
                conv.amount_rub_sent = float(data['amount_rub_sent']) if data['amount_rub_sent'] else None
            if 'held_percent' in data:
                conv.held_percent = float(data['held_percent'])
            if 'held_fixed_rub' in data:
                conv.held_fixed_rub = float(data['held_fixed_rub'])
            if 'wallet_id' in data:
                conv.wallet_id = data['wallet_id'] or None
            if 'notes' in data:
                conv.notes = (data['notes'] or '').strip() or None
            if 'sent_at' in data:
                conv.sent_at = _parse_sent_at(data['sent_at'])
        except (TypeError, ValueError) as e:
            return jsonify({'success': False, 'error': f'Некорректные данные: {e}'}), 400
        db.commit()
        db.refresh(conv)
        return jsonify({'success': True, 'conversion': conv.to_dict()})
    finally:
        db.close()


@app.route('/api/conversions/<int:conv_id>', methods=['DELETE'])
def delete_conversion(conv_id):
    """Удалить пачку — поступления возвращаются в несконвертированные."""
    db = get_session()
    try:
        conv = db.query(Conversion).get(conv_id)
        if not conv:
            return jsonify({'success': False, 'error': 'not_found'}), 404
        _clear_conversion_payin_uses(db, conv)
        db.delete(conv)
        db.commit()
        return jsonify({'success': True})
    finally:
        db.close()


@app.route('/api/sber-incomes', methods=['GET'])
def list_sber_incomes():
    """Пул приходов Сбера для пикера в форме сделки.
    По умолчанию — только незабранные; ?all=1 — все (с меткой сделки).
    ?kind=acquiring|transfer — только СБП-эквайринг либо только реквизиты.
    Фильтр по потоку в Python: вид определяется по тексту назначения, а не колонкой."""
    db = get_session()
    try:
        q = db.query(SberIncome).order_by(SberIncome.operation_date.desc(), SberIncome.id.desc())
        if request.args.get('all') != '1':
            q = q.filter(SberIncome.claimed_deal_id.is_(None))
        kind = (request.args.get('kind') or '').strip()
        items = q.limit(600).all()
        # Один запрос на весь список вместо запроса на строку
        agg = _converted_by_income(db, [i.id for i in items])
        rows = [i.to_dict(agg) for i in items]
        if kind in ('acquiring', 'transfer'):
            rows = [r for r in rows if r['kind'] == kind]
        rows = rows[:300]
        total_free = 0.0
        in_deal_total = 0.0
        legacy_total = 0.0
        if request.args.get('with_conversion') == '1':
            # Одним запросом: в какие пачки ушёл каждый приход. Отменённые не в счёт.
            by_income = {}
            usdt_by_income = {}
            expected_by_income = {}
            # sources/txs каждой пачки грузим сразу: обращение к ним в цикле
            # давало ленивый запрос на пачку — тот же N+1, только этажом выше
            from sqlalchemy.orm import selectinload
            pairs = db.query(ConversionSource, Conversion).join(
                Conversion, ConversionSource.conversion_id == Conversion.id).options(
                selectinload(Conversion.sources), selectinload(Conversion.txs)).filter(
                Conversion.status != ConversionStatus.CANCELLED).all()
            # Доли считаются один раз на пачку, а не на каждый её приход
            shares_cache = {}
            for src, conv in pairs:
                by_income.setdefault(src.sber_income_id, []).append({
                    'id': conv.id, 'display_name': conv.display_name,
                    'broker': conv.broker, 'rate_rub_usdt': conv.rate_rub_usdt,
                    'amount_rub': round(src.amount_rub or 0, 2),
                    'status': conv.status.value if conv.status else None,
                })
                # Сколько USDT пришлось на этот приход. После подтверждения — факт,
                # до него — ожидание по согласованному курсу: менеджер заводит
                # сделку раньше, чем брокер отдаст USDT, и без этой цифры вбивает
                # её руками (так в #501 появился курс 126,70 при рынке 87,93)
                if conv.id not in shares_cache:
                    shares_cache[conv.id] = (
                        conv.status == ConversionStatus.RECEIVED,
                        conversion_shares_for(conv, expected_if_pending=True))
                received, shares = shares_cache[conv.id]
                val = shares.get(src.sber_income_id)
                if val is not None:
                    target = usdt_by_income if received else expected_by_income
                    target[src.sber_income_id] = round(
                        target.get(src.sber_income_id, 0) + val, 2)
            # Сделки обменника из снапшота WL-бота: приход по СБП — это оплата
            # клиента мерчанта, и по ней надо видеть WL-номер и мерчанта, иначе
            # непонятно, откуда деньги и чью выплату они обеспечивают
            wl_deals = []
            snap = db.query(ReestrSnapshot).filter(ReestrSnapshot.view == 'deals').first()
            if snap:
                try:
                    wl_deals = json.loads(snap.payload) or []
                except (ValueError, TypeError):
                    wl_deals = []

            # Инфа о сделке: без неё в таблице виден только номер, а нужно понимать,
            # откуда деньги — обмен, недвижка или что-то ещё
            deal_ids = {r['claimed_deal_id'] for r in rows if r.get('claimed_deal_id')}
            deals_map = {}
            if deal_ids:
                for d in db.query(Deal).filter(Deal.id.in_(deal_ids)).all():
                    deals_map[d.id] = {
                        'client_name': d.client_name,
                        'deal_kind': d.deal_kind or 'exchange',
                        'payin_method': d.payin_method.value if d.payin_method else None,
                        'payin_amount_usdt': d.payin_amount_usdt,
                    }
            for row in rows:
                row['deal'] = deals_map.get(row.get('claimed_deal_id'))
                row['wl'] = _match_wl_deal(row, wl_deals) if row['kind'] == 'acquiring' else None
                links = by_income.get(row['id']) or []
                # Одна пачка — объектом (частый случай), несколько — списком
                row['conversion'] = links[0] if len(links) == 1 else (links or None)
                # Три состояния вместо двух. Приход, у которого в сделке уже стоит
                # USDT, не «лежит на счёте» — рубли обменяли, просто пачку никто
                # не оформил. Считать его несконвертированным значит завышать
                # остаток на счёте и не видеть, где учёт отстал от факта.
                row['usdt'] = usdt_by_income.get(row['id'])
                row['usdt_expected'] = expected_by_income.get(row['id'])
                free = row.get('free_rub') or 0
                # Статусная модель прихода: лежит → на конвертации → сконвертирован.
                # Средний статус нужен, чтобы связь фиксировалась В МОМЕНТ отправки
                # брокеру, а не когда придёт USDT: иначе к вечеру снова гадать,
                # какие сделки ушли в эту пачку
                any_received = any(l['status'] == 'received' for l in links)
                if row.get('excluded'):
                    row['conv_state'] = 'excluded'
                elif links and free > 0.01:
                    row['conv_state'] = 'partial'
                    total_free += free
                elif links and any_received:
                    row['conv_state'] = 'converted'
                elif links:
                    row['conv_state'] = 'in_progress'
                elif ((row.get('operation_date') or '') < CONVERSIONS_LAUNCH_DATE
                      and not row.get('keep_active')):
                    # До запуска учёта — история, а не остаток и не долг по учёту:
                    # пачки по таким приходам никто уже не заведёт. Со сделкой или
                    # без — рубли по ним разошлись, когда системы ещё не было
                    row['conv_state'] = 'legacy'
                    legacy_total += free
                elif (row.get('deal') or {}).get('payin_amount_usdt'):
                    row['conv_state'] = 'in_deal'
                    in_deal_total += free
                else:
                    row['conv_state'] = 'pending'
                    total_free += free
        return jsonify({'success': True, 'incomes': rows,
                        'unconverted_rub': round(total_free, 2),
                        'in_deal_rub': round(in_deal_total, 2),
                        'legacy_rub': round(legacy_total, 2),
                        'launch_date': CONVERSIONS_LAUNCH_DATE})
    finally:
        db.close()


@app.route('/api/sber-incomes/<int:income_id>', methods=['PUT'])
def update_sber_income(income_id):
    """Разметка прихода: исключить из конвертаций, комментарий, источник."""
    db = get_session()
    try:
        inc = db.query(SberIncome).get(income_id)
        if not inc:
            return jsonify({'success': False, 'error': 'not_found'}), 404
        data = request.get_json(silent=True) or {}
        if 'excluded' in data:
            inc.excluded = bool(data['excluded'])
        if 'note' in data:
            inc.note = (str(data['note'] or '').strip() or None)
        if 'source_tag' in data:
            inc.source_tag = (str(data['source_tag'] or '').strip()[:30] or None)
        if 'keep_active' in data:
            inc.keep_active = bool(data['keep_active'])
        db.commit()
        return jsonify({'success': True, 'income': inc.to_dict()})
    finally:
        db.close()


@app.route('/api/sber-incomes/bulk', methods=['POST'])
def bulk_sber_incomes():
    """Массовая разметка. Пока одно действие — отсечка истории.

    До запуска учёта конвертации уже сделаны, но система о них не знает, поэтому
    «не сконвертировано» показывает всю историю счёта. Отсечка помечает всё
    до даты как учтённое ранее и убирает из счётчика.
    """
    db = get_session()
    try:
        data = request.get_json(silent=True) or {}
        action = data.get('action')
        if action != 'converted_earlier':
            return jsonify({'success': False, 'error': 'unknown action'}), 400
        before = str(data.get('before_date') or '').strip()
        if not before:
            return jsonify({'success': False, 'error': 'нужна дата отсечки'}), 400
        rows = db.query(SberIncome).filter(
            SberIncome.operation_date < before,
            SberIncome.excluded.isnot(True)).all()
        for inc in rows:
            inc.excluded = True
            inc.note = inc.note or f'конвертировано до запуска учёта ({before})'
        db.commit()
        return jsonify({'success': True, 'updated': len(rows)})
    finally:
        db.close()


def _sync_sber_claims(session, deal, parts):
    """Синхронизирует забор приходов из пула под части сделки (payin_parts).

    parts — список dict {uuid|null, amount_rub, ...}; части без uuid (ручной ввод)
    пул не трогают. Освобождает приходы, убранные из сделки; забирает новые.
    Бросает ValueError, если приход уже забран другой сделкой (двойной учёт).
    """
    new_uuids = {str(p['uuid']) for p in (parts or []) if p.get('uuid')}
    # освободить убранные
    for inc in session.query(SberIncome).filter(SberIncome.claimed_deal_id == deal.id).all():
        if inc.uuid not in new_uuids:
            inc.claimed_deal_id = None
            inc.claimed_at = None
    # забрать новые (с блокировкой строки от гонки двух сделок)
    for uid in new_uuids:
        inc = session.query(SberIncome).filter(SberIncome.uuid == uid).with_for_update().first()
        if not inc:
            continue  # ручная часть с чужим uuid — просто не трогаем пул
        if inc.claimed_deal_id and inc.claimed_deal_id != deal.id:
            raise ValueError(f'Приход {inc.amount_rub:.0f} ₽ ({inc.payer or uid[:8]}) уже забран в сделке #{inc.claimed_deal_id}')
        inc.claimed_deal_id = deal.id
        inc.claimed_at = datetime.utcnow()


def _normalize_tx_hashes(raw):
    """Хэши прихода крипты → [{'hash':.., 'amount_usdt':..}], без дублей и пустых.

    Принимает и строки, и dict — фронт шлёт объекты с суммой части, интеграции
    могут прислать просто список хэшей.
    """
    out, seen = [], set()
    for item in (raw or []):
        if isinstance(item, str):
            h, amt = item.strip(), None
        elif isinstance(item, dict):
            h = str(item.get('hash') or item.get('tx_hash') or '').strip()
            amt = item.get('amount_usdt')
        else:
            continue
        if not h or h in seen:
            continue
        seen.add(h)
        try:
            amt = float(amt) if amt not in (None, '') else None
        except (TypeError, ValueError):
            amt = None
        out.append({'hash': h, 'amount_usdt': amt})
    return out


def _normalize_payin_extra(raw):
    """Дополнительные приходы → список частей одного формата.

    Часть без суммы USDT выбрасывается: строка без денег ничего не описывает,
    а в выгрузке дала бы пустую строку с чужой долей. Неизвестный метод тоже
    выбрасываем — на нём упал бы лейбл в Sheet и в Telegram.

    Курс считается из рублей, если его не прислали: форма умеет вводить в обе
    стороны, интеграции могут прислать только рубли и USDT.
    """
    out = []
    for item in (raw or []):
        if not isinstance(item, dict):
            continue
        method = str(item.get('method') or '').strip()
        if method not in PAYIN_METHOD_LABELS:
            continue
        try:
            usdt = float(item.get('amount_usdt'))
        except (TypeError, ValueError):
            continue
        if usdt <= 0:
            continue

        def _pos(key):
            try:
                v = float(item.get(key))
            except (TypeError, ValueError):
                return None
            return v if v > 0 else None

        rub = _pos('amount_rub')
        rate = _pos('rate_rub_usdt')
        if rub and not rate:
            rate = round(rub / usdt, 6)
        out.append({
            'method': method,
            'amount_rub': rub,
            'rate_rub_usdt': rate,
            'amount_usdt': round(usdt, 6),
            'partner_name': (str(item.get('partner_name') or '').strip() or None),
            'tx_hashes': _normalize_tx_hashes(item.get('tx_hashes')),
            'sber_uuids': [str(u) for u in (item.get('sber_uuids') or []) if u],
            'note': str(item.get('note') or '').strip(),
        })
    return out


def _payin_extra_list(deal):
    """Дополнительные приходы сделки. Битый JSON = пустой список, не падаем."""
    if not deal.payin_extra:
        return []
    try:
        parsed = json.loads(deal.payin_extra)
    except (ValueError, TypeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _payin_all_parts(deal):
    """Все части прихода, первая — основная, из плоских payin_* полей.

    Основная часть отдельно НЕ хранится: плоские поля после сохранения содержат
    агрегаты, поэтому её суммы восстанавливаются вычитанием дополнительных.
    Так у выгрузки и уведомлений один формат, и они не знают про асимметрию.
    """
    extra = _payin_extra_list(deal)
    main_usdt = round((deal.payin_amount_usdt or 0)
                      - sum(p.get('amount_usdt') or 0 for p in extra), 6)
    main_rub = round((deal.payin_amount_rub or 0)
                     - sum(p.get('amount_rub') or 0 for p in extra), 6)
    # payin_tx_hashes — слитый список по всей сделке (на нём стоит защита от
    # двойного учёта). Основной части оставляем только СВОИ хэши: иначе перевод
    # дополнительной части встаёт и в её строку, и в строку части 1 — в выгрузке
    # он посчитался бы дважды, а в карточке было бы не понять, чей он.
    taken = {h['hash'] for p in extra for h in _normalize_tx_hashes(p.get('tx_hashes'))}
    main_hashes = [h for h in _normalize_tx_hashes(
        json.loads(deal.payin_tx_hashes) if deal.payin_tx_hashes else [])
        if h['hash'] not in taken]
    main = {
        'method': deal.payin_method.value if deal.payin_method else '',
        'amount_rub': main_rub if main_rub > 0 else None,
        'rate_rub_usdt': (round(main_rub / main_usdt, 6)
                          if main_rub > 0 and main_usdt > 0 else None),
        'amount_usdt': main_usdt,
        'partner_name': deal.payin_partner_name or None,
        'tx_hashes': main_hashes,
        'sber_uuids': [],
        'note': '',
    }
    return [main] + extra


def split_by_payin_share(total, part_amounts, digits=2):
    """Делит число по долям приходов частей. Только для выгрузки — в БД доли
    не хранятся.

    Остаток округления добирает ПОСЛЕДНЯЯ часть: иначе сумма строк разойдётся
    с итогом сделки на копейки и лист перестанет сходиться при сверке месяца.
    """
    n = len(part_amounts)
    if not n:
        return []
    total = float(total or 0)
    denom = sum(float(a or 0) for a in part_amounts)
    out, acc = [], 0.0
    for a in part_amounts[:-1]:
        v = round(total * float(a or 0) / denom, digits) if denom else 0.0
        out.append(v)
        acc += v
    out.append(round(total - acc, digits))
    return out


def _apply_payin_extra(session, deal, raw_extra, main_usdt, main_rub):
    """Пишет дополнительные приходы и пересчитывает агрегаты в плоских полях.

    main_usdt / main_rub — суммы ОСНОВНОЙ части, передаются явно. Брать их из
    deal.payin_amount_* нельзя: там уже агрегат, и повторный вызов прибавил бы
    дополнительные части второй раз.

    Хэши и uuid'ы приходов Сбера сливаются в payin_tx_hashes / payin_parts —
    на этом стоит защита от двойного учёта (get_used_transaction_hashes и
    _sync_sber_claims), и она продолжает работать без правок.
    """
    extra = _normalize_payin_extra(raw_extra)
    deal.payin_extra = json.dumps(extra, ensure_ascii=False) if extra else None

    main_usdt = float(main_usdt or 0)
    main_rub = float(main_rub or 0)

    deal.payin_amount_usdt = round(
        main_usdt + sum(p['amount_usdt'] for p in extra), 6) or None
    total_rub = round(main_rub + sum(p['amount_rub'] or 0 for p in extra), 6)
    deal.payin_amount_rub = total_rub or None

    # Средневзвешенный курс — только по рублёвым частям. Курс первой части
    # разошёлся бы с итогом: 800 000 / 86.7052 = 9 226.67 при приходе 9 285.36.
    rub_usdt = main_usdt if main_rub else 0.0
    rub_usdt += sum(p['amount_usdt'] for p in extra if p['amount_rub'])
    deal.payin_rate_rub_usdt = (round(total_rub / rub_usdt, 6)
                                if (total_rub and rub_usdt) else None)

    # payin_method НЕ трогаем: это метод ОСНОВНОЙ части, и восстановить его
    # больше неоткуда — суммы частей выводятся вычитанием, а метод нигде не
    # дублируется. Правило «метод крупнейшей части» затирало его: на сделке
    # 200 000 ₽ по реквизитам + 600 000 ₽ наличными основная часть начинала
    # показываться как «наличные» и в карточке, и в Telegram. Разбивка по
    # каналам теперь видна везде (TG, карточка, строки выгрузки), поэтому
    # сводить сделку к одному «главному» методу больше не требуется.

    # Слияние хэшей: без него приход дополнительной части можно списать второй раз
    merged_hashes = list(_normalize_tx_hashes(
        json.loads(deal.payin_tx_hashes) if deal.payin_tx_hashes else []))
    seen = {h['hash'] for h in merged_hashes}
    for p in extra:
        for h in p['tx_hashes']:
            if h['hash'] not in seen:
                seen.add(h['hash'])
                merged_hashes.append(h)
    if merged_hashes:
        _apply_payin_tx_hashes(deal, merged_hashes)

    # Слияние приходов Сбера: _sync_sber_claims забирает их из пула по payin_parts
    extra_uuids = [u for p in extra for u in p['sber_uuids']]
    if extra_uuids:
        base = []
        if deal.payin_parts:
            try:
                base = json.loads(deal.payin_parts) or []
            except (ValueError, TypeError):
                base = []
        known = {str(x.get('uuid')) for x in base if isinstance(x, dict) and x.get('uuid')}
        for uid in extra_uuids:
            if uid not in known:
                known.add(uid)
                base.append({'uuid': uid, 'amount_rub': None, 'payer': '',
                             'date': '', 'note': 'доп. приход'})
        deal.payin_parts = json.dumps(base, ensure_ascii=False)
        _sync_sber_claims(session, deal, base)


def _normalize_payout_transfers(raw):
    """Переводы отправки → [{'hash','amount_usdt','to_address','date'}].

    Адрес храним, чтобы в карточке и в форме было видно КУДА ушли деньги,
    а не только сколько.
    """
    out, seen = [], set()
    for item in (raw or []):
        if isinstance(item, str):
            h, amt, addr, date = item.strip(), None, '', ''
        elif isinstance(item, dict):
            h = str(item.get('hash') or item.get('tx_hash') or '').strip()
            amt = item.get('amount_usdt')
            addr = str(item.get('to_address') or '').strip()
            date = str(item.get('date') or '').strip()
        else:
            continue
        if not h or h in seen:
            continue
        seen.add(h)
        try:
            amt = float(amt) if amt not in (None, '') else None
        except (TypeError, ValueError):
            amt = None
        out.append({'hash': h, 'amount_usdt': amt, 'to_address': addr, 'date': date})
    return out


def _payout_hash_list(deal):
    """Хэши фактической отправки в компанию."""
    if not deal.payout_tx_hashes:
        return []
    try:
        return [x['hash'] for x in json.loads(deal.payout_tx_hashes) if x.get('hash')]
    except (ValueError, TypeError, KeyError, AttributeError):
        return []


def _payout_transfers_total(deal):
    """Сумма фактической отправки. None, если переводов нет или суммы не заданы."""
    if not deal.payout_tx_hashes:
        return None
    try:
        parts = json.loads(deal.payout_tx_hashes)
    except (ValueError, TypeError):
        return None
    amounts = [p.get('amount_usdt') for p in parts if p.get('amount_usdt') is not None]
    return round(sum(amounts), 2) if amounts else None


def _payin_hash_list(deal):
    """Все хэши Pay-In сделки: из JSON-списка, иначе одиночный payin_tx_hash."""
    if deal.payin_tx_hashes:
        try:
            return [x['hash'] for x in json.loads(deal.payin_tx_hashes) if x.get('hash')]
        except (ValueError, TypeError, KeyError, AttributeError):
            pass
    return [deal.payin_tx_hash] if deal.payin_tx_hash else []


def _payin_tx_parts(deal):
    """Хэши прихода сделки как [{hash, amount_usdt}] — вход для реестра долей."""
    if deal.payin_tx_hashes:
        try:
            return _normalize_tx_hashes(json.loads(deal.payin_tx_hashes))
        except (ValueError, TypeError):
            pass
    if deal.payin_tx_hash:
        return [{'hash': deal.payin_tx_hash, 'amount_usdt': deal.payin_amount_usdt}]
    return []


def _payin_tx_get_or_create(session, tx_hash, claim_usdt):
    """Перевод из реестра, при отсутствии — заводит.

    Сумму тянем из сети: она источник истины, по ней считается остаток и
    ловится попытка отнести больше пришедшего. Сеть не ответила — ставим
    заявленную долю и помечаем source='manual' («не сверено»), иначе первая
    же сделка не сохранилась бы из-за недоступного TronScan.
    """
    tx = session.query(PayinTx).filter(PayinTx.tx_hash == tx_hash).with_for_update().first()
    if tx:
        return tx
    amount, source = None, 'manual'
    try:
        chain = _tron_tx_usdt_amount(tx_hash)
        if chain and chain > 0:
            amount, source = chain, 'tronscan'
    except Exception as e:
        print(f'[PayinTx] сумма из сети недоступна для {tx_hash[:12]}…: {e}')
    tx = PayinTx(tx_hash=tx_hash, amount_usdt=amount or float(claim_usdt or 0),
                 source=source)
    session.add(tx)
    session.flush()
    return tx


def _sync_payin_tx_uses(session, deal, parts):
    """Синхронизирует доли сделки во входящих переводах.

    По образцу _sync_sber_claims: сперва снимаем доли, убранные из сделки,
    затем проставляем текущие. Инвариант — сумма долей по переводу не больше
    того, что пришло (допуск копейка). Превышение это двойной учёт: один и тот
    же приход попал бы в две сделки и раздул бы месяц.
    """
    wanted = {p['hash']: p.get('amount_usdt') for p in (parts or []) if p.get('hash')}

    # Снять доли, которых в сделке больше нет
    for use in session.query(PayinTxUse).filter(PayinTxUse.deal_id == deal.id).all():
        tx = session.query(PayinTx).get(use.tx_id)
        if not tx or tx.tx_hash not in wanted:
            session.delete(use)
    session.flush()

    for tx_hash, claim in wanted.items():
        tx = _payin_tx_get_or_create(session, tx_hash, claim)
        use = session.query(PayinTxUse).filter(
            PayinTxUse.tx_id == tx.id, PayinTxUse.deal_id == deal.id).first()
        # Долю не указали — считаем, что сделка забирает остаток перевода
        share = float(claim) if claim not in (None, '') else None
        if share is None:
            share = round((tx.amount_usdt or 0) - tx.used_usdt()
                          + (use.amount_usdt if use else 0), 2)
        if use:
            use.amount_usdt = share
        else:
            use = PayinTxUse(tx_id=tx.id, deal_id=deal.id, amount_usdt=share)
            session.add(use)
        session.flush()

        if tx.used_usdt() > (tx.amount_usdt or 0) + 0.01:
            if tx.source != 'tronscan':
                # Сумму перевода мы не знаем: сеть молчала, и она равна первой
                # заявленной доле. Отказывать по такому потолку нельзя — он
                # выдуман. Поднимаем сумму до разобранного и оставляем пометку,
                # что перевод с сетью не сверен.
                tx.amount_usdt = tx.used_usdt()
                tx.notes = (tx.notes or '') and tx.notes
                if not tx.notes:
                    tx.notes = 'сумма из CRM, с сетью не сверена'
                session.flush()
            else:
                free = round((tx.amount_usdt or 0) - tx.used_usdt() + share, 2)
                raise ValueError(
                    f'В переводе {tx_hash[:12]}… пришло ${tx.amount_usdt:,.2f}, '
                    f'свободно ${free:,.2f} — нельзя отнести ${share:,.2f}')


def _apply_payin_tx_hashes(deal, raw):
    """Пишет список хэшей в сделку. payin_tx_hash = первый — его читают
    легаси-отображения (карточка, выгрузка в Sheet, DealCloser)."""
    parts = _normalize_tx_hashes(raw)
    deal.payin_tx_hashes = json.dumps(parts, ensure_ascii=False) if parts else None
    if parts:
        deal.payin_tx_hash = parts[0]['hash']


def _find_referrer_by_code(db, code):
    """Ищет активного реферера по коду. Нормализует: GRED и GR-ED → один реферер.

    Возвращает Referrer или None. Единый резолвер для /set-referrer и создания
    сделки — чтобы код из DealCloser линковался так же, как при ручной привязке.
    """
    code = (code or '').strip().upper()
    if not code:
        return None
    referrer = db.query(Referrer).filter(Referrer.code == code, Referrer.active == True).first()
    if referrer:
        return referrer
    normalized = re.sub(r'[^A-Z0-9]', '', code)
    if not normalized:
        return None
    for r in db.query(Referrer).filter(Referrer.active == True).all():
        if re.sub(r'[^A-Z0-9]', '', r.code.upper()) == normalized:
            return r
    return None


@app.route('/api/deals/mf-realty/preview', methods=['POST'])
def preview_mf_realty():
    """Расчёт сделки через MF Corp без сохранения — для формы и проверок.

    Отдаёт разложение по карманам, выплаты партнёрам и подсказку
    «какой процент компании максимум, чтобы хватило на выплаты из крипты».
    """
    data = request.get_json() or {}
    try:
        actual = None
        parts = _normalize_payout_transfers(data.get('payout_tx_hashes'))
        amounts = [x['amount_usdt'] for x in parts if x['amount_usdt'] is not None]
        if amounts:
            actual = round(sum(amounts), 2)
        result = compute_mf_realty(
            data.get('invoice_amount_thb'), data.get('buy_rate_thb_usdt'),
            data.get('payin_amount_usdt'), sell_rate=data.get('sell_rate_thb_usdt'),
            company_percent=data.get('company_percent'),
            company_sent_thb=data.get('company_sent_thb'),
            agents=data.get('agents') or [], actual_cost_usdt=actual)
        result['suggested_company_percent'] = suggest_company_percent(
            data.get('invoice_amount_thb'), data.get('buy_rate_thb_usdt'),
            data.get('payin_amount_usdt'), agents=data.get('agents') or [],
            sell_rate=data.get('sell_rate_thb_usdt'), keep_usdt=data.get('keep_usdt') or 0)
    except (TypeError, ValueError) as e:
        return jsonify({'success': False, 'error': f'Некорректные данные: {e}'}), 400
    return jsonify({'success': True, 'result': result})


@app.route('/api/deals/mf-freehold/preview', methods=['POST'])
def preview_mf_freehold():
    """Расчёт сделки во фрихолде без сохранения — для формы.

    Показывает цепочку «приход → отправка → комиссия перевода → дойдёт
    застройщику» и прибыль после всех расходов вместе с выплатами агентам.
    """
    data = request.get_json() or {}
    try:
        sent = data.get('transfer_sent_usd')
        if sent in (None, ''):
            # Отмеченные переводы = факт отправки, поле «отправлено» можно не трогать
            parts = _normalize_payout_transfers(data.get('payout_tx_hashes'))
            amounts = [x['amount_usdt'] for x in parts if x['amount_usdt'] is not None]
            sent = round(sum(amounts), 2) if amounts else None
        result = compute_mf_freehold(
            data.get('payin_amount_usdt'),
            invoice_usd=data.get('invoice_amount_usd'),
            sent_usd=sent,
            fee_percent=data.get('transfer_fee_percent'),
            fee_fixed_usd=data.get('transfer_fee_fixed_usd'),
            agents=data.get('agents') or [])
    except (TypeError, ValueError) as e:
        return jsonify({'success': False, 'error': f'Некорректные данные: {e}'}), 400
    return jsonify({'success': True, 'result': result})


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
        
        # Одна сделка Битрикса — одна сделка здесь. Повторный клик «Закрыть WON»
        # и ретрай бота отдают уже созданную запись, а не плодят дубль (12.08:
        # кнопка после закрытия оставалась активной, WON записывался дважды).
        # Победа и «не деньги» (отказ, не обращение) считаются отдельно: сделку,
        # ошибочно закрытую отказом, можно перезакрыть в WON.
        is_non_deal = data.get('status') in [s.value for s in NON_DEAL_STATUSES]
        if data.get('bitrix_deal_id'):
            dup_query = session.query(Deal).filter(
                Deal.bitrix_deal_id == int(data['bitrix_deal_id']),
                Deal.status.in_(NON_DEAL_STATUSES) if is_non_deal
                else Deal.status.notin_(NON_DEAL_STATUSES),
            )
            existing_deal = dup_query.first()
            if existing_deal:
                return jsonify({'success': True, 'deal': existing_deal.to_dict(), 'duplicate': True}), 200

        # Автоматически создаём клиента если указано имя и такого клиента ещё нет
        client_id = data.get('client_id')
        client_name = data.get('client_name')

        if not client_id and client_name:
            # Нормализуем имя: trim + регистронезависимый поиск, иначе «Иван»,
            # «иван » и «ИВАН» создавали 3 разных клиента и размазывали статистику.
            client_name = client_name.strip()
            existing_client = session.query(Client).filter(Client.name.ilike(client_name)).first()
            if not existing_client:
                # Для отказа и «не обращения» клиента НЕ создаём (замусорит базу
                # непокупателями), матчинг revive идёт по client_name.
                if not is_non_deal:
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
        ref_comp_model = data.get('referrer_comp_model')
        ref_markup_percent = data.get('referrer_markup_percent')
        ref_fixed_usdt = data.get('referrer_fixed_usdt')
        # Реферер пришёл кодом (DealCloser шлёт "GR-INSIGH" в referrer_name) —
        # резолвим в профиль, иначе сделка оставалась бы с текстовым именем без
        # referrer_id: не попадала в кабинет реферера и без начисления.
        # Код не нашёлся → оставляем текстом (как было), это ручная пометка.
        if ref_name and not ref_id and not is_non_deal:
            referrer = _find_referrer_by_code(session, ref_name)
            if referrer and not (referrer.client_id and referrer.client_id == client_id):
                ref_id = referrer.id
                ref_name = referrer.name
                if ref_percent is None:
                    ref_percent = referrer.default_percent
                ref_comp_model = ref_comp_model or referrer.comp_model
                if ref_markup_percent is None:
                    ref_markup_percent = referrer.markup_percent
        if client_id and not ref_name and not is_non_deal:
            client_obj = session.query(Client).get(client_id)
            if client_obj and client_obj.referrer_id:
                referrer = session.query(Referrer).get(client_obj.referrer_id)
                if referrer and referrer.active:
                    # Защита от самореферала: не начислять если клиент = реферер
                    if not (referrer.client_id and referrer.client_id == client_id):
                        ref_id = referrer.id
                        ref_name = referrer.name
                        ref_percent = referrer.default_percent
                        ref_comp_model = ref_comp_model or referrer.comp_model
                        if ref_markup_percent is None:
                            ref_markup_percent = referrer.markup_percent
        # Реферер выбран явно (ref_id передан): недостающие снапшот модели и имя — из профиля
        if ref_id and (not ref_comp_model or not ref_name):
            ref_obj = session.query(Referrer).get(ref_id)
            if ref_obj:
                ref_name = ref_name or ref_obj.name
                if not ref_comp_model:
                    ref_comp_model = ref_obj.comp_model or 'revshare'
                    if ref_markup_percent is None:
                        ref_markup_percent = ref_obj.markup_percent

        # Умный дефолт needs_reimbursement:
        # если payout не в THB (USDT/RUB/USD) — возмещение не нужно
        # (фаундер не тратил наличные THB из кармана)
        if 'needs_reimbursement' in data:
            needs_reimb = bool(data.get('needs_reimbursement'))
        elif data.get('payout_source') == PayOutSource.BANK_CARD.value:
            # Баты с карты откуплены заранее, при её пополнении — возмещать нечего
            needs_reimb = False
        else:
            payout_is_thb = (
                bool(data.get('payout_amount_thb'))
                or data.get('custom_payout_currency') == 'THB'
            )
            needs_reimb = payout_is_thb

        deal = Deal(
            created_at=created_at,
            manager_name=data.get('manager_name'),
            deal_type=DealType(data.get('deal_type', 'pay_in')),
            status=DealStatus(data.get('status', 'pending')),
            is_test=bool(data.get('is_test', False)),
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
            bank_card_id=data.get('bank_card_id') or None,
            payout_amount_thb=data.get('payout_amount_thb'),
            payout_amount_usdt=data.get('payout_amount_usdt'),
            payout_tx_hash=data.get('payout_tx_hash'),
            payout_founder_name=data.get('payout_founder_name'),
            referrer_id=ref_id,
            referrer_name=ref_name,
            referrer_percent=ref_percent,
            referrer_payout_usdt=data.get('referrer_payout_usdt'),
            referrer_comp_model=ref_comp_model,
            referrer_markup_percent=ref_markup_percent,
            referrer_fixed_usdt=ref_fixed_usdt,
            profit_usdt=data.get('profit_usdt'),
            profit_percent=data.get('profit_percent'),
            net_profit_usdt=data.get('net_profit_usdt'),
            needs_reimbursement=needs_reimb,
            is_custom=data.get('is_custom', False),
            custom_payin_currency=data.get('custom_payin_currency'),
            custom_payin_amount=data.get('custom_payin_amount'),
            custom_payin_rate=data.get('custom_payin_rate'),
            custom_payout_currency=data.get('custom_payout_currency'),
            custom_payout_amount=data.get('custom_payout_amount'),
            custom_payout_rate=data.get('custom_payout_rate'),
            payin_parts=json.dumps(data['payin_parts'], ensure_ascii=False) if data.get('payin_parts') else None,
            deal_kind=(data.get('deal_kind') or None),
            lose_reason=(data.get('lose_reason') or None),
            bitrix_deal_id=int(data['bitrix_deal_id']) if data.get('bitrix_deal_id') else None,
            source_channel=(data.get('source_channel') or '').strip()[:50] or None,
            notes=data.get('notes')
        )
        # Приход крипты частями: несколько хэшей на одну сделку
        if data.get('payin_tx_hashes'):
            _apply_payin_tx_hashes(deal, data['payin_tx_hashes'])

        session.add(deal)
        session.flush()

        # Выдача с карты: снимаем баты с остатка и берём себестоимость по курсу
        # карты. Обязательно до пересчёта финансов — прибыль считается из неё
        card_warning = _sync_card_allocation(session, deal)

        # Забор приходов Сбера из пула под части сделки (sber_reqs)
        if data.get('payin_parts'):
            _sync_sber_claims(session, deal, data['payin_parts'])

        # Дополнительные приходы: плоские поля выше приняли суммы ОСНОВНОЙ части,
        # здесь они превращаются в агрегаты по всей сделке. Должно идти ДО
        # пересчёта финансов — прибыль и выплаты считаются от итогового прихода.
        if data.get('payin_extra'):
            _apply_payin_extra(session, deal, data['payin_extra'],
                               main_usdt=data.get('payin_amount_usdt'),
                               main_rub=data.get('payin_amount_rub'))

        # Доли сделки во входящих переводах: один перевод может обслуживать
        # несколько сделок, поэтому учёт ведётся реестром, а не флагом «занят»
        if deal.payin_tx_hashes or deal.payin_tx_hash:
            _sync_payin_tx_uses(session, deal, _payin_tx_parts(deal))

        # Пересчёт выплаты рефереру и чистой прибыли (фронт мог не знать
        # об авто-привязке реферера к клиенту и прислать referrer_payout_usdt=null)
        # Для отказа и «не обращения» финансов нет — пропускаем пересчёт и агентов.
        if not is_non_deal:
            # Недвижимость через MF Corp считается по своим формулам (два кармана),
            # обычный пересчёт прибыли для неё не подходит
            if deal.deal_kind == MF_REALTY_KIND:
                _apply_mf_realty(deal, data)
            elif deal.deal_kind == MF_FREEHOLD_KIND:
                _apply_mf_freehold(deal, data)
            else:
                _recalculate_deal_financials(deal, data)

            # Мультиагенты: явный массив agents → каскадный пересчёт; иначе зеркалим
            # одиночного реферала (без пересчёта) для единого источника кабинета
            if data.get('agents'):
                _apply_deal_agents(session, deal, data['agents'])
            elif deal.deal_kind in REALTY_KINDS:
                _apply_deal_agents(session, deal, [])  # проставит остаток и чистый доход
            else:
                _mirror_legacy_agent(session, deal)

        _clear_profit_if_payin_unknown(deal)

        # Выдача с карты завершена в момент создания: возмещения ждать не надо.
        # Но «прибыль известна» — только когда приход тоже посчитан в USDT.
        # У СБП приход рублёвый, USDT появляется после конвертации: закрыть
        # такую сделку сразу = прибыль равна минус всей выплате (#519: −319.20
        # при 30 750.72 ₽ прихода) и уведомление с этим минусом уходит в TG.
        # Пока payin_amount_usdt пуст — держим pending, закроется в PUT.
        if (deal.payout_source == PayOutSource.BANK_CARD
                and deal.status == DealStatus.PENDING
                and deal.payout_amount_usdt
                and deal.payin_amount_usdt):
            deal.status = DealStatus.COMPLETED

        # Тип недвижимости без своих полей — протёкшее состояние формы, не сделка
        realty_error = realty_payload_error(deal)
        if realty_error:
            session.rollback()
            return jsonify({'success': False, 'error': realty_error}), 400

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

        # Недвижимость (лизхолд/фрихолд): прибыль известна сразу (возмещения нет),
        # поэтому выгружаем и уведомляем не дожидаясь статуса completed
        if deal.deal_kind in REALTY_KINDS and not skip_sync:
            try:
                sync_realty_deal_to_gsheet(deal)
            except Exception as e:
                print(f'[GSheet realty] sync error on create: {e}')
            # Только для сразу завершённых: сделку в pending уведомит «Завершить»,
            # иначе одно и то же уведомление придёт дважды
            if deal.status == DealStatus.COMPLETED:
                try:
                    _send_deal_telegram(deal)
                except Exception as e:
                    print(f'[Telegram] realty error on create: {e}')

        if deal.status == DealStatus.COMPLETED and not skip_sync and deal.deal_kind not in REALTY_KINDS:
            send_deal_completed_webhook(deal)
            notify_agents_new_deal(session, deal)  # DM реферерам-агентам сделки
            # GSheet + Telegram для завершённых сделок с рассчитанной прибылью
            if deal.profit_usdt is not None:
                try:
                    sync_deals_to_gsheet([deal])
                except Exception as e:
                    print(f'[GSheet] Sync error on create: {e}')
                try:
                    sync_referrer_reward_to_gsheet(deal)
                except Exception as e:
                    print(f'[GSheet] Referrer sync error on create: {e}')
                try:
                    _send_deal_telegram(deal)
                except Exception as e:
                    print(f'[Telegram] Error on create: {e}')

        payload = {'success': True, 'deal': deal.to_dict()}
        if card_warning:
            payload['warning'] = card_warning
        return jsonify(payload), 201
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        session.rollback()
        app.logger.error(f'[create_deal] error: {e}\n{tb}')
        print(f'[create_deal] error: {e}\n{tb}', flush=True)
        return jsonify({'success': False, 'error': f'Ошибка обработки запроса: {type(e).__name__}: {e}'}), 400
    finally:
        session.close()

@app.route('/api/deals/<int:deal_id>', methods=['PUT'])
def update_deal(deal_id):
    session = get_session()
    try:
        # CR-05: блокировка строки сделки. Защищает upsert WalletOperation ниже
        # (раньше два параллельных PUT могли создать две expense-операции, потому
        # что оба прошли через `if not existing_op:` до commit'а другого).
        deal = session.query(Deal).filter(Deal.id == deal_id).with_for_update().first()
        if not deal:
            return jsonify({'success': False, 'error': 'Сделка не найдена'}), 404
        
        data = request.get_json()
        old_status = deal.status
        old_kind = deal.deal_kind
        
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
                      'referrer_paid', 'referrer_comp_model', 'referrer_markup_percent',
                      'notes', 'client_id',
                      'payout_founder_name', 'payout_wallet_id',
                      'is_custom', 'custom_payin_currency', 'custom_payin_amount', 'custom_payin_rate',
                      'custom_payout_currency', 'custom_payout_amount', 'custom_payout_rate',
                      'needs_reimbursement', 'source_channel']:
            if field in data:
                setattr(deal, field, data[field])

        # Части прихода Сбера (sber_reqs): JSON + синхронизация пула
        if 'payin_parts' in data:
            parts = data.get('payin_parts') or []
            deal.payin_parts = json.dumps(parts, ensure_ascii=False) if parts else None
            _sync_sber_claims(session, deal, parts)

        # Приход крипты частями: пустой список = вернуться к одиночному хэшу из формы
        if 'payin_tx_hashes' in data:
            _apply_payin_tx_hashes(deal, data.get('payin_tx_hashes'))
            _sync_payin_tx_uses(session, deal, _payin_tx_parts(deal))

        # Дополнительные приходы. Суммы основной части вычисляем ДО записи
        # агрегатов: если поле не пришло в payload, восстанавливаем её вычитанием
        # СТАРЫХ дополнительных из сохранённого итога — иначе приход поедет вверх
        # на каждом PUT без payin_extra (интеграции их не шлют).
        if 'payin_extra' in data or deal.payin_extra:
            old_extra = _payin_extra_list(deal)
            old_usdt = sum(p.get('amount_usdt') or 0 for p in old_extra)
            old_rub = sum(p.get('amount_rub') or 0 for p in old_extra)
            main_usdt = (data['payin_amount_usdt'] if 'payin_amount_usdt' in data
                         else round((deal.payin_amount_usdt or 0) - old_usdt, 6))
            main_rub = (data['payin_amount_rub'] if 'payin_amount_rub' in data
                        else round((deal.payin_amount_rub or 0) - old_rub, 6))
            _apply_payin_extra(session, deal,
                               data.get('payin_extra', old_extra),
                               main_usdt=main_usdt, main_rub=main_rub)

        # Пересчёт needs_reimbursement если не передан явно, но изменился payout_amount_thb
        if 'needs_reimbursement' not in data and deal.reimbursement_id is None:
            if (data.get('payout_source') or (deal.payout_source.value if deal.payout_source else None)) == PayOutSource.BANK_CARD.value:
                deal.needs_reimbursement = False  # баты с карты уже откуплены
            else:
                payout_is_thb = bool(deal.payout_amount_thb) or deal.custom_payout_currency == 'THB'
                deal.needs_reimbursement = payout_is_thb
        
        # Обновляем Enum поля
        if 'payin_method' in data:
            deal.payin_method = PayInMethod(data['payin_method']) if data['payin_method'] else None
        if 'payout_method' in data:
            deal.payout_method = PayOutMethod(data['payout_method']) if data['payout_method'] else None
        if 'payout_source' in data:
            old_payout_source = deal.payout_source
            deal.payout_source = PayOutSource(data['payout_source']) if data['payout_source'] else None
            # Если источник сменили на founder_personal и возмещения ещё нет →
            # сделка ожидает возмещения, переводим в pending (как заявил
            # пользователь: смена метода выплаты на «карман фаундера» = ждём
            # возмещения, статус pending). Другие изменения статус не трогают.
            if (deal.payout_source == PayOutSource.FOUNDER_PERSONAL
                and old_payout_source != PayOutSource.FOUNDER_PERSONAL
                and deal.reimbursement_id is None):
                deal.status = DealStatus.PENDING

        if 'bank_card_id' in data:
            # Пустое значение при неизменном источнике «карта» не трогает привязку:
            # карта с нулевым остатком выпадает из дропдауна (/api/cards/balance
            # отдаёт только balance_thb > 0), и форма пришлёт пустое поле — тихо
            # отвязывать сделку от карты из-за этого нельзя
            new_card_id = data['bank_card_id'] or None
            keep_existing = (new_card_id is None and deal.bank_card_id
                             and deal.payout_source == PayOutSource.BANK_CARD)
            if not keep_existing:
                deal.bank_card_id = new_card_id

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

        # Если имя клиента изменилось — НЕ переименовываем глобально Client
        # (это бы изменило имя во всех его сделках), а перепривязываем эту
        # конкретную сделку к другому клиенту (find-or-create).
        client_name_val = data.get('client_name')
        if client_name_val and str(client_name_val).strip() != "" and deal.client_id:
            new_name = str(client_name_val).strip()
            current_client = session.query(Client).filter(Client.id == deal.client_id).first()
            if current_client and current_client.name != new_name:
                existing = session.query(Client).filter(Client.name.ilike(new_name)).first()
                if existing:
                    deal.client_id = existing.id
                else:
                    new_client = Client(name=new_name)
                    session.add(new_client)
                    session.flush()
                    deal.client_id = new_client.id
            deal.client_name = new_name
        
        # Если пришел новый client_id, просто привязываем
        if 'client_id' in data:
            deal.client_id = data['client_id']
        
        if 'status' in data:
            deal.status = DealStatus(data['status'])
            # LOSE, вручную переведённый в реальную сделку, выходит из revive-привязки
            if deal.status != DealStatus.LOSE and deal.revived_by_deal_id:
                deal.revived_by_deal_id = None

        if 'deal_kind' in data:
            deal.deal_kind = data.get('deal_kind') or None

        # Автоматический пересчёт прибыли и выплаты рефереру.
        # Недвижимость — по своим формулам (лизхолд: два кармана; фрихолд: расходы
        # на перевод внутри отправки), обычный расчёт для них не подходит.
        if deal.deal_kind in REALTY_KINDS:
            if deal.deal_kind == MF_REALTY_KIND:
                _apply_mf_realty(deal, data)
            else:
                _apply_mf_freehold(deal, data)
            if 'agents' not in data:
                _apply_deal_agents(session, deal, [
                    {'referrer_id': r.referrer_id, 'name': r.name, 'tier': r.tier,
                     'comp_model': r.comp_model, 'percent': r.percent,
                     'fixed_usdt': r.fixed_usdt}
                    for r in sorted(deal.agents, key=lambda x: (x.tier or 1, x.id or 0))
                ])
        else:
            _recalculate_deal_financials(deal, data)

        # Мультиагенты: явный массив agents → каскадный пересчёт (пустой = убрать всех);
        # без массива → зеркалим одиночного реферала (сохраняя ручной payout)
        if 'agents' in data:
            if data.get('agents'):
                _apply_deal_agents(session, deal, data['agents'])
            else:
                # Явное удаление всех агентов из формы. Чистим и мультиагентов,
                # и легаси-реферера (referrer_name/id и снапшоты) — иначе партнёр
                # остаётся в referrer_name и продолжает светиться в списке сделок,
                # хотя в форме его убрали (кейс #429 GR-KARIM).
                _apply_deal_agents(session, deal, [])
                deal.referrer_id = None
                deal.referrer_name = None
                deal.referrer_percent = None
                deal.referrer_markup_percent = None
                deal.referrer_comp_model = None
        elif deal.deal_kind not in REALTY_KINDS:
            # У недвижимости агенты уже пересчитаны выше вместе с прибылью
            _mirror_legacy_agent(session, deal)

        realty_error = realty_payload_error(deal)
        if realty_error:
            session.rollback()
            return jsonify({'success': False, 'error': realty_error}), 400

        _clear_profit_if_payin_unknown(deal)

        # Выдача с карты: пересобираем расход под текущее состояние сделки
        card_warning = _sync_card_allocation(session, deal)

        # Приход досчитали в USDT — себестоимость известна, сделка закрывается
        # сама, а webhook / DM агентам / GSheet / Telegram уходят общей веткой
        # ниже (по переходу old_status → COMPLETED). Явный status в payload
        # приоритетнее: решение оператора не перебиваем.
        if ('status' not in data
                and deal.payout_source == PayOutSource.BANK_CARD
                and deal.status == DealStatus.PENDING
                and deal.payin_amount_usdt
                and deal.payout_amount_usdt):
            deal.status = DealStatus.COMPLETED

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

        # Недвижимость: правки догоняют таблицу через upsert по CRM ID,
        # дубли строк не появляются
        if deal.deal_kind in REALTY_KINDS:
            try:
                sync_realty_deal_to_gsheet(deal)
            except Exception as e:
                print(f'[GSheet realty] sync error on update: {e}')
            # Уведомление шлём при завершении — как у обычных сделок, оператор
            # ждёт его именно после «Завершить». Второй случай: обычную сделку
            # переделали в сделку по недвижимости, тогда уведомления ещё не было
            became_mf = old_kind != deal.deal_kind
            just_done = (deal.status == DealStatus.COMPLETED
                         and old_status != DealStatus.COMPLETED)
            if just_done or (became_mf and deal.status == DealStatus.COMPLETED):
                try:
                    _send_deal_telegram(deal)
                except Exception as e:
                    print(f'[Telegram] realty error on update: {e}')

        # Webhook при завершении
        if (deal.status == DealStatus.COMPLETED and old_status != DealStatus.COMPLETED
                and deal.deal_kind not in REALTY_KINDS):
            send_deal_completed_webhook(deal)
            notify_agents_new_deal(session, deal)  # DM реферерам-агентам сделки
            # GSheet + Telegram только если сделка ещё НЕ была возмещена
            # (возмещение уже отправило уведомления при create_reimbursement)
            if deal.profit_usdt is not None and deal.reimbursement_id is None:
                try:
                    sync_deals_to_gsheet([deal])
                except Exception as e:
                    print(f'[GSheet] Sync error on complete: {e}')
                try:
                    sync_referrer_reward_to_gsheet(deal)
                except Exception as e:
                    print(f'[GSheet] Referrer sync error on complete: {e}')
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

        payload = {'success': True, 'deal': deal.to_dict()}
        if card_warning:
            payload['warning'] = card_warning
        return jsonify(payload)
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        session.rollback()
        app.logger.error(f'[update_deal] error: {e}\n{tb}')
        print(f'[update_deal] error: {e}\n{tb}', flush=True)
        return jsonify({'success': False, 'error': f'Ошибка обработки запроса: {type(e).__name__}: {e}'}), 400
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
        deal_referrer_id = deal.referrer_id
        deal_id_snapshot = deal.id

        # Удаляем связанные операции по кошелькам (Binance списания)
        session.query(WalletOperation).filter(WalletOperation.deal_id == deal_id).delete()

        # Возвращаем батам карту: удалить аллокацию мало, остаток тоже надо вернуть,
        # иначе удаление сделки навсегда съедает деньги с карты
        for alloc in session.query(CardAllocation).filter(CardAllocation.deal_id == deal_id).all():
            card = session.query(BankCard).filter(BankCard.id == alloc.card_id).with_for_update().first()
            if card:
                card.balance_thb = round((card.balance_thb or 0) + alloc.amount_thb, 2)
            session.delete(alloc)

        # Освобождаем забранные приходы Сбера (иначе FK claimed_deal_id заблокирует удаление)
        session.query(SberIncome).filter(SberIncome.claimed_deal_id == deal_id).update(
            {'claimed_deal_id': None, 'claimed_at': None})

        # Снимаем доли сделки во входящих переводах. Без этого FK
        # payin_tx_uses_deal_id_fkey не даёт удалить сделку вовсе, а сама доля
        # осталась бы висеть и занимать остаток перевода
        session.query(PayinTxUse).filter(PayinTxUse.deal_id == deal_id).delete()

        # Отвязываем LOSE, привязанные к этой WON (иначе FK revived_by_deal_id заблокирует удаление)
        session.query(Deal).filter(Deal.revived_by_deal_id == deal_id).update(
            {'revived_by_deal_id': None})

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
            stub.id = deal_id_snapshot
            stub.referrer_id = deal_referrer_id
            delete_deal_from_gsheet(stub)
            if deal_referrer_id:
                try:
                    delete_referrer_reward_from_gsheet(stub)
                except Exception as e:
                    print(f'[GSheet] Referrer delete error: {e}')

        return jsonify({'success': True})
    except Exception as e:
        session.rollback()
        # Error logged internally
        app.logger.error(f'Request error: {e}')
        return jsonify({'success': False, 'error': 'Ошибка обработки запроса'}), 400
    finally:
        session.close()

# ==================== CRM API - LOSE / REVIVE / CONVERSION ====================

@app.route('/api/deals/lose-candidates', methods=['GET'])
def get_lose_candidates():
    """Непривязанные LOSE-сделки клиента — кандидаты на revive при закрытии WON.

    Матчинг: точное имя без регистра (Deal.client_name) + client_id, если клиент найден.
    """
    client_name = (request.args.get('client_name') or '').strip()
    if not client_name:
        return jsonify({'success': False, 'error': 'client_name обязателен'}), 400
    session = get_session()
    try:
        # Матчим в Python: SQL ilike/lower не понижают кириллицу в SQLite,
        # а LOSE-таблица маленькая — тянем все непривязанные и фильтруем.
        name_cf = client_name.casefold()
        client = session.query(Client).filter(Client.name.ilike(client_name)).first()
        all_unrevived = session.query(Deal).filter(
            Deal.status == DealStatus.LOSE,
            Deal.revived_by_deal_id == None,
            Deal.is_test.isnot(True),
        ).order_by(Deal.created_at.desc()).all()
        candidates = [d for d in all_unrevived if (
            (d.client_name and d.client_name.strip().casefold() == name_cf)
            or (client and d.client_id == client.id)
        )][:20]
        return jsonify({'success': True, 'candidates': [{
            'id': d.id,
            'created_at': d.created_at.isoformat() if d.created_at else None,
            'lose_reason': d.lose_reason,
            'payin_amount_rub': d.payin_amount_rub,
            'payin_amount_usdt': d.payin_amount_usdt,
            'bitrix_deal_id': d.bitrix_deal_id,
        } for d in candidates]})
    finally:
        session.close()


@app.route('/api/deals/<int:won_id>/revive', methods=['POST'])
def revive_loses(won_id):
    """Привязать LOSE-сделки к выигрышной: клиент «ожил» и дошёл до сделки.

    LOSE выходят из знаменателя конверсии, становясь касаниями WON-эпизода.
    """
    session = get_session()
    try:
        data = request.get_json() or {}
        lose_ids = data.get('lose_ids') or []
        if not lose_ids:
            return jsonify({'success': False, 'error': 'lose_ids обязателен'}), 400
        won = session.query(Deal).filter(Deal.id == won_id).first()
        if not won:
            return jsonify({'success': False, 'error': 'Сделка не найдена'}), 404
        if won.status in (DealStatus.LOSE, DealStatus.CANCELLED):
            return jsonify({'success': False, 'error': 'Нельзя привязать LOSE к lose/cancelled сделке'}), 400
        revived = []
        for lid in lose_ids:
            lose = session.query(Deal).filter(Deal.id == int(lid)).first()
            if not lose or lose.status != DealStatus.LOSE:
                return jsonify({'success': False, 'error': f'#{lid} не LOSE-сделка'}), 400
            if lose.revived_by_deal_id and lose.revived_by_deal_id != won_id:
                return jsonify({'success': False, 'error': f'#{lid} уже привязана к #{lose.revived_by_deal_id}'}), 400
            lose.revived_by_deal_id = won_id
            revived.append(lose.id)
        session.commit()
        return jsonify({'success': True, 'revived': revived})
    except Exception as e:
        session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        session.close()


@app.route('/api/deals/<int:won_id>/unrevive', methods=['POST'])
def unrevive_loses(won_id):
    """Откатить ошибочную revive-привязку. Пустой lose_ids = отвязать все."""
    session = get_session()
    try:
        data = request.get_json() or {}
        lose_ids = data.get('lose_ids') or []
        q = session.query(Deal).filter(Deal.revived_by_deal_id == won_id)
        if lose_ids:
            q = q.filter(Deal.id.in_([int(i) for i in lose_ids]))
        count = q.update({'revived_by_deal_id': None}, synchronize_session=False)
        session.commit()
        return jsonify({'success': True, 'unrevived': count})
    except Exception as e:
        session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        session.close()


@app.route('/api/analytics/conversion', methods=['GET'])
def analytics_conversion():
    """Конверсия по Красинскому: CR = купившие эпизоды / все эпизоды.

    Эпизод = обращение клиента. WON-эпизод = completed/verified сделка + её
    revive-привязанные LOSE (касания). Проигранный эпизод = каждый непривязанный
    LOSE. Когорта — месяц ПЕРВОГО касания эпизода. Новый/повторный: была ли у
    клиента победа до первого касания. CR новых — главная метрика.
    """
    session = get_session()
    try:
        months = max(1, min(int(request.args.get('months', 12)), 36))
        now = datetime.now()
        # Начало окна — первое число (now - months + 1)-го месяца
        start_year = now.year + (now.month - months) // 12
        start_month = (now.month - months) % 12 + 1
        window_start = datetime(start_year, start_month, 1)

        won_statuses = (DealStatus.COMPLETED, DealStatus.VERIFIED)
        # Тянем все сделки: когорта первого касания и repeat-детект смотрят
        # в прошлое за пределы окна. Объём таблицы малый (сотни строк).
        all_deals = session.query(Deal).filter(
            Deal.status.in_(list(won_statuses) + [DealStatus.LOSE]),
            Deal.is_test.isnot(True),
        ).all()

        def identity(d):
            """Идентичность клиента: client_id либо имя без регистра."""
            if d.client_id:
                return f'c{d.client_id}'
            if d.client_name and d.client_name.strip():
                return f'n{d.client_name.strip().lower()}'
            return f'd{d.id}'  # аноним — каждый сам себе клиент

        wins = [d for d in all_deals if d.status in won_statuses and d.created_at]
        loses = [d for d in all_deals if d.status == DealStatus.LOSE and d.created_at]
        loses_by_win = {}
        for l in loses:
            if l.revived_by_deal_id:
                loses_by_win.setdefault(l.revived_by_deal_id, []).append(l)

        # Даты побед по клиенту — для repeat-детекта
        win_dates = {}
        for w in wins:
            win_dates.setdefault(identity(w), []).append(w.created_at)

        episodes = []
        for w in wins:
            linked = loses_by_win.get(w.id, [])
            first_touch = min([w.created_at] + [l.created_at for l in linked])
            episodes.append({'ident': identity(w), 'first_touch': first_touch,
                             'won': True, 'touches': 1 + len(linked)})
        for l in loses:
            if not l.revived_by_deal_id:
                episodes.append({'ident': identity(l), 'first_touch': l.created_at,
                                 'won': False, 'touches': 1})

        for ep in episodes:
            # Повторный = была победа СТРОГО раньше первого касания эпизода
            ep['repeat'] = any(d < ep['first_touch'] for d in win_dates.get(ep['ident'], []))

        # Средняя прибыль completed в окне — оценка потерь в деньгах
        window_profits = [w.profit_usdt for w in wins
                          if w.created_at >= window_start and w.profit_usdt is not None]
        avg_profit = round(sum(window_profits) / len(window_profits), 2) if window_profits else 0

        monthly = {}
        for ep in episodes:
            if ep['first_touch'] < window_start:
                continue
            key = ep['first_touch'].strftime('%Y-%m')
            m = monthly.setdefault(key, {
                'month': key, 'new_total': 0, 'new_won': 0, 'repeat_total': 0,
                'repeat_won': 0, 'lost_episodes': 0, 'touches_sum': 0, 'touches_won': 0,
            })
            kind = 'repeat' if ep['repeat'] else 'new'
            m[f'{kind}_total'] += 1
            if ep['won']:
                m[f'{kind}_won'] += 1
                m['touches_sum'] += ep['touches']
                m['touches_won'] += 1
            else:
                m['lost_episodes'] += 1

        rows = []
        for key in sorted(monthly.keys()):
            m = monthly[key]
            m['new_cr'] = round(m['new_won'] / m['new_total'] * 100, 1) if m['new_total'] else None
            m['repeat_cr'] = round(m['repeat_won'] / m['repeat_total'] * 100, 1) if m['repeat_total'] else None
            m['avg_touches_to_won'] = round(m['touches_sum'] / m['touches_won'], 2) if m['touches_won'] else None
            m['lost_profit_est_usdt'] = round(m['lost_episodes'] * avg_profit, 2)
            del m['touches_sum'], m['touches_won']
            rows.append(m)

        in_window = [ep for ep in episodes if ep['first_touch'] >= window_start]

        def _totals(subset):
            total = len(subset)
            won = sum(1 for e in subset if e['won'])
            return {'total': total, 'won': won,
                    'cr': round(won / total * 100, 1) if total else None}

        lost_count = sum(1 for e in in_window if not e['won'])
        totals = {
            'new': _totals([e for e in in_window if not e['repeat']]),
            'repeat': _totals([e for e in in_window if e['repeat']]),
            'lost_episodes': lost_count,
            'avg_profit_usdt': avg_profit,
            'lost_profit_est_usdt': round(lost_count * avg_profit, 2),
        }

        lose_list = [{
            'id': l.id,
            'client_name': l.client_name,
            'created_at': l.created_at.isoformat() if l.created_at else None,
            'lose_reason': l.lose_reason,
            'revived_by_deal_id': l.revived_by_deal_id,
        } for l in sorted(loses, key=lambda x: x.created_at, reverse=True)
            if l.created_at >= window_start]

        return jsonify({'success': True, 'months': rows, 'totals': totals,
                        'lose_list': lose_list})
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
        amount_thb = parse_float(data.get('amount_thb'))
        cost_usdt = parse_float(data.get('cost_usdt'))

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

        # Адрес-двойник (× вместо x и прочие гомоглифы) чиним здесь, а не только
        # в форме: кошелёк заводят и через API, и кривой адрес потом навсегда
        # ломает сверку — TronScan такого адреса не знает.
        # Виртуальные кошельки (просто имя вместо адреса) не трогаем.
        if address.startswith('T') and len(address) >= 30:
            fixed_address, fixes = normalize_tron_address(address)
            problem = tron_address_problem(fixed_address)
            if problem:
                return jsonify({'success': False, 'error': problem}), 400
            if fixes:
                app.logger.info(f'[Wallet] адрес поправлен: {address} → {fixed_address}')
            address = fixed_address

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

USDT_TRC20_CONTRACT = 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t'


def _tron_balances(address):
    """Балансы адреса TRON: (usdt, trx). None — если адрес не читается.

    Тот же источник, что и в add_wallet, вынесен отдельно: баланс нужен ещё
    и до создания кошелька — менеджер вводит адрес, а начальный остаток
    подтягивается из сети, чтобы не вбивать руками (и не ошибаться).
    """
    try:
        # Ретрай на 429: с одного IP сюда же ходит фоновый прогрев кэша, и без
        # него баланс молча оказывался «непрочитанным» (кейс 10.08, кошелёк #14)
        for attempt in range(3):
            r = requests.get(f'https://apilist.tronscanapi.com/api/account?address={address}',
                             headers=_TRONSCAN_HEADERS, timeout=8)
            if r.status_code != 429:
                break
            time.sleep(2 * (attempt + 1))
        if r.status_code != 200:
            app.logger.warning(f'TronScan balance HTTP {r.status_code} for {address}')
            return None
        data = r.json()
        if not data or not data.get('address'):
            return None
        trx = float(data.get('balance', 0)) / 1_000_000
        usdt = 0.0
        for token in data.get('trc20token_balances', []) or []:
            if token.get('tokenId') == USDT_TRC20_CONTRACT:
                usdt = float(token.get('balance', 0)) / 1_000_000
                break
        return usdt, trx
    except Exception as e:
        app.logger.warning(f'TronScan balance error for {address}: {e}')
        return None


TRON_B58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'

# Похожие на глаз символы, которые приезжают вместе с адресом из мессенджеров
# и заметок. Классика — «5x5» превращается автозаменой в «5×5»: длина та же,
# начинается с T, поэтому проверка «T + 34 символа» пропускает, а TronScan
# отвечает «адрес не найден», и виноватым выглядит TronScan (кейс 10.08).
TRON_HOMOGLYPHS = {
    '×': 'x', '✕': 'x', '✖': 'x',
    'А': 'A', 'В': 'B', 'Е': 'E', 'К': 'K', 'М': 'M', 'Н': 'H', 'О': 'O',
    'Р': 'P', 'С': 'C', 'Т': 'T', 'У': 'Y', 'Х': 'X',
    'а': 'a', 'е': 'e', 'о': 'o', 'р': 'p', 'с': 'c', 'у': 'y', 'х': 'x',
    ' ': '', '​': '', '–': '', '—': '',
}


def normalize_tron_address(raw):
    """Чинит подменённые символы. Возвращает (адрес, [(позиция, было, стало)])."""
    addr = (raw or '').strip()
    fixes = []
    out = []
    for i, ch in enumerate(addr):
        if ch in TRON_HOMOGLYPHS:
            repl = TRON_HOMOGLYPHS[ch]
            fixes.append({'pos': i + 1, 'from': ch, 'to': repl})
            out.append(repl)
        else:
            out.append(ch)
    return ''.join(out), fixes


def tron_address_problem(addr):
    """Что не так с адресом. None — адрес корректен (включая контрольную сумму).

    Base58Check ловит и опечатку в одном символе, а не только длину: без этой
    проверки «похожий, но чужой» адрес уходил бы в сеть и возвращался как
    «не найден», хотя проблема ровно в вводе.
    """
    if not addr:
        return 'Сначала введи адрес кошелька'
    if not addr.startswith('T'):
        return 'Адрес TRON начинается с T'
    if len(addr) != 34:
        return f'В адресе TRON 34 символа, здесь {len(addr)}'
    bad = [(i + 1, c) for i, c in enumerate(addr) if c not in TRON_B58]
    if bad:
        pos, ch = bad[0]
        return f'Символ {ch!r} (позиция {pos}) не встречается в адресах TRON'
    num = 0
    for c in addr:
        num = num * 58 + TRON_B58.index(c)
    raw = num.to_bytes(25, 'big')
    if hashlib.sha256(hashlib.sha256(raw[:-4]).digest()).digest()[:4] != raw[-4:]:
        return 'Контрольная сумма адреса не сходится — где-то опечатка'
    return None


@app.route('/api/tronscan/balance/<address>', methods=['GET'])
def tronscan_balance(address):
    """Баланс адреса до создания кошелька — для автоподстановки в форму."""
    address, fixes = normalize_tron_address(address)
    problem = tron_address_problem(address)
    if problem:
        return jsonify({'success': False, 'error': problem, 'fixed': fixes}), 400
    balances = _tron_balances(address)
    if balances is None:
        return jsonify({'success': False, 'fixed': fixes,
                        'error': 'TronScan не ответил — попробуй ещё раз'}), 502
    usdt, trx = balances
    return jsonify({'success': True, 'address': address, 'fixed': fixes,
                    'usdt_balance': round(usdt, 2), 'trx_balance': round(trx, 6)})


TRON_RECONCILE_PAGES = 2       # сколько страниц TronScan обходим при сверке
TRON_RECONCILE_PER_PAGE = 50
TRON_RECONCILE_MAX_TRANSFERS = TRON_RECONCILE_PAGES * TRON_RECONCILE_PER_PAGE


def _tron_tx_usdt_amount(tx_hash):
    """Сколько USDT пришло по хэшу, по данным сети. None — сеть не ответила.

    Зовётся при сохранении сделки, поэтому таймаут короткий и без ретраев:
    лучше записать перевод с пометкой «не сверено», чем подвесить менеджеру
    форму на десятки секунд, пока TronScan отдаёт 429.
    """
    # Юнит-тесты в сеть не ходят: сохранение сделки с хэшем зовёт эту функцию,
    # и на прогоне сотни запросов к TronScan вешали сьют на таймаутах
    if os.environ.get('PYTEST_CURRENT_TEST'):
        return None
    try:
        r = requests.get('https://apilist.tronscanapi.com/api/transaction-info',
                         headers=_TRONSCAN_HEADERS, timeout=6,
                         params={'hash': tx_hash})
        if r.status_code != 200:
            return None
        data = r.json() or {}
    except Exception:
        return None

    info = data.get('trc20TransferInfo')
    # У части ответов это список переводов, у части — один объект
    if isinstance(info, dict):
        info = [info]
    total = 0.0
    for t in (info or []):
        if str(t.get('contract_address') or '') != USDT_TRC20_CONTRACT:
            continue
        try:
            decimals = int(t.get('decimals') or 6)
            total += float(t.get('amount_str') or t.get('amount') or 0) / (10 ** decimals)
        except (TypeError, ValueError):
            continue
    return round(total, 6) or None


def _tron_usdt_transfers(address, start_ts=None, pages=TRON_RECONCILE_PAGES,
                         per_page=TRON_RECONCILE_PER_PAGE):
    """TRC20-USDT переводы адреса (входящие и исходящие) по TronScan.

    Отдельно от `_tronscan_fetch_incoming/outgoing`: тем нужен срез по всем
    monitored-кошелькам с отбрасыванием внутренних переводов, а сверке — вся
    история ОДНОГО адреса, включая переводы между своими (для этого кошелька
    они такое же движение денег, как любое другое).

    None — TronScan не ответил; пустой список — переводов нет. Разница важна:
    в первом случае «неучтённых нет» было бы враньём.
    """
    out = []
    for page in range(pages):
        try:
            # 429 у TronScan — обычное дело: по тому же IP стучится фоновый
            # прогрев кэша. Без ретрая сверка падала бы через раз (ловилось
            # на проде 10.08: локально 200, с Railway — пусто).
            for attempt in range(3):
                r = requests.get('https://apilist.tronscanapi.com/api/token_trc20/transfers',
                                 headers=_TRONSCAN_HEADERS, timeout=10,
                                 params={'relatedAddress': address,
                                         'contract_address': USDT_TRC20_CONTRACT,
                                         'limit': per_page, 'start': page * per_page})
                if r.status_code != 429:
                    break
                time.sleep(2 * (attempt + 1))
            if r.status_code != 200:
                app.logger.warning(f'TronScan transfers HTTP {r.status_code} for {address}')
                return None if not out else out
            transfers = r.json().get('token_transfers') or []
        except Exception as e:
            app.logger.warning(f'TronScan transfers error for {address}: {e}')
            return None if not out else out
        if not transfers:
            break
        stop = False
        for tx in transfers:
            ts = tx.get('block_ts') or 0
            if start_ts and ts < start_ts:
                stop = True          # выдача отсортирована по времени ↓
                continue
            if tx.get('finalResult') not in (None, '', 'SUCCESS'):
                continue             # неудавшийся перевод денег не двигал
            frm, to = tx.get('from_address'), tx.get('to_address')
            if address not in (frm, to):
                continue
            out.append({
                'tx_hash': tx.get('transaction_id'),
                'type': 'income' if to == address else 'expense',
                'amount': round(float(tx.get('quant') or 0) / 1_000_000, 6),
                'ts': ts,
                'date': datetime.utcfromtimestamp(ts / 1000).isoformat() if ts else None,
                'counterparty': frm if to == address else to,
            })
        if stop or len(transfers) < per_page:
            break
    return out


def reconcile_wallet(session, wallet, transfers=None):
    """Сверка кошелька с блокчейном: что в сети есть, а в CRM не отмечено.

    Зачем: баланс в CRM складывается из операций, которые заводит человек.
    Забыли отметить выдачу — CRM думает, что деньги на месте; пришёл приход,
    которого никто не ждал — он вообще нигде не виден. Сверка ловит оба случая.

    Матчинг двухступенчатый: сначала по хэшу (надёжно), затем — для операций
    без хэша (заводили руками) — по типу и сумме с точностью до цента, каждая
    операция закрывает не больше одного перевода.

    Переводы берём с момента создания кошелька: всё, что было до, уже сидит
    в стартовом остатке, и показывать его как «неучтённое» — шум.
    """
    ops = session.query(WalletOperation).filter(
        WalletOperation.wallet_id == wallet.id).all()
    crm_balance = round(sum((o.amount or 0) if o.type == 'income' else -(o.amount or 0)
                            for o in ops), 2)

    if transfers is None:
        start_ts = int(wallet.created_at.timestamp() * 1000) if wallet.created_at else None
        transfers = _tron_usdt_transfers(wallet.address, start_ts=start_ts)
    if transfers is None:
        return {'ok': False, 'error': 'TronScan не ответил — сверить не с чем',
                'crm_balance': crm_balance}

    by_hash = {(o.tx_hash or '').lower(): o for o in ops if o.tx_hash}
    # Операции без хэша — кандидаты на матч по сумме; каждую используем один раз
    loose = [o for o in ops if not o.tx_hash]
    used = set()
    unmatched, matched = [], 0
    for t in transfers:
        if (t['tx_hash'] or '').lower() in by_hash:
            matched += 1
            continue
        hit = next((o for o in loose
                    if o.id not in used and o.type == t['type']
                    and abs((o.amount or 0) - t['amount']) < 0.01), None)
        if hit:
            used.add(hit.id)
            matched += 1
            continue
        unmatched.append(t)

    onchain = _tron_balances(wallet.address)
    onchain_usdt = round(onchain[0], 2) if onchain else None
    return {
        'ok': True,
        'wallet_id': wallet.id, 'address': wallet.address, 'label': wallet.label,
        'crm_balance': crm_balance,
        'onchain_balance': onchain_usdt,
        # Глубина обхода ограничена — молчать об этом нельзя, иначе «сверено всё»
        # и «сверено первое, что влезло» выглядят одинаково
        'truncated': len(transfers) >= TRON_RECONCILE_MAX_TRANSFERS,
        # Плюс = в сети денег больше, чем знает CRM (не отметили приход)
        'diff': round(onchain_usdt - crm_balance, 2) if onchain_usdt is not None else None,
        'checked_transfers': len(transfers),
        'matched': matched,
        'unmatched': unmatched,
        'unmatched_income': round(sum(t['amount'] for t in unmatched if t['type'] == 'income'), 2),
        'unmatched_expense': round(sum(t['amount'] for t in unmatched if t['type'] == 'expense'), 2),
        'since': wallet.created_at.isoformat() if wallet.created_at else None,
    }


@app.route('/api/wallets/<int:wallet_id>/reconcile', methods=['GET'])
def wallet_reconcile(wallet_id):
    """Что в блокчейне произошло, а в CRM не отмечено."""
    session = get_session()
    try:
        wallet = session.query(Wallet).filter(Wallet.id == wallet_id).first()
        if not wallet:
            return jsonify({'success': False, 'error': 'Кошелёк не найден'}), 404
        if not (wallet.address or '').startswith('T') or len(wallet.address) != 34:
            return jsonify({'success': False,
                            'error': 'Виртуальный кошелёк — в блокчейне его нет'}), 400
        r = reconcile_wallet(session, wallet)
        if not r.get('ok'):
            return jsonify({'success': False, **r}), 502
        return jsonify({'success': True, **r})
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


@app.route('/api/wallets/<int:wallet_id>', methods=['PATCH'])
def update_wallet(wallet_id):
    """Подпись кошелька. Адресов в мониторинге больше пяти, по строке `T...`
    оператор их не различает и не понимает, куда должен был прийти перевод."""
    session = get_session()
    try:
        data = request.get_json() or {}
        wallet = session.query(Wallet).filter(Wallet.id == wallet_id).first()
        if not wallet:
            return jsonify({'success': False, 'error': 'Кошелёк не найден'}), 404

        if 'label' in data:
            wallet.label = (data.get('label') or '').strip()[:100]
        session.commit()
        return jsonify({'success': True, 'wallet': wallet.to_dict()})
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
    
    # 2. Приход: хэш занят ТОЛЬКО когда разобран полностью. Один перевод часто
    # обслуживает несколько сделок (клиент платит рублями в несколько заходов,
    # обмениваем один раз), поэтому пока в реестре есть остаток — перевод
    # остаётся в списке доступных. Переводы вне реестра (легаси, до бэкфилла)
    # считаем занятыми целиком, как раньше.
    payin_hashes = set()
    deals_payin = session.query(Deal.payin_tx_hash).filter(Deal.payin_tx_hash != None).all()
    for d in deals_payin: payin_hashes.add(d[0])

    # 2c. Фактическая отправка в MF Corp — те же хэши нельзя учесть дважды
    deals_payout_multi = session.query(Deal.payout_tx_hashes).filter(Deal.payout_tx_hashes != None).all()
    for d in deals_payout_multi:
        try:
            for part in json.loads(d[0]) or []:
                if part.get('hash'):
                    used_hashes.add(part['hash'])
        except (ValueError, TypeError, AttributeError):
            continue

    # 2b. Приход частями: остальные хэши лежат в JSON payin_tx_hashes
    deals_multi = session.query(Deal.payin_tx_hashes).filter(Deal.payin_tx_hashes != None).all()
    for d in deals_multi:
        try:
            for part in json.loads(d[0]) or []:
                if part.get('hash'):
                    payin_hashes.add(part['hash'])
        except (ValueError, TypeError, AttributeError):
            continue

    ledger = {t.tx_hash: t for t in session.query(PayinTx).all()}
    for h in payin_hashes:
        tx = ledger.get(h)
        if tx is None or tx.free_usdt() <= 0.01:
            used_hashes.add(h)
    
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

@app.route('/api/wl-transactions', methods=['GET'])
def get_wl_transactions():
    """Прокси к WLExchangeBot API — список PAID транзакций для picker'а в форме."""
    merchant = request.args.get('merchant', 'grusha')
    status = request.args.get('status', 'PAID')
    try:
        headers = {}
        if WL_BOT_API_KEY:
            headers['Authorization'] = f'Bearer {WL_BOT_API_KEY}'
        resp = requests.get(
            f'{WL_BOT_URL}/api/wl-transactions',
            params={'merchant': merchant, 'status': status},
            headers=headers,
            timeout=10,
        )
        resp.raise_for_status()
        return jsonify(resp.json())
    except requests.exceptions.ConnectionError:
        return jsonify({'error': 'WL Bot недоступен'}), 502
    except requests.exceptions.Timeout:
        return jsonify({'error': 'WL Bot timeout'}), 504
    except Exception as e:
        return jsonify({'error': str(e)}), 500


USDT_TRC20_CONTRACT = 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t'
_TRONSCAN_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Apple) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}


def _merge_partial_with_cache(fresh, cache_key, failed_addresses, addr_field):
    """Кошельки, ответившие 429, добираем из прошлого кэша.

    Иначе один rate-limit у TronScan обнуляет их переводы в списке: пользователь
    видит неполную выборку и не знает об этом. Дедуп по tx_hash.
    """
    if not failed_addresses:
        return fresh
    old = (TRONSCAN_CACHE.get(cache_key) or {}).get('data') or []
    seen = {t.get('tx_hash') for t in fresh}
    rescued = [t for t in old
               if t.get(addr_field) in failed_addresses and t.get('tx_hash') not in seen]
    if rescued:
        print(f'[TronScan] {cache_key}: добрал {len(rescued)} переводов из кэша '
              f'для {len(failed_addresses)} кошельков с 429', flush=True)
    merged = fresh + rescued
    merged.sort(key=lambda x: x.get('timestamp') or '', reverse=True)
    return merged


def _tronscan_fetch_incoming(wallets, start_ts=None, end_ts=None):
    """Обход TronScan по кошелькам: TRC20-USDT переводы (входящие помечены is_incoming).

    Вынесено из эндпоинта, чтобы фоновый прогрев кэша (_tronscan_warm_loop)
    использовал ту же логику. Медленно (~10 сек на 3 кошелька) из-за анти-429 пауз.
    Возвращает (транзакции по времени ↓, проверенные адреса, ошибки).
    """
    all_incoming = []
    wallets_checked = []
    wallets_errors = []

    for wallet_idx, wallet in enumerate(wallets):
        wallet_tx_count = 0
        wallets_checked.append(wallet.address)

        # Пауза между кошельками чтобы не словить 429 от TronScan
        if wallet_idx > 0:
            time.sleep(1.5)

        try:
            for page in range(2):  # 2 страницы по 50 = 100 транзакций на кошелек
                url = 'https://apilist.tronscanapi.com/api/token_trc20/transfers'
                params = {
                    'relatedAddress': wallet.address,
                    'contract_address': USDT_TRC20_CONTRACT,
                    'limit': 50,
                    'start': page * 50,
                    't': int(time.time())
                }

                # Retry при 429 (rate limit)
                for attempt in range(3):
                    response = requests.get(url, params=params, headers=_TRONSCAN_HEADERS, timeout=10)
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
    return all_incoming, wallets_checked, wallets_errors


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

        all_incoming, wallets_checked, wallets_errors = _tronscan_fetch_incoming(
            wallets, start_ts=start_ts, end_ts=end_ts)

        # Кошельки, не ответившие из-за 429, добираем из прошлого кэша: иначе
        # один rate-limit TronScan обнуляет их переводы в выборке
        failed = {e.get('address') for e in wallets_errors if e.get('address')}
        all_incoming = _merge_partial_with_cache(all_incoming, 'incoming', failed, 'to_address')

        # Обновляем кэш. Атомарно (одним присваиванием sub-dict), иначе читатель
        # мог увидеть новые data со старым timestamp (окно рассинхрона).
        # Частичный результат кэшируем со СТАРЫМ timestamp — чтобы следующий
        # запрос попробовал снова, а не ждал полный TTL на неполных данных.
        if not wallet_filter:
            ts = current_time if not failed else (
                TRONSCAN_CACHE['incoming'].get('timestamp') or current_time)
            TRONSCAN_CACHE['incoming'] = {'data': all_incoming, 'timestamp': ts}
        
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

MF_REALTY_INPUT_FIELDS = (
    'realty_purpose', 'invoice_amount_thb', 'sell_rate_thb_usdt', 'buy_rate_thb_usdt',
    'company_percent', 'company_sent_thb', 'katika_fee_thb', 'katika_fee_usdt',
    'client_spread_percent',
    'doc_invoice_url', 'doc_contract_url', 'doc_payment_url',
)


def _apply_mf_realty(deal, data):
    """Поля и производные для сделки через MF Corp: себестоимость, комиссия, валовый доход.

    Выплаты партнёрам и остаток на кошельке считаются позже, в _apply_deal_agents —
    там уже известен состав агентов. Прибыль сделки = валовый доход (приход −
    себестоимость), поэтому обычный _recalculate_deal_financials для таких сделок
    не нужен и не вызывается.
    """
    for f in MF_REALTY_INPUT_FIELDS:
        if f in data:
            val = data.get(f)
            setattr(deal, f, val if val not in ('', None) else None)

    # Фактические переводы в компанию (куда и сколько ушло)
    if 'payout_tx_hashes' in data:
        parts = _normalize_payout_transfers(data.get('payout_tx_hashes'))
        deal.payout_tx_hashes = json.dumps(parts, ensure_ascii=False) if parts else None
        if parts and parts[0].get('hash'):
            deal.payout_tx_hash = parts[0]['hash']

    # Комиссию задают с одной из двух сторон. Источник истины — то, что прислали
    # ИМЕННО СЕЙЧАС: иначе сохранённая при создании сумма отправки навсегда
    # перебивала бы правку процента и сделку нельзя было бы пересчитать.
    if data.get('company_sent_thb') not in (None, ''):
        sent_thb, percent = deal.company_sent_thb, None
    elif data.get('company_percent') not in (None, ''):
        sent_thb, percent = None, deal.company_percent
    else:
        sent_thb, percent = None, deal.company_percent  # правят другое поле — считаем от процента

    r = compute_mf_realty(
        deal.invoice_amount_thb, deal.buy_rate_thb_usdt, deal.payin_amount_usdt,
        sell_rate=deal.sell_rate_thb_usdt, company_percent=percent,
        company_sent_thb=sent_thb, agents=[],
        actual_cost_usdt=_payout_transfers_total(deal))

    if not deal.payin_amount_usdt:
        deal.payin_amount_usdt = r['payin_usdt']
    deal.company_percent = r['company_percent']
    deal.company_sent_thb = r['company_sent_thb']
    deal.company_fee_thb = r['company_fee_thb']
    deal.company_fee_usdt = r['company_fee_usdt']
    # С кошелька уходит вся отправка в компанию (инвойс + комиссия)
    deal.payout_amount_usdt = r['cost_usdt']
    # Прибыль сделки = то, что осталось в крипте. Комиссия в батах — второй
    # карман, она приплюсовывается в net_profit_usdt (см. _apply_deal_agents)
    deal.profit_usdt = r['crypto_profit_usdt']
    deal.profit_percent = (r['crypto_profit_usdt'] / r['cost_usdt'] * 100) if r['cost_usdt'] else 0
    # Платим со своего кошелька, а не из кармана фаундера — возмещать нечего
    deal.needs_reimbursement = False
    return r


def realty_payload_error(deal):
    """Проверка, что сделка по недвижимости не пустая по своему типу.

    Страховка от порчи данных со стороны формы: если тип проставлен, а полей нет,
    почти всегда это протёкшее состояние редактора, а не осознанный ввод (кейс #463:
    обычная сделка сохранилась как фрихолд с пустыми полями перевода — прибыль
    обнулилась, а выплата агенту осталась). Сервер такую сделку не принимает.
    Возвращает текст ошибки или None.
    """
    if deal.deal_kind == MF_REALTY_KIND:
        if not (deal.invoice_amount_thb and deal.buy_rate_thb_usdt):
            return ('Лизхолд без суммы инвойса в батах и курса покупки. '
                    'Проверь тип сделки — похоже, форма сохранила не то.')
    if deal.deal_kind == MF_FREEHOLD_KIND:
        if not (deal.invoice_amount_usd or deal.transfer_sent_usd
                or _payout_transfers_total(deal)):
            return ('Фрихолд без инвойса застройщику и суммы отправки. '
                    'Проверь тип сделки — похоже, форма сохранила не то.')
    return None


MF_FREEHOLD_INPUT_FIELDS = (
    'realty_purpose', 'invoice_amount_usd', 'transfer_sent_usd',
    'transfer_fee_percent', 'transfer_fee_fixed_usd',
    'doc_invoice_url', 'doc_contract_url', 'doc_payment_url',
)


def _apply_mf_freehold(deal, data):
    """Поля и производные сделки во фрихолде: отправка, комиссия перевода, прибыль.

    Прибыль сделки = приход − отправка, и это УЖЕ после всех расходов (комиссия
    банка снимается с отправляемой суммы). Выплаты агентам считаются позже, в
    _apply_deal_agents, от этого же числа — обычной веткой, без карманов.
    """
    for f in MF_FREEHOLD_INPUT_FIELDS:
        if f in data:
            val = data.get(f)
            setattr(deal, f, val if val not in ('', None) else None)

    # Приход в рублях: USDT считаем по курсу брокера, как в лизхолде (rub-*)
    if not deal.payin_amount_usdt and deal.payin_amount_rub and deal.payin_rate_rub_usdt:
        deal.payin_amount_usdt = round(deal.payin_amount_rub / deal.payin_rate_rub_usdt, 2)

    # Фактические переводы, которыми ушли деньги: адрес и хэш, чтобы отправку
    # можно было сверить в блокчейне, а не верить полю с суммой
    if 'payout_tx_hashes' in data:
        parts = _normalize_payout_transfers(data.get('payout_tx_hashes'))
        deal.payout_tx_hashes = json.dumps(parts, ensure_ascii=False) if parts else None
        if parts and parts[0].get('hash'):
            deal.payout_tx_hash = parts[0]['hash']

    # Отправку задают либо фактом, либо через инвойс. Источник истины — то, что
    # прислали ИМЕННО СЕЙЧАС: иначе сохранённый факт навсегда перебивал бы правку
    # инвойса или комиссии и сделку нельзя было бы пересчитать (грабля лизхолда).
    sent = deal.transfer_sent_usd if data.get('transfer_sent_usd') not in (None, '') else None
    # Переводы отмечены — их сумма и есть фактическая отправка
    if sent is None:
        sent = _payout_transfers_total(deal)

    r = compute_mf_freehold(
        deal.payin_amount_usdt, invoice_usd=deal.invoice_amount_usd, sent_usd=sent,
        fee_percent=deal.transfer_fee_percent, fee_fixed_usd=deal.transfer_fee_fixed_usd,
        agents=[])

    deal.transfer_sent_usd = r['sent_usd']
    deal.transfer_arrive_usd = r['arrive_usd']
    deal.transfer_fee_usd = r['fee_usd']
    # С нашей стороны ушла вся отправка — она и есть себестоимость сделки
    deal.payout_amount_usdt = r['sent_usd']
    deal.profit_usdt = r['gross_profit_usdt']
    deal.profit_percent = r['profit_percent']
    # Платим со своего кошелька, а не из кармана фаундера — возмещать нечего
    deal.needs_reimbursement = False
    return r


def _dedupe_transfers(transfers):
    """Убирает повторы переводов — строго по tx_hash.

    Дубли возникают на стыке страниц TronScan и когда один перевод виден с двух
    наших кошельков. Раньше ключом было amount + 15-минутное окно: одинаковые
    суммы, отправленные подряд (выплата 500k пятью переводами по 100k), схлопывались
    в одну — из дропдауна возмещений пропадали реальные переводы (кейс 04.08).
    Разные переводы всегда имеют разные хэши, поэтому потерь больше нет.
    """
    seen = set()
    deduped = []
    for tx in transfers:
        h = tx.get('tx_hash')
        if h and h in seen:
            continue
        if h:
            seen.add(h)
        deduped.append(tx)
    return deduped


def _tronscan_fetch_outgoing(wallets, internal_wallet_addresses, start_ts=None, end_ts=None,
                             result_limit=None, with_errors=False):
    """Обход TronScan: исходящие TRC20-USDT переводы, внутренние помечены is_internal.

    Вынесено из эндпоинта — общая логика для запроса и фонового прогрева кэша.
    Возвращает дедуплицированный список по времени ↓; с with_errors=True —
    пару (список, адреса кошельков, не ответивших из-за 429/ошибки), чтобы
    вызывающий не принял частичную выборку за полную.
    """
    all_outgoing = []
    failed = []

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
                    'contract_address': USDT_TRC20_CONTRACT,
                    'limit': api_limit,
                    'start': page * api_limit,
                    't': int(time.time())
                }

                # Retry при 429 (rate limit)
                for attempt in range(3):
                    response = requests.get(url, params=params, headers=_TRONSCAN_HEADERS, timeout=10)
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

                        # Только исходящие (from_address == наш кошелёк). Переводы на
                        # другой monitored-кошелёк раньше выбрасывались здесь — и перевод
                        # фаундеру на адрес, заведённый у нас, молча пропадал из подбора
                        # возмещений (кошелёк Виталия → #21/#17, 18.08). Теперь помечаем
                        # флагом, а прячет их уже выдача эндпоинта.
                        if tx.get('from_address') == wallet.address:
                            amount = float(tx.get('quant', 0)) / 1_000_000
                            all_outgoing.append({
                                'tx_hash': tx.get('transaction_id'),
                                'from_address': tx.get('from_address'),
                                'to_address': tx.get('to_address'),
                                'amount_usdt': amount,
                                'timestamp': datetime.fromtimestamp(tx_ts / 1000).isoformat(),
                                'confirmed': tx.get('confirmed', False),
                                'is_internal': tx.get('to_address') in internal_wallet_addresses
                            })

                    if reached_start_ts:
                        break
                    time.sleep(1)
                else:
                    print(f"[DEBUG] TronScan outgoing HTTP {response.status_code} for {wallet.address[:10]}...")
                    failed.append(wallet.address)
                    break
        except Exception as e:
            print(f"[DEBUG] TronScan outgoing error for {wallet.address}: {e}")
            failed.append(wallet.address)

    all_outgoing.sort(key=lambda x: x['timestamp'], reverse=True)
    deduped = _dedupe_transfers(all_outgoing)
    return (deduped, failed) if with_errors else deduped


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
        # Переводы на свои же monitored-кошельки. По умолчанию скрыты (подбор выплаты
        # клиенту), но форма возмещений просит их показать: возмещение фаундеру может
        # уйти на адрес, который заведён у нас, и без флага перевод не найти.
        include_internal = request.args.get('include_internal', 'false').lower() in ('1', 'true')

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
            if not include_internal:
                cached_data = [tx for tx in cached_data if not tx.get('is_internal')]

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

        # Только monitored-кошельки — для фильтрации внутренних переводов между своими.
        # Balance-кошельки (is_monitored=False) НЕ считаются внутренними: переводы туда
        # — легитимные исходящие (например, возмещения фаундеру на его balance-адрес),
        # и их нужно видеть в дропдауне возмещений.
        internal_wallet_addresses = set(w.address for w in session.query(Wallet).filter(Wallet.active == True, Wallet.is_monitored == True).all())

        all_outgoing, failed_out = _tronscan_fetch_outgoing(
            wallets, internal_wallet_addresses,
            start_ts=start_ts, end_ts=end_ts, result_limit=result_limit, with_errors=True)
        failed_out = set(failed_out)
        all_outgoing = _merge_partial_with_cache(all_outgoing, 'outgoing', failed_out, 'from_address')

        # Обновляем кэш (полный набор, без limit-фильтра). Атомарно — см. incoming.
        if not wallet_filter and not result_limit:
            ts = current_time if not failed_out else (
                TRONSCAN_CACHE['outgoing'].get('timestamp') or current_time)
            TRONSCAN_CACHE['outgoing'] = {'data': all_outgoing, 'timestamp': ts}

        final_limit = result_limit or 1000
        visible = all_outgoing if include_internal else [
            tx for tx in all_outgoing if not tx.get('is_internal')]
        return jsonify({
            'success': True,
            'available': visible[:final_limit],
            'wallets_errors': [{'address': a, 'error': 'rate limit'} for a in sorted(failed_out)],
            'cached': False
        })
    except Exception as e:
        app.logger.error(f'Server error: {e}')
        return jsonify({'success': False, 'error': 'Внутренняя ошибка сервера'}), 500
    finally:
        session.close()

TRONSCAN_WARM_INTERVAL = 240  # сек — меньше CACHE_TTL (300), чтобы кэш не протухал между проходами
TRONSCAN_WARM_START_DATE = '2025-12-01'  # синхронно с дефолтным фильтром дат на фронте CRM


def _tronscan_warm_loop():
    """Фоновый прогрев TRONSCAN_CACHE: медленный обход TronScan (~20 сек с анти-429
    паузами) больше не случается внутри HTTP-запроса — эндпоинты transactions/*
    практически всегда отвечают из кэша. Ошибки глушим: старый кэш остаётся,
    следующий проход попробует снова."""
    time.sleep(10)  # даём приложению подняться
    while True:
        try:
            start_ts = int(datetime.strptime(TRONSCAN_WARM_START_DATE, '%Y-%m-%d').timestamp() * 1000)
            session = get_session()
            try:
                wallets = session.query(Wallet).filter(Wallet.active == True, Wallet.is_monitored == True).all()
            finally:
                session.close()
            if wallets:
                # Прогрев — главный писатель кэша. Кошельки, огрызнувшиеся 429,
                # добираем из прошлых данных и НЕ обновляем timestamp: иначе
                # неполная выборка живёт полный TTL и юзер видит не все переводы.
                incoming, _, in_errors = _tronscan_fetch_incoming(wallets, start_ts=start_ts)
                failed_in = {e.get('address') for e in in_errors if e.get('address')}
                incoming = _merge_partial_with_cache(incoming, 'incoming', failed_in, 'to_address')
                TRONSCAN_CACHE['incoming'] = {
                    'data': incoming,
                    'timestamp': (TRONSCAN_CACHE['incoming'].get('timestamp') or 0)
                    if failed_in else time.time()}

                internal = set(w.address for w in wallets)
                outgoing, failed_out = _tronscan_fetch_outgoing(
                    wallets, internal, start_ts=start_ts, with_errors=True)
                failed_out = set(failed_out)
                outgoing = _merge_partial_with_cache(outgoing, 'outgoing', failed_out, 'from_address')
                TRONSCAN_CACHE['outgoing'] = {
                    'data': outgoing,
                    'timestamp': (TRONSCAN_CACHE['outgoing'].get('timestamp') or 0)
                    if failed_out else time.time()}
                if failed_in or failed_out:
                    print(f'[TronScan] прогрев неполный: 429 у {len(failed_in)} вх. / '
                          f'{len(failed_out)} исх. кошельков', flush=True)
        except Exception as e:
            print(f"ℹ️ tronscan warm loop: {e}", flush=True)
        time.sleep(TRONSCAN_WARM_INTERVAL)


if os.environ.get('TRONSCAN_WARM_ENABLED', '1') == '1' and 'pytest' not in sys.modules:
    threading.Thread(target=_tronscan_warm_loop, daemon=True, name='tronscan-warm').start()


# ==================== ТРАФИК ПО КАНАЛАМ (Яндекс.Метрика) ====================
METRIKA_TOKEN = os.environ.get('METRIKA_TOKEN', '')
METRIKA_COUNTER_ID = os.environ.get('METRIKA_COUNTER_ID', '106232718')  # счётчик grusha.space
CHANNEL_TRAFFIC_INTERVAL = 6 * 3600  # раз в 6 часов достаточно — дневные агрегаты


def _sync_metrika_traffic(days=7):
    """Тянет из Reporting API Метрики дневных пользователей/визиты по utm_source.

    UA канала = ym:s:users (пользователи, НЕ визиты — конверсию по Красинскому
    считаем по людям, по сессиям она занижена). Канал без метки → 'без метки',
    совпадает с каналом сделок без utm. Upsert по (date, channel, provider).
    """
    resp = requests.get('https://api-metrika.yandex.net/stat/v1/data', params={
        'ids': METRIKA_COUNTER_ID,
        'metrics': 'ym:s:visits,ym:s:users',
        'dimensions': 'ym:s:date,ym:s:UTMSource',
        'date1': (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d'),
        'date2': 'today',
        'accuracy': 'full',
        'limit': 10000,
    }, headers={'Authorization': f'OAuth {METRIKA_TOKEN}'}, timeout=30)
    resp.raise_for_status()
    rows = resp.json().get('data', [])
    session = get_session()
    try:
        for row in rows:
            day_str = row['dimensions'][0]['name']
            channel = (row['dimensions'][1].get('name') or '').strip().lower() or 'без метки'
            day = datetime.strptime(day_str, '%Y-%m-%d')
            rec = session.query(ChannelTraffic).filter_by(
                date=day, channel=channel[:50], provider='metrika').first()
            if not rec:
                rec = ChannelTraffic(date=day, channel=channel[:50], provider='metrika')
                session.add(rec)
            rec.visits = int(row['metrics'][0])
            rec.users = int(row['metrics'][1])
        session.commit()
        print(f"[Metrika] synced {len(rows)} rows", flush=True)
    finally:
        session.close()


def _channel_traffic_loop():
    """Фоновый синк трафика по каналам. Не стартует без METRIKA_TOKEN."""
    time.sleep(30)
    while True:
        try:
            _sync_metrika_traffic()
        except Exception as e:
            print(f"ℹ️ metrika sync: {e}", flush=True)
        time.sleep(CHANNEL_TRAFFIC_INTERVAL)


if METRIKA_TOKEN and 'pytest' not in sys.modules:
    threading.Thread(target=_channel_traffic_loop, daemon=True, name='channel-traffic').start()


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
        if request.args.get('include_test') != '1':
            query = query.filter(Client.is_test.isnot(True))  # демо-клиенты тестового реферера
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
            amount=parse_float(data.get('amount')),
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
            avg_rate = _card_avg_rate(c)
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
        # CR-05: блокируем строку карты на время транзакции (FOR UPDATE на Postgres,
        # no-op на SQLite). Защита от двойного пополнения карты в параллельных запросах.
        card = session.query(BankCard).filter(BankCard.id == card_id).with_for_update().first()
        if not card:
            return jsonify({'success': False, 'error': 'Карта не найдена'}), 404

        amount_thb = parse_float(data.get('amount_thb'))
        source_type = data['source_type'] # 'cash_batch' or 'separate'

        cost_usdt = 0
        purchase_rate = 0
        source_batch_id = None

        if source_type == 'cash_batch':
            batch_id = int(data['source_batch_id'])
            # CR-05: блокировка партии — без неё два параллельных запроса проходят
            # проверку remaining_thb >= amount и оба декрементируют → баланс в минус.
            batch = session.query(CashBatch).filter(CashBatch.id == batch_id).with_for_update().first()
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
            cost_usdt = parse_float(data.get('cost_usdt'))
            purchase_rate = amount_thb / cost_usdt
            
        topup = CardTopup(
            card_id=card.id,
            amount_thb=amount_thb,
            cost_usdt=cost_usdt,
            purchase_rate=purchase_rate,
            source_type=source_type,
            source_batch_id=source_batch_id,
            reference=(data.get('reference') or '').strip()[:120] or None,
            notes=(data.get('notes') or '').strip() or None
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
                'source_batch_id': t.source_batch_id,
                'reference': t.reference,
                'notes': t.notes
            }
            result.append(topup_data)

        # Расходы: выдачи клиентам с этой карты
        allocations = session.query(CardAllocation).filter(
            CardAllocation.card_id == card_id
        ).order_by(CardAllocation.created_at.desc()).all()

        return jsonify({
            'success': True,
            'card': {
                'id': card.id,
                'bank_name': card.bank_name,
                'card_name': card.card_name,
                'balance_thb': card.balance_thb
            },
            'topups': result,
            'total_topups': len(result),
            'allocations': [a.to_dict() for a in allocations],
            'total_spent_thb': round(sum(a.amount_thb for a in allocations), 2),
            'total_spent_usdt': round(sum(a.cost_usdt for a in allocations), 2)
        })
    finally:
        session.close()

@app.route('/api/cards/<int:card_id>/adjust', methods=['POST'])
def adjust_card(card_id):
    """Ручное списание бат с карты, не связанное со сделкой.

    Нужно для движений мимо клиентов: тестовый перевод, комиссия банка,
    перекидка на другой свой счёт. Списание оформляется как пополнение
    с минусом, а стоимость в USDT снимается по текущему среднему курсу
    карты — иначе средний курс поехал бы вниз, будто баты подешевели.

    Принимает `amount_thb` (сколько снять, положительное число) либо
    `new_balance_thb` (каким должен стать остаток).
    """
    session = get_session()
    try:
        data = request.get_json() or {}
        card = session.query(BankCard).filter(BankCard.id == card_id).with_for_update().first()
        if not card:
            return jsonify({'success': False, 'error': 'Карта не найдена'}), 404

        current = card.balance_thb or 0
        if data.get('new_balance_thb') is not None:
            amount_thb = round(current - parse_float(data.get('new_balance_thb')), 2)
        else:
            amount_thb = round(parse_float(data.get('amount_thb')), 2)
        if not amount_thb:
            return jsonify({'success': False, 'error': 'Укажите сумму списания'}), 400

        rate = _card_avg_rate(card)
        reason = (data.get('reason') or '').strip()[:200] or 'Ручная корректировка'
        session.add(CardTopup(
            card_id=card.id,
            amount_thb=-amount_thb,
            cost_usdt=round(-amount_thb / rate, 2) if rate else 0,
            purchase_rate=round(rate, 4),
            source_type='adjustment',
            reference=(data.get('reference') or '').strip()[:120] or None,
            notes=reason,
        ))
        card.balance_thb = round(current - amount_thb, 2)
        session.commit()
        return jsonify({'success': True, 'card': card.to_dict(),
                        'balance_thb': card.balance_thb, 'adjusted_thb': amount_thb})
    except Exception as e:
        session.rollback()
        app.logger.error(f'[adjust_card] error: {e}')
        return jsonify({'success': False, 'error': 'Ошибка обработки запроса'}), 400
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

def _deal_usdt_volume_cost(deal):
    """USDT-эквивалент (объём по pay-in, себестоимость по pay-out) сделки.

    Стандартные сделки → payin/payout_amount_usdt. Кастомные без этих полей
    (валюта в custom_*) → конвертируем по сохранённому курсу:
      RUB/THB — курс хранится как «валюта за 1 USD» → делим;
      EUR     — курс хранится как «USD за 1 EUR» → умножаем;
      USD/USDT — 1:1.
    Так кастомные сделки (RUB→EUR, USD→USDT и т.п.) попадают в объём.
    """
    def to_usdt(amount, currency, rate):
        a = float(amount or 0)
        if not a:
            return 0.0
        cur = (currency or '').upper()
        r = float(rate or 0)
        if cur in ('USD', 'USDT'):
            return a
        if cur in ('RUB', 'THB'):
            return a / r if r else 0.0
        if cur == 'EUR':
            return a * r if r else a
        # неизвестная валюта: эвристика по величине курса
        return a / r if r > 5 else (a * r if r else 0.0)

    payin = float(deal.payin_amount_usdt or 0)
    payout = float(deal.payout_amount_usdt or 0)
    if deal.is_custom:
        if not payin:
            payin = to_usdt(deal.custom_payin_amount, deal.custom_payin_currency, deal.custom_payin_rate)
        if not payout:
            payout = to_usdt(deal.custom_payout_amount, deal.custom_payout_currency, deal.custom_payout_rate)
    return payin, payout


@app.route('/api/analytics/dashboard', methods=['GET'])
def get_dashboard():
    session = get_session()
    try:
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        week_ago = today - timedelta(days=7)

        # Период для графиков: пресет или произвольный диапазон date_from/date_to
        period = request.args.get('period', '30d')
        date_from = request.args.get('date_from')
        date_to = request.args.get('date_to')
        chart_end = today + timedelta(days=1)  # эксклюзивная граница
        if date_from:
            try:
                chart_start = datetime.strptime(date_from, '%Y-%m-%d')
                if date_to:
                    chart_end = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)
            except ValueError:
                return jsonify({'success': False, 'error': 'Invalid date format, expected YYYY-MM-DD'}), 400
        elif period == 'today':
            chart_start = today
        elif period == 'week':
            chart_start = week_ago
        elif period == 'month':
            chart_start = today.replace(day=1)
        elif period == 'all':
            chart_start = datetime(2024, 1, 1)
        else:  # 30d
            chart_start = today - timedelta(days=30)

        # Фильтр по рефереру: all (по умолчанию), none (без реферала), <id>
        referrer_filter = request.args.get('referrer_id', '')

        # Фильтр по направлению: all (по умолчанию), exchange (обычные обмены),
        # realty (вся недвижимость), mf_realty (лизхолд), mf_freehold (фрихолд)
        kind_filter = request.args.get('deal_kind', '')
        if kind_filter not in ('', 'all', 'exchange', 'realty') + REALTY_KINDS:
            return jsonify({'success': False, 'error': 'Invalid deal_kind'}), 400

        cash_batches = session.query(CashBatch).filter(CashBatch.status == CashBatchStatus.ACTIVE).all()
        pending_deals = session.query(Deal).filter(
            Deal.status == DealStatus.PENDING, Deal.is_test.isnot(True)).all()

        # Невозмещенные
        unreimbursed = session.query(Deal).filter(
            Deal.payout_source == PayOutSource.FOUNDER_PERSONAL,
            Deal.reimbursement_id == None,
            Deal.is_test.isnot(True)
        ).all()

        # Метрики за период. Только завершённые сделки (completed/verified) —
        # pending не учитываем в прибыли/объёме (прибыль ещё не реализована).
        ACTIVE_STATUSES = [DealStatus.COMPLETED, DealStatus.VERIFIED]
        deals_q = session.query(Deal).filter(
            Deal.created_at >= chart_start,
            Deal.created_at < chart_end,
            Deal.status.in_(ACTIVE_STATUSES),
            Deal.is_test.isnot(True),
        )
        if referrer_filter == 'none':
            deals_q = deals_q.filter(Deal.referrer_id == None)
        elif referrer_filter == 'any':
            deals_q = deals_q.filter(Deal.referrer_id != None)
        elif referrer_filter and referrer_filter != 'all':
            try:
                deals_q = deals_q.filter(Deal.referrer_id == int(referrer_filter))
            except ValueError:
                return jsonify({'success': False, 'error': 'Invalid referrer_id'}), 400
        # Обычные обмены = всё, что не недвижимость (deal_kind NULL или 'exchange')
        if kind_filter == 'exchange':
            deals_q = deals_q.filter(or_(Deal.deal_kind.is_(None),
                                         Deal.deal_kind.notin_(REALTY_KINDS)))
        elif kind_filter == 'realty':
            deals_q = deals_q.filter(Deal.deal_kind.in_(REALTY_KINDS))
        elif kind_filter in REALTY_KINDS:
            deals_q = deals_q.filter(Deal.deal_kind == kind_filter)
        period_deals = deals_q.all()
        # USDT-эквивалент объёма/себестоимости каждой сделки (учитывает кастомные)
        usdt = {d.id: _deal_usdt_volume_cost(d) for d in period_deals}
        period_with_margin = [d for d in period_deals if d.profit_percent and d.profit_percent > 0]
        period_avg_margin = round(sum(d.profit_percent for d in period_with_margin) / len(period_with_margin), 1) if period_with_margin else 0
        period_with_payin = [d for d in period_deals if usdt[d.id][0] > 0]
        period_avg_check = round(sum(usdt[d.id][0] for d in period_with_payin) / len(period_with_payin), 2) if period_with_payin else 0
        period_profit = round(sum(d.net_profit_usdt or d.profit_usdt or 0 for d in period_deals), 2)
        period_volume = round(sum(usdt[d.id][0] for d in period_deals), 2)
        # Себестоимость = что мы потратили на покупку валюты для сделок (payout в USDT)
        period_cost = round(sum(usdt[d.id][1] for d in period_deals), 2)
        # Сделки с реферралами и сумма выплат реферралам
        period_referrer_deals = [d for d in period_deals if d.referrer_id]
        period_referrer_payout = round(sum(d.referrer_payout_usdt or 0 for d in period_referrer_deals), 2)
        # ── Маржа в разрезах: сколько закладываем vs сколько реально забираем ──
        # Одна цифра «ср. маржа» врала сразу тремя способами: среднее по сделкам
        # не взвешено (сделка на $500 весит как сделка на $200k), считается от
        # себестоимости и ничего не знает про выплаты рефералам. Держим оба
        # взгляда рядом — среднее по сделкам («сколько закладываем») и по
        # деньгам («сколько реально забрали»), до и после выплат.
        def _gross_of(d):
            """Прибыль до выплат агентам. У лизхолда MF два кармана: крипта в
            profit_usdt и комиссия батами — без неё gross вышел бы меньше net."""
            g = d.profit_usdt or 0
            if d.deal_kind == MF_REALTY_KIND:
                g += d.company_fee_usdt or 0
            return g

        def _margin_slice(deals):
            volume = sum(usdt[d.id][0] for d in deals)
            gross = sum(_gross_of(d) for d in deals)
            payout = sum(d.referrer_payout_usdt or 0 for d in deals)
            net = sum((d.net_profit_usdt if d.net_profit_usdt is not None else d.profit_usdt) or 0
                      for d in deals)
            # В среднее по сделкам идут только сделки с обеими известными ногами:
            # без прихода в USDT процента не существует, а не «минус сто»
            rated = [d for d in deals if d.profit_percent is not None
                     and d.payin_amount_usdt and d.payout_amount_usdt]
            return {
                'deals': len(deals),
                'volume_usdt': round(volume, 2),
                'avg_check': round(volume / len(deals), 2) if deals else 0,
                # Среднее по сделкам, база — себестоимость (как в карточке сделки)
                'avg_margin_deal': round(sum(d.profit_percent for d in rated) / len(rated), 2)
                                   if rated else None,
                'rated_deals': len(rated),
                'loss_deals': len([d for d in rated if d.profit_percent <= 0]),
                # По деньгам — доля от объёма, взвешивается сама собой
                'margin_gross': round(gross / volume * 100, 2) if volume else None,
                'margin_net': round(net / volume * 100, 2) if volume else None,
                'gross_profit_usdt': round(gross, 2),
                'referrer_payout_usdt': round(payout, 2),
                'net_profit_usdt': round(net, 2),
                'profit_per_deal': round(net / len(deals), 2) if deals else 0,
            }

        _ref_deals = [d for d in period_deals if d.referrer_id]
        _own_deals = [d for d in period_deals if not d.referrer_id]
        # Уникальные рефереры: и «главный» на сделке, и агенты каскада — иначе
        # партнёр второго уровня в счёт не попадёт. Одним запросом, не в цикле
        _agent_ref_ids = set()
        if period_deals:
            _agent_ref_ids = {rid for (rid,) in session.query(DealAgent.referrer_id).filter(
                DealAgent.deal_id.in_([d.id for d in period_deals]),
                DealAgent.referrer_id.isnot(None)).distinct().all()}
        margin_block = {
            'all': _margin_slice(period_deals),
            'with_referrer': _margin_slice(_ref_deals),
            'own': _margin_slice(_own_deals),
            'unique_referrers': len({d.referrer_id for d in _ref_deals} | _agent_ref_ids),
        }

        # Доход лизхолда расходится по двум карманам: комиссия оседает БАТАМИ на
        # счёте MF Corp, в USDT остаётся только остаток кошелька. Сумма в батах —
        # отдельно, иначе по дашборду кажется, что весь доход лежит в крипте.
        realty_fee_thb = round(sum(d.company_fee_thb or 0 for d in period_deals
                                   if d.deal_kind == MF_REALTY_KIND), 2)
        realty_fee_usdt = round(sum(d.company_fee_usdt or 0 for d in period_deals
                                    if d.deal_kind == MF_REALTY_KIND), 2)

        # ── Единая идентичность клиента (шапка юнит-экономики И каналы) ──
        # У части WON-сделок нет client_id (карточку не завели), у LOSE его нет
        # никогда. Ключ = client_id, если есть; иначе имя, сматченное на
        # client_id через мост «имя → id». Раньше шапка считала B по client_id,
        # а каналы — по имени: один человек дробился на двух покупателей и
        # суммы по каналам не сходились с итогом.
        from sqlalchemy import func as _f

        def _norm_name(d):
            return (d.client_name or (d.client.name if d.client else '') or '').strip().lower()

        _name_to_cid = {}
        for d in period_deals:
            nm = _norm_name(d)
            if nm and d.client_id:
                _name_to_cid.setdefault(nm, d.client_id)

        def _client_ident(d):
            """Идентичность клиента: client_id, иначе имя (сматченное на id)."""
            if d.client_id:
                return f'c{d.client_id}'
            nm = _norm_name(d)
            if nm:
                cid = _name_to_cid.get(nm)
                return f'c{cid}' if cid else f'n{nm}'
            return f'd{d.id}'

        period_buyer_idents = {_client_ident(d) for d in period_deals}

        # Дата первой сделки каждого покупателя — новые/повторные (итог и каналы)
        _first_seen = {}
        _cids = [int(i[1:]) for i in period_buyer_idents if i.startswith('c')]
        if _cids:
            for cid, ts in session.query(Deal.client_id, _f.min(Deal.created_at)).filter(
                Deal.client_id.in_(_cids), Deal.status.in_(ACTIVE_STATUSES),
            ).group_by(Deal.client_id):
                _first_seen[f'c{cid}'] = ts
        _names = [i[1:] for i in period_buyer_idents if i.startswith('n')]
        if _names:
            _name_key = _f.lower(_f.trim(Deal.client_name))
            for nm, ts in session.query(_name_key, _f.min(Deal.created_at)).filter(
                _name_key.in_(_names), Deal.status.in_(ACTIVE_STATUSES),
            ).group_by(_name_key):
                _first_seen[f'n{nm}'] = ts

        def _is_new_buyer(ident):
            first = _first_seen.get(ident)
            return first is None or first >= chart_start

        # График: прибыль и объём по дням (те же завершённые сделки периода)
        month_deals = period_deals
        daily_data = {}
        for d in month_deals:
            day_key = d.created_at.strftime('%d.%m') if d.created_at else None
            if not day_key:
                continue
            if day_key not in daily_data:
                daily_data[day_key] = {'profit': 0, 'volume': 0, 'count': 0}
            daily_data[day_key]['profit'] += d.net_profit_usdt or d.profit_usdt or 0
            daily_data[day_key]['volume'] += usdt[d.id][0]
            daily_data[day_key]['count'] += 1

        # Сортируем по дате (до конца диапазона, но не дальше сегодня)
        chart_days = []
        last_day = min(today, chart_end - timedelta(days=1))
        num_days = max((last_day - chart_start).days, 0)
        for i in range(num_days + 1):
            day = chart_start + timedelta(days=i)
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
            method_stats[method]['volume'] += usdt[d.id][0]

        # New vs Old buyers за выбранный период (та же идентичность, что и B)
        new_buyers = sum(1 for i in period_buyer_idents if _is_new_buyer(i))
        old_buyers = len(period_buyer_idents) - new_buyers

        # Юнит-экономика по Красинскому: CM = B × APC × (AvP − COGS)
        buyers_total = len(period_buyer_idents)
        unit_apc = round(len(period_deals) / buyers_total, 2) if buyers_total else 0
        # AvP по всем сделкам периода, чтобы AvP × Orders = Revenue (period_avg_check
        # считается по подмножеству с payin > 0 — для карточки «Ср. чек», не для UE)
        unit_avp = round(period_volume / len(period_deals), 2) if period_deals else 0
        unit_profit_per_deal = round(period_profit / len(period_deals), 2) if period_deals else 0
        # COGS = ВСЕ переменные затраты на сделку (закупка валюты + выплаты
        # агентам), т.е. AvP − маржа. Раньше брали только закупку, а маржу —
        # из net_profit_usdt (уже после агентов): колонки одной строки считались
        # по разным базам и AvP − COGS не сходилось с «маржой со сделки».
        # Считаем разностью, чтобы строка билась до цента при любом округлении.
        unit_cogs_per_deal = round(unit_avp - unit_profit_per_deal, 2)
        unit_arpc = round(period_profit / buyers_total, 2) if buyers_total else 0

        # Лиды/CR: поток = уникальные клиенты с эпизодами (WON + LOSE) за период.
        # LOSE пушит DealCloser с 2026-07-20 — это «дошедшие до диалога», не весь
        # трафик, поэтому CR = конверсия из обращения в покупку (НЕ C1). Если LOSE
        # в периоде нет вообще — потока не знаем, оставляем None (иначе фиктивные
        # 100%). При фильтре по рефереру тоже None: у LOSE нет referrer_id.
        unit_ua = unit_c1 = unit_arpu = None
        channels_block = None
        # При фильтре по направлению лиды/каналы тоже не считаем: LOSE-сделки
        # направлением не размечены, CR вышел бы против всех обращений
        if referrer_filter in ('', 'all') and kind_filter in ('', 'all'):
            period_loses = session.query(Deal).filter(
                Deal.created_at >= chart_start,
                Deal.created_at < chart_end,
                Deal.status == DealStatus.LOSE,
                Deal.is_test.isnot(True),
            ).all()
            if period_loses and buyers_total:
                ua_idents = period_buyer_idents | {_client_ident(d) for d in period_loses}
                unit_ua = len(ua_idents)
                if unit_ua:
                    unit_c1 = round(buyers_total / unit_ua * 100, 1)
                    unit_arpu = round(unit_arpc * buyers_total / unit_ua, 2)

            # ── Воронка по каналам привлечения (методология Красинского) ──
            # Канал = utm_source из start-парама бота (пишет DealCloser).
            # Раздельные знаменатели: UA (Метрика, users — не визиты) → лиды
            # (обращения WON+LOSE) → покупатели (новых отдельно — CAC канала
            # относится только к новым; «Старые = Все − Новые»).
            def _deal_channel(d):
                if d.source_channel:
                    return d.source_channel
                # Легаси-сделки без канала: рефские выводим из имени реферера
                if d.referrer_name:
                    return f'ref:{d.referrer_name}'
                return 'без метки'

            ch_agg = {}
            def _ch_entry(name):
                return ch_agg.setdefault(name, {
                    'channel': name, 'lead_idents': set(), 'buyer_idents': set(),
                    'new_buyers': 0, 'deals': 0, 'volume_usdt': 0.0, 'profit_usdt': 0.0,
                })
            for d in period_deals:
                e = _ch_entry(_deal_channel(d))
                e['deals'] += 1
                e['volume_usdt'] += usdt[d.id][0]
                e['profit_usdt'] += d.net_profit_usdt if d.net_profit_usdt is not None else (d.profit_usdt or 0)

            # Лиды/покупатели — по каналу ПЕРВОГО касания клиента в периоде.
            # Клиент со сделками из разных каналов иначе считается в каждом и
            # сумма по каналам больше итога (у Красинского лид принадлежит
            # каналу привлечения). Сделки/объём/маржа остаются по метке сделки.
            first_touch = {}
            for d in sorted(period_deals + period_loses,
                            key=lambda x: x.created_at or chart_start):
                first_touch.setdefault(_client_ident(d), _deal_channel(d))
            for ident, ch_name in first_touch.items():
                e = _ch_entry(ch_name)
                e['lead_idents'].add(ident)
                if ident in period_buyer_idents:
                    e['buyer_idents'].add(ident)
                    if _is_new_buyer(ident):
                        e['new_buyers'] += 1

            # Трафик/расход по каналам из Метрики/рекламных кабинетов (если синкается)
            traffic_rows = session.query(
                ChannelTraffic.channel,
                _f.sum(ChannelTraffic.users), _f.sum(ChannelTraffic.visits),
                _f.sum(ChannelTraffic.spend_usd),
            ).filter(
                ChannelTraffic.date >= chart_start,
                ChannelTraffic.date < chart_end,
            ).group_by(ChannelTraffic.channel).all()
            traffic = {r[0]: {'users': int(r[1] or 0), 'visits': int(r[2] or 0),
                              'spend': round(float(r[3] or 0), 2)} for r in traffic_rows}

            channels_block = []
            for name in set(ch_agg) | set(traffic):
                e = ch_agg.get(name)
                t = traffic.get(name)
                leads = len(e['lead_idents']) if e else 0
                buyers = len(e['buyer_idents']) if e else 0
                profit = round(e['profit_usdt'], 2) if e else 0.0
                ua = t['users'] if t else None
                spend = t['spend'] if t and t['spend'] else 0.0
                row = {
                    'channel': name,
                    'ua': ua,                                  # пользователи (не визиты!)
                    'visits': t['visits'] if t else None,
                    'leads': leads,
                    # CR визит→обращение: по пользователям, не сессиям
                    'cr_visit_lead': round(leads / ua * 100, 1) if ua else None,
                    'buyers': buyers,
                    'new_buyers': e['new_buyers'] if e else 0,
                    'cr_lead_buyer': round(buyers / leads * 100, 1) if leads else None,
                    # C1 по Красинскому = покупатели / привлечённые (UA)
                    'c1': round(buyers / ua * 100, 2) if ua else None,
                    'deals': e['deals'] if e else 0,
                    'volume_usdt': round(e['volume_usdt'], 2) if e else 0.0,
                    'profit_usdt': profit,
                    'spend_usd': spend,
                    # Сходимость канала: ARPU vs CPUser (CAC — не actionable)
                    'cpuser': round(spend / ua, 2) if ua and spend else None,
                    'arpu': round(profit / ua, 2) if ua else None,
                    'gross_profit': round(profit - spend, 2) if spend else None,
                }
                channels_block.append(row)
            channels_block.sort(key=lambda r: r['profit_usdt'], reverse=True)

        # Разбивка по рефererам (для режима «Только рефералы»)
        ref_agg = {}
        for d in period_referrer_deals:
            e = ref_agg.setdefault(d.referrer_id, {
                'referrer_id': d.referrer_id,
                'name': d.referrer_name or (d.referrer_ref.name if d.referrer_ref else f'#{d.referrer_id}'),
                'deals': 0, 'volume_usdt': 0.0, 'profit_usdt': 0.0,
                'net_usdt': 0.0, 'payout_usdt': 0.0, 'clients': set(),
            })
            e['deals'] += 1
            e['volume_usdt'] += usdt[d.id][0]
            # gross = маржа сделки до выплаты рефереру, net = после (net_profit_usdt)
            e['profit_usdt'] += d.profit_usdt or 0
            e['net_usdt'] += d.net_profit_usdt if d.net_profit_usdt is not None else (d.profit_usdt or 0)
            e['payout_usdt'] += d.referrer_payout_usdt or 0
            if d.client_id:
                e['clients'].add(d.client_id)
        referrer_breakdown = []
        for e in sorted(ref_agg.values(), key=lambda x: x['profit_usdt'], reverse=True):
            referrer_breakdown.append({
                'referrer_id': e['referrer_id'],
                'name': e['name'],
                'deals': e['deals'],
                'clients': len(e['clients']),
                'volume_usdt': round(e['volume_usdt'], 2),
                'profit_usdt': round(e['profit_usdt'], 2),
                'payout_usdt': round(e['payout_usdt'], 2),
                'net_usdt': round(e['net_usdt'], 2),
                'avg_check': round(e['volume_usdt'] / e['deals'], 2) if e['deals'] else 0,
            })

        return jsonify({
            'success': True,
            'dashboard': {
                'period': {
                    'deals_count': len(period_deals),
                    'profit_usdt': period_profit,
                    'volume_usdt': period_volume,
                    'cost_usdt': period_cost,
                    'avg_margin': period_avg_margin,
                    'avg_check': period_avg_check,
                    'referrer_deals_count': len(period_referrer_deals),
                    'referrer_payout_usdt': period_referrer_payout,
                    # Карман MF Corp (лизхолд): часть чистой прибыли — баты на компании
                    'realty_fee_thb': realty_fee_thb,
                    'realty_fee_usdt': realty_fee_usdt,
                    'profit_wallet_usdt': round(period_profit - realty_fee_usdt, 2),
                },
                'unit_economics': {
                    # ТЕРМИНОЛОГИЯ: ключи легаси. 'ua' = ЛИДЫ (обращения WON+LOSE
                    # из DealCloser с 2026-07-20), 'c1' = CR лид→покупка (НЕ C1
                    # Красинского — трафика/привлечённых в CRM нет), 'arpu' =
                    # маржа на лида. None — когда LOSE в периоде нет или фильтр
                    # по рефереру. UI подписывает честно: Leads / CR / ARPL.
                    'ua': unit_ua,
                    'c1': unit_c1,
                    'buyers': buyers_total,
                    'orders': len(period_deals),
                    'apc': unit_apc,
                    'avp': unit_avp,
                    'cogs_per_deal': unit_cogs_per_deal,
                    'profit_per_deal': unit_profit_per_deal,
                    'arpc': unit_arpc,
                    # Маркетинга пока нет (органика) — CPA явный ноль, не «нет данных»
                    'cpa': 0.0,
                    'arpu': unit_arpu,
                    'cm': period_profit,
                    'revenue': period_volume,
                },
                'margins': margin_block,
                'referrer_breakdown': referrer_breakdown,
                # Воронка по каналам (None при фильтре по рефереру)
                'channels': channels_block,
                'attention': {
                    'pending_deals': len(pending_deals),
                    'unreimbursed_founders': len(unreimbursed),
                    'unreimbursed_total_usdt': round(sum(d.payout_amount_usdt or 0 for d in unreimbursed), 2)
                },
                'charts': {
                    'daily': chart_days,
                    'methods': method_stats,
                    'buyers': {'new': new_buyers, 'old': old_buyers, 'total': buyers_total}
                }
            }
        })
    finally:
        session.close()

# ==================== REIMBURSEMENTS API ====================

def _tron_tx_amount(tx_hash):
    """Сумма USDT перевода по хэшу из TronScan. None — если не прочиталась.

    Сумму перевода берём из сети, а не с рук: именно она задаёт потолок,
    сколько можно разнести по сделкам.
    """
    try:
        r = requests.get(f'https://apilist.tronscanapi.com/api/transaction-info?hash={tx_hash}',
                         timeout=10)
        if r.status_code != 200:
            return None
        trc = (r.json() or {}).get('trc20TransferInfo') or []
        if not trc:
            return None
        return round(float(trc[0].get('amount_str', 0)) / 1_000_000, 2) or None
    except Exception as e:
        app.logger.warning(f'tron tx amount {tx_hash[:16]}: {e}')
        return None


def _tron_tx_to_address(tx_hash):
    """Кошелёк-получатель перевода по хэшу. None — если не прочиталось.

    Отдельно от _tron_tx_amount: та функция мокается в тестах и используется
    возмещениями, её контракт не трогаем.
    """
    try:
        r = requests.get(f'https://apilist.tronscanapi.com/api/transaction-info?hash={tx_hash}',
                         timeout=10)
        if r.status_code != 200:
            return None
        trc = (r.json() or {}).get('trc20TransferInfo') or []
        return (trc[0].get('to_address') or None) if trc else None
    except Exception as e:
        app.logger.warning(f'tron tx to_address {tx_hash[:16]}: {e}')
        return None


@app.route('/api/reimbursements/tx', methods=['GET'])
def get_reimbursement_txs():
    """Переводы с остатками — подсказка для формы возмещения.

    `?founder=` фильтрует по фаундеру, `?only_free=1` оставляет только те,
    из которых ещё есть что взять.
    """
    from sqlalchemy.orm import selectinload
    session = get_session()
    try:
        q = session.query(ReimbursementTx).options(selectinload(ReimbursementTx.uses))
        founder = (request.args.get('founder') or '').strip()
        if founder:
            q = q.filter(ReimbursementTx.founder_name == founder)
        txs = [t.to_dict() for t in q.order_by(ReimbursementTx.created_at.desc()).all()]
        if request.args.get('only_free') == '1':
            txs = [t for t in txs if t['free_usdt'] > 0.01]
        return jsonify({'success': True, 'txs': txs})
    finally:
        session.close()


@app.route('/api/reimbursements/pending', methods=['GET'])
def get_pending_reimbursements():
    """Get deals awaiting reimbursement, grouped by founder"""
    from sqlalchemy.orm import joinedload, selectinload
    session = get_session()
    try:
        # Find deals with founder_personal source that haven't been reimbursed
        deals = session.query(Deal).options(joinedload(Deal.client), selectinload(Deal.agents)).filter(
            Deal.payout_source == PayOutSource.FOUNDER_PERSONAL,
            Deal.reimbursement_id == None,
            Deal.payout_founder_name != None,
            Deal.needs_reimbursement != False,
            Deal.is_test.isnot(True)
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

        # ── Переводы: сколько берём из каждого ────────────────────────────
        # Раньше ничто не мешало ввести тот же хэш второй раз и «возместить» одни
        # и те же деньги дважды. Теперь перевод — сущность с суммой, а возмещение
        # берёт из него долю; больше остатка взять нельзя.
        tx_uses_req = data.get('tx_uses') or []
        if not tx_uses_req and tx_hashes:
            # Обратная совместимость: старый фронт шлёт только хэши. Считаем,
            # что берём всю сумму возмещения, разложенную по переводам поровну.
            share = float(amount_usdt) / len(tx_hashes)
            tx_uses_req = [{'tx_hash': h.strip(), 'amount_usdt': share}
                           for h in tx_hashes if h.strip()]

        prepared_uses = []
        for item in tx_uses_req:
            h = str(item.get('tx_hash') or '').strip()
            if not h:
                continue
            try:
                take = round(float(item.get('amount_usdt') or 0), 2)
            except (TypeError, ValueError):
                return jsonify({'success': False, 'error': f'Некорректная сумма по переводу {h[:16]}…'}), 400

            tx = session.query(ReimbursementTx).filter(ReimbursementTx.tx_hash == h).first()
            if tx is None:
                # Первый раз видим перевод — сумму берём из блокчейна, а не с рук.
                onchain = _tron_tx_amount(h)
                tx = ReimbursementTx(
                    tx_hash=h, founder_name=founder_name,
                    amount_usdt=onchain if onchain is not None else (take or 0),
                    source='tronscan' if onchain is not None else 'manual',
                )
                session.add(tx)
                session.flush()
            if not take:
                take = tx.free_usdt()

            free = tx.free_usdt()
            if take > free + 0.01 and not data.get('force'):
                # Куда перевод уже ушёл. Без этого «доступно $0.00» читается как
                # поломка, хотя чаще всего это повторный клик по устаревшей форме:
                # возмещение уже создано, сделка из списка ожидающих ушла.
                with session.no_autoflush:
                    prev = session.query(ReimbursementTxUse, Reimbursement).join(
                        Reimbursement, ReimbursementTxUse.reimbursement_id == Reimbursement.id
                    ).filter(ReimbursementTxUse.tx_id == tx.id).all()
                where = '; '.join(
                    f'возмещение #{r.id} от {r.created_at.strftime("%d.%m")} на ${u.amount_usdt:.2f}'
                    for u, r in prev)
                return jsonify({
                    'success': False,
                    'error': (f'Из перевода {h[:16]}… доступно ${free:.2f} '
                              f'(всего ${(tx.amount_usdt or 0):.2f}), запрошено ${take:.2f}'
                              + (f'. Уже учтён: {where} — обнови страницу.' if where else '')),
                    'tx_hash': h, 'tx_free_usdt': free,
                    'used_in': [{'reimbursement_id': r.id, 'amount_usdt': u.amount_usdt}
                                for u, r in prev],
                }), 409
            prepared_uses.append((tx, take))

        # ── Явные доли по сделкам ─────────────────────────────────────────
        alloc_req = {}
        for item in (data.get('deal_allocations') or []):
            try:
                alloc_req[int(item.get('deal_id'))] = round(float(item.get('amount_usdt') or 0), 2)
            except (TypeError, ValueError):
                return jsonify({'success': False, 'error': 'Некорректная сумма в распределении'}), 400
        taken_total = round(sum(t for _, t in prepared_uses), 2)
        if alloc_req and taken_total and round(sum(alloc_req.values()), 2) > taken_total + 0.01:
            return jsonify({
                'success': False,
                'error': f'Распределено ${sum(alloc_req.values()):.2f}, а из переводов взято ${taken_total:.2f}',
            }), 400

        # Create reimbursement
        reimbursement = Reimbursement(
            founder_name=founder_name,
            amount_usdt=amount_usdt,
            tx_hash=tx_hash
        )
        session.add(reimbursement)
        session.flush()  # Get the ID

        for tx, take in prepared_uses:
            session.add(ReimbursementTxUse(tx_id=tx.id, reimbursement_id=reimbursement.id,
                                           amount_usdt=take))
        
        # Update deals
        # CR-05: блокировка строк сделок на время возмещения. Без with_for_update
        # параллельный create_reimbursement / update_deal по тем же id мог переписать
        # payout_amount_usdt и привести к двойной выплате/потере.
        # ORDER BY id для предотвращения deadlock-а при пересекающихся deal_ids.
        deals = (
            session.query(Deal)
            .filter(Deal.id.in_(deal_ids))
            .order_by(Deal.id)
            .with_for_update()
            .all()
        )
        total_thb = 0
        # Для пропорционального распределения USDT учитываем custom_payout_amount
        total_payout = sum((d.payout_amount_thb or d.custom_payout_amount or 0) for d in deals)
        for deal in deals:
            deal.reimbursement_id = reimbursement.id
            deal_payout = deal.payout_amount_thb or deal.custom_payout_amount or 0
            if deal.id in alloc_req:
                # Менеджер сказал явно, сколько этой сделке — верим ему, а не пропорции
                deal.payout_amount_usdt = alloc_req[deal.id]
            else:
                deal.payout_amount_usdt = amount_usdt * (deal_payout / total_payout) if deal_payout and total_payout else 0
            total_thb += deal_payout
            
            # Recalculate profit now that we know payout USDT
            if deal.payin_amount_usdt and deal.payout_amount_usdt:
                deal.profit_usdt = round(deal.payin_amount_usdt - deal.payout_amount_usdt, 2)
                deal.profit_percent = (deal.profit_usdt / deal.payout_amount_usdt * 100) if deal.payout_amount_usdt > 0 else 0

                # Пересчёт выплат агентам + net от новой прибыли И синхронизация
                # строк deal_agents (источник Telegram-уведомления). Раньше тут
                # пересчитывался только legacy-реферер, а строки deal_agents
                # оставались со стартовым payout=0 → уведомление расходилось с net.
                _refresh_deal_agents(session, deal)

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

        # Webhook в DealCloser/Bitrix — как в update_deal при завершении. Без него
        # возмещённые сделки не долетали до внешних систем (несогласованность путей).
        for deal in deals:
            try:
                send_deal_completed_webhook(deal)
            except Exception as wh_err:
                print(f'[Webhook] Error on reimbursement: {wh_err}')

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
    # Возвращаем только факт конфигурации, не сам URL — нечего показывать в UI
    # компрометированному аккаунту, и нечего экспортировать через XSS.
    return jsonify({'success': True, 'is_configured': bool(WEBHOOK_URL)})

@app.route('/api/webhook/config', methods=['POST'])
def set_webhook_config():
    """CR-06: эндпоинт отключён.

    Раньше любой авторизованный пользователь мог подменить WEBHOOK_URL в глобальной
    переменной → все будущие выплаты сделок уходили на сторонний URL (SSRF/exfil
    канал, без валидации схемы и приватных IP, без аудит-лога, переживало между
    запросами в gunicorn-воркере с недетерминированным состоянием между воркерами).

    Теперь URL задаётся только через CRM_WEBHOOK_URL env var на Railway. Менять —
    через дашборд Railway, не через API.

    TODO: при необходимости UI-управления — модель SystemSettings + audit log +
    валидация (https-only, блокировка приватных диапазонов 127/10/172.16/192.168/169.254).
    """
    return jsonify({
        'success': False,
        'error': 'Endpoint disabled. Set CRM_WEBHOOK_URL via Railway env vars.',
    }), 403

# ==================== TELEGRAM NOTIFICATION ====================

def send_telegram_notification(text, thread_id=None):
    """Отправляет сообщение ботом в чат.

    thread_id: id топика. Если не передан — берётся из env TELEGRAM_THREAD_ID
    (топик «Сделки», 2108 по умолчанию). Явный аргумент имеет приоритет —
    так заявки на выплату уходят в отдельный топик «Задачи».
    """
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    chat_id = os.environ.get('TELEGRAM_CHAT_ID', '-1002274229486').strip()
    if thread_id is None:
        thread_id = os.environ.get('TELEGRAM_THREAD_ID', '2108')
    thread_id = str(thread_id).strip()
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

# ── Вход реферера через Telegram Login Widget ──────────────────────────────
_login_bot_username_cache = None

def get_login_bot_token():
    """Токен бота для виджета входа. REF_LOGIN_BOT_TOKEN или фолбэк на нотификатор."""
    return (os.environ.get('REF_LOGIN_BOT_TOKEN')
            or os.environ.get('TELEGRAM_BOT_TOKEN') or '').strip()

def get_bot_username():
    """Username бота-логина без @ (getMe, кэш в памяти). None если токена нет."""
    global _login_bot_username_cache
    if _login_bot_username_cache is not None:
        return _login_bot_username_cache
    token = get_login_bot_token()
    if not token:
        return None
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
        _login_bot_username_cache = r.json()['result']['username']
    except Exception as e:
        print(f'[LoginBot] getMe error: {e}')
        return None
    return _login_bot_username_cache


def get_login_bot_id():
    """Числовой bot_id (префикс токена) для popup-авторизации Telegram.Login.auth."""
    tok = get_login_bot_token()
    return tok.split(':')[0] if tok and ':' in tok else None

def verify_telegram_auth(data: dict, bot_token: str, max_age_sec: int = 86400) -> bool:
    """Проверка подписи Telegram Login Widget (HMAC-SHA256) и свежести auth_date."""
    if not bot_token or not data.get('hash'):
        return False
    received_hash = data['hash']
    secret = hashlib.sha256(bot_token.encode()).digest()
    check = '\n'.join(f'{k}={data[k]}' for k in sorted(data) if k != 'hash')
    calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, str(received_hash)):
        return False
    try:
        if (time.time() - int(data.get('auth_date', 0))) > max_age_sec:
            return False
    except (TypeError, ValueError):
        return False
    return True

def apply_referrer_tg_binding(referrer, tg_id, tg_username):
    """
    Привязка TG-аккаунта к рефереру (trust-on-first-login). Коммитит id при первом входе.
    Возвращает (ok: bool, error: str|None).
    - есть telegram_user_id → пришедший id обязан совпасть;
    - иначе задан referrer.telegram (@username) → сверка username, совпал → биндим id;
    - иначе → биндим первый вошедший id.
    """
    tg_id = int(tg_id)
    if referrer.telegram_user_id:
        if int(referrer.telegram_user_id) != tg_id:
            return False, 'Этот Telegram-аккаунт не привязан к кабинету'
        return True, None

    expected = (referrer.telegram or '').lstrip('@').strip().lower()
    if expected:
        got = (tg_username or '').lstrip('@').strip().lower()
        if got != expected:
            return False, 'Ваш Telegram не совпадает с указанным для этого реферера'

    # Биндим id (совпал username, либо username не задан → первый вошедший)
    s = get_session()
    try:
        r = s.query(Referrer).get(referrer.id)
        r.telegram_user_id = tg_id
        s.commit()
    finally:
        s.close()
    return True, None

def ref_session_authorized(referrer, token) -> bool:
    """True если реферер в link-режиме ИЛИ в сессии есть валидная привязка по токену."""
    if (referrer.auth_mode or 'link') != 'telegram':
        return True
    auth = flask_session.get('ref_auth') or {}
    bound = auth.get(token)
    return bool(bound and referrer.telegram_user_id and int(bound) == int(referrer.telegram_user_id))


def _referrer_balance(db, referrer):
    """(доступно_к_выводу, всего_выплачено) по строкам агента на завершённых сделках."""
    agent_rows = db.query(DealAgent).filter(DealAgent.referrer_id == referrer.id).all()
    if not agent_rows:
        return 0.0, 0.0
    completed_ids = {row.id for row in db.query(Deal.id).filter(
        Deal.id.in_(list({r.deal_id for r in agent_rows})),
        Deal.status == DealStatus.COMPLETED).all()}
    rows = [r for r in agent_rows if r.deal_id in completed_ids]
    earned = sum(r.payout_usdt or 0 for r in rows)
    paid = sum((r.payout_usdt or 0) for r in rows if r.paid)
    return round(earned - paid, 2), round(paid, 2)


# ── Выплата рефереру в батах: курс со стакана Bitazza ──────────────────────
# Публичный HTTPS-мост AlphaPoint APEX (авторизация не нужна).
# Уровень стакана: idx 6 = Price, 8 = Quantity (USDT), 9 = Side (0=bid, 1=ask).
BITAZZA_L2_URL = 'https://apexapi.bitazza.com/AP/GetL2Snapshot'
BITAZZA_INST_USDT_THB = 5      # InstrumentId пары USDT/THB (OMSId=1)
THB_PAYOUT_MARGIN = 0.0025     # −0.25% от VWAP — курс клиенту
THB_PAYOUT_FEE = 20            # фикс за банковский перевод, ฿ (клиенту не показываем)
_BITAZZA_CACHE = {'bids': None, 'ts': 0.0}
_BITAZZA_TTL = 30              # сек; VWAP на сумму считаем локально из кэша


def _bitazza_bids():
    """Bids стакана USDT/THB [(price, qty), …] по цене ↓. Кэш 30 сек, при ошибке сети — последний удачный."""
    now = time.time()
    if _BITAZZA_CACHE['bids'] and now - _BITAZZA_CACHE['ts'] < _BITAZZA_TTL:
        return _BITAZZA_CACHE['bids']
    try:
        r = requests.get(BITAZZA_L2_URL, timeout=6, params={
            'OMSId': 1, 'InstrumentId': BITAZZA_INST_USDT_THB, 'Depth': 400})
        bids = sorted(((float(l[6]), float(l[8])) for l in r.json()
                       if l[9] == 0 and float(l[8]) > 0), reverse=True)
        if bids:
            _BITAZZA_CACHE.update(bids=bids, ts=now)
    except Exception as e:
        print(f'[Bitazza] book error: {e}')
    return _BITAZZA_CACHE['bids']


def thb_payout_quote(amount_usdt, bids=None):
    """Котировка выплаты в батах: VWAP по стакану на объём → −0.25% → −20฿.

    None — если стакана нет / объём не покрыт / сумма после вычетов ≤ 0.
    Курс фиксируется в момент заявки — задача команды успеть откупить.
    """
    if bids is None:
        bids = _bitazza_bids()
    if not bids or not amount_usdt or amount_usdt <= 0:
        return None
    remaining, thb = amount_usdt, 0.0
    for price, qty in bids:
        take = min(remaining, qty)
        thb += take * price
        remaining -= take
        if remaining <= 0:
            break
    if remaining > 0:  # стакан не покрыл объём — не считаем по неполному
        return None
    vwap = thb / amount_usdt
    client_rate = vwap * (1 - THB_PAYOUT_MARGIN)
    thb_amount = int(amount_usdt * client_rate - THB_PAYOUT_FEE)  # округление вниз до бата
    if thb_amount <= 0:
        return None
    return {'bitazza_rate': round(vwap, 4),
            'client_rate': round(client_rate, 4),
            'thb_amount': thb_amount}


def ref_lang(referrer):
    """Язык партнёра: 'ru' | 'en'. Реферер может быть None (защитный дефолт)."""
    return 'en' if (referrer is not None and (getattr(referrer, 'lang', None) or 'ru') == 'en') else 'ru'


def ref_t(referrer, ru, en):
    """Текст сообщения партнёру на его языке. Кабинет и уведомления должны совпадать:
    англоязычный партнёр не должен получать русские пуши после английского кабинета."""
    return en if ref_lang(referrer) == 'en' else ru


def _cancel_button(req_id, referrer=None):
    """Inline-клавиатура с кнопкой отмены заявки."""
    label = ref_t(referrer, '❌ Отменить заявку', '❌ Cancel request')
    return [[{'text': label, 'callback_data': f'cancel:{req_id}'}]]


def send_referrer_dm(referrer, text, buttons=None):
    """DM рефереру через @grusha_lk_bot. Пропуск если нет токена/привязки TG."""
    token = get_login_bot_token()
    if not token or not referrer.telegram_user_id:
        return False
    payload = {'chat_id': int(referrer.telegram_user_id), 'text': text,
               'parse_mode': 'HTML', 'disable_web_page_preview': True}
    if buttons:
        payload['reply_markup'] = json.dumps({'inline_keyboard': buttons})
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json=payload, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f'[ReferrerDM] error: {e}')
        return False


def _tg_send_document(token, chat_id, blob, filename, caption, thread_id=None):
    """sendDocument ботом (чек выплаты). Возвращает file_id или None.

    Файл на диске не храним (Railway ephemeral FS) — он живёт в Telegram.
    """
    if not token or not chat_id:
        return None
    try:
        data = {'chat_id': chat_id, 'caption': caption, 'parse_mode': 'HTML'}
        if thread_id:
            data['message_thread_id'] = int(thread_id)
        r = requests.post(f"https://api.telegram.org/bot{token}/sendDocument",
                          data=data, files={'document': (filename, blob)}, timeout=20)
        if r.status_code == 200:
            return ((r.json().get('result') or {}).get('document') or {}).get('file_id')
        print(f'[TG sendDocument] {r.status_code}: {r.text[:200]}')
    except Exception as e:
        print(f'[TG sendDocument] error: {e}')
    return None


def _cancel_payout(db, req):
    """Отмена заявки: статус→cancelled + processed_at. True если реально отменили."""
    if req.status not in ('new', 'in_progress'):
        return False
    req.status = 'cancelled'
    req.processed_at = datetime.utcnow()
    db.commit()
    return True


def notify_agents_new_deal(db, deal):
    """DM каждому реферер-агенту завершённой сделки: начислено + кнопка «Вывести».
    Мульти-агент: каждому шлём его сумму. Пропуск агентов без привязки TG или без начисления."""
    try:
        for ag in (deal.agents or []):
            if not ag.referrer_id or not (ag.payout_usdt or 0):
                continue
            referrer = db.query(Referrer).get(ag.referrer_id)
            if not referrer or not referrer.telegram_user_id:
                continue
            available, _ = _referrer_balance(db, referrer)
            msg = ref_t(referrer,
                        f"🎉 <b>Новая сделка!</b>\n\n"
                        f"Начислено к выводу: <b>${ag.payout_usdt:.2f}</b>\n"
                        f"Всего доступно: <b>${available:.2f}</b>",
                        f"🎉 <b>New deal!</b>\n\n"
                        f"Added to your balance: <b>${ag.payout_usdt:.2f}</b>\n"
                        f"Total available: <b>${available:.2f}</b>")
            url = f"https://grusha.up.railway.app/ref/{referrer.token}"
            btn = ref_t(referrer, '💸 Вывести', '💸 Withdraw')
            send_referrer_dm(referrer, msg, buttons=[[{'text': btn, 'url': url}]])
    except Exception as e:
        print(f'[ReferrerDM] new deal notify error: {e}')


def _tg_answer_callback(token, cq_id, text):
    """Ответ на callback_query (всплывающий тост в Telegram)."""
    try:
        requests.post(f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                      json={'callback_query_id': cq_id, 'text': text}, timeout=10)
    except Exception as e:
        print(f'[LKBot] answerCallback error: {e}')


def _tg_edit_message(token, cq, new_text):
    """Правка исходного сообщения с кнопкой (убираем клавиатуру, меняем текст)."""
    msg = cq.get('message') or {}
    chat = (msg.get('chat') or {}).get('id')
    mid = msg.get('message_id')
    if not chat or not mid:
        return
    try:
        requests.post(f"https://api.telegram.org/bot{token}/editMessageText",
                      json={'chat_id': chat, 'message_id': mid, 'text': new_text,
                            'parse_mode': 'HTML'}, timeout=10)
    except Exception as e:
        print(f'[LKBot] editMessage error: {e}')


@app.route('/api/tg/lk-webhook', methods=['POST'])
def lk_bot_webhook():
    """Webhook @grusha_lk_bot: inline-отмена заявки + вход через бота (/start login_)."""
    secret = os.environ.get('REF_LK_WEBHOOK_SECRET', '')
    if not secret or request.headers.get('X-Telegram-Bot-Api-Secret-Token') != secret:
        return jsonify({'ok': False}), 403
    update = request.get_json(silent=True) or {}

    # Вход через бота: /start login_<nonce> — юзер выбрал аккаунт в приложении Telegram
    msg = update.get('message') or {}
    text = (msg.get('text') or '').strip()
    if text.startswith('/start login_'):
        nonce = text[len('/start login_'):].strip()
        frm = msg.get('from') or {}
        chat_id = (msg.get('chat') or {}).get('id')
        token = get_login_bot_token()
        db = get_session()
        try:
            ln = db.query(LoginNonce).get(nonce)
            fresh = ln and not ln.used and not ln.admin_id and not ln.tg_id and (
                (datetime.utcnow() - (ln.created_at or datetime.utcnow())).total_seconds() <= LOGIN_NONCE_TTL_SEC)
            if not fresh:
                reply = '⏰ Код входа устарел. Вернитесь на страницу входа и нажмите кнопку ещё раз.'
            elif ln.referrer_id:
                # Вход в кабинет реферера: те же правила привязки, что и у виджета
                referrer = db.query(Referrer).filter_by(id=ln.referrer_id, active=True).first()
                ok, err = (apply_referrer_tg_binding(referrer, frm.get('id'), frm.get('username'))
                           if referrer else (False, 'Кабинет не найден'))
                # apply_referrer_tg_binding закрывает scoped-сессию → ln отцепился; перечитываем
                ln = db.query(LoginNonce).get(nonce)
                if ok:
                    ln.tg_id = int(frm.get('id'))
                    db.commit()
                    reply = ref_t(referrer,
                                  '✅ Вход подтверждён!\n'
                                  'Вернитесь в браузер — кабинет откроется автоматически.',
                                  '✅ Login confirmed!\n'
                                  'Go back to the browser — your dashboard will open automatically.')
                else:
                    ln.denied = True
                    db.commit()
                    reply = f'❌ {err or ref_t(referrer, "Этот Telegram-аккаунт не подходит для этого кабинета.", "This Telegram account cannot access this dashboard.")}'
                    # Security-уведомление владельцу кабинета о чужой попытке входа
                    try:
                        if referrer and referrer.telegram_user_id:
                            who = ('@' + frm['username']) if frm.get('username') else (
                                frm.get('first_name') or ref_t(referrer, 'неизвестный аккаунт', 'unknown account'))
                            send_referrer_dm(referrer, ref_t(referrer,
                                f"⚠️ <b>Попытка входа в ваш кабинет</b>\n\n"
                                f"По вашей ссылке пытались войти с другого Telegram-аккаунта "
                                f"({who}) — вход отклонён.\n\n"
                                f"Если это были вы — войдите со своего привязанного аккаунта.",
                                f"⚠️ <b>Login attempt on your account</b>\n\n"
                                f"Someone tried to open your dashboard from a different Telegram "
                                f"account ({who}) — the attempt was rejected.\n\n"
                                f"If that was you, sign in with your linked account."))
                    except Exception as e:
                        print(f'[LKBot] attempt notify error: {e}')
            else:
                admin = _match_admin_by_tg(db, frm.get('id'), frm.get('username'))
                if admin:
                    ln.admin_id = admin.id
                    db.commit()
                    reply = (f'✅ Вход подтверждён, {admin.display_name or admin.username}!\n'
                             f'Вернитесь в браузер — CRM откроется автоматически.')
                else:
                    ln.denied = True
                    db.commit()
                    reply = '❌ Этот Telegram-аккаунт не в списке администраторов CRM.'
        finally:
            db.close()
        if chat_id and token:
            try:
                requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                              json={'chat_id': chat_id, 'text': reply}, timeout=10)
            except Exception as e:
                print(f'[LKBot] login reply error: {e}')
        return jsonify({'ok': True})

    cq = update.get('callback_query')
    if not cq:
        return jsonify({'ok': True})
    token = get_login_bot_token()
    data = cq.get('data') or ''
    from_id = (cq.get('from') or {}).get('id')
    if data.startswith('cancel:'):
        try:
            req_id = int(data.split(':', 1)[1])
        except ValueError:
            return jsonify({'ok': True})
        db = get_session()
        try:
            req = db.query(PayoutRequest).get(req_id)
            referrer = db.query(Referrer).get(req.referrer_id) if req else None
            # Авторизация: колбэк только от владельца заявки
            if (not req or not referrer or not referrer.telegram_user_id
                    or int(referrer.telegram_user_id) != int(from_id or 0)):
                _tg_answer_callback(token, cq.get('id'),
                                    ref_t(referrer, 'Нет доступа', 'No access'))
                return jsonify({'ok': True})
            if _cancel_payout(db, req):
                _tg_answer_callback(token, cq.get('id'),
                                    ref_t(referrer, 'Заявка отменена', 'Request cancelled'))
                _tg_edit_message(token, cq, ref_t(referrer,
                                                  '❌ Заявка на выплату отменена',
                                                  '❌ Withdrawal request cancelled'))
            else:
                _tg_answer_callback(token, cq.get('id'),
                                    ref_t(referrer, 'Заявка уже обработана', 'Request already processed'))
        finally:
            db.close()
    return jsonify({'ok': True})

@app.route('/api/doverka/payments', methods=['GET'])
def doverka_payments_history():
    """Прокси для получения истории платежей Доверки.

    Курсы с Доверки больше не тянем (RUB-USDT = Рапира+2%), но история
    платежей нужна для сверки старых сделок — ключ читаем напрямую из env.
    """
    key = os.getenv('DOVERKA_API_KEY', '')
    if not key:
        return jsonify({'success': False, 'error': 'No Doverka API key'}), 500
    params = {k: v for k, v in request.args.items()}
    resp = requests.get(
        'https://api.doverkapay.com/v1/payments',
        headers={'Authorization': f'Bearer {key}', 'accept': 'application/json'},
        params=params, timeout=15
    )
    return jsonify(resp.json()), resp.status_code


# Рельс платёжных ссылок Grusha Exchange. sberbank-sbp — сберовский СБП с QR НСПК
# (то же, чем платят клиенты WL-бота). Менять только через env, не в коде.
CONNECTOR_PROVIDER = os.environ.get('CONNECTOR_PROVIDER', 'sberbank-sbp')


def _extract_sbp_link(data):
    """Прямая ссылка НСПК из ответа коннектора (она же за QR на странице оплаты)."""
    ext = ((data.get('provider_payload') or {}).get('externalParams') or {})
    sbp = ext.get('sbpPayload') or data.get('approve_url')
    return sbp if sbp and 'nspk.ru' in str(sbp) else None


# Детали выставленных ссылок: order_id → сумма/฿/комментарий. Нужны, чтобы
# уведомление об оплате было человеческим — коннектор в вебхуке шлёт только
# order_id и статус. Память процесса, ограничена по размеру: потеря записи
# после рестарта не критична (уведомление придёт без деталей).
_PAYMENT_LINKS = {}
_PAYMENT_LINKS_MAX = 500
PAYMENT_PAID_STATUSES = {'PAID', 'SUCCESS', 'SUCCEEDED', 'COMPLETED', 'DONE'}


def payment_webhook_key():
    """Ключ вебхука оплаты. Из env, иначе стабильно выводится из SECRET_KEY."""
    key = os.environ.get('PAYMENT_WEBHOOK_KEY', '').strip()
    if key:
        return key
    import hashlib
    return hashlib.sha256(('payment-link:' + str(app.secret_key)).encode()).hexdigest()[:32]


def _payment_id_from_link(link):
    """UUID платежа из ссылки вида https://grushab-2-b.ru/iframe-v2/<uuid>/."""
    m = re.search(r'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})',
                  str(link or ''), re.I)
    return m.group(1) if m else None


def _remember_payment_link(payload, data):
    if len(_PAYMENT_LINKS) >= _PAYMENT_LINKS_MAX:
        for k in list(_PAYMENT_LINKS)[:_PAYMENT_LINKS_MAX // 5]:
            _PAYMENT_LINKS.pop(k, None)
    meta = payload.get('metadata') or {}
    _PAYMENT_LINKS[str(payload.get('order_id'))] = {
        'amount': payload.get('amount'),
        'thb': meta.get('thb_amount'),
        'comment': str(meta.get('comment') or '').strip(),
        'link': data.get('public_link') or '',
    }
    # БД — источник правды для поллера: переживает рестарты и деплои,
    # из-за которых память процесса терялась. Upsert: повторный order_id —
    # это новая ссылка, строка возвращается в PENDING.
    try:
        link = data.get('public_link') or ''
        db = get_session()
        try:
            fields = dict(
                payment_id=_payment_id_from_link(link) or str(data.get('payment_id') or '')[:64] or None,
                amount=float(payload.get('amount') or 0),
                thb=float(meta.get('thb_amount') or 0) or None,
                comment=str(meta.get('comment') or '').strip()[:256],
                link=link[:512],
            )
            row = db.query(PaymentLinkOrder).filter_by(order_id=str(payload.get('order_id'))).first()
            if row:
                for k, v in fields.items():
                    setattr(row, k, v)
                row.status = 'PENDING'
                row.paid_at = None
                row.created_at = datetime.utcnow()
            else:
                db.add(PaymentLinkOrder(order_id=str(payload.get('order_id')), **fields))
            db.commit()
        finally:
            db.close()
    except Exception as e:
        app.logger.warning(f'payment link persist failed: {e}')


def _claim_payment_link_paid(order_id):
    """Атомарно переводит ссылку PENDING→PAID (дедуп вебхука и поллера).

    Возвращает данные строки для уведомления, {'dup': True} если уже оплачена
    (второе уведомление не нужно), None если строки нет (легаси-ссылка до
    появления таблицы — уведомляем по старому пути).
    """
    db = get_session()
    try:
        row = db.query(PaymentLinkOrder).filter_by(order_id=str(order_id)).first()
        if not row:
            return None
        claimed = (db.query(PaymentLinkOrder)
                   .filter(PaymentLinkOrder.id == row.id,
                           PaymentLinkOrder.status == 'PENDING')
                   .update({'status': 'PAID', 'paid_at': datetime.utcnow()}))
        db.commit()
        if not claimed:
            return {'dup': True}
        return {'amount': row.amount, 'thb': row.thb, 'comment': row.comment or ''}
    except Exception as e:
        # БД упала — не глушим оплату: вернём None, уведомление уйдёт по старому пути
        app.logger.warning(f'payment link claim failed: {e}')
        return None
    finally:
        db.close()


def _notify_payment_paid(info, fallback_amount=0):
    """Уведомление «Оплачено» в рабочий чат — общий текст вебхука и поллера."""
    amount = (info or {}).get('amount') or fallback_amount or 0
    thb = (info or {}).get('thb')
    try:
        msg = f"💰 <b>Оплачено</b>\n{float(amount):,.0f} ₽"
        if thb:
            msg += f" → {float(thb):,.2f} ฿"
    except (TypeError, ValueError):
        msg = "💰 <b>Оплачено</b>"
    if (info or {}).get('comment'):
        msg += f"\n{info['comment']}"
    send_telegram_notification(msg)


def _notify_payment_link_created(payload, data):
    """Уведомление в рабочий чат: ссылка выставлена, ждём оплату.

    Раньше созданная ссылка нигде не светилась — команда узнавала о платеже
    только когда клиент напишет. WL-бот про свои ссылки пишет, а калькулятор молчал.
    """
    try:
        meta = payload.get('metadata') or {}
        comment = str(meta.get('comment') or '').strip()
        thb = meta.get('thb_amount') or 0
        msg = (f"🔗 <b>Ссылка на оплату создана</b>\n"
               f"{payload.get('amount', 0):,.0f} ₽" + (f" → {float(thb):,.2f} ฿" if thb else "") + "\n")
        if comment:
            msg += f"{comment}\n"
        link = data.get('public_link') or data.get('approve_url') or ''
        msg += link
        send_telegram_notification(msg)
    except Exception as e:
        app.logger.warning(f'payment link notify failed: {e}')


@app.route('/api/proxy/create-payment', methods=['POST'])
def proxy_create_payment():
    """Прокси для создания платежа. Сначала grushab-2-b.ru, fallback на Doverka API.

    CR-07: whitelist полей. Раньше форвардили произвольный JSON с серверным
    Doverka API-ключом → авторизованный пользователь мог пробрасывать любые
    Doverka-поля (callback_url, order_transaction_id чужих транзакций, и т.п.).
    """
    raw = request.get_json() or {}
    provider = str(raw.get('provider') or 'grusha')

    # Strict whitelist + явная типизация и обрезка длин.
    try:
        amount_val = float(raw.get('amount') or 0)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'invalid amount'}), 400
    if amount_val <= 0 or amount_val > 10_000_000:
        return jsonify({'success': False, 'message': 'amount out of range'}), 400

    order_id = str(raw.get('order_id') or f'GR-{int(__import__("time").time() * 1000)}')[:64]
    # Описание видно клиенту на странице оплаты, поэтому суммы туда не пишем —
    # они и так показаны отдельной строкой. Оставляем только бренд.
    description = 'Grusha Exchange'

    # Доп. безопасные поля для grushab-2-b.ru (whitelist значений где можно).
    ALLOWED_CURRENCIES = {'RUB', 'USD', 'USDT', 'THB', 'EUR'}
    ALLOWED_MERCHANTS = {'grusha'}
    currency = str(raw.get('currency') or 'RUB')[:8].upper()
    if currency not in ALLOWED_CURRENCIES:
        currency = 'RUB'
    merchant_id = str(raw.get('merchant_id') or 'grusha')[:32]
    if merchant_id not in ALLOWED_MERCHANTS:
        merchant_id = 'grusha'

    def _safe_url(u, max_len=512):
        """Только https://... URL, обрезаем длину. Пустая строка / не-https → None."""
        s = str(u or '')[:max_len]
        return s if s.startswith('https://') else ''

    success_url = _safe_url(raw.get('success_url'))
    cancel_url = _safe_url(raw.get('cancel_url'))
    failure_url = _safe_url(raw.get('failure_url'))
    merchant_image_url = _safe_url(raw.get('merchant_image_url'))
    merchant_description = str(raw.get('merchant_description') or '')[:128]

    # metadata — dict с примитивами, max 20 ключей, max 256 байт каждый.
    raw_meta = raw.get('metadata') or {}
    metadata = {}
    if isinstance(raw_meta, dict):
        for k, v in list(raw_meta.items())[:20]:
            ks = str(k)[:64]
            if isinstance(v, (int, float, bool)) or v is None:
                metadata[ks] = v
            else:
                metadata[ks] = str(v)[:256]

    # Куда коннектор постучится об оплате. Без этого CalcCRM про оплату не узнаёт
    # (раньше так и было — ссылку выставили и ждали, пока клиент сам напишет).
    base = os.environ.get('PUBLIC_BASE_URL', 'https://grusha.up.railway.app').rstrip('/')
    webhook_url = f'{base}/api/webhook/payment-link?key={payment_webhook_key()}'

    # Безопасный payload, отдаваемый в grushab-2-b.ru.
    safe_payload = {
        'webhook_url': webhook_url,
        'amount': amount_val,
        'currency': currency,
        'order_id': order_id,
        'merchant_id': merchant_id,
        'description': description,
        'success_url': success_url,
        'cancel_url': cancel_url,
        'failure_url': failure_url,
        'metadata': metadata,
        'merchant_image_url': merchant_image_url,
        'merchant_description': merchant_description,
    }

    if provider == 'grusha':
        # Страница оплаты Grusha Exchange. Рельс задаётся заголовком провайдера:
        # sberbank-sbp = наш сберовский СБП (QR НСПК, тот же, что у WL-бота),
        # sberbank = форма payecom, doverkapay = Доверка (ей больше не пользуемся).
        try:
            response = requests.post(
                'https://grushab-2-b.ru/api/payments',
                json=safe_payload,
                headers={'Content-Type': 'application/json',
                         'X-Provider-Name': CONNECTOR_PROVIDER},
                timeout=8
            )
            try:
                data = response.json()
            except Exception:
                return jsonify({'success': False, 'message': f'Grusha HTTP {response.status_code}', 'grusha_down': True}), 502
            if response.status_code < 400 and isinstance(data, dict):
                # Прямая СБП-ссылка (её же показывает QR на странице оплаты) —
                # менеджеру бывает нужна сама ссылка, а не страница-обёртка.
                data['sbp_link'] = _extract_sbp_link(data)
                _remember_payment_link(safe_payload, data)
                _notify_payment_link_created(safe_payload, data)
            return jsonify(data), response.status_code
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            return jsonify({'success': False, 'message': 'grushab-2-b.ru не отвечает', 'grusha_down': True}), 503

    elif provider == 'doverka':
        # Прямой Doverka Partner API
        key = os.getenv('DOVERKA_API_KEY', '')
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
                'amount_rub': safe_payload['amount'],
                'order_transaction_id': safe_payload['order_id'],
                'order_title': safe_payload['description'],
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
    key = os.getenv('DOVERKA_API_KEY', '')
    if not key:
        return jsonify({'success': False, 'error': 'No Doverka API key'}), 500
    resp = requests.get(
        'https://api.doverkapay.com/v1/currencies',
        headers={'Authorization': f'Bearer {key}', 'accept': 'application/json'},
        timeout=15
    )
    return jsonify(resp.json()), resp.status_code

@app.route('/api/webhook/payment-link', methods=['POST'])
def payment_link_webhook():
    """Коннектор сообщает, что ссылку оплатили → уведомление в рабочий чат.

    Отвечаем 200 даже на мусор: иначе коннектор будет ретраить бесконечно.
    Защита — ключ в query (публичный путь, тела не подписываются).
    """
    if not secrets.compare_digest(str(request.args.get('key', '')), payment_webhook_key()):
        return jsonify({'ok': False}), 403

    data = request.get_json(silent=True) or {}
    status = str(data.get('status') or '').upper().strip()
    order_id = str(data.get('order_id') or '')
    if not order_id or status not in PAYMENT_PAID_STATUSES:
        return jsonify({'ok': True}), 200

    row = _claim_payment_link_paid(order_id)
    mem = _PAYMENT_LINKS.pop(order_id, {})
    if row and row.get('dup'):
        # Поллер (или повторный вебхук) уже уведомил — молчим
        return jsonify({'ok': True}), 200
    _notify_payment_paid(row or mem, fallback_amount=data.get('amount') or 0)
    return jsonify({'ok': True}), 200


# Страховочный поллер оплат: вебхук — быстрый путь, поллер — надёжный.
PAYMENT_POLL_INTERVAL = int(os.environ.get('PAYMENT_POLL_INTERVAL', '30'))
PAYMENT_POLL_TTL_HOURS = 24
_PAYMENT_FINAL_BAD = {'EXPIRED', 'FAILED', 'CANCELED', 'CANCELLED', 'DECLINED'}


def _poll_pending_payment_links():
    """Одна итерация поллера: перепроверить PENDING-ссылки в коннекторе.

    Возвращает число отправленных уведомлений (для тестов).
    """
    sent = 0
    db = get_session()
    try:
        rows = db.query(PaymentLinkOrder).filter(PaymentLinkOrder.status == 'PENDING').all()
        cutoff = datetime.utcnow() - timedelta(hours=PAYMENT_POLL_TTL_HOURS)
        for row in rows:
            if row.created_at and row.created_at < cutoff:
                row.status = 'EXPIRED'
                db.commit()
                continue
            if not row.payment_id:
                continue
            try:
                resp = requests.get(
                    f'https://grushab-2-b.ru/api/payments/{row.payment_id}',
                    headers={'X-Provider-Name': CONNECTOR_PROVIDER}, timeout=10)
                status = str((resp.json() or {}).get('status') or '').upper()
            except Exception:
                continue  # коннектор недоступен — попробуем в следующий тик
            if status in PAYMENT_PAID_STATUSES:
                info = _claim_payment_link_paid(row.order_id)
                _PAYMENT_LINKS.pop(row.order_id, None)
                if info and not info.get('dup'):
                    _notify_payment_paid(info)
                    sent += 1
            elif status in _PAYMENT_FINAL_BAD:
                row.status = status[:16]
                db.commit()
    finally:
        db.close()
    return sent


def _payment_link_poll_loop():
    """Фоновый поллер статусов платёжных ссылок (страховка потерянных вебхуков)."""
    while True:
        time.sleep(PAYMENT_POLL_INTERVAL)
        try:
            _poll_pending_payment_links()
        except Exception as e:
            print(f"ℹ️ payment poll loop: {e}", flush=True)


if os.environ.get('PAYMENT_POLL_ENABLED', '1') == '1':
    threading.Thread(target=_payment_link_poll_loop, daemon=True, name='payment-link-poll').start()


@app.route('/api/webhook/doverka', methods=['POST'])
def doverka_webhook():
    try:
        # Публичный эндпоинт → обязательна проверка HMAC-подписи, иначе любой мог
        # бы слать фейковые «оплата получена» в рабочий чат.
        import hmac as _hmac, hashlib as _hashlib
        secret = os.environ.get('DOVERKA_WEBHOOK_SECRET', '')
        if not secret:
            app.logger.error('Webhook Doverka: DOVERKA_WEBHOOK_SECRET не задан — отклоняю')
            return jsonify({'error': 'webhook not configured'}), 503
        raw = request.get_data()
        signature = request.headers.get('X-Signature', '')
        expected = _hmac.new(secret.encode(), raw, _hashlib.sha256).hexdigest()
        if not _hmac.compare_digest(signature, expected):
            app.logger.warning('Webhook Doverka: неверная подпись')
            return jsonify({'error': 'invalid signature'}), 401

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
        old_status = deal.status
        just_completed = False
        if deal.status == DealStatus.PENDING:
            deal.status = DealStatus.COMPLETED
            just_completed = True

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

        # Согласованность с update_deal: при переходе в COMPLETED шлём
        # webhook (DealCloser/Bitrix) + GSheet + Telegram, иначе сделки,
        # завершённые через подтверждение Doverka, никуда не долетали.
        if just_completed:
            try:
                send_deal_completed_webhook(deal)
            except Exception as wh_err:
                print(f'[Webhook] Error on doverka confirm: {wh_err}')
            if deal.profit_usdt is not None and deal.reimbursement_id is None:
                try:
                    sync_deals_to_gsheet([deal])
                except Exception as gs_err:
                    print(f'[GSheet] Error on doverka confirm: {gs_err}')
                try:
                    _send_deal_telegram(deal)
                except Exception as tg_err:
                    print(f'[Telegram] Error on doverka confirm: {tg_err}')

        return jsonify({'success': True, 'deal': deal.to_dict()})
    except Exception as e:
        session.rollback()
        app.logger.error(f'Request error: {e}')
        return jsonify({'success': False, 'error': 'Ошибка обработки запроса'}), 400
    finally:
        session.close()

# ==================== KYC API ====================

import secrets
import io
import zipfile
from werkzeug.utils import secure_filename

# Сколько дней держим документы после решения менеджера. Дальше фоновый
# сборщик стирает файлы, сама запись KYC (кто, когда, кем одобрен) остаётся.
KYC_RETENTION_DAYS = int(os.environ.get('KYC_RETENTION_DAYS', '365'))


def kyc_statement_template(client_name=''):
    """Дефолтный текст видео-заявления. Менеджер правит его перед отправкой ссылки."""
    who = (client_name or '').strip() or '[фамилия имя]'
    today = datetime.now().strftime('%d.%m.%Y')
    return (f'Я, {who}, сегодня {today}, подтверждаю, что провожу обмен '
            f'добровольно и в своих интересах. Денежные средства принадлежат мне, '
            f'по просьбе третьих лиц я не действую.')


@app.route('/api/kyc/generate', methods=['POST'])
def kyc_generate_token():
    """Менеджер генерирует ссылку для клиента"""
    session = get_session()
    try:
        data = request.json or {}
        client_id = data.get('client_id')
        client_name = data.get('client_name', '')
        statement_required = bool(data.get('statement_required', False))
        statement_text = (data.get('statement_text') or '').strip()
        if statement_required and not statement_text:
            statement_text = kyc_statement_template(client_name)

        # Проверяем, нет ли уже активного KYC для клиента
        if client_id:
            existing = session.query(KycRequest).filter(
                KycRequest.client_id == client_id,
                KycRequest.status == KycStatus.PENDING
            ).first()
            if existing:
                # Условия видео-заявления могли поменяться — переносим на живую ссылку,
                # иначе менеджер думает, что задал текст, а клиент видит старый.
                existing.statement_required = statement_required
                existing.statement_text = statement_text or None
                session.commit()
                return jsonify({'success': True, 'token': existing.token, 'existing': True})

        token = secrets.token_urlsafe(16)
        kyc = KycRequest(
            token=token,
            client_id=client_id,
            client_name=client_name,
            statement_required=statement_required,
            statement_text=statement_text or None
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

        result = {
            'success': True, 'status': kyc.status,
            'statement_required': bool(kyc.statement_required),
            'statement_text': kyc.statement_text or '',
        }
        if kyc.client_name:
            result['client_name'] = kyc.client_name
        if kyc.status == KycStatus.REJECTED:
            result['rejection_reason'] = kyc.rejection_reason
        return jsonify(result)
    finally:
        session.close()

# ==================== KYC FILE VALIDATION (CR-04) ====================
# Допустимые MIME-типы фото KYC. SVG/HTML исключены — они исполняют JS при отдаче.
KYC_ALLOWED_MIME = {'image/jpeg', 'image/png', 'image/webp'}
KYC_MAX_FILE_BYTES = 5 * 1024 * 1024   # 5 МБ на фото
KYC_MAX_LIVENESS_FRAMES = 8            # макс. кадров liveness в одном запросе
# Видео-заявление: webm (Android/Chrome) или mp4 (Safari на iOS).
# 15 МБ с запасом покрывают 20 сек 480p при битрейте, который ставит страница.
KYC_ALLOWED_VIDEO_MIME = {'video/webm', 'video/mp4', 'video/quicktime', 'video/x-matroska'}
KYC_MAX_VIDEO_BYTES = 15 * 1024 * 1024

# Расширение → MIME для отдачи файла обратно менеджеру
KYC_EXT_MIME = {
    'jpg': 'image/jpeg', 'png': 'image/png', 'webp': 'image/webp',
    'webm': 'video/webm', 'mp4': 'video/mp4',
}


def _read_upload(file_storage):
    """Считать загруженный файл целиком и вернуть (blob, size)."""
    stream = file_storage.stream
    stream.seek(0)
    blob = stream.read()
    return blob, len(blob)


def _validate_kyc_image(file_storage):
    """Валидация загружаемого фото: MIME, magic bytes, размер.

    Возвращает (ok: bool, error: str | None, ext: str | None, blob: bytes | None).
    ext — нормализованное расширение под фактический magic-bytes тип.
    """
    if file_storage is None or not file_storage.filename:
        return False, 'empty_file', None, None

    mime = (file_storage.mimetype or '').lower().split(';')[0].strip()
    if mime not in KYC_ALLOWED_MIME:
        return False, f'unsupported_type:{mime}', None, None

    blob, size = _read_upload(file_storage)
    head = blob[:12]

    if head.startswith(b'\xff\xd8\xff'):
        actual_ext = 'jpg'
    elif head.startswith(b'\x89PNG\r\n\x1a\n'):
        actual_ext = 'png'
    elif head[:4] == b'RIFF' and head[8:12] == b'WEBP':
        actual_ext = 'webp'
    else:
        return False, 'invalid_image_magic', None, None

    if size <= 0:
        return False, 'empty_file', None, None
    if size > KYC_MAX_FILE_BYTES:
        return False, 'too_large', None, None

    return True, None, actual_ext, blob


def _validate_kyc_video(file_storage):
    """Валидация видео-заявления: MIME, magic bytes, размер.

    Возвращает (ok, error, ext, blob). Как и у фото, доверяем magic bytes,
    а не заголовку и не имени файла: заявленный MIME можно подделать.
    """
    if file_storage is None or not file_storage.filename:
        return False, 'empty_file', None, None

    mime = (file_storage.mimetype or '').lower().split(';')[0].strip()
    if mime not in KYC_ALLOWED_VIDEO_MIME:
        return False, f'unsupported_type:{mime}', None, None

    blob, size = _read_upload(file_storage)
    head = blob[:12]

    if head.startswith(b'\x1a\x45\xdf\xa3'):      # EBML — webm/mkv
        actual_ext = 'webm'
    elif head[4:8] == b'ftyp':                     # ISO BMFF — mp4/mov
        actual_ext = 'mp4'
    else:
        return False, 'invalid_video_magic', None, None

    if size <= 0:
        return False, 'empty_file', None, None
    if size > KYC_MAX_VIDEO_BYTES:
        return False, 'too_large', None, None

    return True, None, actual_ext, blob


@app.route('/api/kyc/submit', methods=['POST'])
@limiter.limit("10 per hour")
def kyc_submit():
    """Клиент загружает файлы верификации.

    CR-04: MIME + magic-bytes валидация (whitelist jpeg/png/webp), лимит размера 5МБ,
    rate-limit 10/час по IP, перенумерация имён файлов (имя клиента не доверяем),
    лимит количества liveness-кадров.

    Файлы кладём в БД (таблица kyc_files), а не на диск: контейнер Railway
    эфемерный, тома нет — папка kyc_uploads/ умирала с каждым деплоем.
    """
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

        # Видео-заявление обязательно, если менеджер его затребовал: без него
        # шаг легко пропустить, отредактировав запрос в обход страницы.
        statement = request.files.get('statement')
        if kyc.statement_required and (statement is None or not statement.filename):
            return jsonify({'success': False, 'error': 'statement_required'}), 400

        # Пересабмит: чистим прежние файлы, иначе старые кадры остаются
        # сиротами с PII и путаются с новыми в галерее менеджера.
        new_files = []

        # Документ
        doc = request.files.get('document')
        if doc:
            ok, err, ext, blob = _validate_kyc_image(doc)
            if not ok:
                return jsonify({'success': False, 'error': f'document_{err}'}), 400
            new_files.append(KycFile(kind='doc', idx=0, ext=ext,
                                     mime=KYC_EXT_MIME[ext], size=len(blob), data=blob))

        # Селфи с документом
        selfie = request.files.get('selfie')
        if selfie:
            ok, err, ext, blob = _validate_kyc_image(selfie)
            if not ok:
                return jsonify({'success': False, 'error': f'selfie_{err}'}), 400
            new_files.append(KycFile(kind='selfie', idx=0, ext=ext,
                                     mime=KYC_EXT_MIME[ext], size=len(blob), data=blob))

        # Liveness-кадры
        liveness_files = request.files.getlist('liveness')
        if liveness_files:
            if len(liveness_files) > KYC_MAX_LIVENESS_FRAMES:
                return jsonify({'success': False, 'error': 'too_many_liveness_frames'}), 400
            for i, f in enumerate(liveness_files):
                ok, err, ext, blob = _validate_kyc_image(f)
                if not ok:
                    return jsonify({'success': False, 'error': f'liveness_{i}_{err}'}), 400
                new_files.append(KycFile(kind='liveness', idx=i, ext=ext,
                                         mime=KYC_EXT_MIME[ext], size=len(blob), data=blob))

        # Видео-заявление
        if statement and statement.filename:
            ok, err, ext, blob = _validate_kyc_video(statement)
            if not ok:
                return jsonify({'success': False, 'error': f'statement_{err}'}), 400
            new_files.append(KycFile(kind='statement', idx=0, ext=ext,
                                     mime=KYC_EXT_MIME[ext], size=len(blob), data=blob))

        # Всё провалидировано — только теперь затираем прошлую попытку.
        # Порядок важен: при ошибке выше старые файлы остаются целы.
        session.query(KycFile).filter(KycFile.kyc_id == kyc.id).delete(synchronize_session=False)
        for f in new_files:
            f.kyc_id = kyc.id
            session.add(f)

        # Сбрасываем статус на pending если клиент перезагружает после отклонения
        kyc.status = KycStatus.PENDING
        kyc.rejection_reason = None
        kyc.reviewed_at = None
        kyc.reviewed_by = None
        kyc.files_purged_at = None

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

def _kyc_safe_name(kyc):
    """Основа имени файла при скачивании: имя клиента латиницей или id."""
    raw = secure_filename(kyc.client_name or '') or f'kyc-{kyc.id}'
    return raw[:40]


@app.route('/api/kyc/photo/<token>/<photo_type>', methods=['GET'])
def kyc_photo(token, photo_type):
    """CRM: файл верификации — doc, selfie, liveness_0..7, statement.

    `?download=1` отдаёт с Content-Disposition: attachment, чтобы менеджер мог
    сохранить документ, а не только посмотреть его в модалке.
    """
    if not flask_session.get('user_id'):
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    session = get_session()
    try:
        kyc = session.query(KycRequest).filter(KycRequest.token == token).first()
        if not kyc:
            return '', 404

        f = next((x for x in kyc.files if x.slot == photo_type), None)
        if not f:
            return '', 404

        as_attachment = request.args.get('download') in ('1', 'true', 'yes')
        return send_file(
            io.BytesIO(f.data), mimetype=f.mime,
            as_attachment=as_attachment,
            download_name=f'{_kyc_safe_name(kyc)}-{f.slot}.{f.ext}',
            max_age=0,
        )
    finally:
        session.close()


@app.route('/api/kyc/archive/<token>', methods=['GET'])
def kyc_archive(token):
    """CRM: все файлы верификации одним zip — паспорт, селфи, кадры, видео.

    Внутрь кладём README.txt с текстом заявления и решением менеджера: без него
    видео вне контекста бесполезно — непонятно, что человек должен был сказать.
    """
    if not flask_session.get('user_id'):
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    session = get_session()
    try:
        kyc = session.query(KycRequest).filter(KycRequest.token == token).first()
        if not kyc:
            return jsonify({'success': False, 'error': 'not_found'}), 404
        if not kyc.files:
            return jsonify({'success': False, 'error': 'no_files'}), 404

        base = _kyc_safe_name(kyc)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            for f in kyc.files:
                zf.writestr(f'{base}/{f.slot}.{f.ext}', f.data)
            info = [
                f'Клиент: {kyc.client_name or "—"}',
                f'Запрос создан: {kyc.created_at.strftime("%d.%m.%Y %H:%M") if kyc.created_at else "—"} UTC',
                f'Статус: {kyc.status}',
                f'Проверил: {kyc.reviewed_by or "—"}'
                + (f' {kyc.reviewed_at.strftime("%d.%m.%Y %H:%M")} UTC' if kyc.reviewed_at else ''),
            ]
            if kyc.rejection_reason:
                info.append(f'Причина отклонения: {kyc.rejection_reason}')
            if kyc.statement_text:
                info += ['', 'Текст видео-заявления, который клиент должен был произнести:',
                         kyc.statement_text]
            zf.writestr(f'{base}/README.txt', '\n'.join(info))

        buf.seek(0)
        return send_file(buf, mimetype='application/zip', as_attachment=True,
                         download_name=f'{base}-kyc.zip', max_age=0)
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

        # Файлы НЕ удаляем: документы нужны потом — вопрос банка, спор с клиентом,
        # запрос комплаенса. Их стирает ретенция через KYC_RETENTION_DAYS.
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

        # Файлы оставляем: если клиент перезальёт — kyc_submit сам заменит их,
        # а до тех пор менеджеру видно, что именно было не так.
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

        # Удаляем запись вместе с файлами (cascade на relationship files)
        session.delete(kyc)
        session.commit()
        return jsonify({'success': True})
    except Exception as e:
        session.rollback()
        app.logger.error(f'Server error: {e}')
        return jsonify({'success': False, 'error': 'Внутренняя ошибка сервера'}), 500
    finally:
        session.close()


@app.route('/api/kyc/files/<token>', methods=['DELETE'])
def kyc_purge_files(token):
    """CRM: стереть документы досрочно, оставив саму запись о верификации.

    Нужно, когда клиент просит удалить персональные данные, а факт проверки
    (кто, когда, кем одобрен) обязан остаться в истории.
    """
    session = get_session()
    try:
        kyc = session.query(KycRequest).filter(KycRequest.token == token).first()
        if not kyc:
            return jsonify({'success': False, 'error': 'not_found'}), 404
        removed = session.query(KycFile).filter(KycFile.kyc_id == kyc.id).delete(synchronize_session=False)
        kyc.files_purged_at = datetime.utcnow()
        session.commit()
        return jsonify({'success': True, 'removed': removed})
    except Exception as e:
        session.rollback()
        app.logger.error(f'Server error: {e}')
        return jsonify({'success': False, 'error': 'Внутренняя ошибка сервера'}), 500
    finally:
        session.close()


def purge_expired_kyc_files():
    """Стереть документы старше KYC_RETENTION_DAYS, сохранив записи о верификации.

    Отсчёт от даты решения менеджера, а для незакрытых заявок — от создания.
    Возвращает число очищенных заявок.
    """
    cutoff = datetime.utcnow() - timedelta(days=KYC_RETENTION_DAYS)
    session = get_session()
    try:
        stale = session.query(KycRequest).filter(
            KycRequest.files_purged_at == None,  # noqa: E711 — SQL IS NULL
            or_(
                and_(KycRequest.reviewed_at != None, KycRequest.reviewed_at < cutoff),
                and_(KycRequest.reviewed_at == None, KycRequest.created_at < cutoff),
            )
        ).all()
        purged = 0
        for kyc in stale:
            n = session.query(KycFile).filter(KycFile.kyc_id == kyc.id).delete(synchronize_session=False)
            kyc.files_purged_at = datetime.utcnow()
            if n:
                purged += 1
        if stale:
            session.commit()
        return purged
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _kyc_retention_loop():
    """Раз в сутки чистит просроченные документы KYC. Ошибки глушит — падение
    сборщика не должно ронять сервис, следующая попытка через сутки."""
    while True:
        try:
            purged = purge_expired_kyc_files()
            if purged:
                print(f"🧹 KYC retention: очищено заявок — {purged}", flush=True)
        except Exception as e:
            print(f"ℹ️ kyc retention loop: {e}", flush=True)
        time.sleep(24 * 3600)


if os.environ.get('KYC_RETENTION_ENABLED', '1') == '1':
    threading.Thread(target=_kyc_retention_loop, daemon=True, name='kyc-retention').start()

# ==================== ЗАКРЫТИЕ СДЕЛОК BITRIX (перенос из бота DealCloser) ====

@app.route('/api/bitrix/active-deals', methods=['GET'])
def bitrix_active_deals():
    """Незакрытые сделки основной воронки — список для оператора."""
    try:
        import bitrix_deals
        return jsonify({'success': True, 'deals': bitrix_deals.get_active_deals()})
    except Exception as e:
        app.logger.error(f'bitrix active deals: {e}')
        return jsonify({'success': False, 'error': f'Bitrix недоступен: {e}'}), 502


@app.route('/api/bitrix/deals/<int:deal_id>/analyze', methods=['GET'])
def bitrix_analyze_deal(deal_id):
    """Читает чат сделки и разбирает его: суммы, метод, фаундер, WON/LOSE.

    Логика разбора — та же, что была в боте: сначала ищем прошлую закрытую
    сделку этого контакта, её CLOSEDATE становится отсечкой, чтобы суммы
    прошлого обмена не приехали в новую сделку.
    """
    try:
        import bitrix_deals
        from deal_chat_analyzer import analyze_chat

        deal = bitrix_deals.get_deal(deal_id)
        if not deal:
            return jsonify({'success': False, 'error': 'Сделка не найдена в Bitrix'}), 404

        messages = bitrix_deals.get_deal_chat_messages(deal_id)
        prev_deal, total_closed = bitrix_deals.get_last_closed_deal_by_contact(
            deal.get('CONTACT_ID'), deal_id)
        prev_messages = None
        if prev_deal and 'LOSE' in str(prev_deal.get('STAGE_ID', '')):
            # Мягкая отсечка: клиент мог вернуться к тому же намерению («давай как вчера»)
            prev_messages = bitrix_deals.get_deal_chat_messages(int(prev_deal['ID']))

        result = asyncio.run(analyze_chat(
            messages,
            deal_title=deal.get('TITLE', ''),
            prev_deal=prev_deal,
            prev_deal_messages=prev_messages,
            total_closed=total_closed,
        ))

        client_name = (deal.get('TITLE') or '').replace(' - exgreen.pro', '').strip()
        payload = result.to_calccrm_payload(client_name=client_name)
        payload['bitrix_deal_id'] = deal_id
        return jsonify({
            'success': True,
            'deal': {'id': deal_id, 'title': deal.get('TITLE'), 'stage': deal.get('STAGE_ID'),
                     'contact_id': deal.get('CONTACT_ID'), 'client_name': client_name},
            'analysis': {
                'verdict': result.verdict, 'confidence': result.confidence,
                'summary': result.summary, 'intent': result.intent,
                'lose_reason': result.lose_reason, 'payment_time': result.payment_time,
                'prev_deal_id': result.prev_deal_id, 'prev_deal_stage': result.prev_deal_stage,
                'prev_deal_summary': result.prev_deal_summary,
                'prev_deal_closedate': result.prev_deal_closedate,
                'total_closed_deals': result.total_closed_deals,
                'messages_count': len(messages),
            },
            'deal_payload': payload,
        })
    except Exception as e:
        app.logger.error(f'bitrix analyze {deal_id}: {e}')
        return jsonify({'success': False, 'error': str(e)}), 502


@app.route('/api/bitrix/deals/<int:deal_id>/close-won', methods=['POST'])
def bitrix_close_won(deal_id):
    """Переводит сделку в WON. Сделку в CalcCRM фронт создаёт ДО этого вызова.

    Порядок именно такой: если запись в CRM не прошла, в Bitrix ничего не
    двигаем — иначе сделка «выиграна», а денег в учёте нет.
    """
    data = request.get_json(silent=True) or {}
    try:
        import bitrix_deals
        ok, err = bitrix_deals.close_won(deal_id, data)
        if not ok:
            return jsonify({'success': False, 'error': err}), 502
        ref = str(data.get('referrer_name') or '').strip()
        if ref:
            try:
                bitrix_deals.set_deal_utm(deal_id, ref)
            except Exception as e:
                app.logger.warning(f'utm set failed for {deal_id}: {e}')
        return jsonify({'success': True})
    except Exception as e:
        app.logger.error(f'bitrix close won {deal_id}: {e}')
        return jsonify({'success': False, 'error': str(e)}), 502


@app.route('/api/bitrix/deals/<int:deal_id>/close-lose', methods=['POST'])
def bitrix_close_lose(deal_id):
    """Переводит сделку в LOSE. Lose-сделку в CalcCRM фронт создаёт ДО вызова —
    без неё отказ не попадёт в конверсию."""
    data = request.get_json(silent=True) or {}
    try:
        import bitrix_deals
        ok, err = bitrix_deals.close_lose(deal_id, str(data.get('reason') or ''))
        if not ok:
            return jsonify({'success': False, 'error': err}), 502
        return jsonify({'success': True})
    except Exception as e:
        app.logger.error(f'bitrix close lose {deal_id}: {e}')
        return jsonify({'success': False, 'error': str(e)}), 502


# ==================== BITRIX CONTACTS SEARCH ====================

@app.route('/api/bitrix/contacts/search', methods=['GET'])
def search_bitrix_contacts():
    """Поиск контактов по сделкам основной воронки Grusha в Bitrix.
    Возвращает уникальные контакты по похожему имени в TITLE."""
    query = request.args.get('q', '').strip()
    if len(query) < 2:
        return jsonify({'success': True, 'contacts': []})

    import bitrix_deals
    try:
        data = bitrix_deals._post('crm.deal.list', {
            'filter[CATEGORY_ID]': bitrix_deals.BITRIX_PIPELINE_ID,
            'filter[%TITLE]': query,
            'order[ID]': 'DESC',
            'select[0]': 'ID',
            'select[1]': 'TITLE',
            'select[2]': 'CONTACT_ID',
        })
        # Уникальные контакты из найденных сделок
        seen = {}
        for deal in data.get('result', []):
            cid = deal.get('CONTACT_ID')
            title = deal.get('TITLE', '').replace(' - Grusha', '').strip()
            if cid and cid not in seen:
                seen[cid] = title
        contacts = [{'id': cid, 'name': name} for cid, name in list(seen.items())[:20]]
        return jsonify({'success': True, 'contacts': contacts})
    except Exception as e:
        return jsonify({'success': True, 'contacts': [], 'error': str(e)})


# ==================== REFERRAL SYSTEM ====================

@app.route('/ref/<token>')
def referrer_page(token):
    """Страница статистики реферера (публичная, по токену)"""
    return send_from_directory('static/referrer', 'index.html')


@app.route('/api/ref/<token>/tg-login', methods=['POST'])
def referrer_tg_login(token):
    """Вход реферера в кабинет через Telegram Login Widget."""
    data = request.get_json(silent=True) or {}
    db = get_session()
    try:
        referrer = db.query(Referrer).filter(Referrer.token == token, Referrer.active == True).first()
    finally:
        db.close()
    if not referrer:
        return jsonify({'success': False, 'error': 'Реферер не найден'}), 404

    bot_token = get_login_bot_token()
    if not verify_telegram_auth(data, bot_token):
        return jsonify({'success': False, 'error': 'Подпись Telegram недействительна или устарела'}), 403

    ok, err = apply_referrer_tg_binding(referrer, data.get('id'), data.get('username'))
    if not ok:
        return jsonify({'success': False, 'error': err}), 403

    flask_session.permanent = True
    auth = dict(flask_session.get('ref_auth') or {})
    auth[token] = int(data['id'])
    flask_session['ref_auth'] = auth

    _send_referrer_login_summary(referrer.id)
    return jsonify({'success': True})


def _send_referrer_login_summary(referrer_id):
    """Сводка в личку после входа в кабинет (баланс + активная заявка)."""
    try:
        db2 = get_session()
        try:
            ref2 = db2.query(Referrer).get(referrer_id)
            if not ref2:
                return
            available, total_paid = _referrer_balance(db2, ref2)
            active = db2.query(PayoutRequest).filter(
                PayoutRequest.referrer_id == ref2.id,
                PayoutRequest.status.in_(['new', 'in_progress'])).first()
            msg = ref_t(ref2,
                        f"👋 <b>Вы вошли в кабинет</b>\n\n"
                        f"💰 Доступно к выводу: <b>${available:.2f}</b>\n"
                        f"✅ Всего выплачено: ${total_paid:.2f}",
                        f"👋 <b>You are signed in</b>\n\n"
                        f"💰 Available to withdraw: <b>${available:.2f}</b>\n"
                        f"✅ Paid out in total: ${total_paid:.2f}")
            buttons = None
            if active:
                msg += ref_t(ref2,
                             f"\n\n📋 Активная заявка #{active.id} на ${active.amount_usdt:.2f} — на обработке.",
                             f"\n\n📋 Request #{active.id} for ${active.amount_usdt:.2f} is being processed.")
                buttons = _cancel_button(active.id, ref2)
            send_referrer_dm(ref2, msg, buttons=buttons)
        finally:
            db2.close()
    except Exception as e:
        print(f'[ReferrerDM] login summary error: {e}')


@app.route('/api/ref/<token>/tg-start', methods=['POST'])
@limiter.limit("10/minute")
def referrer_tg_start(token):
    """Вход реферера через бота: nonce + deep-link (аккаунт выбирается в приложении)."""
    import secrets as _secrets
    db = get_session()
    try:
        referrer = db.query(Referrer).filter_by(token=token, active=True).first()
        if not referrer:
            return jsonify({'success': False, 'error': 'Реферер не найден'}), 404
        nonce = _secrets.token_urlsafe(24)
        cutoff = datetime.utcnow() - timedelta(seconds=LOGIN_NONCE_TTL_SEC * 2)
        db.query(LoginNonce).filter(LoginNonce.created_at < cutoff).delete()
        db.add(LoginNonce(nonce=nonce, referrer_id=referrer.id))
        db.commit()
    finally:
        db.close()
    bot = get_bot_username()
    if not bot:
        return jsonify({'success': False, 'error': 'Бот недоступен'}), 503
    return jsonify({'success': True, 'nonce': nonce,
                    'link': f'https://t.me/{bot}?start=login_{nonce}'})


@app.route('/api/ref/<token>/tg-poll', methods=['GET'])
@limiter.limit("60/minute")
def referrer_tg_poll(token):
    """Поллинг браузером: бот подтвердил вход реферера? Выдаёт ref_auth-сессию один раз."""
    nonce = (request.args.get('nonce') or '').strip()
    if not nonce:
        return jsonify({'success': False, 'error': 'nonce required'}), 400
    db = get_session()
    try:
        referrer = db.query(Referrer).filter_by(token=token, active=True).first()
        ln = db.query(LoginNonce).get(nonce)
        if not referrer or not ln or ln.used or ln.referrer_id != referrer.id:
            return jsonify({'success': False, 'status': 'invalid'}), 404
        if (datetime.utcnow() - (ln.created_at or datetime.utcnow())).total_seconds() > LOGIN_NONCE_TTL_SEC:
            return jsonify({'success': False, 'status': 'expired'})
        if ln.denied:
            return jsonify({'success': False, 'status': 'denied',
                            'error': 'Ваш Telegram не совпадает с указанным для этого кабинета'})
        if not ln.tg_id:
            return jsonify({'success': False, 'status': 'pending'})
        ln.used = True
        db.commit()
        rid, bound_tg = referrer.id, int(ln.tg_id)
    finally:
        db.close()
    flask_session.permanent = True
    auth = dict(flask_session.get('ref_auth') or {})
    auth[token] = bound_tg
    flask_session['ref_auth'] = auth
    _send_referrer_login_summary(rid)
    return jsonify({'success': True, 'status': 'ok'})


@app.route('/api/ref/<token>/logout', methods=['POST'])
def referrer_logout(token):
    """Выход из кабинета реферера: убирает привязку токена из сессии."""
    auth = dict(flask_session.get('ref_auth') or {})
    if token in auth:
        del auth[token]
        flask_session['ref_auth'] = auth
    return jsonify({'success': True})


@app.route('/api/ref/<token>/stats', methods=['GET'])
def referrer_stats(token):
    """Публичная статистика реферера"""
    db = get_session()
    try:
        referrer = db.query(Referrer).filter(Referrer.token == token, Referrer.active == True).first()
        if not referrer:
            return jsonify({'success': False, 'error': 'Реферер не найден'}), 404

        if not ref_session_authorized(referrer, token):
            return jsonify({'success': False, 'auth_required': True,
                            'bot_username': get_bot_username(),
                            'bot_id': get_login_bot_id(),
                            'lang': referrer.lang or 'ru',
                            'referrer_name': referrer.name}), 401

        # Мультиагенты: сделки, где этот реферал участвует (любой уровень), читаем из deal_agents.
        # Один реферал может иметь НЕСКОЛЬКО строк в одной сделке (напр. markup 0.5% с верха
        # + revshare 30% от остатка) — группируем списком, а не одной строкой на сделку.
        agent_rows = db.query(DealAgent).filter(DealAgent.referrer_id == referrer.id).all()
        rows_by_deal = {}
        for r in agent_rows:
            rows_by_deal.setdefault(r.deal_id, []).append(r)
        for rows in rows_by_deal.values():
            rows.sort(key=lambda x: (x.tier or 1, x.id or 0))
        deal_ids = list(rows_by_deal.keys())
        deals = db.query(Deal).filter(
            Deal.id.in_(deal_ids),
            Deal.status == DealStatus.COMPLETED
        ).order_by(Deal.created_at.desc()).limit(200).all() if deal_ids else []

        recent_deals = []
        for deal in deals:
            deal_rows = rows_by_deal.get(deal.id) or []
            ag = deal_rows[0] if deal_rows else None
            # Маскируем имя клиента для конфиденциальности
            client_name = ''
            if deal.client:
                client_name = deal.client.name or ''
            name_parts = client_name.split()
            masked = name_parts[0][:3] + '***' if name_parts and len(name_parts[0]) > 2 else client_name[:3] + '***'
            initials = ''.join(p[0].upper() for p in name_parts[:2] if p) or '??'
            # Сумма и валюта выдачи: custom-сделки могут быть в USDT, а не в THB.
            # Раньше custom_payout_amount всегда показывался как ฿ → USD-сделки рисовались батами.
            cpc = (deal.custom_payout_currency or '').lower()  # 'usd' | 'usdt' | 'thb' | 'rub'
            if deal.custom_payout_amount:
                payout_amount = deal.custom_payout_amount
                payout_cur = cpc or 'thb'
            elif deal.payout_amount_thb:
                payout_amount = deal.payout_amount_thb
                payout_cur = 'thb'
            elif deal.payout_amount_usdt:
                payout_amount = deal.payout_amount_usdt
                payout_cur = 'usdt'
            else:
                payout_amount = 0
                payout_cur = 'thb'
            recent_deals.append({
                'date': deal.created_at.strftime('%d.%m.%Y') if deal.created_at else None,
                # ISO — чтобы кабинет отформатировал дату по языку партнёра
                # ('date' оставлен как есть: на него смотрят старые кэши страниц)
                'date_iso': deal.created_at.isoformat() if deal.created_at else None,
                'volume_usdt': max(deal.payin_amount_usdt or 0, deal.payout_amount_usdt or 0),
                'payout_amount': payout_amount,
                'payout_currency': payout_cur,
                'payout_thb': payout_amount if payout_cur == 'thb' else 0,  # legacy
                # Выплата/модель/процент — из строк ЭТОГО агента (не из кэша сделки).
                # commission = СУММА всех его строк в сделке; components — разбивка
                # (markup+revshare), фронт рисует «0.5% × объём + 30% × прибыль».
                # profit_usdt = база агента (для ур.2+ это остаток — каскад агенту не виден).
                'commission_usdt': round(sum(r.payout_usdt or 0 for r in deal_rows), 2) if deal_rows else None,
                'paid': all(r.paid for r in deal_rows) if deal_rows else False,
                'paid_note': next((r.paid_note for r in deal_rows if r.paid_note), None),
                'client_masked': masked,
                'client_initials': initials,
                'comp_model': (ag.comp_model if ag else None) or 'revshare',
                'percent': ag.percent if ag else None,
                'profit_usdt': ag.base_usdt if ag else deal.profit_usdt,
                'components': [{
                    'comp_model': r.comp_model or 'revshare',
                    'percent': r.percent or 0,
                    'payout_usdt': r.payout_usdt or 0,
                    'base_usdt': r.base_usdt,
                } for r in deal_rows],
            })

        # Считаем из строк агента (его доля по каждой сделке), а не из кэша сделки
        completed_rows = [r for d in deals for r in (rows_by_deal.get(d.id) or [])]
        total_earned = sum(r.payout_usdt or 0 for r in completed_rows)
        total_paid = sum((r.payout_usdt or 0) for r in completed_rows if r.paid)
        referred_clients = db.query(Client).filter(Client.referrer_id == referrer.id).count()

        # Конверсия: клиенты с хотя бы 1 завершённой сделкой (где агент участвует) / все приведённые
        clients_with_deals = len({d.client_id for d in deals if d.client_id})
        conversion_rate = round(clients_with_deals / referred_clients * 100, 1) if referred_clients > 0 else 0

        # Средний доход на сделку
        avg_deal_income = round(total_earned / len(deals), 2) if deals else 0

        # Метрики за последние 30 дней — отдельный блок «За 30 дней» в кабинете
        cutoff_30d = datetime.utcnow() - timedelta(days=30)
        deals_30d = [d for d in deals if d.created_at and d.created_at >= cutoff_30d]
        volume_30d_usdt = round(
            sum(max(d.payin_amount_usdt or 0, d.payout_amount_usdt or 0) for d in deals_30d), 2
        )
        clients_30d = db.query(Client).filter(
            Client.referrer_id == referrer.id,
            Client.created_at >= cutoff_30d,
        ).count()

        # История заявок на выплату (все, с tx_hash для отображения)
        all_payout_requests = db.query(PayoutRequest).filter_by(referrer_id=referrer.id) \
                                                     .order_by(PayoutRequest.created_at.desc()).limit(50).all()
        payout_requests_list = [r.to_dict() for r in all_payout_requests]

        # Активная заявка (new / in_progress) — блокирует CTA
        active_request = next((r for r in payout_requests_list if r['status'] in ('new', 'in_progress')), None)
        active_amount = active_request['amount_usdt'] if active_request else 0
        available_for_withdraw = round(max(0, (total_earned - total_paid) - active_amount), 2)

        # Недавно выплаченная (за 7 дней) — баннер "деньги пришли"
        recent_paid = None
        cutoff = datetime.utcnow() - timedelta(days=7)
        for r in all_payout_requests:
            if r.status == 'paid' and r.processed_at and r.processed_at >= cutoff:
                recent_paid = r.to_dict()
                break

        # Сумма USDT, фактически отправленная реферреру за 30д (для блока «За 30 дней»)
        paid_to_referrer_30d_usdt = round(sum(
            r.amount_usdt or 0
            for r in all_payout_requests
            if r.status == 'paid' and r.processed_at and r.processed_at >= cutoff_30d
        ), 2)

        # Ранее использованные кошельки (для автоподсказки в модалке)
        prev_wallets = []
        seen = set()
        for r in all_payout_requests:
            if r.wallet and r.wallet not in seen:
                seen.add(r.wallet)
                prev_wallets.append(r.wallet)
            if len(prev_wallets) >= 5:
                break

        return jsonify({
            'success': True,
            'name': referrer.name,
            'code': referrer.code,
            'lang': referrer.lang or 'ru',
            **referral_links(referrer.code, referrer.lang or 'ru'),
            'payout_currency': referrer.payout_currency or 'USDT',
            'telegram': referrer.telegram or '',
            'auth_mode': referrer.auth_mode or 'link',
            'default_percent': referrer.default_percent,
            'comp_model': referrer.comp_model or 'revshare',
            'markup_percent': referrer.markup_percent or 0.0,
            'can_create_links': bool(referrer.can_create_links),
            'link_logo_url': referrer.link_logo_url,
            'link_description': referrer.link_description,
            'total_referred_clients': referred_clients,
            'clients_with_deals': clients_with_deals,
            'conversion_rate': conversion_rate,
            'total_deals': len(deals),
            'avg_deal_income': avg_deal_income,
            'total_earned_usdt': round(total_earned, 2),
            'total_paid_usdt': round(total_paid, 2),
            'pending_usdt': round(total_earned - total_paid, 2),
            'available_for_withdraw': available_for_withdraw,
            'volume_30d_usdt': volume_30d_usdt,
            'deals_30d': len(deals_30d),
            'clients_30d': clients_30d,
            'paid_to_referrer_30d_usdt': paid_to_referrer_30d_usdt,
            'active_request': active_request,
            'recent_paid_request': recent_paid,
            'payout_requests': payout_requests_list,
            'recent_deals': recent_deals,
            'previous_wallets': prev_wallets,
        })
    finally:
        db.close()


@app.route('/api/ref/<token>/payout-quote', methods=['GET'])
def ref_payout_quote(token):
    """Котировка вывода в батах на текущий баланс реферера (индикативная).

    Показывается в модалке выбора способа. Финальный курс фиксируется
    сервером в момент создания заявки, не этим ответом.
    """
    db = get_session()
    try:
        referrer = db.query(Referrer).filter_by(token=token, active=True).first()
        if not referrer:
            return jsonify({'success': False, 'error': 'Реферер не найден'}), 404
        if not ref_session_authorized(referrer, token):
            return jsonify({'success': False, 'auth_required': True,
                            'error': 'Требуется вход через Telegram'}), 401
        pending, _ = _referrer_balance(db, referrer)
        quote = thb_payout_quote(pending) if pending >= 20 else None
        return jsonify({'success': True, 'usdt': pending, 'quote': quote})
    finally:
        db.close()


def _link_partner_or_error(db, token):
    """(referrer, None) если партнёру можно делать ссылки, иначе (None, ответ с ошибкой).

    Флаг проверяется на сервере в каждом эндпоинте ссылок, а не только в UI.
    """
    referrer = db.query(Referrer).filter_by(token=token, active=True).first()
    if not referrer:
        return None, (jsonify({'success': False, 'error': 'Реферер не найден'}), 404)
    if not ref_session_authorized(referrer, token):
        return None, (jsonify({'success': False, 'auth_required': True,
                               'error': 'Требуется вход через Telegram'}), 401)
    if not referrer.can_create_links:
        return None, (jsonify({'success': False, 'error': 'Создание ссылок не подключено'}), 403)
    # Второй рубеж: даже с поднятым флагом в режиме link кабинет открывает любой,
    # у кого есть URL с токеном, — платежи от нашего имени так отдавать нельзя.
    # Флаг мог быть выставлен в обход PUT (миграция, ручной UPDATE), поэтому проверяем здесь.
    local_stand = os.environ.get('LOCAL_NO_AUTH') == '1' and 'postgresql' not in DATABASE_URL
    if (referrer.auth_mode or 'link') != 'telegram' and not local_stand:
        return None, (jsonify({'success': False,
                               'error': 'Нужен вход через Telegram'}), 403)
    return referrer, None


LINK_MIN_RUB, LINK_MAX_RUB = 1000, 1_000_000


@app.route('/api/ref/<token>/links/quote', methods=['POST'])
def ref_link_quote(token):
    """Котировка платёжной ссылки: партнёр вводит сумму в ₽ или ฿, курс считает сервер.

    Цифрам из браузера не верим — принимаем только сумму и валюту ввода.
    Наружу отдаём суммы, курс и вознаграждение партнёра; наша прибыль
    и курсы закупки остаются внутри.
    """
    data = request.get_json() or {}
    db = get_session()
    try:
        referrer, err = _link_partner_or_error(db, token)
        if err:
            return err

        currency = (data.get('currency') or 'THB').strip().upper()
        if currency not in ('RUB', 'THB'):
            return jsonify({'success': False, 'error': 'Валюта: RUB или THB'}), 400
        try:
            amount = float(data.get('amount') or 0)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'Некорректная сумма'}), 400
        if amount <= 0:
            return jsonify({'success': False, 'error': 'Сумма должна быть больше нуля'}), 400

        try:
            q = partner_rates.quote(
                thb_amount=amount if currency == 'THB' else None,
                rub_amount=amount if currency == 'RUB' else None,
                base_markup=referrer.link_base_markup_percent,
                partner_markup=referrer.link_markup_percent or 0.0,
                partner_revshare=referrer.link_revshare_percent or 0.0)
        except partner_rates.RateError as e:
            return jsonify({'success': False, 'error': str(e)}), 503

        if not (LINK_MIN_RUB <= q['amount_rub'] <= LINK_MAX_RUB):
            return jsonify({'success': False,
                            'error': f'Сумма вне лимитов: {LINK_MIN_RUB:,} – {LINK_MAX_RUB:,} ₽'
                                     .replace(',', ' ')}), 400

        return jsonify({'success': True, 'quote': {
            'amount_rub': q['amount_rub'],
            'amount_thb': q['amount_thb'],
            'rate': q['rate'],
            'reward_usdt': q['partner_usdt'],
            'reward_thb': q['partner_thb'],
            'expires_in': 900,
        }})
    finally:
        db.close()


@app.route('/api/ref/<token>/payout-request', methods=['POST'])
def create_payout_request(token):
    """Реферер создаёт заявку на выплату. Публичный эндпоинт по токену."""
    data = request.get_json(silent=True) or {}
    payout_method = (data.get('payout_method') or 'usdt').strip().lower()
    wallet = (data.get('wallet') or '').strip()
    bank_name = (data.get('bank_name') or '').strip()
    account_name = (data.get('account_name') or '').strip()
    account_number = (data.get('account_number') or '').strip()
    contact_method = (data.get('contact_method') or '').strip().lower()
    contact_value = (data.get('contact_value') or '').strip()
    notes = (data.get('notes') or '').strip() or None

    if payout_method not in ('usdt', 'thb'):
        return jsonify({'success': False, 'error': 'Неизвестный способ вывода'}), 400
    if payout_method == 'usdt':
        if not wallet:
            return jsonify({'success': False, 'error': 'Укажите кошелёк для выплаты'}), 400
    else:
        if not bank_name or not account_name or not account_number:
            return jsonify({'success': False, 'error': 'Укажите банк, имя получателя и номер счёта'}), 400
        if len(bank_name) > 100 or len(account_name) > 150 or len(account_number) > 60:
            return jsonify({'success': False, 'error': 'Слишком длинные реквизиты'}), 400
        wallet = ''  # для батовой заявки кошелёк не используется
    if contact_method not in ('telegram', 'whatsapp'):
        return jsonify({'success': False, 'error': 'Выберите Telegram или WhatsApp'}), 400
    if not contact_value:
        return jsonify({'success': False, 'error': 'Укажите контакт для связи'}), 400
    if len(wallet) > 200 or len(contact_value) > 100 or (notes and len(notes) > 1000):
        return jsonify({'success': False, 'error': 'Слишком длинные поля'}), 400

    db = get_session()
    try:
        referrer = db.query(Referrer).filter_by(token=token, active=True).first()
        if not referrer:
            return jsonify({'success': False, 'error': 'Реферер не найден'}), 404
        if not ref_session_authorized(referrer, token):
            return jsonify({'success': False, 'auth_required': True,
                            'error': 'Требуется вход через Telegram'}), 401

        # Считаем pending из строк агента (мультиагентная модель), ТОЧНО как в /stats.
        # Раньше тут было Deal.referrer_payout_usdt (легаси-кэш на сделке) — у рефереров
        # с мультиагентными сделками оно = 0/None, поэтому кабинет показывал доступный
        # баланс, а оформление вывода отвечало «Доступно: $0.00» и резало запрос.
        # Несколько строк одного реферала в сделке (markup+revshare) — суммируем ВСЕ
        agent_rows = db.query(DealAgent).filter(DealAgent.referrer_id == referrer.id).all()
        if agent_rows:
            completed_ids = {
                row.id for row in db.query(Deal.id).filter(
                    Deal.id.in_(list({r.deal_id for r in agent_rows})),
                    Deal.status == DealStatus.COMPLETED,
                ).all()
            }
            rows = [r for r in agent_rows if r.deal_id in completed_ids]
            total_earned = sum(r.payout_usdt or 0 for r in rows)
            total_paid = sum((r.payout_usdt or 0) for r in rows if r.paid)
        else:
            total_earned = total_paid = 0
        pending = round(total_earned - total_paid, 2)

        if pending < 20:
            return jsonify({
                'success': False,
                'error': f'Минимальная сумма для вывода — $20. Доступно: ${pending:.2f}'
            }), 400

        # Анти-спам: запрет если есть активная заявка (new или in_progress)
        existing = db.query(PayoutRequest).filter(
            PayoutRequest.referrer_id == referrer.id,
            PayoutRequest.status.in_(['new', 'in_progress'])
        ).first()
        if existing:
            return jsonify({
                'success': False,
                'error': 'У вас уже есть активная заявка. Дождитесь обработки.'
            }), 409

        # Снапшот сделок заявки: paid пометит оплаченными ТОЛЬКО их —
        # сделки, закрытые после создания заявки, не сгорают
        unpaid_deal_ids = sorted({r.deal_id for r in rows if not r.paid and (r.payout_usdt or 0)}) if agent_rows else []

        # Батовая выплата: курс фиксируем СЕЙЧАС, сервером (не доверяем фронту) —
        # задача команды успеть откупить по зафиксированному
        quote = None
        if payout_method == 'thb':
            quote = thb_payout_quote(pending)
            if not quote:
                return jsonify({
                    'success': False,
                    'error': 'Курс временно недоступен — попробуйте позже или выведите в USDT'
                }), 503

        req = PayoutRequest(
            referrer_id=referrer.id,
            amount_usdt=pending,
            wallet=wallet,
            contact_method=contact_method,
            contact_value=contact_value,
            notes=notes,
            status='new',
            deal_ids=json.dumps(unpaid_deal_ids),
            payout_method=payout_method,
            bitazza_rate=quote['bitazza_rate'] if quote else None,
            client_rate=quote['client_rate'] if quote else None,
            thb_amount=quote['thb_amount'] if quote else None,
            bank_name=bank_name or None,
            account_name=account_name or None,
            account_number=account_number or None,
        )
        db.add(req)
        db.commit()
        db.refresh(req)

        # Уведомление в TG-чат (пропускаем для тестовых рефереров)
        if referrer.is_test:
            print(f'[PayoutRequest] Skip TG notify: referrer #{referrer.id} is test')
        else:
            try:
                contact_label = 'Telegram' if contact_method == 'telegram' else 'WhatsApp'
                if payout_method == 'thb':
                    thb_fmt = f"{quote['thb_amount']:,.0f}".replace(',', ' ')
                    msg = (
                        f"💸 <b>Новая заявка на выплату — БАТЫ</b>\n\n"
                        f"<b>Реферер:</b> {referrer.name} ({referrer.code})\n"
                        f"━━━━━━━━━━━━━━\n"
                        f"<b>Возместить:</b> ${pending:.2f} USDT\n"
                        f"<b>Откуп по:</b> {quote['bitazza_rate']} ฿/$ (Bitazza VWAP)\n"
                        f"<b>Клиенту:</b> {thb_fmt} ฿ · курс {quote['client_rate']}\n"
                        f"━━━━━━━━━━━━━━\n"
                        f"<b>Банк:</b> {bank_name}\n"
                        f"<b>Имя:</b> {account_name}\n"
                        f"<b>Счёт:</b> <code>{account_number}</code>\n\n"
                        f"<b>Связь:</b> {contact_label} — {contact_value}"
                    )
                else:
                    msg = (
                        f"💸 <b>Новая заявка на выплату</b>\n\n"
                        f"<b>Реферер:</b> {referrer.name} ({referrer.code})\n"
                        f"<b>Сумма:</b> ${pending:.2f} USDT\n"
                        f"<b>Валюта:</b> USDT (TRC-20)\n\n"
                        f"<b>Кошелёк:</b>\n<code>{wallet}</code>\n\n"
                        f"<b>Связь:</b> {contact_label} — {contact_value}"
                    )
                if notes:
                    msg += f"\n\n<b>Комментарий:</b> {notes}"
                crm_url = 'https://grusha.up.railway.app/crm'
                msg += (
                    f"\n\nЗаявка #{req.id} · "
                    f"<a href=\"{crm_url}\">CRM → Заявки на выплату</a>"
                )
                # Заявки на выплату — в топик «Задачи» (а не «Сделки»)
                tasks_thread = os.environ.get('TELEGRAM_TASKS_THREAD_ID', '2112')
                send_telegram_notification(msg, thread_id=tasks_thread)
            except Exception as e:
                print(f'[PayoutRequest] Telegram notify failed: {e}')

        # DM рефереру: подтверждение + кнопка отмены
        try:
            if payout_method == 'thb':
                thb_fmt = f"{quote['thb_amount']:,.0f}".replace(',', ' ')
                msg = ref_t(referrer,
                            f"💸 <b>Заявка на выплату создана</b>\n\n"
                            f"Сумма: <b>{thb_fmt} ฿</b> (курс {round(quote['client_rate'], 2)})\n"
                            f"Банк: {bank_name} · <code>{account_number}</code>\n\n"
                            f"Заявка #{req.id} принята в обработку.",
                            f"💸 <b>Withdrawal request created</b>\n\n"
                            f"Amount: <b>{thb_fmt} ฿</b> (rate {round(quote['client_rate'], 2)})\n"
                            f"Bank: {bank_name} · <code>{account_number}</code>\n\n"
                            f"Request #{req.id} is now being processed.")
            else:
                msg = ref_t(referrer,
                            f"💸 <b>Заявка на выплату создана</b>\n\n"
                            f"Сумма: <b>${pending:.2f}</b>\n"
                            f"Кошелёк: <code>{wallet}</code>\n\n"
                            f"Заявка #{req.id} принята в обработку.",
                            f"💸 <b>Withdrawal request created</b>\n\n"
                            f"Amount: <b>${pending:.2f}</b>\n"
                            f"Wallet: <code>{wallet}</code>\n\n"
                            f"Request #{req.id} is now being processed.")
            send_referrer_dm(referrer, msg, buttons=_cancel_button(req.id, referrer))
        except Exception as e:
            print(f'[ReferrerDM] create notify error: {e}')

        return jsonify({'success': True, 'request': req.to_dict()})
    finally:
        db.close()


@app.route('/api/payout-requests', methods=['GET'])
def list_payout_requests():
    """Список заявок на выплату для CRM."""
    db = get_session()
    try:
        status_filter = (request.args.get('status') or '').strip()
        q = db.query(PayoutRequest).order_by(PayoutRequest.created_at.desc())
        if status_filter:
            q = q.filter(PayoutRequest.status == status_filter)
        if request.args.get('include_test') != '1':
            # Заявки демо-рефереров (витрина) команде в списке не нужны
            test_ids = [r.id for r in db.query(Referrer.id).filter(Referrer.is_test == True).all()]
            if test_ids:
                q = q.filter(~PayoutRequest.referrer_id.in_(test_ids))
        items = [r.to_dict(with_referrer=True) for r in q.limit(200).all()]
        return jsonify({'success': True, 'requests': items})
    finally:
        db.close()


@app.route('/api/payout-requests', methods=['POST'])
def create_payout_request_manual():
    """Вручную внести запись о выплате (старую/внешнюю) — только CRM (авторизация).

    НЕ трогает сделки и баланс — это запись в историю выплат реферера.
    Поддерживает явную дату paid_date (ISO).
    """
    data = request.get_json(silent=True) or {}
    referrer_id = data.get('referrer_id')
    try:
        amount = round(float(data.get('amount_usdt') or 0), 2)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'Некорректная сумма'}), 400
    wallet = (data.get('wallet') or '').strip()
    tx_hash = (data.get('tx_hash') or '').strip() or None
    status = (data.get('status') or 'paid').strip().lower()
    contact_method = (data.get('contact_method') or 'telegram').strip().lower()
    contact_value = (data.get('contact_value') or '—').strip() or '—'
    notes = (data.get('notes') or '').strip() or None

    if not referrer_id or amount <= 0 or not wallet:
        return jsonify({'success': False, 'error': 'Нужны referrer_id, amount_usdt и wallet'}), 400
    if status not in ('new', 'in_progress', 'paid', 'cancelled'):
        return jsonify({'success': False, 'error': 'Недопустимый статус'}), 400
    if contact_method not in ('telegram', 'whatsapp'):
        contact_method = 'telegram'

    db = get_session()
    try:
        referrer = db.query(Referrer).get(referrer_id)
        if not referrer:
            return jsonify({'success': False, 'error': 'Реферер не найден'}), 404

        dt = None
        raw_date = (data.get('paid_date') or '').strip()
        if raw_date:
            try:
                dt = datetime.fromisoformat(raw_date.replace('Z', '+00:00')).replace(tzinfo=None)
            except ValueError:
                return jsonify({'success': False, 'error': 'Некорректная дата (нужен ISO)'}), 400

        req = PayoutRequest(
            referrer_id=referrer_id, amount_usdt=amount, wallet=wallet,
            contact_method=contact_method, contact_value=contact_value,
            notes=notes, status=status, tx_hash=tx_hash,
        )
        if dt:
            req.created_at = dt
        if status in ('paid', 'cancelled'):
            req.processed_at = dt or datetime.utcnow()
        db.add(req)
        db.commit()
        db.refresh(req)
        return jsonify({'success': True, 'request': req.to_dict(with_referrer=True)})
    finally:
        db.close()


@app.route('/api/referrers/<int:referrer_id>/payout-requests', methods=['GET'])
def referrer_payout_requests(referrer_id):
    """История заявок конкретного реферера (для карточки в CRM)."""
    db = get_session()
    try:
        q = db.query(PayoutRequest).filter_by(referrer_id=referrer_id) \
              .order_by(PayoutRequest.created_at.desc()).limit(50).all()
        return jsonify({'success': True, 'requests': [r.to_dict() for r in q]})
    finally:
        db.close()


def _apply_payout_paid(db, req, now):
    """paid → помечаем сделки реферера выплаченными, иначе «Доступно к выводу»
    не уменьшится и партнёр сможет запросить ту же сумму повторно.
    Только сделки из снапшота заявки (deal_ids) — закрытые после заявки не сгорают.
    Легаси-заявки без снапшота — старое поведение (все неоплаченные)."""
    referrer = db.query(Referrer).get(req.referrer_id)
    if not referrer:
        return []
    snap_ids = None
    if req.deal_ids:
        try:
            snap_ids = json.loads(req.deal_ids) or None
        except (ValueError, TypeError):
            snap_ids = None
    paid_deal_ids, _ = _mark_referrer_deals_paid(db, referrer, now, deal_ids=snap_ids)
    return paid_deal_ids


@app.route('/api/payout-requests/<int:req_id>', methods=['PATCH'])
def update_payout_request(req_id):
    """Изменить статус заявки (in_progress / paid / cancelled).

    paid: USDT-заявка — обязателен tx_hash; батовая — закрывается только
    через POST /receipt (чек), напрямую в paid не переводится.
    """
    data = request.get_json(silent=True) or {}
    new_status = (data.get('status') or '').strip().lower()
    tx_hash = (data.get('tx_hash') or '').strip() or None
    if new_status not in ('new', 'in_progress', 'paid', 'cancelled'):
        return jsonify({'success': False, 'error': 'Недопустимый статус'}), 400

    db = get_session()
    try:
        req = db.query(PayoutRequest).get(req_id)
        if not req:
            return jsonify({'success': False, 'error': 'Заявка не найдена'}), 404
        if new_status == 'paid':
            if (req.payout_method or 'usdt') == 'thb':
                return jsonify({'success': False,
                                'error': 'Батовая заявка закрывается загрузкой чека'}), 400
            if not tx_hash:
                return jsonify({'success': False, 'error': 'Для статуса paid обязателен tx_hash'}), 400
        req.status = new_status
        if tx_hash:
            req.tx_hash = tx_hash
        now = datetime.utcnow()
        paid_deal_ids = []
        if new_status in ('paid', 'cancelled'):
            req.processed_at = now
        if new_status == 'paid':
            paid_deal_ids = _apply_payout_paid(db, req, now)
        db.commit()
        db.refresh(req)
        if paid_deal_ids:
            try:
                mark_referrer_rewards_paid_in_gsheet(paid_deal_ids, now)
            except Exception as e:
                print(f'[GSheet] mark paid error: {e}')
        # DM рефереру: выплата отправлена
        if new_status == 'paid':
            try:
                referrer2 = db.query(Referrer).get(req.referrer_id)
                if referrer2:
                    tx = f"\nTx: <code>{req.tx_hash}</code>" if req.tx_hash else ""
                    send_referrer_dm(referrer2, ref_t(referrer2,
                        f"✅ <b>Выплата отправлена</b>\n\nСумма: <b>${req.amount_usdt:.2f}</b>{tx}",
                        f"✅ <b>Payout sent</b>\n\nAmount: <b>${req.amount_usdt:.2f}</b>{tx}"))
            except Exception as e:
                print(f'[ReferrerDM] paid notify error: {e}')
        return jsonify({'success': True, 'request': req.to_dict(with_referrer=True)})
    finally:
        db.close()


@app.route('/api/payout-requests/<int:req_id>/receipt', methods=['POST'])
def payout_request_receipt(req_id):
    """Выплата батовой заявки: чек (фото/PDF) → рефереру в DM + в рабочий топик,
    статус paid. Файл не сохраняем на диск (Railway ephemeral) — живёт в Telegram."""
    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'success': False, 'error': 'Приложи файл чека'}), 400
    blob = f.read()
    if not blob or len(blob) > 15 * 1024 * 1024:
        return jsonify({'success': False, 'error': 'Файл пустой или больше 15 МБ'}), 400

    db = get_session()
    try:
        req = db.query(PayoutRequest).get(req_id)
        if not req:
            return jsonify({'success': False, 'error': 'Заявка не найдена'}), 404
        if (req.payout_method or 'usdt') != 'thb':
            return jsonify({'success': False, 'error': 'Чек — только для батовых заявок'}), 400
        if req.status in ('paid', 'cancelled'):
            return jsonify({'success': False, 'error': 'Заявка уже закрыта'}), 400

        referrer = db.query(Referrer).get(req.referrer_id)
        thb_fmt = f"{(req.thb_amount or 0):,.0f}".replace(',', ' ')

        # 1) Чек рефереру в DM (если привязан TG)
        dm_file_id = None
        if referrer and referrer.telegram_user_id and get_login_bot_token():
            dm_file_id = _tg_send_document(
                get_login_bot_token(), int(referrer.telegram_user_id), blob, f.filename,
                ref_t(referrer,
                      f"✅ <b>Выплата отправлена</b>\n\nСумма: <b>{thb_fmt} ฿</b>",
                      f"✅ <b>Payout sent</b>\n\nAmount: <b>{thb_fmt} ฿</b>"))

        # 2) Чек в рабочий топик «Задачи»
        team_file_id = None
        if not (referrer and referrer.is_test):
            ref_label = f"{referrer.name} ({referrer.code})" if referrer else f"#{req.referrer_id}"
            team_file_id = _tg_send_document(
                os.environ.get('TELEGRAM_BOT_TOKEN', '').strip(),
                os.environ.get('TELEGRAM_CHAT_ID', '-1002274229486').strip(),
                blob, f.filename,
                f"📄 Чек по заявке #{req.id} — {ref_label} · {thb_fmt} ฿",
                thread_id=os.environ.get('TELEGRAM_TASKS_THREAD_ID', '2112'))
            if not dm_file_id and not team_file_id:
                return jsonify({'success': False,
                                'error': 'Не удалось отправить чек в Telegram — заявка не закрыта'}), 502

        now = datetime.utcnow()
        req.receipt_tg_file_id = team_file_id or dm_file_id or 'sent'
        req.status = 'paid'
        req.processed_at = now
        paid_deal_ids = _apply_payout_paid(db, req, now)
        db.commit()
        db.refresh(req)
        if paid_deal_ids:
            try:
                mark_referrer_rewards_paid_in_gsheet(paid_deal_ids, now)
            except Exception as e:
                print(f'[GSheet] mark paid error: {e}')
        return jsonify({'success': True, 'request': req.to_dict(with_referrer=True)})
    finally:
        db.close()


@app.route('/api/payout-requests/<int:req_id>', methods=['DELETE'])
def delete_payout_request(req_id):
    """Жёсткое удаление заявки (для очистки тестовых данных)."""
    db = get_session()
    try:
        req = db.query(PayoutRequest).get(req_id)
        if not req:
            return jsonify({'success': False, 'error': 'Заявка не найдена'}), 404
        db.delete(req)
        db.commit()
        return jsonify({'success': True})
    finally:
        db.close()


@app.route('/api/ref/<token>/payout-request/<int:req_id>/cancel', methods=['POST'])
def cancel_payout_request_public(token, req_id):
    """Реферер сам отменяет свою активную заявку. Публичный эндпоинт по токену."""
    db = get_session()
    try:
        referrer = db.query(Referrer).filter_by(token=token, active=True).first()
        if not referrer:
            return jsonify({'success': False, 'error': 'Реферер не найден'}), 404
        if not ref_session_authorized(referrer, token):
            return jsonify({'success': False, 'auth_required': True,
                            'error': 'Требуется вход через Telegram'}), 401
        req = db.query(PayoutRequest).filter_by(id=req_id, referrer_id=referrer.id).first()
        if not req:
            return jsonify({'success': False, 'error': 'Заявка не найдена'}), 404
        if req.status not in ('new', 'in_progress'):
            return jsonify({'success': False, 'error': 'Заявку уже нельзя отменить'}), 400
        # in_progress отменять нельзя — менеджер уже в работе
        if req.status == 'in_progress':
            return jsonify({'success': False, 'error': 'Заявка уже в работе, обратитесь к менеджеру'}), 400
        req.status = 'cancelled'
        req.processed_at = datetime.utcnow()
        db.commit()
        return jsonify({'success': True})
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
            # Доля ИМЕННО этого реферала по каждой сделке — из deal_agents (как в ЛК и при выплате),
            # а НЕ deal.referrer_payout_usdt: та содержит сумму выплат ВСЕХ агентов сделки,
            # из-за чего основному рефералу приписывались доли остальных (4511 vs реальные 1514).
            # Реферал может иметь несколько строк в одной сделке (markup+revshare) — суммируем все
            agent_rows = db.query(DealAgent).filter(DealAgent.referrer_id == r.id).all()
            completed_ids = {
                did for (did,) in db.query(Deal.id).filter(
                    Deal.id.in_(list({ar.deal_id for ar in agent_rows})),
                    Deal.status == DealStatus.COMPLETED,
                ).all()
            } if agent_rows else set()
            rows = [ar for ar in agent_rows if ar.deal_id in completed_ids]
            d['total_deals'] = len(completed_ids)
            d['total_earned_usdt'] = round(sum(ar.payout_usdt or 0 for ar in rows), 2)
            d['total_paid_usdt'] = round(sum((ar.payout_usdt or 0) for ar in rows if ar.paid), 2)
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
    comp_model = (data.get('comp_model') or 'revshare').strip().lower()
    if comp_model not in ('revshare', 'markup'):
        comp_model = 'revshare'
    markup_percent = float(data.get('markup_percent') or 0)
    lang = (data.get('lang') or 'ru').strip().lower()
    if lang not in ('ru', 'en'):
        lang = 'ru'

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
            comp_model=comp_model,
            markup_percent=markup_percent,
            lang=lang,
            client_id=data.get('client_id'),
            is_test=bool(data.get('is_test', False)),
            auth_mode=('telegram' if (data.get('auth_mode') == 'telegram') else 'link'),
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
        if 'code' in data:
            new_code = data['code'].strip().upper()
            if new_code and new_code != referrer.code:
                existing = db.query(Referrer).filter(Referrer.code == new_code, Referrer.id != referrer.id).first()
                if existing:
                    return jsonify({'success': False, 'error': f'Код {new_code} уже занят'}), 400
                referrer.code = new_code
        if 'default_percent' in data:
            referrer.default_percent = parse_float(data.get('default_percent'))
        if 'comp_model' in data:
            cm = (data['comp_model'] or 'revshare').strip().lower()
            if cm in ('revshare', 'markup'):
                referrer.comp_model = cm
        if 'markup_percent' in data:
            referrer.markup_percent = float(data['markup_percent'] or 0)
        if 'lang' in data:
            lg = (data['lang'] or 'ru').strip().lower()
            if lg in ('ru', 'en'):
                referrer.lang = lg
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
            referrer.total_paid_usdt = parse_float(data.get('total_paid_usdt'))
        if 'auth_mode' in data:
            referrer.auth_mode = 'telegram' if data['auth_mode'] == 'telegram' else 'link'
        # Настройки платёжных ссылок
        if 'can_create_links' in data:
            want = bool(data['can_create_links'])
            # В режиме link кабинет пускает любого, у кого есть URL с токеном, а тут
            # создаются платежи от нашего имени. Пока нет своего логина — только TG.
            if want and (referrer.auth_mode or 'link') != 'telegram':
                return jsonify({'success': False,
                                'error': 'Ссылки можно включить только при входе через Telegram'}), 400
            referrer.can_create_links = want
        if 'link_base_markup_percent' in data:
            raw = data['link_base_markup_percent']
            referrer.link_base_markup_percent = None if raw in (None, '') else float(raw)
        if 'link_markup_percent' in data:
            referrer.link_markup_percent = float(data['link_markup_percent'] or 0)
        if 'link_revshare_percent' in data:
            referrer.link_revshare_percent = float(data['link_revshare_percent'] or 0)
        if 'link_logo_url' in data:
            referrer.link_logo_url = (data['link_logo_url'] or '').strip() or None
        if 'link_description' in data:
            referrer.link_description = (data['link_description'] or '').strip()[:200] or None

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
    code = request.args.get('code', '').strip().upper()
    if not code:
        return jsonify({'success': False, 'error': 'Укажите код'}), 400

    db = get_session()
    try:
        # Точный + нормализованный поиск (без дефисов/подчёркиваний) — для start-параметра TG
        referrer = _find_referrer_by_code(db, code)
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
            # Нормализованный поиск (GRED → GR-ED)
            referrer = _find_referrer_by_code(db, code)
        elif referrer_id:
            referrer = db.query(Referrer).get(referrer_id)
        else:
            return jsonify({'success': False, 'error': 'Укажите code или referrer_id'}), 400

        if not referrer:
            return jsonify({'success': False, 'error': 'Реферер не найден'}), 404

        # Защита от самореферала
        if referrer.client_id and referrer.client_id == client_id:
            return jsonify({'success': False, 'error': 'Нельзя быть реферером самому себе'}), 400

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


def _mark_referrer_deals_paid(db, referrer, now, deal_ids=None, note=None):
    """Помечает завершённые неоплаченные сделки реферера выплаченными.

    deal_ids — выборочная выплата (None = все неоплаченные, как раньше).
    note — чем выплачено (хэш транзакции / «Оплачено по SCB» и т.п.), пишется
    в DealAgent.paid_note и виден рефералу в кабинете вместо хэша.
    НЕ коммитит — это делает вызывающий. Идемпотентна: уже оплаченные сделки
    не трогает. Возвращает (paid_deal_ids, total_paid).
    """
    # Мультиагенты: платим по строкам агента (любой уровень), а не по кэшу сделки
    q = db.query(DealAgent).join(Deal, DealAgent.deal_id == Deal.id).filter(
        DealAgent.referrer_id == referrer.id,
        DealAgent.paid == False,
        Deal.status == DealStatus.COMPLETED,
    )
    if deal_ids:
        q = q.filter(DealAgent.deal_id.in_([int(d) for d in deal_ids]))
    rows = q.all()
    total_paid = 0
    paid_deal_ids = []
    for r in rows:
        if not r.payout_usdt:
            continue
        r.paid = True
        r.paid_at = now
        if note:
            r.paid_note = str(note)[:255]
        total_paid += r.payout_usdt or 0
        if r.deal_id not in paid_deal_ids:  # у реферала может быть 2 строки в сделке (markup+revshare)
            paid_deal_ids.append(r.deal_id)
        # синхрон legacy-флага на сделке, если реферал — основной (ур.1)
        deal = db.query(Deal).get(r.deal_id)
        if deal and deal.referrer_id == referrer.id:
            deal.referrer_paid = True
            deal.referrer_paid_at = now
    referrer.total_paid_usdt = round((referrer.total_paid_usdt or 0) + total_paid, 2)
    return paid_deal_ids, round(total_paid, 2)


@app.route('/api/referrers/<int:referrer_id>/unpaid', methods=['GET'])
def referrer_unpaid_deals(referrer_id):
    """Неоплаченные строки реферера по завершённым сделкам — для модалки выборочной выплаты."""
    db = get_session()
    try:
        rows = db.query(DealAgent, Deal).join(Deal, DealAgent.deal_id == Deal.id).filter(
            DealAgent.referrer_id == referrer_id,
            DealAgent.paid == False,
            Deal.status == DealStatus.COMPLETED,
        ).order_by(Deal.created_at.asc()).all()
        # Группируем по сделке (у реферала может быть 2 строки: markup+revshare)
        by_deal = {}
        for ag, deal in rows:
            e = by_deal.setdefault(deal.id, {
                'deal_id': deal.id,
                'date': deal.created_at.strftime('%d.%m.%Y') if deal.created_at else '',
                'client_name': deal.client_name or (deal.client.name if deal.client else ''),
                'payout_usdt': 0.0,
            })
            e['payout_usdt'] = round(e['payout_usdt'] + (ag.payout_usdt or 0), 2)
        return jsonify({'success': True, 'deals': list(by_deal.values())})
    finally:
        db.close()


@app.route('/api/referrers/<int:referrer_id>/pay', methods=['POST'])
def pay_referrer(referrer_id):
    """Отметить выплату рефереру. Body (опционально): {deal_ids: [...], note: '...'} —
    выборочная выплата по сделкам + комментарий (хэш / «Оплачено по SCB»)."""
    db = get_session()
    try:
        referrer = db.query(Referrer).get(referrer_id)
        if not referrer:
            return jsonify({'success': False, 'error': 'Реферер не найден'}), 404

        body = request.get_json(silent=True) or {}
        deal_ids = body.get('deal_ids') or None
        note = (body.get('note') or '').strip() or None

        now = datetime.utcnow()
        paid_deal_ids, total_paid = _mark_referrer_deals_paid(db, referrer, now, deal_ids=deal_ids, note=note)
        db.commit()

        # Обновляем колонку "Выплачено" в листе «рефереры»
        if paid_deal_ids:
            try:
                mark_referrer_rewards_paid_in_gsheet(paid_deal_ids, now)
            except Exception as e:
                print(f'[GSheet] mark paid error: {e}')

        return jsonify({
            'success': True,
            'deals_paid': len(paid_deal_ids),
            'amount_usdt': total_paid,
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

        # Определяем направление парсинга — через приоритетную очередь (priority=0 → партнёр вперёд)
        if usdt_amount:
            playwright_result = playwright_queue.submit(
                lambda: ExchangeRateProvider.get_precise_binance_rate(
                    usdt_amount=round(float(usdt_amount), 2),
                    direction='usdt_to_thb'
                ),
                priority=0,
                timeout=60
            )
            # Если упал (не таймаут очереди) — ретрай с безопасной суммой
            if 'error' in playwright_result and playwright_result.get('error') != 'queue_timeout':
                print(f"⚠️ Playwright failed for {usdt_amount} USDT, retrying with {SAFE_USDT}", flush=True)
                playwright_result = playwright_queue.submit(
                    lambda: ExchangeRateProvider.get_precise_binance_rate(
                        usdt_amount=SAFE_USDT,
                        direction='usdt_to_thb'
                    ),
                    priority=0,
                    timeout=60
                )
        else:
            playwright_result = playwright_queue.submit(
                lambda: ExchangeRateProvider.get_precise_binance_rate(
                    thb_amount=round(float(thb_amount)),
                    direction='usdt_to_thb_reverse'
                ),
                priority=0,
                timeout=60
            )
            if 'error' in playwright_result and playwright_result.get('error') != 'queue_timeout':
                print(f"⚠️ Playwright failed for {thb_amount} THB, retrying with {SAFE_THB}", flush=True)
                playwright_result = playwright_queue.submit(
                    lambda: ExchangeRateProvider.get_precise_binance_rate(
                        thb_amount=SAFE_THB,
                        direction='usdt_to_thb_reverse'
                    ),
                    priority=0,
                    timeout=60
                )

        if playwright_result.get('error') == 'queue_timeout':
            return jsonify({'success': False, 'error': 'queue_timeout'}), 503

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
            partner.markup_percent = parse_float(data.get('markup_percent'))
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
    # debug только по явному флагу env: иначе Werkzeug-дебаггер на 0.0.0.0
    # отдаёт трейсбеки и позволяет исполнять код (RCE) при прямом запуске.
    debug_mode = os.environ.get('FLASK_DEBUG', '').lower() == 'true'
    app.run(debug=debug_mode, host='0.0.0.0', port=port)
