"""Private, first-party active-player metrics based on observed activity."""
from datetime import datetime, timedelta, timezone
from flask import Blueprint, abort, current_app, render_template, request, session, jsonify
from flask_login import current_user, login_required
from sqlalchemy import Date, cast, func, select, text, union
from sqlalchemy.dialects.postgresql import insert
from .extensions import db
from .models import (User, UserActivityDay, UserTournament, DirectMessage,
    GlobalChatMessage, TournamentChatMessage, TournamentMatchChatMessage)

activity = Blueprint('activity', __name__)
LAGOS = timezone(timedelta(hours=1))


def activity_report(now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    today = now.astimezone(LAGOS).date()
    start = today - timedelta(days=29)
    lower = datetime.combine(start, datetime.min.time(), LAGOS).astimezone(timezone.utc).replace(tzinfo=None)
    upper = datetime.combine(today + timedelta(days=1), datetime.min.time(), LAGOS).astimezone(timezone.utc).replace(tzinfo=None)
    observations = [select(UserActivityDay.user_id.label('user_id'), UserActivityDay.activity_date.label('day')).where(
        UserActivityDay.activity_date.between(start, today))]
    for model, owner, timestamp in (
        (UserTournament, UserTournament.user_id, UserTournament.joined_at),
        (DirectMessage, DirectMessage.sender_id, DirectMessage.created_at),
        (GlobalChatMessage, GlobalChatMessage.user_id, GlobalChatMessage.created_at),
        (TournamentChatMessage, TournamentChatMessage.user_id, TournamentChatMessage.created_at),
        (TournamentMatchChatMessage, TournamentMatchChatMessage.user_id, TournamentMatchChatMessage.created_at),
    ):
        observations.append(select(owner.label('user_id'), cast(timestamp + text("INTERVAL '1 hour'"), Date).label('day'))
            .select_from(model).where(timestamp >= lower, timestamp < upper))
    observed = union(*observations).subquery()
    players = select(observed.c.user_id, observed.c.day).join(User, User.id == observed.c.user_id).where(User.is_admin.isnot(True)).subquery()
    daily = dict(db.session.execute(select(players.c.day, func.count(func.distinct(players.c.user_id))).group_by(players.c.day)).all())
    active = db.session.execute(select(User.id, User.username, func.max(players.c.day), func.count(func.distinct(players.c.day)))
        .join(players, players.c.user_id == User.id).group_by(User.id, User.username)
        .order_by(func.max(players.c.day).desc(), User.username)).all()
    weekly = db.session.execute(select(func.count(func.distinct(players.c.user_id))).where(players.c.day >= today - timedelta(days=6))).scalar() or 0
    total = db.session.execute(select(func.count(User.id)).where(User.is_admin.isnot(True))).scalar() or 0
    days = [{'date': start + timedelta(days=i), 'count': daily.get(start + timedelta(days=i), 0)} for i in range(30)]
    return dict(today=today, start=start, days=days, total=total, active_30=len(active), active_7=weekly,
        active_today=daily.get(today, 0), players=active, peak=max(d['count'] for d in days), scale=max([d['count'] for d in days] + [1]))


@activity.route('/admin/activity')
@login_required
def dashboard():
    if not current_user.is_admin:
        abort(403)
    return render_template('admin_activity.html', report=activity_report())


@activity.route('/admin/activity/live')
@login_required
def live_report():
    if not current_user.is_admin:
        abort(403)
    response = jsonify(html=render_template('_activity_report.html', report=activity_report()))
    response.headers['Cache-Control'] = 'private, no-store'
    return response


def notify_activity_changed():
    socket = current_app.extensions.get('socketio')
    if socket:
        socket.emit('activity_updated', {}, room='admin:activity')


def record_player_visit(response):
    # Automatic polling/static requests must not keep absent players active.
    if response.status_code >= 400 or request.method not in ('GET', 'POST'):
        return response
    if not current_user.is_authenticated or current_user.is_admin or current_user.suspended:
        return response
    if request.method == 'GET' and not (
        request.headers.get('Sec-Fetch-Dest') == 'document' or
        (not request.headers.get('Sec-Fetch-Dest') and 'text/html' in request.headers.get('Accept', ''))
    ):
        return response
    if (request.path.startswith(('/static/', '/socket.io/', '/admin/', '/api/', '/push/', '/notifications/'))
        or request.path.endswith('/read')):
        return response
    day = datetime.now(timezone.utc).astimezone(LAGOS).date()
    marker = str(current_user.id) + ':' + day.isoformat()
    if session.get('_activity_day') == marker:
        return response
    try:
        # Separate transaction: analytics never commits a route's pending work.
        with db.engine.begin() as connection:
            result = connection.execute(insert(UserActivityDay).values(user_id=current_user.id, activity_date=day)
                .on_conflict_do_nothing(index_elements=['user_id', 'activity_date']))
        session['_activity_day'] = marker
        if result.rowcount:
            notify_activity_changed()
    except Exception:
        current_app.logger.warning('Daily activity tracking unavailable; request completed normally.')
    return response


def init_activity(app):
    app.register_blueprint(activity)
    app.after_request(record_player_visit)
