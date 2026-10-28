"""Локальный стенд для скриншотов: STAND_MODE=1, временная SQLite, пользователи по ролям.
Запуск: shots_server.py <port> <workdir>. Печатает JSON с cookie ролей. Сеть наружу не используется."""
import json, os, sys, tempfile
work = sys.argv[2]
os.makedirs(work, exist_ok=True)
os.environ.update(SECRET_KEY='shots-secret', DATABASE_URL=f'sqlite:///{work}/shots.db', STAND_MODE='1',
                  LOCAL_NO_AUTH='0', REESTR_SYNC_ENABLED='0', PAYMENT_POLL_ENABLED='0', PAYIN_ADDR_BACKFILL='0',
                  KYC_RETENTION_ENABLED='0', TRONSCAN_WARM_ENABLED='0', METRIKA_TOKEN='',
                  STAND_SBER_MIRROR_ENABLED='0', STAND_TG_UPDATES_ENABLED='0', STAND_TRANSFER_POLL_ENABLED='0',
                  STAND_TG_ENABLED='0')
sys.path.insert(0, sys.argv[3])
import app as m
import stand_egress
stand_egress.read_get = lambda *a, **k: (None, None, 'shots: сеть закрыта')
m._stand_deliver_notes = lambda: []
m._stand_migrate()
m._stand_seed_wallets()
db = m.get_session()
users = {}
for role, name in (('operator', 'Настя'), ('findir', 'Виталий'), ('teodor', 'Теодор'),
                   ('manager', 'Елизавета'), ('admin', 'Админ')):
    u = db.query(m.AdminUser).filter_by(username=f'shots-{role}').first()
    if not u:
        u = m.AdminUser(username=f'shots-{role}', role=role, password_hash='unused', display_name=name)
        db.add(u); db.commit()
    users[role] = u.id
db.close()
ser = m.app.session_interface.get_signing_serializer(m.app)
cookies = {r: ser.dumps({'user_id': i}) for r, i in users.items()}

from flask import request, jsonify
@m.app.route('/__shots/board', methods=['POST'])
def shots_board():
    data = request.get_json()
    s = m.get_session()
    try:
        row = m._stand_row(s)
        row.data = json.dumps(data['state'], ensure_ascii=False)
        row.version = (row.version or 0) + 1
        s.commit()
        return jsonify(ok=True, version=row.version)
    finally:
        s.close()

@m.app.route('/__shots/info')
def shots_info():
    s = m.get_session()
    try:
        ids = {w.address: w.id for w in s.query(m.Wallet).all()}
        return jsonify(users=users, wallets=ids)
    finally:
        s.close()

from werkzeug.serving import make_server
server = make_server('127.0.0.1', int(sys.argv[1]), m.app, threaded=True)
print('READY ' + json.dumps({'cookies': cookies, 'users': users}), flush=True)
server.serve_forever()
