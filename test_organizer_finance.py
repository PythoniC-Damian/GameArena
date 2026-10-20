"""Financial conservation, funding gates and exactly-once event close."""
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
import pytest
from test_tournament_artwork import artwork_uploads
from app import app, db, User, WalletTransaction
from gamearena.models import OrganizerDraft, OrganizerFinance, OrganizerProfile, Tournament, UserTournament
from gamearena.organizer_finance import fund, close_event, AGREEMENT_VERSION
from gamearena.economy import spend_cash
from test_interface_contracts import player, client, token


def setup_event():
    host=player('event_host'); entrant=player('event_entrant'); other=player('event_other')
    host.wallet_balance=2000;host.wallet_winnings_balance=500
    entrant.wallet_balance=1000;entrant.wallet_winnings_balance=700
    draft=OrganizerDraft(owner_id=host.id,name='Funded cup',game='Free Fire',rules='Published scoring and refund rules.',entry_fee=101,prize_pool=1000,capacity=16,
        starts_at=datetime.utcnow()+timedelta(days=2),agreement_version=AGREEMENT_VERSION,accepted_at=datetime.utcnow())
    event=Tournament(name=draft.name,game=draft.game,prize=1000,entry_fee=101,max_participants=16,status='open')
    db.session.add_all([draft,event]);db.session.flush();draft.tournament_id=event.id;draft.status='published'
    fund(event,draft,host)
    payment=WalletTransaction(user_id=entrant.id,type='tournament_entry',amount=101,status='completed',transaction_ref='gp_test_entry',winnings_spent=spend_cash(entrant,101))
    db.session.add_all([payment,UserTournament(user_id=entrant.id,tournament_id=event.id,payment_status='paid',amount_paid=101,transaction_ref=payment.transaction_ref)])
    db.session.commit()
    return host,entrant,other,draft,event


def test_settlement_conserves_funds_and_credits_winnings_once():
    with app.app_context():
        host,entrant,other,draft,event=setup_event()
        with pytest.raises(ValueError):close_event(event.id,host.id,{entrant.id:1000},'Evidence reviewed')
        db.session.rollback();event.status='finished';db.session.commit()
        for awards in ({other.id:1000},{entrant.id:999}):
            with pytest.raises(ValueError):close_event(event.id,host.id,awards,'Evidence reviewed')
            db.session.rollback()
        finance=close_event(event.id,host.id,{entrant.id:1000},'Scoreboard and disputes reviewed');db.session.commit()
        assert finance.platform_fee==5 and finance.entry_revenue==101
        db.session.refresh(host);db.session.refresh(entrant)
        assert host.wallet_balance==1096 and host.wallet_winnings_balance==596
        assert entrant.wallet_balance==1899 and entrant.wallet_winnings_balance==1700
        assert host.wallet_balance+entrant.wallet_balance+finance.platform_fee==3000
        with pytest.raises(ValueError):close_event(event.id,host.id,{entrant.id:1000},'Retry')
        db.session.rollback()
        assert WalletTransaction.query.filter_by(type='prize_credit').count()==1
        html=client(entrant).get('/wallet').text
        assert 'Tournament prize' in html
        receipt=WalletTransaction.query.filter_by(type='prize_credit').one()
        assert client(other).get(f'/wallet/transactions/{receipt.id}').status_code==404
        assert 'GameArena GP wallet' in client(entrant).get(f'/wallet/transactions/{receipt.id}').text


def test_cancellation_restores_original_sources_without_fee():
    with app.app_context():
        host,entrant,other,draft,event=setup_event()
        finance=close_event(event.id,host.id,None,'Event cancelled');db.session.commit()
        db.session.refresh(host);db.session.refresh(entrant)
        assert (host.wallet_balance,host.wallet_winnings_balance)==(2000,500)
        assert (entrant.wallet_balance,entrant.wallet_winnings_balance)==(1000,700)
        assert finance.platform_fee==0 and event.status=='cancelled'
        assert UserTournament.query.one().payment_status=='refunded'
        with pytest.raises(ValueError):close_event(event.id,host.id,None,'Retry')
        db.session.rollback()
        assert WalletTransaction.query.filter_by(type='entry_refund').count()==1


