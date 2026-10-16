"""Organiser drafts and a platform-admin review gate for publication."""
import csv
import io
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, Response
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload
from gamearena.extensions import db
from gamearena.models import OrganizerDraft, Tournament, UserTournament
from gamearena.gp import gp_to_naira

organizers = Blueprint('organizers', __name__)

def can_use():
    if current_user.suspended: abort(403)

def money(value):
    return 0 if value == '0' else gp_to_naira(value)

def event_fields(data):
    name, game, rules = (data.get(k, '').strip() for k in ('name','game','rules'))
    fee, prize = money(data.get('entry_gp', '')), money(data.get('prize_gp', ''))
    capacity = int(data.get('capacity', ''))
    starts = datetime.strptime(data.get('starts_at', ''), '%Y-%m-%dT%H:%M')
    if not (3 <= len(name) <= 120 and 2 <= len(game) <= 100 and 20 <= len(rules) <= 10000 and 2 <= capacity <= 10000 and starts > datetime.utcnow()):
        raise ValueError()
    return dict(name=name, game=game, rules=rules, entry_fee=fee, prize_pool=prize,
        capacity=capacity, starts_at=starts)


@organizers.route('/organizers/<int:draft_id>/edit', methods=['GET','POST'])
@login_required
def edit(draft_id):
    can_use()
    row = OrganizerDraft.query.filter_by(id=draft_id, owner_id=current_user.id).with_for_update().populate_existing().first_or_404()
    if row.status not in {'draft','rejected'}:
        db.session.rollback()
        abort(409)
    if request.method == 'POST':
        try:
            values = event_fields(request.form)
        except (ValueError, TypeError):
            db.session.rollback()
            flash('Check the event name, game, rules, GP amounts, capacity and future start time (UTC).', 'error')
            return redirect(url_for('.edit', draft_id=draft_id))
        for key,value in values.items(): setattr(row,key,value)
        row.status='draft'
        db.session.commit()
        flash('Event draft saved. Submit it when ready for review.', 'success')
        return redirect(url_for('.workspace'))
    # Release the write lock before rendering a read-only page.
    db.session.commit()
    return render_template('organizers.html', active_draft=row, drafts=[], review=[])


@organizers.route('/organizers', methods=['GET', 'POST'])
@login_required
def workspace():
    can_use()
    if request.method == 'POST':
        data = request.form
        name, game, rules = (data.get(k, '').strip() for k in ('name','game','rules'))
        try:
            fee, prize = money(data.get('entry_gp', '')), money(data.get('prize_gp', ''))
            capacity = int(data.get('capacity', ''))
            starts = datetime.strptime(data.get('starts_at', ''), '%Y-%m-%dT%H:%M')
            if not (3 <= len(name) <= 120 and 2 <= len(game) <= 100 and 20 <= len(rules) <= 10000 and 2 <= capacity <= 10000 and starts > datetime.utcnow()):
                raise ValueError()
        except (ValueError, TypeError):
            flash('Check the event name, game, rules, GP amounts, capacity and future start time (UTC).', 'error')
            return redirect(url_for('.workspace'))
        db.session.add(OrganizerDraft(owner_id=current_user.id, name=name, game=game, rules=rules,
            entry_fee=fee, prize_pool=prize, capacity=capacity, starts_at=starts))
        db.session.commit()
        flash('Event draft saved. Submit it when ready for review.', 'success')
        return redirect(url_for('.workspace'))
    drafts = OrganizerDraft.query.filter_by(owner_id=current_user.id).order_by(OrganizerDraft.id.desc()).limit(100).all()
    review = OrganizerDraft.query.options(joinedload(OrganizerDraft.owner)).filter_by(status='review').order_by(OrganizerDraft.id).limit(100).all() if current_user.is_admin else []
    return render_template('organizers.html', drafts=drafts, review=review)

@organizers.route('/organizers/<int:draft_id>/submit', methods=['POST'])
@login_required
def submit(draft_id):
    can_use()
    row = OrganizerDraft.query.filter_by(id=draft_id, owner_id=current_user.id).with_for_update().first_or_404()
    if row.status not in {'draft', 'rejected'}: abort(409)
    if row.starts_at <= datetime.utcnow(): abort(400, description='Create a draft with a future start time.')
    row.status = 'review'
    row.review_note = None
    db.session.commit()
    flash('Submitted for review. This event is not public yet.', 'success')
    return redirect(url_for('.workspace'))

@organizers.route('/organizers/<int:draft_id>/review', methods=['POST'])
@login_required
def review(draft_id):
    can_use()
    if not current_user.is_admin: abort(403)
    row = OrganizerDraft.query.filter_by(id=draft_id).with_for_update().first_or_404()
    if row.status != 'review': abort(409)
    action = request.form.get('action')
    note = request.form.get('note', '').strip()
    if len(note) > 500 or action not in {'approve','reject'}: abort(400)
    if action == 'approve':
        if request.form.get('checked') != 'yes' or row.starts_at <= datetime.utcnow():
            abort(400, description='Review the rules, prize funding and permissions before publication.')
        event = Tournament(name=row.name, game=row.game, description=row.rules, entry_fee=row.entry_fee,
            prize=row.prize_pool, max_participants=row.capacity, match_time=row.starts_at, status='open')
        db.session.add(event)
        db.session.flush()
        row.tournament_id = event.id
        row.status = 'published'
    else:
        if not note: abort(400, description='Add a reason for the organiser.')
        row.status = 'rejected'
    row.review_note = note or None
    db.session.commit()
    flash('Review saved.', 'success')
    return redirect(url_for('.workspace'))

@organizers.route('/organizers/<int:draft_id>/participants.csv')
@login_required
def participants(draft_id):
    can_use()
    row = OrganizerDraft.query.filter_by(id=draft_id).first_or_404()
    if row.owner_id != current_user.id and not current_user.is_admin: abort(404)
    if not row.tournament_id: abort(409)
    output = io.StringIO(); writer = csv.writer(output)
    writer.writerow(['Player', 'Entry status', 'GP paid', 'Joined (UTC)'])
    from gamearena.gp import gp_label
    entries = UserTournament.query.options(joinedload(UserTournament.user)).filter_by(tournament_id=row.tournament_id).order_by(UserTournament.id).yield_per(100)
    for entry in entries:
        name = entry.user.username
        if name.lstrip().startswith(('=', '+', '-', '@')): name = "'" + name
        writer.writerow([name, entry.payment_status, gp_label(entry.amount_paid), entry.joined_at.isoformat()])
    return Response('\ufeff'+output.getvalue(), mimetype='text/csv', headers={
        'Content-Disposition':'attachment; filename="gamearena-participants.csv"', 'Cache-Control':'private, no-store'})
