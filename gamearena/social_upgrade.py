"""Profile friends and authenticated acknowledgements from visible app tabs."""
from datetime import datetime
from flask import Blueprint,abort,current_app,jsonify,request,render_template
from flask_login import current_user,login_required
from sqlalchemy import or_,and_,case
from gamearena.extensions import db
from gamearena.models import User,UserSettings,UserBlock,PlayerConnection,Notification

social=Blueprint('social',__name__)

def friend_query(user_id):
    return PlayerConnection.query.filter(PlayerConnection.status=='accepted',or_(PlayerConnection.low_id==user_id,PlayerConnection.high_id==user_id))

def friend_count(user_id):
    return friend_query(user_id).count()

@social.post('/notifications/<int:notification_id>/seen-live')
@login_required
def seen_live(notification_id):
    row=Notification.query.filter_by(id=notification_id,user_id=current_user.id,kind='messages').first_or_404()
    if not row.read_at:row.read_at=datetime.utcnow();db.session.commit()
    from app import socketio,get_unread_notification_count
    unread=get_unread_notification_count(current_user.id)
    socketio.emit('notification_unread_count',{'unread':unread},room=f'user:{current_user.id}')
    response=jsonify(ok=True,unread=unread);response.headers['Cache-Control']='no-store'
    return response

@social.get('/players/<int:user_id>/friends')
@login_required
def friends(user_id):
    from app import users_have_block
    owner=User.query.get_or_404(user_id)
    settings=UserSettings.query.filter_by(user_id=user_id).first()
    if owner.suspended or users_have_block(current_user.id,user_id) or (user_id!=current_user.id and settings and not settings.profile_public):abort(404)
    try:offset=min(100000,max(0,int(request.args.get('offset',0))))
    except ValueError:abort(400)
    partner=case((PlayerConnection.low_id==user_id,PlayerConnection.high_id),else_=PlayerConnection.low_id)
    ids=friend_query(user_id).with_entities(partner.label('friend_id')).subquery()
    blocked=db.session.query(UserBlock.blocked_id).filter_by(blocker_id=current_user.id).union(db.session.query(UserBlock.blocker_id).filter_by(blocked_id=current_user.id))
    query=User.query.join(ids,User.id==ids.c.friend_id).outerjoin(UserSettings,UserSettings.user_id==User.id).filter(User.suspended.is_(False),~User.id.in_(blocked),or_(UserSettings.profile_public.is_(True),UserSettings.user_id.is_(None),User.id==current_user.id)).order_by(User.username,User.id)
    players=query.offset(offset).limit(21).all();more=len(players)>20;players=players[:20]
    player_ids=[p.id for p in players]
    relationships=PlayerConnection.query.filter(or_(and_(PlayerConnection.low_id==current_user.id,PlayerConnection.high_id.in_(player_ids)),and_(PlayerConnection.high_id==current_user.id,PlayerConnection.low_id.in_(player_ids)))).all() if player_ids else []
    states={r.high_id if r.low_id==current_user.id else r.low_id:r for r in relationships}
    response=jsonify(html=render_template('_friend_rows.html',friends=players,friend_states=states,now=datetime.utcnow()),count=friend_count(user_id),next_offset=offset+20 if more else None)
    response.headers['Cache-Control']='no-store'
    return response

def init_social(app):
    app.register_blueprint(social)
    app.jinja_env.globals['friend_count']=friend_count
