"""Exercise the complete checked-in bracket, privacy and disputed outcomes."""
import io
from datetime import datetime,timedelta
from concurrent.futures import ThreadPoolExecutor
import pytest
from PIL import Image
import app as application
from app import app,db
from gamearena.models import (Tournament,UserTournament,TournamentMatch,TournamentCompetition,TournamentCheckIn,MatchLobby,MatchEvidence,TournamentMatchDispute)
from test_interface_contracts import player,client,token


def post(browser,path,data=None):
    return browser.post(path,data=dict(data or {},csrf_token=token(browser.get('/tournaments'))))


def fixture(monkeypatch,count=4,configure=True):
    monkeypatch.setattr(application,'create_and_emit_notification',lambda *a,**kw:None)
    monkeypatch.setattr(application,'award_achievements_for_user',lambda *a,**kw:None)
    admin=player('flow_admin');admin.is_admin=True
    users=[player('flow_player_'+str(i)) for i in range(count)]
    event=Tournament(name='GameArena 1v1 Cup',game='COD Mobile',entry_fee=0,prize=0,max_participants=count,status='open')
    db.session.add(event);db.session.commit()
    if configure:
        response=post(client(admin),f'/tournament/{event.id}/competition/setup',rules())
        assert response.status_code==302,response.text
    return admin,users,event


def rules():
    return dict(game_rules='1v1, agreed map, first to 10 eliminations. No cheating.',no_show_policy='Wait 10 minutes, then report an issue with evidence. Staff review; ties require a replay.',rules_ack='yes')


def register(users,event):
    for user in users:db.session.add(UserTournament(user_id=user.id,tournament_id=event.id,payment_status='free'))
    db.session.commit()


def check_in(admin,users,event):
    register(users,event)
    assert post(client(admin),f'/tournament/{event.id}/competition/open-check-in',{'deadline':(datetime.utcnow()+timedelta(minutes=30)).strftime('%Y-%m-%dT%H:%M')}).status_code==302
    for i,user in enumerate(users):
        response=post(client(user),f'/tournament/{event.id}/competition/check-in',{'game_id':f'PLAYER_{i}#123','agree':'yes'})
        assert response.status_code==302,response.text


def start(admin,event):
    response=post(client(admin),f'/tournament/{event.id}/competition/start')
    assert response.status_code==302,response.text


def screenshot():
    output=io.BytesIO();Image.new('RGB',(640,360),'#146454').save(output,'PNG');output.seek(0)
    return output,'result.png'


def scores(match,**changes):
    data=dict(player_one_score='10',player_two_score='7',winner_user_id=str(match.player_one_user_id),evidence=screenshot(),proof_note='Actual scoreboard and scores.')
    data.update(changes);return data


def play_and_report(match):
    host,opponent=client(match.player_one),client(match.player_two)
    assert post(host,f'/match/{match.id}/room',dict(room_code='PRIVATE_ROOM_123',room_password='PRIVATE_PASS')).status_code==302
    for browser in (host,opponent):assert post(browser,f'/match/{match.id}/ready',{'agree':'yes'}).status_code==302
    assert post(host,f'/match/{match.id}/submit-result',scores(match)).status_code==302
    db.session.refresh(match);assert match.status=='pending_confirmation'
    return host,opponent


