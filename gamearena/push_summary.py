"""Bounded, latest-per-sender summaries; no cross-user notification data."""
from sqlalchemy import func
from gamearena.extensions import db
from gamearena.models import Notification,User,DirectMessage

def payload_for(record):
    base={'title':'GameArena','body':record.message,'url':record.target_url or '/notifications','id':record.id,'kind':record.kind,'owner_id':record.user_id}
    if record.kind not in {'messages','requests'}:return base
    query=Notification.query.filter_by(user_id=record.user_id,read_at=None,kind=record.kind)
    latest=query.with_entities(Notification.sender_id,func.max(Notification.id).label('latest_id')).group_by(Notification.sender_id).subquery()
    rows=Notification.query.join(latest,Notification.id==latest.c.latest_id).order_by(Notification.id.desc()).limit(7).all()
    senders={p.id:p.username for p in User.query.filter(User.id.in_([r.sender_id for r in rows if r.sender_id])).all()}
    previews={}
    if record.kind=='messages':
        for message in DirectMessage.query.filter(DirectMessage.recipient_id==record.user_id,DirectMessage.sender_id.in_(list(senders)),DirectMessage.deleted_at.is_(None)).order_by(DirectMessage.id.desc()).limit(200).all():
            previews.setdefault(message.sender_id,message.message)
    entries=[{'sender_id':r.sender_id,'name':senders.get(r.sender_id,'Player')[:40],'text':(previews.get(r.sender_id,r.message) if (r.target_url or '').startswith('/messages/') and record.kind=='messages' else r.message)[:90],'url':r.target_url or '/notifications'} for r in rows]
    total=query.count()
    base.update(title=('Messages' if record.kind=='messages' else 'Friend requests')+f' · {total} unread',
        body='\n'.join(e['name']+': '+e['text'] for e in entries),url='/chat' if record.kind=='messages' else '/chat?inbox=requests',
        group=record.kind,version=max([r.id for r in rows] or [record.id]),entries=entries)
    return base
