"""Deletion requires admin, CSRF, exact confirmation and no protected history."""
import pytest
from datetime import datetime, timedelta
from app import app, db
from gamearena.models import (Tournament, UserTournament, SavedTournament, TournamentCompetition,
    TournamentLaunchPlan, TournamentVisit)
from test_interface_contracts import player, client, token


def event():
    row=Tournament(name='Unused pilot',game='eFootball',entry_fee=200,prize=1000,max_participants=4)
    db.session.add(row);db.session.commit();return row


def test_delete_unused_event_and_dependent_setup_only():
    with app.app_context():
        admin=player('delete_admin');admin.is_admin=True;other=player('delete_viewer');row=event();db.session.commit()
        tid=row.id
        db.session.add_all([TournamentCompetition(tournament_id=tid,phase='registration',game_rules='Test rules',no_show_policy='Evidence review'),
            TournamentLaunchPlan(tournament_id=tid,registration_closes_at=datetime.utcnow()+timedelta(hours=1),eligibility='Test players',rules='Test rules',cancellation_policy='Refund entries',funding_note='Owner funds prize',reviewed_by=admin.id,snapshot='test'),
            TournamentVisit(tournament_id=tid,user_id=other.id),SavedTournament(tournament_id=tid,user_id=other.id)])
        db.session.commit();browser=client(admin);path=f'/admin/tournaments/{tid}/delete'
        assert browser.post(path,data={'confirm_name':row.name}).status_code==400
        csrf=token(browser.get('/admin'))
        assert browser.post(path,data={'confirm_name':'wrong','csrf_token':csrf}).status_code==302
        assert db.session.get(Tournament,tid)
        assert browser.post(path,data={'confirm_name':row.name,'csrf_token':csrf}).status_code==302
        db.session.expire_all()
        assert db.session.get(Tournament,tid) is None
        assert browser.get(f'/tournament/{tid}').status_code==404
        assert SavedTournament.query.filter_by(tournament_id=tid).count()==0


@pytest.mark.parametrize('status',['pending','paid','refunded','free'])
def test_delete_preserves_all_entry_history(status):
    with app.app_context():
        admin=player('history_admin');admin.is_admin=True;entrant=player('history_entrant');row=event()
        db.session.add(UserTournament(user_id=entrant.id,tournament_id=row.id,payment_status=status));db.session.commit()
        browser=client(admin);csrf=token(browser.get('/admin'))
        assert browser.post(f'/admin/tournaments/{row.id}/delete',data={'confirm_name':row.name,'csrf_token':csrf}).status_code==302
        assert db.session.get(Tournament,row.id)
        assert UserTournament.query.filter_by(tournament_id=row.id,payment_status=status).count()==1


def test_delete_rejects_non_admin():
    with app.app_context():
        user=player('no_delete');row=event();browser=client(user)
        csrf=token(browser.get('/tournaments'))
        assert browser.post(f'/admin/tournaments/{row.id}/delete',data={'confirm_name':row.name,'csrf_token':csrf}).status_code==403
        assert db.session.get(Tournament,row.id)


def test_delete_preserves_drawn_matches(monkeypatch):
    from test_competition_flow import fixture, check_in, start
    from gamearena.models import TournamentMatch
    with app.app_context():
        admin,users,row=fixture(monkeypatch)
        check_in(admin,users,row);start(admin,row)
        browser=client(admin);csrf=token(browser.get('/admin'))
        assert browser.post(f'/admin/tournaments/{row.id}/delete',data={'confirm_name':row.name,'csrf_token':csrf}).status_code==302
        assert TournamentMatch.query.filter_by(tournament_id=row.id).count()==2
        assert db.session.get(Tournament,row.id)