def test_complete_four_player_bracket_and_private_evidence(monkeypatch):
    with app.app_context():
        admin,users,event=fixture(monkeypatch);check_in(admin,users,event);start(admin,event)
        page=client(users[0]).get(f'/tournament/{event.id}')
        assert page.status_code==200 and 'How this tournament works' in page.text and 'first to 10' in page.text
        matches=TournamentMatch.query.filter_by(tournament_id=event.id,round_number=1).order_by(TournamentMatch.id).all()
        assert len(matches)==2 and MatchLobby.query.count()==2
        assert {uid for m in matches for uid in (m.player_one_user_id,m.player_two_user_id)}=={u.id for u in users}
        match=matches[0];host,opponent=play_and_report(match)
        stranger=next(u for u in users if u.id not in {match.player_one_user_id,match.player_two_user_id})
        evidence=MatchEvidence.query.filter_by(match_id=match.id).one()
        assert client(stranger).get(f'/match/{match.id}/play').status_code==404
        assert client(stranger).get(f'/media/match-evidence/{evidence.id}.webp').status_code==404
        assert 'PRIVATE_PASS' not in client(stranger).get(f'/tournament/{event.id}').text
        assert 'PRIVATE_PASS' not in app.test_client().get(f'/api/v1/tournaments/{event.id}').text
        private=opponent.get(f'/media/match-evidence/{evidence.id}.webp')
        assert private.status_code==200 and 'no-store' in private.headers['Cache-Control']
        with Image.open(io.BytesIO(private.data)) as image:assert image.size==(640,360)
        assert post(host,f'/match/{match.id}/confirm-result').status_code==302
        db.session.refresh(match);assert match.status=='pending_confirmation'
        assert post(opponent,f'/match/{match.id}/confirm-result').status_code==302
        assert TournamentMatch.query.filter_by(round_number=2).count()==0
        _,other=play_and_report(matches[1]);assert post(other,f'/match/{matches[1].id}/confirm-result').status_code==302
        final=TournamentMatch.query.filter_by(tournament_id=event.id,round_number=2).one()
        assert final.player_one_profile_id and final.player_two_profile_id and db.session.get(MatchLobby,final.id)
        _,last=play_and_report(final);assert post(last,f'/match/{final.id}/confirm-result').status_code==302
        db.session.refresh(event);assert event.status=='finished' and db.session.get(TournamentCompetition,event.id).phase=='finished'
        assert post(last,f'/match/{final.id}/ready',{'agree':'yes'}).status_code==409
        assert post(client(admin),f'/tournament/{event.id}/competition/start').status_code==409
        assert TournamentMatch.query.count()==3
        assert 'You have been eliminated' in client(final.player_two).get(f'/match/{final.id}/play').text
        assert 'You are the champion!' in client(final.player_one).get(f'/match/{final.id}/play').text
        assert final.player_one.username in app.test_client().get(f'/tournament/{event.id}').text


def test_checkin_rejects_ineligible_duplicate_and_expired_accounts(monkeypatch):
    with app.app_context():
        admin,users,event=fixture(monkeypatch);register(users,event)
        assert post(client(admin),f'/tournament/{event.id}/competition/open-check-in',{'deadline':(datetime.utcnow()+timedelta(minutes=10)).strftime('%Y-%m-%dT%H:%M')}).status_code==302
        outsider=player('flow_outsider');url=f'/tournament/{event.id}/competition/check-in'
        assert post(client(outsider),url,{'game_id':'outside','agree':'yes'}).status_code==403
        assert post(client(users[0]),url,{'game_id':'same-id'}).status_code==400
        assert post(client(users[0]),url,{'game_id':'same-id','agree':'yes'}).status_code==302
        assert post(client(users[1]),url,{'game_id':'SAME-ID','agree':'yes'}).status_code==409
        assert post(client(admin),f'/tournament/{event.id}/competition/start').status_code==409
        assert TournamentMatch.query.count()==0
        config=db.session.get(TournamentCompetition,event.id);config.checkin_closes_at=datetime.utcnow()-timedelta(seconds=1);db.session.commit()
        assert post(client(users[1]),url,{'game_id':'another-id','agree':'yes'}).status_code==409


def test_rules_are_public_and_cannot_change_after_entries(monkeypatch):
    with app.app_context():
        admin,users,event=fixture(monkeypatch,configure=False)
        url=f'/tournament/{event.id}/competition/setup'
        assert post(client(users[0]),url,rules()).status_code==403
        assert post(client(admin),url,rules()).status_code==302
        assert post(client(admin),url,rules()).status_code==409
        guide=app.test_client().get('/tournaments/guide/1v1');assert guide.status_code==200 and 'silently removed' in guide.text
        assert 'Published game rules' in app.test_client().get(f'/tournament/{event.id}').text
        assert app.test_client().get(f'/api/v1/tournaments/{event.id}').json['data']['format']=='single_elimination_1v1'
        second=Tournament(name='Existing entries',game='eFootball',max_participants=2,status='open');db.session.add(second);db.session.flush();register(users[:1],second)
        assert post(client(admin),f'/tournament/{second.id}/competition/setup',rules()).status_code==409


