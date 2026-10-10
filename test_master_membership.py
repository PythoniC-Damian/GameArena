"""Membership authorization, expiry, private bookmarks and idempotent reminders."""
from datetime import datetime, timedelta
from app import app, db, User, UserSettings, TournamentMatch, TournamentStat, UserTournament, Notification
from gamearena.models import SavedTournament
from gamearena.pro import deliver_due_reminders, performance_summary
from test_interface_contracts import player, client, token, event

def activate(user, days=30):
    user.master_expires_at = datetime.utcnow()+timedelta(days=days)
    db.session.commit()

def headers(viewer):
    return {'Accept':'application/json','X-CSRFToken':token(viewer.get('/pro'))}

def test_membership_authorization_and_expiry():
    with app.app_context():
        owner=player('master_owner'); viewer=client(owner); h=headers(viewer)
        payload={'frame':'green','profile_theme':'forest'}
        assert viewer.post('/pro/appearance',json=payload,headers=h).status_code==403
        activate(owner)
        assert viewer.post('/pro/appearance',json=payload,headers=h).status_code==200
        db.session.refresh(owner)
        assert owner.master_frame=='green' and owner.master_profile_theme=='forest'
        assert 'ga-master-badge' in viewer.get(f'/players/{owner.id}').text
        assert viewer.post('/pro/appearance',json={'frame':'<script>','profile_theme':'forest'},headers=h).status_code==400
        assert viewer.post('/pro/appearance',json=payload).status_code==400
        activate(owner, -1)
        assert viewer.post('/pro/appearance',json=payload,headers=h).status_code==403
        assert 'aria-label="Master membership"' not in viewer.get(f'/players/{owner.id}').text
        assert not owner.master_active
    assert app.test_client().get('/pro').status_code==302

def test_bookmarks_private_and_idempotent():
    with app.app_context():
        owner,other=player('saved_owner'),player('saved_other'); activate(owner)
        tournament=event('Private saved event'); tournament.match_time=datetime.utcnow()+timedelta(days=1);db.session.commit()
        viewer=client(owner); h=headers(viewer); url=f'/pro/saved/{tournament.id}'
        for _ in range(2): assert viewer.post(url,json={'action':'save'},headers=h).json['saved']
        assert SavedTournament.query.count()==1
        assert viewer.post(url,json={'action':'reminder','enabled':True},headers=h).json['reminder']
        assert 'Private saved event' in viewer.get('/pro').text
        assert 'Private saved event' not in client(other).get('/pro').text
        activate(owner,-1)
        assert viewer.post(url,json={'action':'save'},headers=h).status_code==403
        assert viewer.post(url,json={'action':'remove'},headers=h).json['saved'] is False
        assert SavedTournament.query.count()==0

def test_reminder_schedule_validation_and_preferences():
    with app.app_context():
        owner=player('remind_owner');activate(owner); tournament=event(); viewer=client(owner);h=headers(viewer);url=f'/pro/saved/{tournament.id}'
        assert viewer.post(url,json={'action':'reminder','enabled':True},headers=h).status_code==409
        assert viewer.post(url,json={'action':'reminder','enabled':'true'},headers=h).status_code==400
        now=datetime.utcnow();tournament.match_time=now+timedelta(minutes=30);db.session.commit()
        viewer.post(url,json={'action':'reminder','enabled':True},headers=h)
        preferences=UserSettings(user_id=owner.id,tournament_notifications=False); db.session.add(preferences); db.session.commit()
        assert deliver_due_reminders(now)==[]
        preferences.tournament_notifications=True;db.session.commit()
        assert len(deliver_due_reminders(now))==1
        assert deliver_due_reminders(now)==[]
        assert Notification.query.count()==1
        assert Notification.query.first().target_url==f'/tournament/{tournament.id}'
        tournament.match_time=now+timedelta(minutes=45);db.session.commit()
        assert len(deliver_due_reminders(now))==1
        assert Notification.query.count()==2
        tournament.match_time=now+timedelta(minutes=50);activate(owner,-1)
        assert deliver_due_reminders(now)==[]

def test_statistics_include_only_recent_confirmed_results():
    with app.app_context():
        owner,other=player('stats_master'),player('stats_other'); now=datetime.utcnow()
        tournament=event('Recent finished event',status='finished');tournament.match_time=now-timedelta(days=2)
        old=event('Old finished event',status='finished');old.match_time=now-timedelta(days=40)
        db.session.add_all([UserTournament(user_id=owner.id,tournament_id=tournament.id,payment_status='free',joined_at=now-timedelta(days=3)),TournamentStat(user_id=owner.id,tournament_id=tournament.id,rank=2),TournamentStat(user_id=owner.id,tournament_id=old.id,rank=1)])
        for status,age,winner in [('confirmed',2,owner.id),('confirmed',40,owner.id),('disputed',1,owner.id),('confirmed',1,other.id)]:
            db.session.add(TournamentMatch(tournament_id=tournament.id,player_one_user_id=owner.id,player_two_user_id=other.id,status=status,winner_user_id=winner,updated_at=now-timedelta(days=age)))
        db.session.commit()
        assert performance_summary(owner.id,now)==dict(matches=2,wins=1,losses=1,win_rate=50,tournaments=1,podiums=1)
        activate(owner)
        page=client(owner).get('/profile')
        assert page.status_code==200 and 'Last 30 days' in page.text
        assert client(owner).get('/pro').status_code==200


def test_price_symbol_and_suspended_members_are_not_entitled():
    from app import format_naira
    assert format_naira(1000) == '\u20a61,000'
    with app.app_context():
        owner=player('suspended_master');activate(owner);viewer=client(owner);h=headers(viewer)
        owner.suspended=True;db.session.commit()
        assert viewer.post('/pro/appearance',json={'frame':'blue','profile_theme':'arena'},headers=h).status_code==401
