"""Publish reviewable event terms before taking entries; never invent dates or funding."""
import hashlib
import json
import re
from datetime import datetime
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import case
from sqlalchemy.dialects.postgresql import insert
from gamearena.extensions import db
from gamearena.gp import NAIRA_PER_GP, gp_label
from gamearena.models import (Tournament, TournamentLaunchPlan, TournamentVisit,
    TournamentMatch, TournamentCheckIn, UserTournament, OrganizerFinance)

launch = Blueprint('launch', __name__)
PREPARING = 'This event is in preparation. Registration opens after its schedule, rules and prizes are confirmed.'


def prize_amount(value):
    """Published placement amounts are whole GP; do not guess arbitrary text."""
    text = str('' if value is None else value).strip()
    if not re.fullmatch(r'(?:\d+|\d{1,3}(?:,\d{3})+)(?:\s*GP)?', text, re.I):
        return None
    return int(re.sub(r'[,\s]|GP', '', text, flags=re.I))


def signature(event, plan):
    config = event.competition
    values = [event.name, event.game, event.entry_fee, event.prize, event.max_participants,
        str(event.match_time), event.first_place, event.second_place, event.third_place,
        config.game_rules if config else None, config.no_show_policy if config else None,
        str(plan.registration_closes_at), plan.eligibility, plan.rules, plan.cancellation_policy, plan.funding_note]
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()


def preparation_issues(event, plan=None):
    from gamearena.competition import supports_bracket
    plan = plan or event.launch_plan
    issues = []
    if not event.match_time:
        issues.append('Confirm a start date and time in UTC.')
    if supports_bracket(event.game) and not event.competition:
        issues.append('Publish the 1v1 competition format and match rules before accepting entries.')
    amounts = [prize_amount(getattr(event, key)) for key in ('first_place','second_place','third_place')]
    if event.prize:
        if None in amounts or sum(a or 0 for a in amounts) != event.prize:
            issues.append('Publish whole GP amounts for all three places (use 0 for no award), totalling the prize pool.')
        if event.competition and amounts[2]:
            issues.append('Use 0 GP for third place: this knockout format has no third-place match.')
    elif any(amount for amount in amounts if amount is not None):
        issues.append('A zero prize pool cannot advertise a non-zero placement award.')
    if event.entry_fee < 0 or event.prize < 0 or event.max_participants < 1:
        issues.append('Set valid entry, prize and capacity amounts.')
    if not plan:
        issues.append('Publish eligibility, registration deadline, game rules, cancellation terms and a prize funding commitment.')
    elif not event.match_time or plan.registration_closes_at > event.match_time:
        issues.append('Registration must close on or before the start time.')
    return issues


def registration_ready(event):
    plan = event.launch_plan
    if event.status != 'open' or not event.match_time or event.match_time <= datetime.utcnow():
        return False
    # The launch checklist is optional for existing open events. Published terms
    # still apply once an organiser has explicitly confirmed a launch plan.
    if plan is None:
        if event.entry_fee:
            amounts = [prize_amount(getattr(event,key)) for key in ('first_place','second_place','third_place')]
            rules = event.rules or (event.competition.game_rules if event.competition else '')
            if not rules or None in amounts or sum(amounts) != event.prize or event.payout_method == 'unconfirmed':
                return False
        return True
    return bool(not preparation_issues(event, plan)
        and plan.snapshot == signature(event, plan)
        and datetime.utcnow() < plan.registration_closes_at
        and datetime.utcnow() < event.match_time)


def public_status(event):
    if event.status != 'open':
        return event.status.replace('_', ' ').capitalize()
    if not event.match_time:
        return 'To be decided'
    if event.match_time <= datetime.utcnow():
        return 'Registration closed'
    plan = event.launch_plan
    if plan and (datetime.utcnow() >= plan.registration_closes_at or
                 event.match_time and datetime.utcnow() >= event.match_time):
        return 'Registration closed'
    return 'Open' if registration_ready(event) else 'In preparation'


def track_visit(event_id, intent=False):
    from gamearena.privacy_controls import analytics_allowed
    if not analytics_allowed(): return
    if not current_user.is_authenticated or current_user.is_admin or current_user.suspended:
        return
    statement = insert(TournamentVisit).values(tournament_id=event_id,
        user_id=current_user.id, viewed_at=datetime.utcnow(), join_requested=intent)
    if intent:
        statement = statement.on_conflict_do_update(index_elements=['tournament_id','user_id'], set_={'join_requested':True})
    else:
        statement = statement.on_conflict_do_nothing(index_elements=['tournament_id','user_id'])
    db.session.execute(statement)
    db.session.commit()


@launch.app_context_processor
def helpers():
    return dict(registration_ready=registration_ready, event_public_status=public_status,
        preparation_issues=preparation_issues, gp_naira_rate=NAIRA_PER_GP,
        published_prize=published_prize)


def published_prize(value):
    amount = prize_amount(value)
    return gp_label(amount) if amount is not None else (value or 'Not published')