def test_host_readiness_scores_and_saved_ids_are_enforced(monkeypatch):
    with app.app_context():
        admin,users,event=fixture(monkeypatch,2);check_in(admin,users,event);start(admin,event)
        match=TournamentMatch.query.one();host,opponent=client(match.player_one),client(match.player_two)
        assert post(opponent,f'/match/{match.id}/room',{'room_code':'bad'}).status_code==403
        assert post(host,f'/match/{match.id}/ready',{'agree':'yes'}).status_code==409
        assert post(host,f'/match/{match.id}/room',{'room_code':'real'}).status_code==302
        assert post(host,f'/match/{match.id}/ready',{'agree':'yes'}).status_code==302
        assert post(host,f'/match/{match.id}/room',{'room_code':'changed'}).status_code==409
        assert post(host,f'/match/{match.id}/submit-result',scores(match)).status_code==302
        assert MatchEvidence.query.count()==0
        assert post(opponent,f'/match/{match.id}/ready',{'agree':'yes'}).status_code==302
        for change in ({'player_two_score':'10'},{'winner_user_id':str(match.player_two_user_id)},{'evidence':(io.BytesIO(b'<svg/>'),'fake.png')}):
            assert post(host,f'/match/{match.id}/submit-result',scores(match,**change)).status_code==302
            db.session.refresh(match);assert match.status=='ongoing' and MatchEvidence.query.count()==0
        assert post(host,f'/match/{match.id}/submit-result',scores(match,room_code='FAKE',player_profile_id='IMPERSONATED')).status_code==302
        db.session.refresh(match);assert match.room_code=='real' and match.player_one_profile_id!='IMPERSONATED'


def test_no_show_pauses_for_staff_decision(monkeypatch):
    with app.app_context():
        admin,users,event=fixture(monkeypatch,2);check_in(admin,users,event);start(admin,event)
        match=TournamentMatch.query.one();browser=client(match.player_one)
        assert post(browser,f'/match/{match.id}/report-issue',{'reason':'Opponent has not joined after the published waiting time.'}).status_code==302
        db.session.refresh(match);assert match.status=='disputed' and match.winner_user_id is None
        assert post(browser,f'/match/{match.id}/ready',{'agree':'yes'}).status_code==409
        data=dict(decision='confirm',winner_user_id=str(match.player_one_user_id),review_note='Verified room timing and evidence under the published rules.',review_ack='yes')
        url=f'/admin/matches/{match.id}/review-dispute'
        assert post(browser,url,data).status_code==403
        assert post(client(admin),url,{'decision':'confirm'}).status_code==400
        assert post(client(admin),url,data).status_code==302
        db.session.refresh(match);assert match.status=='confirmed' and match.winner_user_id==match.player_one_user_id
        assert TournamentMatchDispute.query.one().status=='resolved'
        assert db.session.get(MatchLobby,match.id).reviewed_by==admin.id


def test_concurrent_start_creates_one_bracket(monkeypatch):
    with app.app_context():
        admin,users,event=fixture(monkeypatch);check_in(admin,users,event);eid=event.id
    def draw(_):
        with app.app_context():
            try:return bool(application.create_tournament_matches(db.session.get(Tournament,eid)))
            finally:db.session.rollback()
    with ThreadPoolExecutor(max_workers=2) as pool:assert all(pool.map(draw,range(2)))
    with app.app_context():assert TournamentMatch.query.filter_by(tournament_id=eid).count()==2


@pytest.mark.parametrize('closed',['cancelled','finished'])
def test_closed_events_cannot_be_restarted(monkeypatch,closed):
    with app.app_context():
        admin,users,event=fixture(monkeypatch,2,configure=False);register(users,event);event.status=closed;db.session.commit()
        assert post(client(users[0]),f'/tournament/{event.id}/matchmake').status_code==409
        assert application.create_tournament_matches(event)==[]
        db.session.refresh(event);assert event.status==closed and TournamentMatch.query.count()==0


