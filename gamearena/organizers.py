"""Organiser drafts and a platform-admin review gate for publication."""
import csv
import io
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, Response
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload
from gamearena.extensions import db
from gamearena.models import OrganizerDraft, Tournament, UserTournament, OrganizerProfile, OrganizerFinance, User, TournamentArtwork
from gamearena.organizer_finance import AGREEMENT_VERSION, fund, close_event
from gamearena.tournament_artwork import read_artwork, replace_artwork
from gamearena.gp import gp_to_naira

organizers = Blueprint('organizers', __name__)

def can_use():
    if current_user.suspended: abort(403)
    if request.method == 'POST':
        from app import consume_rate_limit
        if consume_rate_limit('organizer:' + str(current_user.id), 20, 60) is not None:
            abort(429, description='Too many changes. Please try again in a minute.')


def render_workspace(**context):
    profile = db.session.get(OrganizerProfile, current_user.id)
    profiles = OrganizerProfile.query.options(joinedload(OrganizerProfile.user)).filter_by(status='pending').limit(50).all() if current_user.is_admin else []
    ids = [d.tournament_id for d in context.get('drafts', []) if d.tournament_id]
    finances = {f.tournament_id:f for f in OrganizerFinance.query.filter(OrganizerFinance.tournament_id.in_(ids)).all()} if ids else {}
    funded_events=OrganizerDraft.query.join(OrganizerFinance, OrganizerFinance.tournament_id == OrganizerDraft.tournament_id).order_by(OrganizerDraft.id.desc()).limit(50).all() if current_user.is_admin else []
    return render_template('organizers.html', profile=profile, profile_reviews=profiles, finances=finances, funded_events=funded_events, **context)

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
            images = read_artwork(request.files.getlist('images'), len(row.artwork))
        except (ValueError, TypeError) as error:
            db.session.rollback()
            flash(str(error) or 'Check the event name, game, rules, GP amounts, capacity and future start time (UTC).', 'error')
            return render_workspace(active_draft=row, drafts=[], review=[], form_values=request.form), 400
        for key,value in values.items(): setattr(row,key,value)
        replace_artwork(row, images)
        row.status='draft'
        db.session.commit()
        flash('Event draft saved. Submit it when ready for review.', 'success')
        return redirect(url_for('.workspace'))
    # Release the write lock before rendering a read-only page.
    db.session.commit()
    return render_workspace(active_draft=row, drafts=[], review=[])


@organizers.route('/organizers', methods=['GET', 'POST'])
@login_required
def workspace():
    can_use()
    if request.method == 'POST':
        User.query.filter_by(id=current_user.id).with_for_update().one()
        if OrganizerDraft.query.filter_by(owner_id=current_user.id).filter(OrganizerDraft.status.in_(['draft','rejected','review','published'])).count() >= 30:
            db.session.rollback()
            abort(409, description='You have reached the 30-event workspace limit. Contact support.')
        try:
            values = event_fields(request.form)
            images = read_artwork(request.files.getlist('images'))
        except (ValueError, TypeError) as error:
            db.session.rollback()
            flash(str(error) or 'Check the event name, game, rules, GP amounts, capacity and future start time (UTC).', 'error')
            return render_workspace(drafts=[], review=[], form_values=request.form), 400
        draft = OrganizerDraft(owner_id=current_user.id, **values)
        db.session.add(draft)
        replace_artwork(draft, images)
        db.session.commit()
        flash('Event draft saved. Submit it when ready for review.', 'success')
        return redirect(url_for('.workspace'))
    drafts = OrganizerDraft.query.filter_by(owner_id=current_user.id).order_by(OrganizerDraft.id.desc()).limit(100).all()
    review = OrganizerDraft.query.options(joinedload(OrganizerDraft.owner)).filter_by(status='review').order_by(OrganizerDraft.id).limit(100).all() if current_user.is_admin else []
    return render_workspace(drafts=drafts, review=review)

@organizers.route('/organizers/<int:draft_id>/submit', methods=['POST'])
@login_required
def submit(draft_id):
    can_use()
    row = OrganizerDraft.query.filter_by(id=draft_id, owner_id=current_user.id).with_for_update().first_or_404()
    if row.status not in {'draft', 'rejected'}:
        db.session.rollback(); abort(409)
    profile = db.session.get(OrganizerProfile, current_user.id)
    if not current_user.email_verified or not profile or profile.status != 'approved':
        db.session.rollback(); abort(403, description='A verified email and approved organiser contact are required.')
    if request.form.get('agree') != 'yes':
        db.session.rollback(); abort(400, description='Accept the organiser rules and fee before submitting.')
    if row.starts_at <= datetime.utcnow():
        db.session.rollback(); abort(400, description='Create a draft with a future start time.')
    if len(row.artwork) != 3:
        db.session.rollback(); abort(400, description='Upload exactly 3 tournament images before submitting.')
    row.agreement_version = AGREEMENT_VERSION
    row.accepted_at = datetime.utcnow()
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
    if row.status != 'review':
        db.session.rollback(); abort(409)
    action = request.form.get('action')
    note = request.form.get('note', '').strip()
    if len(note) > 500 or action not in {'approve','reject'}:
        db.session.rollback(); abort(400)
    if action == 'approve':
        if request.form.get('checked') != 'yes' or row.starts_at <= datetime.utcnow():
            db.session.rollback()
            abort(400, description='Review the rules, prize funding and permissions before publication.')
        if len(row.artwork) != 3:
            db.session.rollback(); abort(400, description='Review requires exactly 3 tournament images.')
        owner = User.query.filter_by(id=row.owner_id).with_for_update().populate_existing().one()
        profile = OrganizerProfile.query.filter_by(user_id=row.owner_id).with_for_update().populate_existing().first()
        if not owner.email_verified or owner.suspended or not profile or profile.status != 'approved' or row.agreement_version != AGREEMENT_VERSION or not row.accepted_at:
            db.session.rollback(); abort(409, description='Organiser eligibility and a current agreement are required.')
        if (owner.wallet_balance or 0) < row.prize_pool:
            db.session.rollback(); abort(409, description='Fund the full advertised prize pool before publication.')
        event = Tournament(name=row.name, game=row.game, description=row.rules, rules=row.rules, payout_method='gp_wallet', entry_fee=row.entry_fee,
            prize=row.prize_pool, max_participants=row.capacity, match_time=row.starts_at, status='open')
        db.session.add(event)
        db.session.flush()
        fund(event, row, owner)
        row.tournament_id = event.id
        for image in row.artwork:
            image.tournament_id = event.id
        row.status = 'published'
    else:
        if not note:
            db.session.rollback(); abort(400, description='Add a reason for the organiser.')
        row.status = 'rejected'
    row.review_note = note or None
    db.session.commit()
    flash('Review saved.', 'success')
    return redirect(url_for('.workspace'))