@launch.route('/tournament/<int:tournament_id>/launch', methods=['GET','POST'])
@login_required
def review(tournament_id):
    from gamearena.competition import can_manage, event_lock, limit
    event = event_lock(tournament_id)
    if not can_manage(event): abort(403)
    plan = event.launch_plan
    errors = []
    has_entries = UserTournament.query.filter(
        UserTournament.tournament_id == event.id,
        db.or_(UserTournament.payment_status.in_(('paid','free')),
               db.and_(UserTournament.payment_status == 'pending', UserTournament.transaction_ref.isnot(None)))).first() is not None
    blocked_reason = None
    if has_entries:
        blocked_reason = 'Entries or pending payments already exist. Launch terms cannot be replaced. Continue with the agreed rules, or arrange cancellation and refunds before creating a replacement event.'
    elif event.status != 'open':
        blocked_reason = 'Registration is not open. If check-in was opened before anyone joined, reopen registration from the organiser round controls first. Live or closed events cannot publish new launch terms.'
    can_reopen = bool(not has_entries and event.competition and event.competition.phase == 'check_in'
        and event.status == 'ongoing' and not TournamentMatch.query.filter_by(tournament_id=event.id).first())
    def render_review(status=200):
        finance = db.session.get(OrganizerFinance, event.id)
        return render_template('tournament_launch.html', tournament=event, plan=plan, errors=errors,
            blocked_reason=blocked_reason, can_reopen=can_reopen,
            funded=finance and finance.state=='funded' and finance.prize_reserved >= event.prize,
            entry_ceiling=event.entry_fee*event.max_participants,
            funding_gap=max(0,event.prize-event.entry_fee*event.max_participants)), status
    if request.method == 'POST':
        limit()
        if blocked_reason:
            db.session.rollback()
            return render_review(409)
        try:
            deadline = datetime.strptime(request.form.get('registration_closes_at',''), '%Y-%m-%dT%H:%M')
        except ValueError:
            deadline = None
            errors.append('Choose a registration deadline in UTC.')
        fields = {}
        for key, minimum, maximum in (('eligibility',10,1000),('rules',40,10000),
                ('cancellation_policy',20,2000),('funding_note',10,1000)):
            fields[key] = request.form.get(key,'').strip()
            if not minimum <= len(fields[key]) <= maximum:
                errors.append('Complete '+key.replace('_',' ')+f' ({minimum}–{maximum} characters).')
        if request.form.get('launch_ack') != 'yes':
            errors.append('Acknowledge the event and prize commitments.')
        if not event.match_time or event.match_time <= datetime.utcnow() or deadline and deadline <= datetime.utcnow():
            errors.append('Start and registration deadline must be in the future.')
        if not errors:
            candidate = TournamentLaunchPlan(tournament_id=event.id, registration_closes_at=deadline,
                reviewed_by=current_user.id, **fields)
            errors.extend(preparation_issues(event, candidate))
            if not errors:
                if not plan:
                    plan = candidate
                    db.session.add(plan)
                else:
                    plan.registration_closes_at = deadline
                    for key, value in fields.items(): setattr(plan,key,value)
                    plan.reviewed_by = current_user.id
                plan.reviewed_at = datetime.utcnow()
                plan.snapshot = signature(event, plan)
                db.session.commit()
                flash('Launch checklist complete. Registration is open until the published deadline.', 'success')
                return redirect(url_for('tournament_details',tournament_id=event.id))
        db.session.rollback()
    return render_review()


@launch.route('/admin/tournament-funnel')
@login_required
def funnel():
    if not current_user.is_admin or current_user.suspended: abort(403)
    # All aggregation is bounded to the displayed events; no participant details are exposed.
    page = Tournament.query.order_by(Tournament.id.desc()).paginate(
        page=max(1,request.args.get('page',1,type=int) or 1),per_page=25,error_out=False)
    ids = [e.id for e in page.items]
    views = {tid:(count,intents or 0) for tid,count,intents in db.session.query(TournamentVisit.tournament_id,
        db.func.count(),db.func.sum(case((TournamentVisit.join_requested.is_(True),1),else_=0)))
        .filter(TournamentVisit.tournament_id.in_(ids)).group_by(TournamentVisit.tournament_id).all()}
    entries = dict(db.session.query(UserTournament.tournament_id,db.func.count()).filter(
        UserTournament.tournament_id.in_(ids),UserTournament.payment_status.in_(('paid','free'))).group_by(UserTournament.tournament_id).all())
    checkins = dict(db.session.query(TournamentCheckIn.tournament_id,db.func.count()).filter(
        TournamentCheckIn.tournament_id.in_(ids)).group_by(TournamentCheckIn.tournament_id).all())
    matches = dict(db.session.query(TournamentMatch.tournament_id,db.func.count()).filter(
        TournamentMatch.tournament_id.in_(ids),TournamentMatch.status=='confirmed').group_by(TournamentMatch.tournament_id).all())
    return render_template('tournament_funnel.html', pagination=page,views=views,entries=entries,checkins=checkins,matches=matches)


def validate_admin_terms(form):
    if not 0 <= int(form.entry_fee.data) <= 10000000 or not 0 <= int(form.prize_pool.data) <= 10000000:
        raise ValueError('Entry fee and prize pool must be between 0 and 10,000,000 GP.')
    places = [form.first_place.data,form.second_place.data,form.third_place.data]
    if any(str(value or '').strip() for value in places):
        amounts = [prize_amount(value) for value in places]
        if None in amounts or sum(amounts) != int(form.prize_pool.data):
            raise ValueError('Enter whole GP amounts for all three places, totalling the prize pool. Use 0 for no award.')
