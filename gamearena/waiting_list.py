"""Free expressions of interest are separate from paid or confirmed entries."""
from flask import Blueprint,abort,redirect,url_for,request
from flask_login import current_user,login_required
from sqlalchemy.dialects.postgresql import insert
from gamearena.extensions import db
from gamearena.models import Tournament,TournamentInterest
from gamearena.tournament_launch import registration_ready
waiting_list=Blueprint('waiting_list',__name__)


@waiting_list.post('/tournament/<int:event_id>/waiting-list')
@login_required
def join(event_id):
    if current_user.suspended:abort(403)
    from app import consume_rate_limit,rate_limit_response
    wait=consume_rate_limit('waiting_list:'+str(current_user.id),20,3600)
    if wait:return rate_limit_response(wait)
    event=Tournament.query.filter_by(id=event_id).with_for_update().populate_existing().first_or_404()
    if event.status!='open':abort(409,description='This tournament is not accepting waiting-list signups.')
    if registration_ready(event):
        db.session.rollback();return redirect(url_for('join_tournament',tournament_id=event.id))
    if request.form.get('action')=='leave':
        TournamentInterest.query.filter_by(tournament_id=event.id,user_id=current_user.id).delete()
    elif request.form.get('action')=='join':
        db.session.execute(insert(TournamentInterest).values(tournament_id=event.id,user_id=current_user.id).on_conflict_do_nothing(index_elements=['tournament_id','user_id']))
    else:abort(400)
    db.session.commit()
    return redirect(url_for('join_tournament',tournament_id=event.id))