@organizers.route('/organizers/profile', methods=['POST'])
@login_required
def apply_profile():
    can_use()
    if not current_user.email_verified: abort(403, description='Verify your email first.')
    contact = request.form.get('contact', '').strip()
    if not 5 <= len(contact) <= 150: abort(400)
    User.query.filter_by(id=current_user.id).with_for_update().one()
    profile = db.session.get(OrganizerProfile, current_user.id)
    if profile and profile.status == 'approved':
        db.session.rollback(); abort(409, description='Contact support to change your approved contact.')
    if not profile:
        profile = OrganizerProfile(user_id=current_user.id)
        db.session.add(profile)
    profile.contact = contact
    profile.status = 'pending'
    db.session.commit()
    flash('Contact submitted. GameArena will verify it before approving your organiser profile.', 'success')
    return redirect(url_for('.workspace'))


@organizers.route('/organizers/profiles/<int:user_id>/review', methods=['POST'])
@login_required
def profile_review(user_id):
    can_use()
    if not current_user.is_admin: abort(403)
    row = OrganizerProfile.query.filter_by(user_id=user_id).with_for_update().first_or_404()
    action = request.form.get('action')
    if action not in {'approved', 'rejected'} or (action == 'approved' and request.form.get('verified') != 'yes'):
        db.session.rollback(); abort(400, description='Confirm that you verified the organiser contact.')
    row.status = action
    row.review_note = request.form.get('note', '')[:500]
    row.reviewed_by = current_user.id
    row.reviewed_at = datetime.utcnow()
    db.session.commit()
    return redirect(url_for('.workspace'))


@organizers.route('/organizers/<int:draft_id>/settle', methods=['GET', 'POST'])
@login_required
def settlement(draft_id):
    can_use()
    if not current_user.is_admin: abort(403)
    row = db.session.get(OrganizerDraft, draft_id)
    if not row or not row.tournament_id: abort(404)
    finance = db.session.get(OrganizerFinance, row.tournament_id)
    if not finance: abort(409, description='Legacy event: contact support for a funding review.')
    if request.method == 'POST':
        try:
            if request.form.get('confirmed') != 'yes': raise ValueError('Confirm the result and financial review.')
            awards = None
            if request.form.get('action') == 'settle':
                awards = {}
                for line in request.form.get('awards', '').strip().splitlines():
                    uid, amount = line.split(':')
                    uid = int(uid.strip()); amount = gp_to_naira(amount.strip())
                    if uid in awards: raise ValueError('Each player must appear once.')
                    awards[uid] = amount
            elif request.form.get('action') != 'cancel':
                raise ValueError('Choose settlement or cancellation.')
            close_event(row.tournament_id, current_user.id, awards, request.form.get('note', ''))
            db.session.commit()
        except (ValueError, TypeError) as error:
            db.session.rollback()
            flash(str(error) or 'Check the prize allocation.', 'error')
            return redirect(url_for('.settlement', draft_id=draft_id))
        flash('Financial close completed. Wallet records are available to each recipient.', 'success')
        return redirect(url_for('.workspace'))
    entries = UserTournament.query.options(joinedload(UserTournament.user)).filter(UserTournament.tournament_id == row.tournament_id, UserTournament.payment_status.in_(['paid','free'])).all()
    revenue = sum(e.amount_paid or 0 for e in entries if e.payment_status == 'paid')
    return render_template('organizer_settlement.html', draft=row, finance=finance, entries=entries, revenue=revenue, fee=revenue*finance.fee_bps//10000)


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


@organizers.route('/media/tournament-artwork/<string:image_id>.webp')
def artwork(image_id):
    if len(image_id) != 32 or any(c not in '0123456789abcdef' for c in image_id):
        abort(404)
    image = db.session.get(TournamentArtwork, image_id)
    if not image:
        abort(404)
    draft = db.session.get(OrganizerDraft, image.draft_id) if image.draft_id else None
    direct_event = db.session.get(Tournament, image.tournament_id) if not image.draft_id and image.tournament_id else None
    public = draft and draft.status == 'published' and draft.tournament_id == image.tournament_id and image.tournament_id is not None
    public = public or bool(direct_event and direct_event.status in {'open','ongoing','live','finished','cancelled'})
    if not public and not (draft and current_user.is_authenticated and not current_user.suspended and (current_user.id == draft.owner_id or current_user.is_admin)):
        abort(404)
    response = Response(image.image, mimetype='image/webp')
    response.headers['Cache-Control'] = 'public, max-age=31536000, immutable' if public else 'private, no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    if public:
        response.set_etag(image.id)
        response.make_conditional(request)
    return response
