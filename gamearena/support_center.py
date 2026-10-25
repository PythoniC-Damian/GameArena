"""Private support threads and self-service account exports."""
from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from datetime import datetime
from gamearena.extensions import db
from gamearena.models import UserReport, SupportReply, WalletTransaction, UserTournament, CosmeticOwnership

support_center=Blueprint('support_center',__name__)
TICKET_TYPES={'support','account_closure','data_request'}


def own_ticket(ticket_id):
    row=db.get_or_404(UserReport,ticket_id)
    if row.content_type not in TICKET_TYPES or current_user.suspended or (row.reporter_id!=current_user.id and not current_user.is_admin):
        abort(404)
    return row


@support_center.route('/support/tickets/<int:ticket_id>',methods=['GET','POST'])
@login_required
def ticket(ticket_id):
    row=own_ticket(ticket_id)
    if request.method=='POST':
        from app import consume_rate_limit,create_and_emit_notification
        if consume_rate_limit('support_reply:'+str(current_user.id),10,300) is not None: abort(429)
        message=request.form.get('message','').strip()
        if not 2<=len(message)<=2000: abort(400,description='Write a reply of 2–2,000 characters.')
        db.session.add(SupportReply(report_id=row.id,author_id=current_user.id,message=message))
        if current_user.is_admin and request.form.get('resolve')=='yes':
            row.status='resolved';row.reviewed_by_id=current_user.id;row.reviewed_at=datetime.utcnow()
        elif current_user.id==row.reporter_id:
            row.status='pending';row.reviewed_at=None
        db.session.commit()
        if current_user.id!=row.reporter_id:
            create_and_emit_notification(row.reporter_id,f'Support replied to ticket #{row.id}.',category='system',target_url=url_for('.ticket',ticket_id=row.id))
        return redirect(url_for('.ticket',ticket_id=row.id))
    replies=SupportReply.query.filter_by(report_id=row.id).order_by(SupportReply.created_at,SupportReply.id).paginate(page=max(1,request.args.get('page',1,type=int) or 1),per_page=30,error_out=False)
    return render_template('support_ticket.html',ticket=row,replies=replies)


@support_center.route('/account/export')
@login_required
def export():
    if current_user.suspended: abort(403)
    user=current_user
    payments=WalletTransaction.query.filter_by(user_id=user.id).order_by(WalletTransaction.id).limit(1001).all()
    entries=UserTournament.query.filter_by(user_id=user.id).order_by(UserTournament.id).limit(1001).all()
    payload=dict(profile=dict(id=user.id,username=user.username,email=user.email,bio=user.bio,
        email_verified=user.email_verified),wallet=dict(total_gp=user.wallet_balance or 0,
        winnings_gp=user.wallet_winnings_balance or 0,bonus_gp=user.wallet_bonus_balance or 0),
        cosmetics=[r.item_key for r in CosmeticOwnership.query.filter_by(user_id=user.id)],
        transactions=[dict(id=r.public_transaction_id,reference=r.transaction_ref,type=r.type,amount_gp=r.amount,status=r.status,created_at=r.created_at.isoformat()+'Z') for r in payments[:1000]],
        entries=[dict(tournament_id=r.tournament_id,status=r.payment_status) for r in entries[:1000]],
        exported_at=datetime.utcnow().isoformat()+'Z',
        more_records_available=len(payments)>1000 or len(entries)>1000,
        scope='Profile, GP balances, cosmetic ownership, and up to 1,000 transactions and entries. Request other account data through your support ticket.')
    response=jsonify(payload);response.headers['Content-Disposition']='attachment; filename="gamearena-account-data.json"'
    response.headers['Cache-Control']='private, no-store'
    return response


@support_center.route('/account/requests',methods=['POST'])
@login_required
def account_request():
    if current_user.suspended: abort(403)
    kind=request.form.get('kind')
    if kind not in {'account_closure','data_request'} or request.form.get('confirmed')!='yes': abort(400)
    existing=UserReport.query.filter_by(reporter_id=current_user.id,content_type=kind,status='pending').first()
    if existing: return redirect(url_for('.ticket',ticket_id=existing.id))
    row=UserReport(reporter_id=current_user.id,content_type=kind,
        reason='Account closure requested. Review remaining balances, active entries and retention requirements before closing.' if kind=='account_closure' else 'A complete account data export has been requested.')
    db.session.add(row);db.session.commit()
    flash('Request recorded. Track its status and replies in this ticket. Your account stays active during review.','success')
    return redirect(url_for('.ticket',ticket_id=row.id))