def test_selected_wallet_cannot_spend_another_wallet():
    with app.app_context():
        owner=player('wallet_source');owner.wallet_balance=1000;owner.wallet_winnings_balance=700
        with pytest.raises(ValueError):spend_cash(owner,301,'purchased')
        with pytest.raises(ValueError):spend_cash(owner,701,'winnings')
        assert spend_cash(owner,200,'winnings')==200
        assert (owner.wallet_balance,owner.wallet_winnings_balance)==(800,500)
        assert spend_cash(owner,300,'purchased')==0
        assert (owner.wallet_balance,owner.wallet_winnings_balance)==(500,500)


def test_concurrent_event_close_pays_once():
    with app.app_context():
        host,entrant,other,draft,event=setup_event();event.status='finished';db.session.commit()
        event_id,host_id,entrant_id=event.id,host.id,entrant.id
    def settle(_):
        with app.app_context():
            try:
                close_event(event_id,host_id,{entrant_id:1000},'Results reviewed');db.session.commit();return True
            except ValueError:
                db.session.rollback();return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(settle,range(2)))==[False,True]
    with app.app_context():
        assert WalletTransaction.query.filter_by(type='prize_credit').count()==1
        assert db.session.get(User,entrant_id).wallet_balance==1899


def test_publication_requires_eligibility_agreement_and_cash_reserve():
    with app.app_context():
        owner=player('gate_host');admin=player('gate_admin');admin.is_admin=True
        owner.wallet_bonus_balance=5000;db.session.commit()
        browser=client(owner);reviewer=client(admin)
        def post(c,path,data):
            return c.post(path,data=dict(data,csrf_token=token(c.get('/organizers'))))
        data=dict(name='Approval cup',game='COD Mobile',rules='Scores, refund policy and dispute process are published.',entry_gp='100',prize_gp='1000',capacity='16',starts_at=(datetime.utcnow()+timedelta(days=3)).strftime('%Y-%m-%dT%H:%M'))
        assert post(browser,'/organizers',dict(data,images=artwork_uploads())).status_code==302
        row=OrganizerDraft.query.one()
        assert post(browser,f'/organizers/{row.id}/submit',{'agree':'yes'}).status_code==403
        assert post(browser,'/organizers/profile',{'contact':'verified@example.test'}).status_code==302
        assert post(browser,f'/organizers/profiles/{owner.id}/review',{'action':'approved','verified':'yes'}).status_code==403
        assert post(reviewer,f'/organizers/profiles/{owner.id}/review',{'action':'approved'}).status_code==400
        assert post(reviewer,f'/organizers/profiles/{owner.id}/review',{'action':'approved','verified':'yes'}).status_code==302
        assert post(browser,f'/organizers/{row.id}/submit',{}).status_code==400
        assert post(browser,f'/organizers/{row.id}/submit',{'agree':'yes'}).status_code==302
        assert post(reviewer,f'/organizers/{row.id}/review',{'action':'approve','checked':'yes'}).status_code==409
        assert Tournament.query.count()==0 and OrganizerFinance.query.count()==0
        owner.wallet_balance=1000;db.session.commit()
        assert post(reviewer,f'/organizers/{row.id}/review',{'action':'approve','checked':'yes'}).status_code==302
        db.session.refresh(owner);db.session.refresh(row)
        assert owner.wallet_balance==0 and owner.wallet_bonus_balance==5000
        assert OrganizerFinance.query.one().prize_reserved==1000
        assert 'settlement' in reviewer.get(f'/organizers/{row.id}/settle').text
        assert browser.get(f'/organizers/{row.id}/settle').status_code==403


def test_free_event_has_no_revenue_fee_and_cannot_mint_prizes():
    with app.app_context():
        host=player('free_host');entrant=player('free_player');host.wallet_balance=100
        event=Tournament(name='Free cup',game='Free Fire',prize=100,entry_fee=0,max_participants=4,status='finished')
        draft=OrganizerDraft(owner_id=host.id,name=event.name,game=event.game,rules='Free entry and fair results.',prize_pool=100,entry_fee=0,capacity=4,agreement_version=AGREEMENT_VERSION,accepted_at=datetime.utcnow())
        db.session.add_all([event,draft]);db.session.flush();draft.tournament_id=event.id
        fund(event,draft,host);db.session.add(UserTournament(user_id=entrant.id,tournament_id=event.id,payment_status='free',amount_paid=0));db.session.commit()
        finance=close_event(event.id,host.id,{entrant.id:100},'Winner and evidence reviewed');db.session.commit()
        assert finance.platform_fee==0 and finance.entry_revenue==0
        assert host.wallet_balance==0 and entrant.wallet_balance==100 and entrant.wallet_winnings_balance==100


