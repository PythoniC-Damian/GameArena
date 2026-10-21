"""Registration safety, honest public copy and derived 1v1 standings."""
from datetime import datetime, timedelta
import app as application
from app import app, db
from gamearena.models import (Tournament, TournamentLaunchPlan, TournamentVisit, TournamentStat,
    TournamentMatch, UserTournament)
from gamearena.tournament_launch import signature, registration_ready, prize_amount
from test_interface_contracts import player, client, token
from test_competition_flow import fixture, check_in, start, play_and_report, post


def launch_terms():
    return dict(registration_closes_at=(datetime.utcnow()+timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M'),
        eligibility='Mobile devices, current game version, test region, eligible adults.',
        rules='Single elimination, best of one, ten minutes per match. Submit evidence; staff review disputes.',
        cancellation_policy='If the minimum field is not reached, cancel and return all paid entry GP.',
        funding_note='The organiser covers the announced prize independently of entry revenue.',launch_ack='yes')


def event(admin, **changes):
    values=dict(name='Real pilot',game='Free Fire',entry_fee=0,prize=0,max_participants=4,
        match_time=datetime.utcnow()+timedelta(hours=2),status='open')
    values.update(changes)
    row=Tournament(**values);db.session.add(row);db.session.commit()
    return row


def approve(admin,row):
    response=post(client(admin),f'/tournament/{row.id}/launch',launch_terms())
    assert response.status_code==302,response.text
    db.session.refresh(row)
    assert registration_ready(row)


def test_gp_policies_share_the_actual_wallet_rate_and_public_support(monkeypatch):
    monkeypatch.setenv('GAMEARENA_SUPPORT_EMAIL','help@example.test')
    visitor=app.test_client()
    for path in ('/faq','/terms'):
        page=visitor.get(path)
        assert page.status_code==200
        assert 'NGN 10 per GP' not in page.text and '1 GP = NGN 10,' not in page.text
        assert 'NGN 1' in page.text
    assert 'NGN 1,000 buys 1,000 GP' in visitor.get('/faq').text
    support=visitor.get('/support')
    assert support.status_code==200 and 'mailto:help@example.test' in support.text
    assert 'name="reason"' not in support.text
    assert visitor.post('/support',data={'reason':'spam','csrf_token':token(visitor.get('/tournaments'))}).status_code==401


def test_unready_events_cannot_charge_or_accept_free_entries(monkeypatch):
    with app.app_context():
        user=player('not_ready_player');browser=client(user)
        row=event(user,entry_fee=500,prize=1000,match_time=None)
        db.session.add(TournamentLaunchPlan(tournament_id=row.id, registration_closes_at=datetime.utcnow()+timedelta(hours=1), eligibility='Published eligibility', rules='Published competition rules', cancellation_policy='Published refund terms', funding_note='Owner funds prizes', reviewed_by=user.id, snapshot='outdated'))
        user.wallet_balance=1000;db.session.commit()
        monkeypatch.setattr(application.requests,'post',lambda *a,**k:(_ for _ in ()).throw(AssertionError('provider contacted')))
        assert 'In preparation' in browser.get('/tournaments').text
        assert browser.get(f'/pay/{row.id}').status_code==302
        assert post(browser,f'/initialize-payment/{row.id}').status_code==409
        response=browser.post(f'/tournaments/{row.id}/pay-gp',json={'amount':500},headers={'X-CSRFToken':token(browser.get('/tournaments'))})
        assert response.status_code==409 and 'preparation' in response.json['message']
        row.entry_fee=0;db.session.commit()
        assert post(browser,f'/join-tournament/{row.id}').status_code==302
        assert UserTournament.query.count()==0
        db.session.refresh(user);assert user.wallet_balance==1000


def test_launch_review_requires_dates_prize_totals_and_explicit_commitment():
    with app.app_context():
        admin=player('launch_admin');admin.is_admin=True;db.session.commit()
        row=event(admin,entry_fee=2500,prize=155000,max_participants=60)
        browser=client(admin);path=f'/tournament/{row.id}/launch'
        page=browser.get(path)
        assert page.status_code==200 and '5,000 GP' in page.text and '150,000 GP' in page.text
        assert post(browser,path,launch_terms()).status_code==200
        assert TournamentLaunchPlan.query.count()==0
        row.first_place='100,000 GP';row.second_place='55,000';row.third_place='0';db.session.commit()
        data=launch_terms();data.pop('launch_ack')
        assert post(browser,path,data).status_code==200 and TournamentLaunchPlan.query.count()==0
        approve(admin,row)
        public=app.test_client().get(f'/tournament/{row.id}')
        assert 'Registration closes (UTC)' in public.text and 'covers the announced prize' in public.text
        assert 'not a completed payout' in public.text
        assert 'Open' in app.test_client().get('/tournaments').text
        row.prize=160000;db.session.commit()
        assert not registration_ready(row)


def test_cod_launch_requires_configured_competition_format():
    with app.app_context():
        admin=player('format_launch_admin');admin.is_admin=True;db.session.commit()
        row=event(admin,game='COD Mobile')
        response=post(client(admin),f'/tournament/{row.id}/launch',launch_terms())
        assert response.status_code==200 and 'Publish the 1v1 competition format' in response.text
        assert TournamentLaunchPlan.query.count()==0 and registration_ready(row)


def test_ready_free_pilot_join_and_deadline_enforced(monkeypatch):
    with app.app_context():
        admin=player('ready_admin');admin.is_admin=True;user=player('ready_player');db.session.commit()
        row=event(admin);approve(admin,row)
        monkeypatch.setattr(application,'create_and_emit_notification',lambda *a,**k:None)
        assert post(client(user),f'/join-tournament/{row.id}').status_code==302
        assert UserTournament.query.filter_by(tournament_id=row.id,user_id=user.id).one().payment_status=='free'
        assert post(client(admin),f'/tournament/{row.id}/launch',launch_terms()).status_code==409
        row.launch_plan.registration_closes_at=datetime.utcnow()-timedelta(seconds=1)
        row.launch_plan.snapshot=signature(row,row.launch_plan);db.session.commit()
        assert not registration_ready(row)


def test_launch_and_funnel_permissions_and_unique_signed_in_counts():
    with app.app_context():
        admin=player('funnel_admin');admin.is_admin=True;user=player('funnel_player');db.session.commit()
        row=event(admin)
        assert client(user).get(f'/tournament/{row.id}/launch').status_code==403
        assert client(user).get('/admin/tournament-funnel').status_code==403
        visitor=app.test_client();visitor.get(f'/tournament/{row.id}')
        client(admin).get(f'/tournament/{row.id}')
        assert TournamentVisit.query.count()==0
        browser=client(user)
        for _ in range(3):browser.get(f'/tournament/{row.id}')
        browser.get(f'/join-tournament/{row.id}')
        assert TournamentVisit.query.count()==1 and TournamentVisit.query.one().join_requested
        page=client(admin).get('/admin/tournament-funnel')
        assert page.status_code==200 and 'Real pilot' in page.text and 'different units' in page.text


def test_ready_gp_entries_debit_once_without_changing_accepted_terms(monkeypatch):
    with app.app_context():
        admin=player('gp_launch_admin');admin.is_admin=True;user=player('gp_launch_player');db.session.commit()
        row=event(admin,entry_fee=500);approve(admin,row)
        user.wallet_balance=1000;db.session.commit()
        monkeypatch.setattr(application,'create_and_emit_notification',lambda *a,**k:None)
        monkeypatch.setattr(application,'award_achievements_for_user',lambda *a,**k:None)
        browser=client(user);headers={'X-CSRFToken':token(browser.get('/wallet'))}
        path=f'/tournaments/{row.id}/pay-gp'
        assert browser.post(path,json={'amount_gp':'500'},headers=headers).status_code==200
        assert browser.post(path,json={'amount_gp':'500'},headers=headers).json['already_paid']
        db.session.refresh(user);assert user.wallet_balance==500
        form=dict(entry_fee='600',prize_pool='0',max_participants='4',status='open',
            match_time=row.match_time.strftime('%Y-%m-%d %H:%M'))
        assert post(client(admin),f'/admin/tournaments/{row.id}/edit',form).status_code==409
        db.session.refresh(row);assert row.entry_fee==500


def test_finished_bracket_derives_tied_standings_without_paying_money(monkeypatch):
    from gamearena.competition import sync_standings
    with app.app_context():
        admin,users,row=fixture(monkeypatch);check_in(admin,users,row);start(admin,row)
        first_round=TournamentMatch.query.filter_by(tournament_id=row.id,round_number=1).all()
        for match in first_round:
            _,opponent=play_and_report(match)
            assert TournamentStat.query.count() in (0,4)
            assert post(opponent,f'/match/{match.id}/confirm-result').status_code==302
        assert all(stat.rank==0 for stat in TournamentStat.query.all())
        final=TournamentMatch.query.filter_by(tournament_id=row.id,round_number=2).one()
        _,opponent=play_and_report(final)
        assert post(opponent,f'/match/{final.id}/confirm-result').status_code==302
        stats=TournamentStat.query.filter_by(tournament_id=row.id).all()
        assert sorted(s.rank for s in stats)==[1,2,3,3]
        assert sorted(s.wins for s in stats)==[0,0,1,2]
        champion=next(s for s in stats if s.rank==1)
        champion.prize_status='pending';champion.paystack_transfer_ref='KEEP_REAL_REFERENCE';db.session.commit()
        sync_standings(row);db.session.commit();sync_standings(row);db.session.commit()
        assert TournamentStat.query.count()==4 and champion.prize_status=='pending'
        assert champion.paystack_transfer_ref=='KEEP_REAL_REFERENCE'
        assert all(s.kills==0 and s.points==s.wins for s in stats)
        assert all(u.wallet_balance==0 for u in users)
        assert champion.user.username in app.test_client().get(f'/leaderboard?tournament={row.id}').text
        assert post(client(admin),f'/admin/tournaments/{row.id}/leaderboard',{}).status_code==409
        assert post(client(admin),f'/admin/tournaments/{row.id}/leaderboard/delete/{champion.id}').status_code==409


def test_prize_parser_does_not_turn_arbitrary_labels_into_money():
    assert prize_amount('55,000 GP')==55000 and prize_amount('0')==0
    for value in ('Winner: 50,000','TBA','-10','1.5','1,2,3','GP 50'):
        assert prize_amount(value) is None


def test_pilot_prize_settlement_must_match_published_winner(monkeypatch):
    import pytest
    from gamearena.models import OrganizerDraft
    from gamearena.organizer_finance import fund, close_event, AGREEMENT_VERSION
    with app.app_context():
        admin,users,row=fixture(monkeypatch,2)
        row.prize=1000;row.first_place='1000';row.second_place='0';row.third_place='0'
        row.match_time=datetime.utcnow()+timedelta(hours=2);admin.wallet_balance=2000;db.session.commit()
        approve(admin,row)
        draft=OrganizerDraft(owner_id=admin.id,name=row.name,game=row.game,rules='Published pilot match and refund terms.',
            prize_pool=1000,entry_fee=0,capacity=2,tournament_id=row.id,status='published',
            agreement_version=AGREEMENT_VERSION,accepted_at=datetime.utcnow())
        db.session.add(draft);fund(row,draft,admin);db.session.commit()
        check_in(admin,users,row);start(admin,row)
        match=TournamentMatch.query.filter_by(tournament_id=row.id).one()
        _,opponent=play_and_report(match)
        assert post(opponent,f'/match/{match.id}/confirm-result').status_code==302
        with pytest.raises(ValueError,match='published GP allocation'):
            close_event(row.id,admin.id,{match.player_two_user_id:1000},'Reviewed the pilot final and evidence.')
        db.session.rollback()
        close_event(row.id,admin.id,{match.player_one_user_id:1000},'Reviewed the pilot final and evidence.')
        db.session.commit()
        db.session.refresh(match.player_one)
        assert match.player_one.wallet_balance==1000
        assert TournamentStat.query.filter_by(user_id=match.player_one_user_id,tournament_id=row.id).one().prize_status=='paid'


def test_open_event_join_restored_without_launch_checklist():
    with app.app_context():
        user=player('legacy_join');row=event(user,match_time=None)
        browser=client(user)
        assert registration_ready(row)
        assert 'Join tournament' in browser.get(f'/tournament/{row.id}').text
        response=post(browser,f'/join-tournament/{row.id}')
        assert response.status_code==302
        assert UserTournament.query.filter_by(tournament_id=row.id,user_id=user.id,payment_status='free').one()
        row.status='ongoing';db.session.commit()
        assert not registration_ready(row)
