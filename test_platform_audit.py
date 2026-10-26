"""Confirmed audit gaps: prices, scheduling, artwork, private support and UI truth."""
import io, importlib
from datetime import datetime,timedelta
from alembic.operations import Operations
from alembic.migration import MigrationContext
from PIL import Image
import app as application
from app import app,db
from gamearena.models import (User,Tournament,UserTournament,WalletTransaction,CosmeticOwnership,PlatformSetting,UserReport,SupportReply,Notification,TournamentCompetition,TournamentMatch)
from gamearena.market import CATALOG
from gamearena.tournament_launch import registration_ready,public_status
from test_interface_contracts import player,client,token


def admin_user(name='platform_owner'):
    owner=player(name);owner.is_admin=True;db.session.commit();return owner,client(owner)


def post(viewer,url,data,source='/admin/platform'):
    return viewer.post(url,data=dict(data,csrf_token=token(viewer.get(source))))


def catalogue_fields():
    result={'section':'shop'}
    for key,item in CATALOG.items():
        for field in ('name','description','price'):result[field+'__'+key]=str(item[field])
    return result


def png():
    buffer=io.BytesIO();Image.new('RGB',(640,360),'#123544').save(buffer,'PNG');buffer.seek(0);return buffer,'art.png'


def test_admin_prices_apply_to_checkout_and_stale_quotes_cannot_debit():
    with app.app_context():
        admin,staff=admin_user();buyer=player('priced_buyer');buyer.wallet_balance=1000;db.session.commit();viewer=client(buyer)
        assert viewer.get('/admin/platform').status_code==403
        data=catalogue_fields();data['price__solar-nameplate']='75';data['name__solar-nameplate']='Solar Gold'
        assert post(staff,'/admin/platform',data).status_code==302
        page=viewer.get('/shop');assert 'Solar Gold' in page.text and '75 GP' in page.text
        assert viewer.post('/shop/solar-nameplate/buy',data={'csrf_token':token(page),'price_gp':'250','confirm':'yes'}).status_code==400
        assert viewer.post('/shop/solar-nameplate/buy',data={'csrf_token':token(page),'price_gp':'75','confirm':'yes'}).status_code==302
        db.session.refresh(buyer);assert buyer.wallet_balance==925
        ledger=WalletTransaction.query.filter_by(user_id=buyer.id).one();assert ledger.amount==75 and ledger.account_name=='Solar Gold'
        data['price__solar-nameplate']='-1'
        assert post(staff,'/admin/platform',data).status_code==400
        assert PlatformSetting.query.get('shop_catalog').value['solar-nameplate']['price']==75
        assert staff.post('/admin/platform',data=data).status_code==400
        assert post(staff,'/shop/solar-nameplate/buy',{},source='/shop').status_code==302
        assert WalletTransaction.query.count()==1


def test_admin_creates_unscheduled_event_with_real_artwork_and_edits_terms():
    with app.app_context():
        admin,staff=admin_user('event_editor')
        values=dict(name='Launch Room Cup',game='Free Fire',description='Launch event',rules='Solo room: published points for placement and eliminations. Review disputed evidence.',eligibility='Mobile players with their own Free Fire account.',event_format='battle_royale',payout_method='organizer_bank',entry_fee='200',prize_pool='1000',max_participants='4',first_place='1000',second_place='0',third_place='0',match_time='',images=[png(),png(),png()])
        response=post(staff,'/admin/create-tournament',values,source='/admin/create-tournament');assert response.status_code==302,response.text
        event=Tournament.query.filter_by(name='Launch Room Cup').one();assert event.match_time is None and len(event.artwork)==3
        assert public_status(event)=='To be decided' and not registration_ready(event)
        public=app.test_client().get(f'/tournament/{event.id}');assert public.status_code==200 and 'To be decided' in public.text
        image=app.test_client().get('/media/tournament-artwork/'+event.artwork[0].id+'.webp');assert image.status_code==200 and image.mimetype=='image/webp'
        values.pop('images');values['match_time']=(datetime.utcnow()+timedelta(days=3)).strftime('%Y-%m-%d %H:%M');values['status']='open'
        assert post(staff,f'/admin/tournaments/{event.id}/edit',values,source=f'/admin/tournaments/{event.id}/edit').status_code==302
        db.session.refresh(event);assert registration_ready(event) and len(event.artwork)==3
        values['match_time']=''
        assert post(staff,f'/admin/tournaments/{event.id}/edit',values,source=f'/admin/tournaments/{event.id}/edit').status_code==302
        db.session.refresh(event);assert event.match_time is None and not registration_ready(event)
        values.update(images=[(io.BytesIO(b'<svg onload="bad"/>'),'fake.png')],name='Bad upload')
        assert post(staff,'/admin/create-tournament',values,source='/admin/create-tournament').status_code==400
        assert not Tournament.query.filter_by(name='Bad upload').first()


def test_expired_and_incomplete_events_cannot_take_entry_payments():
    with app.app_context():
        buyer=player('blocked_entry');viewer=client(buyer)
        event=Tournament(name='Unscheduled',game='Free Fire',entry_fee=200,prize=1000,max_participants=4,status='open')
        db.session.add(event);db.session.commit()
        assert not registration_ready(event)
        assert viewer.get(f'/join-tournament/{event.id}').status_code in (302,409)
        assert not UserTournament.query.filter_by(tournament_id=event.id).first()
        event.match_time=datetime.utcnow()-timedelta(days=1);db.session.commit()
        assert public_status(event)=='Registration closed'
        event.match_time=datetime.utcnow()+timedelta(days=1);db.session.commit()
        assert not registration_ready(event)
        event.first_place='1000';event.second_place='0';event.third_place='0';event.rules='Solo room, verified final scoreboard and published points.';event.payout_method='organizer_bank';db.session.commit()
        assert registration_ready(event)