def test_withdrawal_api_honors_source_and_idempotency(monkeypatch):
    from unittest.mock import Mock
    import app as application
    from test_wallet_updates import setup, payload, provider
    with app.app_context():
        owner,browser,headers=setup(monkeypatch)
        owner.wallet_winnings_balance=800;db.session.commit()
        call=Mock(side_effect=provider('pending'))
        monkeypatch.setattr(application,'paystack_transfer_request',call)
        assert browser.post('/wallet/withdraw',json=payload(owner,wallet_source='purchased'),headers=headers).status_code==400
        db.session.refresh(owner);assert owner.wallet_balance==1000 and WalletTransaction.query.count()==0
        data=payload(owner,wallet_source='winnings')
        response=browser.post('/wallet/withdraw',json=data,headers=headers)
        assert response.status_code==202
        row=WalletTransaction.query.one();db.session.refresh(owner)
        assert row.wallet_source=='winnings' and row.winnings_spent==300
        assert (owner.wallet_balance,owner.wallet_winnings_balance)==(700,500)
        assert browser.post('/wallet/withdraw',json=dict(data,wallet_source='combined'),headers=headers).status_code==409
        assert browser.post('/wallet/withdraw',json=data,headers=headers).status_code==200
        assert WalletTransaction.query.count()==1


def test_cancel_races_settlement_without_double_credit():
    with app.app_context():
        host,entrant,other,draft,event=setup_event();event.status='finished';db.session.commit()
        event_id,host_id,entrant_id=event.id,host.id,entrant.id
    def close(cancel):
        with app.app_context():
            try:
                close_event(event_id,host_id,None if cancel else {entrant_id:1000},'Reviewed close')
                db.session.commit();return True
            except ValueError:
                db.session.rollback();return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(close,[True,False]))==[False,True]
    with app.app_context():
        finance=db.session.get(OrganizerFinance,event_id)
        total=sum(u.wallet_balance for u in User.query.all())+finance.platform_fee
        assert total==3000
        assert WalletTransaction.query.filter_by(type='prize_credit').count()+WalletTransaction.query.filter_by(type='entry_refund').count()==1


def test_disputes_and_existing_prize_payout_block_settlement():
    from gamearena.models import TournamentMatch, TournamentMatchDispute, TournamentStat
    with app.app_context():
        host,entrant,other,draft,event=setup_event();event.status='finished'
        match=TournamentMatch(tournament_id=event.id,player_one_user_id=entrant.id,player_two_user_id=other.id)
        db.session.add(match);db.session.flush()
        dispute=TournamentMatchDispute(match_id=match.id,user_id=entrant.id,reason='Result contested',status='pending')
        db.session.add(dispute);db.session.commit()
        with pytest.raises(ValueError,match='disputes'):close_event(event.id,host.id,{entrant.id:1000},'Review')
        db.session.rollback()
        dispute.status='resolved'
        db.session.add(TournamentStat(tournament_id=event.id,user_id=entrant.id,prize_status='paid',paystack_transfer_ref='test-existing-only'))
        db.session.commit()
        with pytest.raises(ValueError,match='payout already exists'):close_event(event.id,host.id,{entrant.id:1000},'Review')
        db.session.rollback()
        assert WalletTransaction.query.filter_by(type='prize_credit').count()==0
        assert entrant.wallet_balance==899


def test_admin_cancel_redirects_to_financial_close_and_entries_use_gp():
    with app.app_context():
        host,entrant,other,draft,event=setup_event();host.is_admin=True;db.session.commit()
        from test_interface_contracts import ready_event
        ready_event(event,host)
        browser=client(host);headers={'X-CSRFToken':token(browser.get('/wallet'))}
        response=browser.post(f'/admin/tournaments/cancel/{event.id}',headers=headers)
        assert response.status_code==302 and response.location.endswith(f'/organizers/{draft.id}/settle')
        db.session.refresh(event);assert event.status=='open' and OrganizerFinance.query.one().state=='funded'
        assert browser.post(f'/initialize-payment/{event.id}',headers=headers).status_code==409
        page=browser.get(f'/pay/{event.id}')
        assert page.status_code==200 and 'id="gpEntryForm"' in page.text and 'id="paymentForm"' not in page.text
        assert 'Cancelled entries are refunded' in page.text