def test_approved_owner_can_manage_but_other_users_cannot(monkeypatch):
    from gamearena.models import OrganizerDraft,OrganizerProfile
    with app.app_context():
        admin,users,event=fixture(monkeypatch,2,configure=False)
        owner,other=users
        db.session.add_all([OrganizerProfile(user_id=owner.id,status='approved',contact='verified@example.test'),OrganizerDraft(owner_id=owner.id,name=event.name,game=event.game,rules='Published game and refund rules.',starts_at=datetime.utcnow()+timedelta(days=2),tournament_id=event.id,status='published')]);db.session.commit()
        assert post(client(other),f'/tournament/{event.id}/competition/setup',rules()).status_code==403
        assert post(client(owner),f'/tournament/{event.id}/competition/setup',rules()).status_code==302
        assert post(client(other),f'/tournament/{event.id}/competition/open-check-in',{'deadline':(datetime.utcnow()+timedelta(minutes=10)).strftime('%Y-%m-%dT%H:%M')}).status_code==403


def test_partial_field_waits_until_deadline_without_dropping_players(monkeypatch):
    with app.app_context():
        admin,users,event=fixture(monkeypatch,4)
        check_in(admin,users[:2],event)
        assert post(client(admin),f'/tournament/{event.id}/competition/start').status_code==409
        config=db.session.get(TournamentCompetition,event.id);config.checkin_closes_at=datetime.utcnow()-timedelta(seconds=1);db.session.commit()
        start(admin,event);assert TournamentMatch.query.count()==1


def test_pending_payments_and_suspended_entrants_block_start(monkeypatch):
    with app.app_context():
        admin,users,event=fixture(monkeypatch,2);check_in(admin,users,event)
        extra=player('pending_player');row=UserTournament(user_id=extra.id,tournament_id=event.id,payment_status='pending',transaction_ref='pending_reconciliation')
        db.session.add(row);db.session.commit()
        assert post(client(admin),f'/tournament/{event.id}/competition/start').status_code==409
        row.payment_status='failed';users[0].suspended=True;db.session.commit()
        assert post(client(admin),f'/tournament/{event.id}/competition/start').status_code==409
        assert TournamentMatch.query.count()==0


def test_status_and_checkin_require_permission_and_csrf(monkeypatch):
    with app.app_context():
        admin,users,event=fixture(monkeypatch,2);check_in(admin,users,event)
        outsider=player('status_outsider')
        assert client(outsider).get(f'/tournament/{event.id}/competition/status').status_code==403
        page=client(users[0]);status=page.get(f'/tournament/{event.id}/competition/status')
        assert status.status_code==200 and 'no-store' in status.headers['Cache-Control']
        assert 'game_id' not in status.text and 'room_password' not in status.text
        assert page.post(f'/tournament/{event.id}/competition/check-in',data={'game_id':'NO_CSRF','agree':'yes'}).status_code==400
        assert post(client(admin),f'/admin/tournaments/end/{event.id}').status_code==409
        assert post(client(admin),f'/admin/tournaments/start/{event.id}').status_code==409


def test_staff_reopen_preserves_ids_and_requires_new_result(monkeypatch):
    with app.app_context():
        admin,users,event=fixture(monkeypatch,2);check_in(admin,users,event);start(admin,event)
        match=TournamentMatch.query.one();first,other=play_and_report(match)
        assert post(other,f'/match/{match.id}/dispute',{'reason':'The submitted score differs from the final scoreboard.'}).status_code==302
        assert post(client(admin),f'/admin/matches/{match.id}/review-dispute',{'decision':'reopen','review_note':'Evidence conflicts; replay required under published rules.','review_ack':'yes'}).status_code==302
        db.session.refresh(match);assert match.status=='scheduled' and match.winner_user_id is None
        assert match.player_one_profile_id and match.player_two_profile_id
        assert db.session.get(MatchLobby,match.id).player_one_score is None
        assert post(other,f'/match/{match.id}/confirm-result').status_code==302
        db.session.refresh(match);assert match.status=='scheduled'


