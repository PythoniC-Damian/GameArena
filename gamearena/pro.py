"""Master features; entitlement is checked on every protected write."""
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, jsonify, abort
from flask_login import current_user, login_required
from sqlalchemy import or_
from sqlalchemy.orm import joinedload
from gamearena.extensions import db
from gamearena.models import User, UserSettings, Tournament, TournamentMatch, TournamentStat, UserTournament, SavedTournament, Notification, MasterSubscription, MasterPayment

pro = Blueprint('pro', __name__)
FRAMES = {'blue', 'green', 'classic'}
THEMES = {'arena', 'ocean', 'forest'}

def require_master():
    if not current_user.master_active or current_user.suspended:
        abort(403, description='An active Master membership is required.')

def performance_summary(user_id, now=None):
    now = now or datetime.utcnow()
    since = now - timedelta(days=30)
    matches = TournamentMatch.query.filter(TournamentMatch.status == 'confirmed', TournamentMatch.winner_user_id.isnot(None), TournamentMatch.updated_at >= since, TournamentMatch.updated_at <= now, or_(TournamentMatch.player_one_user_id == user_id, TournamentMatch.player_two_user_id == user_id))
    played = matches.count()
    wins = matches.filter(TournamentMatch.winner_user_id == user_id).count()
    entered = UserTournament.query.filter(UserTournament.user_id == user_id, UserTournament.payment_status.in_(['paid', 'free']), UserTournament.joined_at >= since, UserTournament.joined_at <= now).count()
    # Use dated finished tournaments; undated results are excluded rather than guessed.
    results = TournamentStat.query.join(Tournament).filter(TournamentStat.user_id == user_id, Tournament.status == 'finished', Tournament.match_time >= since, Tournament.match_time <= now)
    podiums = results.filter(TournamentStat.rank.between(1, 3)).count()
    return dict(matches=played, wins=wins, losses=played-wins, win_rate=round(wins/played*100) if played else 0, tournaments=entered, podiums=podiums)

@pro.route('/pro')
@login_required
def membership():
    saved = SavedTournament.query.options(joinedload(SavedTournament.tournament)).filter_by(user_id=current_user.id).order_by(SavedTournament.created_at.desc()).all()
    from gamearena.master_billing import configured
    subscription = MasterSubscription.query.filter_by(user_id=current_user.id).order_by(MasterSubscription.id.desc()).first()
    pending_payment = MasterPayment.query.filter_by(subscription_id=subscription.id, status='pending').first() if subscription else None
    return render_template('pro.html', saved_tournaments=saved, performance=performance_summary(current_user.id) if current_user.master_active else None, subscription=subscription, pending_payment=pending_payment, billing_enabled=configured())

@pro.route('/pro/appearance', methods=['POST'])
@login_required
def appearance():
    require_master()
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict) or payload.get('frame') not in FRAMES or payload.get('profile_theme') not in THEMES:
        return jsonify(error='Choose a valid frame and profile theme.'), 400
    current_user.master_frame = payload['frame']
    current_user.master_profile_theme = payload['profile_theme']
    db.session.commit()
    return jsonify(frame=current_user.master_frame, profile_theme=current_user.master_profile_theme, message='Profile appearance saved.')

@pro.route('/pro/saved/<int:tournament_id>', methods=['POST'])
@login_required
def save_tournament(tournament_id):
    tournament = db.get_or_404(Tournament, tournament_id)
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict) or payload.get('action') not in {'save', 'remove', 'reminder'}:
        return jsonify(error='Choose a saved-tournament action.'), 400
    action = payload['action']
    if action != 'remove': require_master()
    if action == 'reminder' and type(payload.get('enabled')) is not bool:
        return jsonify(error='Choose whether to enable the reminder.'), 400
    if action == 'reminder' and payload['enabled'] and (not tournament.match_time or tournament.match_time <= datetime.utcnow() or tournament.status not in {'open', 'live', 'ongoing'}):
        return jsonify(error='A future tournament start time is needed for a reminder.'), 409
    # Serialise actions for one player and make repeated save requests idempotent.
    db.session.execute(db.select(User).where(User.id == current_user.id).with_for_update())
    row = SavedTournament.query.filter_by(user_id=current_user.id, tournament_id=tournament_id).first()
    if action == 'remove':
        if row: db.session.delete(row)
        db.session.commit()
        return jsonify(saved=False, reminder=False, message='Tournament removed from saved events.')
    if not row:
        row = SavedTournament(user_id=current_user.id, tournament_id=tournament_id)
        db.session.add(row)
    if action == 'reminder': row.reminder_enabled = payload['enabled']
    db.session.commit()
    return jsonify(saved=True, reminder=row.reminder_enabled, message='Reminder updated.' if action == 'reminder' else 'Tournament saved.')

def deliver_due_reminders(now=None, limit=200):
    """Run every minute. Lock each bookmark; notification and sent marker commit together."""
    now = now or datetime.utcnow()
    rows = SavedTournament.query.join(Tournament).join(User).filter(SavedTournament.reminder_enabled.is_(True), User.master_expires_at > now, User.suspended.is_(False), Tournament.status.in_(['open', 'live', 'ongoing']), Tournament.match_time > now, Tournament.match_time <= now+timedelta(hours=1), or_(SavedTournament.reminded_for.is_(None), SavedTournament.reminded_for != Tournament.match_time)).order_by(Tournament.match_time).limit(limit).with_for_update(of=SavedTournament, skip_locked=True).all()
    notifications = []
    for row in rows:
        preferences = UserSettings.query.filter_by(user_id=row.user_id).first()
        if preferences and not preferences.tournament_notifications: continue
        notification = Notification(user_id=row.user_id, category='tournament', message=f'{row.tournament.name[:350]} starts within an hour. Check the tournament details.', target_url=f'/tournament/{row.tournament_id}')
        db.session.add(notification)
        row.reminded_for = row.tournament.match_time
        notifications.append(notification)
    db.session.commit()
    return notifications
