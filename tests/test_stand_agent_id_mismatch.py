"""QA перепроверка T7, FAIL №8 (server_delta.py): задачник стенда шлёт referrer_id
из своего справочника вместе с именем агента, снятым со сделки. Если сделка старая
и id теперь принадлежит другому человеку в таблице referrers (referrer_id/name не
совпадают), сервер раньше молча привязывал выплату по чужому id. На стенде это
должно откатываться на сопоставление по имени (старый безопасный путь); прод шлёт
referrer_id только из настоящей CRM, где имя и id всегда согласованы, — там
поведение не меняется."""

import app as appmod


def _mk_referrer(db, name, code):
    import secrets
    ref = appmod.Referrer(name=name, code=code, token=secrets.token_hex(8), active=True)
    db.add(ref)
    db.flush()
    return ref


def _mk_deal(db):
    deal = appmod.Deal(client_name='QA', deal_type=appmod.DealType.PAY_IN,
                        profit_usdt=100, payin_amount_usdt=1000, payout_amount_usdt=900)
    db.add(deal)
    db.flush()
    return deal


def test_stand_rejects_mismatched_referrer_id_and_falls_back_to_name(monkeypatch):
    monkeypatch.setattr(appmod, 'STAND_MODE', True)
    db = appmod.get_session()
    try:
        ivan = _mk_referrer(db, 'Иван', 'QA-IVAN')
        stranger = _mk_referrer(db, 'Чужой', 'QA-STRANGER')
        deal = _mk_deal(db)

        # Легаси: задачник шлёт referrer_id, оставшийся от старого refsSync(), но
        # имя в сделке — от давно удалённого/переименованного ручного агента.
        appmod._apply_deal_agents(db, deal, [
            {'referrer_id': stranger.id, 'name': 'Мой старый агент', 'tier': 1,
             'comp_model': 'revshare', 'percent': 10},
        ])
        db.flush()
        assert len(deal.agents) == 1
        assert deal.agents[0].referrer_id is None, \
            'имя не совпало с записью referrers — id чужого человека привязывать нельзя'
        assert deal.agents[0].name == 'Мой старый агент'

        # Тот же вызов, но имя совпадает с настоящей записью — id принимаем.
        appmod._apply_deal_agents(db, deal, [
            {'referrer_id': ivan.id, 'name': 'Иван', 'tier': 1,
             'comp_model': 'revshare', 'percent': 10},
        ])
        db.flush()
        assert deal.agents[0].referrer_id == ivan.id

        # Без имени вообще (интеграция шлёт только id) — старое поведение: доверяем id.
        appmod._apply_deal_agents(db, deal, [
            {'referrer_id': stranger.id, 'tier': 1, 'comp_model': 'revshare', 'percent': 10},
        ])
        db.flush()
        assert deal.agents[0].referrer_id == stranger.id
        assert deal.agents[0].name == 'Чужой', 'имя подтянулось из профиля, как и раньше'
    finally:
        db.rollback()
        db.close()


def test_prod_still_trusts_referrer_id_even_if_name_differs(monkeypatch):
    """Негативный контроль: прод шлёт referrer_id только из настоящей CRM, где имя
    и id всегда согласованы. Проверка добавлена только для стенда — на проде
    поведение (в т.ч. на рассинхроне) не должно измениться."""
    monkeypatch.setattr(appmod, 'STAND_MODE', False)
    db = appmod.get_session()
    try:
        stranger = _mk_referrer(db, 'Чужой', 'QA-PROD-STRANGER')
        deal = _mk_deal(db)
        appmod._apply_deal_agents(db, deal, [
            {'referrer_id': stranger.id, 'name': 'Другое имя', 'tier': 1,
             'comp_model': 'revshare', 'percent': 10},
        ])
        db.flush()
        assert deal.agents[0].referrer_id == stranger.id, 'на проде поведение прежнее — id не перепроверяем'
    finally:
        db.rollback()
        db.close()


def test_stand_ambiguous_and_unique_name_fallback_unchanged(monkeypatch):
    """Существующий фолбэк по имени (без referrer_id) — не должен ломаться новой
    проверкой: несколько тёзок — не гадаем, один тёзка — привязываем."""
    monkeypatch.setattr(appmod, 'STAND_MODE', True)
    db = appmod.get_session()
    try:
        _mk_referrer(db, 'Тёзка', 'QA-T1')
        _mk_referrer(db, 'Тёзка', 'QA-T2')
        unique = _mk_referrer(db, 'Уникальный', 'QA-U1')
        deal = _mk_deal(db)

        appmod._apply_deal_agents(db, deal, [
            {'name': 'Тёзка', 'tier': 1, 'comp_model': 'revshare', 'percent': 10},
        ])
        db.flush()
        assert deal.agents[0].referrer_id is None, 'несколько тёзок — не гадаем'

        appmod._apply_deal_agents(db, deal, [
            {'name': 'Уникальный', 'tier': 1, 'comp_model': 'revshare', 'percent': 10},
        ])
        db.flush()
        assert deal.agents[0].referrer_id == unique.id
    finally:
        db.rollback()
        db.close()