def test_dispute_evidence_revisions_are_retained_after_replay(monkeypatch):
    with app.app_context():
        admin,users,event=fixture(monkeypatch,2);check_in(admin,users,event);start(admin,event)
        match=TournamentMatch.query.one();first,other=play_and_report(match)
        original=MatchEvidence.query.one().id
        assert post(other,f'/match/{match.id}/dispute',{'reason':'My scoreboard shows a different score.','evidence':screenshot()}).status_code==302
        assert MatchEvidence.query.count()==2
        assert post(client(admin),f'/admin/matches/{match.id}/review-dispute',{'decision':'reopen','review_note':'Both screenshots were reviewed. A replay is required.','review_ack':'yes'}).status_code==302
        assert post(first,f'/match/{match.id}/room',{'room_code':'REPLAY_ROOM'}).status_code==302
        for browser in (first,other):assert post(browser,f'/match/{match.id}/ready',{'agree':'yes'}).status_code==302
        assert post(first,f'/match/{match.id}/submit-result',scores(match)).status_code==302
        assert MatchEvidence.query.count()==3
        assert first.get(f'/media/match-evidence/{original}.webp').status_code==200


def test_staff_cannot_judge_own_match_and_closed_chat_is_blocked(monkeypatch):
    with app.app_context():
        admin,users,event=fixture(monkeypatch,2);check_in(admin,users,event);start(admin,event)
        match=TournamentMatch.query.one();match.player_one.is_admin=True;db.session.commit()
        first=client(match.player_one)
        assert post(first,f'/match/{match.id}/report-issue',{'reason':'My opponent did not arrive within the published time.'}).status_code==302
        data={'decision':'confirm','winner_user_id':str(match.player_one_user_id),'review_note':'This outcome requires an independent staff review.','review_ack':'yes'}
        assert post(first,f'/admin/matches/{match.id}/review-dispute',data).status_code==403
        event.status='cancelled';db.session.commit()
        assert post(first,f'/match/{match.id}/chat',{'message':'cannot change a closed match'}).status_code==409
        assert post(first,f'/match/{match.id}/report-issue',{'reason':'Another issue with the closed match.'}).status_code==409


@pytest.mark.parametrize('game,capacity',[('Free Fire',16),('PUBG Mobile',16),('COD Mobile',3)])
def test_unsupported_format_is_not_enabled(monkeypatch,game,capacity):
    with app.app_context():
        admin,users,event=fixture(monkeypatch,2,configure=False);event.game=game;event.max_participants=capacity;db.session.commit()
        assert post(client(admin),f'/tournament/{event.id}/competition/setup',rules()).status_code==400
        assert TournamentCompetition.query.count()==0


def test_live_updates_only_reach_authorized_competition_watchers(monkeypatch):
    from gamearena.competition import announce_change
    with app.app_context():
        admin,users,event=fixture(monkeypatch,2);register(users,event)
        outsider=player('socket_outsider');uid,eid=users[0].id,event.id
        member_client,other_client=client(users[0]),client(outsider)
    one=application.socketio.test_client(app,flask_test_client=member_client)
    other=application.socketio.test_client(app,flask_test_client=other_client)
    try:
        assert one.emit('watch_competition',{'tournament_id':eid},callback=True)=={'status':'ok'}
        assert other.emit('watch_competition',{'tournament_id':eid},callback=True)=={'status':'denied'}
        assert one.emit('watch_competition',{'tournament_id':True},callback=True)=={'status':'denied'}
        one.get_received();other.get_received()
        with app.app_context():announce_change(eid)
        events=[row for row in one.get_received() if row['name']=='competition_update']
        assert len(events)==1 and events[0]['args']==[{'tournament_id':eid}]
        assert not [row for row in other.get_received() if row['name']=='competition_update']
    finally:
        one.disconnect();other.disconnect()


def test_staff_queue_has_paused_match_and_rejects_players(monkeypatch):
    with app.app_context():
        admin,users,event=fixture(monkeypatch,2);check_in(admin,users,event);start(admin,event)
        match=TournamentMatch.query.one();match.status='disputed';db.session.commit()
        assert client(users[0]).get('/admin/competition/reviews').status_code==403
        page=client(admin).get('/admin/competition/reviews')
        assert page.status_code==200 and event.name in page.text and f'/match/{match.id}/play' in page.text