def test_private_support_threads_replies_status_and_account_data(monkeypatch):
    monkeypatch.setattr(application,'create_and_emit_notification',lambda *a,**kw:None)
    with app.app_context():
        owner=player('support_owner');other=player('support_other');admin,staff=admin_user('support_staff');viewer=client(owner)
        assert post(viewer,'/support',{'reason':'My top-up needs review.'},source='/support').status_code==302
        ticket=UserReport.query.filter_by(reporter_id=owner.id).one()
        url=f'/support/tickets/{ticket.id}'
        assert client(other).get(url).status_code==404
        assert post(staff,url,{'message':'We are checking the transaction.','resolve':'yes'},source=url).status_code==302
        assert 'We are checking the transaction.' in viewer.get(url).text
        db.session.refresh(ticket);assert ticket.status=='resolved'
        assert post(viewer,url,{'message':'Thanks, please check again.'},source=url).status_code==302
        db.session.refresh(ticket);assert ticket.status=='pending' and SupportReply.query.count()==2
        export=viewer.get('/account/export');assert export.status_code==200 and export.json['profile']['email']==owner.email
        assert 'password' not in export.json['profile'] and 'no-store' in export.headers['Cache-Control']
        assert post(viewer,'/account/requests',{'kind':'account_closure','confirmed':'yes'},source='/support').status_code==302
        assert UserReport.query.filter_by(reporter_id=owner.id,content_type='account_closure').count()==1
        assert post(viewer,'/account/requests',{'kind':'account_closure','confirmed':'yes'},source='/support').status_code==302
        assert UserReport.query.filter_by(reporter_id=owner.id,content_type='account_closure').count()==1
        assert not owner.suspended


def test_notification_filters_registration_copy_and_locked_achievements():
    with app.app_context():
        owner=player('audit_ui');other=player('audit_private');viewer=client(owner)
        for index in range(35):db.session.add(Notification(user_id=owner.id,message='Wallet \\u00e2\\u201a\\u00a6'.encode().decode('unicode_escape')+'300',category='wallet'))
        db.session.add(Notification(user_id=owner.id,message='Chat only message',category='chat'))
        db.session.add(Notification(user_id=other.id,message='Secret unrelated account',category='wallet'));db.session.commit()
        page=viewer.get('/notifications?category=wallet&unread=1');assert page.status_code==200
        assert 'Chat only message' not in page.text and 'Secret unrelated account' not in page.text
        assert '\u20a6300' in page.text and 'Next' in page.text
        preview=viewer.get('/notifications/preview').json
        assert any('\u20a6300' in item['message'] for item in preview['notifications'])
        assert viewer.get('/notifications?category=invalid').status_code==400
        page=app.test_client().get('/register');assert 'type="email"' in page.text and 'letters, numbers and underscores' in page.text
        page=app.test_client().get('/verify-email');assert 'We sent a verification code' not in page.text
        from gamearena.models import Achievement,UserAchievement
        achievement=Achievement(key='audit_first_win',name='First Win',description='Win a confirmed match.',rule_type='wins',threshold=1,hidden=False)
        db.session.add(achievement);db.session.flush();db.session.add(UserAchievement(user_id=owner.id,achievement_id=achievement.id,progress=0));db.session.commit()
        page=app.test_client().get(f'/players/{owner.id}');assert 'Email verified' not in page.text and f'@{owner.username}' not in page.text
        assert 'Locked' in page.text
        home=app.test_client().get('/');assert 'data-pro-welcome' not in home.text
        shop=viewer.get('/shop');assert 'data-collection="emerald-bundle"' in shop.text and 'data-collection="neon-bundle"' in shop.text


def test_migration_preserves_accepted_event_dates_and_existing_prices():
    with app.app_context():
        admin,_=admin_user('migration_admin');old=datetime.utcnow()-timedelta(days=1)
        empty=Tournament(name='Unused old date',game='Free Fire',match_time=old,status='open')
        accepted=Tournament(name='Accepted date',game='Free Fire',match_time=old,status='open')
        db.session.add_all([empty,accepted]);db.session.flush()
        db.session.add(UserTournament(user_id=admin.id,tournament_id=accepted.id,payment_status='paid'));db.session.commit()
        ids=empty.id,accepted.id
        db.session.commit()
        db.session.remove()
        with db.engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                migration=importlib.import_module('migrations.versions.20261024_platform_controls');migration.upgrade();migration.upgrade()
        db.session.expire_all()
        assert db.session.get(Tournament,ids[0]).match_time is None
        assert db.session.get(Tournament,ids[1]).match_time==old


def test_admin_setup_can_add_a_bracket_to_an_unused_event():
    with app.app_context():
        admin,staff=admin_user('bracket_editor')
        event=Tournament(name='New bracket',game='eFootball Mobile',entry_fee=200,prize=1000,max_participants=4,status='open')
        db.session.add(event);db.session.commit()
        url=f'/admin/tournaments/{event.id}/edit'
        values=dict(name=event.name,game=event.game,description='Four player cup',rules='One ten-minute match, extra time and penalties for a draw.',no_show_policy='Allow five minutes to join, then staff review the evidence.',eligibility='Mobile players',event_format='single_elimination_1v1',payout_method='organizer_bank',entry_fee='200',prize_pool='1000',max_participants='4',first_place='1000',second_place='0',third_place='0',match_time='',status='open')
        response=post(staff,url,values,source=url)
        assert response.status_code==302,response.text
        db.session.expire_all()
        config=db.session.get(TournamentCompetition,event.id)
        assert config and config.phase=='registration'
        assert db.session.get(Tournament,event.id).event_format=='single_elimination_1v1'
