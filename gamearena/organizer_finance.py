"""Atomic, reviewed GP settlement. No external game result is inferred here."""
from datetime import datetime
from gamearena.extensions import db
from gamearena.models import User, Tournament, UserTournament, WalletTransaction, OrganizerFinance, OrganizerDraft, TournamentStat, TournamentMatch, TournamentMatchDispute
from gamearena.economy import spend_cash

AGREEMENT_VERSION = 'organizer-gp-v1'

def record(owner, kind, amount, event, suffix, winnings=0):
    if amount:
        db.session.add(WalletTransaction(user_id=owner.id, type=kind, amount=amount, status='completed',
            winnings_spent=winnings, account_name=event.name, transaction_ref=f'event_{event.id}_{suffix}', completed_at=datetime.utcnow()))

def fund(event, draft, owner):
    used = spend_cash(owner, draft.prize_pool)
    db.session.add(OrganizerFinance(tournament_id=event.id, owner_id=owner.id,
        prize_reserved=draft.prize_pool, reserve_winnings=used, fee_bps=500,
        agreement_version=draft.agreement_version, accepted_at=draft.accepted_at))
    record(owner, 'prize_reserve', draft.prize_pool, event, 'reserve', used)

def close_event(tournament_id, actor_id, awards=None, note=''):
    """Caller commits; lock order: tournament, finance, then users by ID."""
    event = Tournament.query.filter_by(id=tournament_id).with_for_update().populate_existing().one()
    finance = OrganizerFinance.query.filter_by(tournament_id=event.id).with_for_update().populate_existing().one()
    if finance.state != 'funded':
        raise ValueError('This event has already been settled or refunded.')
    if not note.strip():
        raise ValueError('Record the evidence and decision for this financial close.')
    entries = UserTournament.query.filter_by(tournament_id=event.id).order_by(UserTournament.id).all()
    if any(e.payment_status == 'pending' and e.transaction_ref for e in entries):
        raise ValueError('Resolve pending payments before closing this event.')
    paid = [e for e in entries if e.payment_status == 'paid']
    payments = {p.transaction_ref:p for p in WalletTransaction.query.filter(WalletTransaction.transaction_ref.in_([e.transaction_ref for e in paid]), WalletTransaction.type == 'tournament_entry').all()}
    if any(not payments.get(e.transaction_ref) or payments[e.transaction_ref].status != 'completed' or payments[e.transaction_ref].amount != e.amount_paid or payments[e.transaction_ref].user_id != e.user_id for e in paid):
        raise ValueError('Entry ledger could not be reconciled. Contact support before closing the event.')
    eligible = {e.user_id for e in entries if e.payment_status in ('paid', 'free')}
    if awards is not None:
        if event.status != 'finished' or not note.strip():
            raise ValueError('Finish the event and record the evidence review before settlement.')
        if TournamentMatchDispute.query.join(TournamentMatch, TournamentMatch.id == TournamentMatchDispute.match_id).filter(
                TournamentMatch.tournament_id == event.id, TournamentMatchDispute.status == 'pending').first():
            raise ValueError('Resolve match disputes before settlement.')
        if any(uid not in eligible or type(amount) is not int or amount <= 0 for uid, amount in awards.items()) or sum(awards.values()) != finance.prize_reserved:
            raise ValueError('Prizes must total the funded pool and belong to registered players.')
        if event.launch_plan and event.competition:
            from gamearena.tournament_launch import prize_amount
            placements = TournamentStat.query.filter_by(tournament_id=event.id).all()
            amounts = {1:prize_amount(event.first_place), 2:prize_amount(event.second_place)}
            expected = {stat.user_id:amounts[stat.rank] for stat in placements
                if stat.rank in amounts and amounts[stat.rank]}
            if awards != expected:
                raise ValueError('Prizes must match the confirmed 1v1 placements and published GP allocation.')
    owners = {u.id:u for u in User.query.filter(User.id.in_(sorted(eligible | {finance.owner_id}))).order_by(User.id).with_for_update().populate_existing().all()}
    revenue = sum(e.amount_paid or 0 for e in paid)
    if awards is None:
        for entry in paid:
            payment = payments.get(entry.transaction_ref)
            if not payment or payment.status != 'completed' or payment.amount != entry.amount_paid:
                raise ValueError('Entry ledger could not be reconciled. Contact support before refunding.')
            owner = owners[entry.user_id]
            owner.wallet_balance += entry.amount_paid
            owner.wallet_winnings_balance += payment.winnings_spent or 0
            record(owner, 'entry_refund', entry.amount_paid, event, f'refund_{entry.id}')
            entry.payment_status = 'refunded'
        host = owners[finance.owner_id]
        host.wallet_balance += finance.prize_reserved
        host.wallet_winnings_balance += finance.reserve_winnings
        record(host, 'reserve_refund', finance.prize_reserved, event, 'reserve_refund')
        finance.state = 'refunded'
        event.status = 'cancelled'
    else:
        stats = {stat.user_id:stat for stat in TournamentStat.query.filter(
            TournamentStat.tournament_id == event.id, TournamentStat.user_id.in_(list(awards))).with_for_update().all()}
        if any(stat.prize_status in ('paid', 'pending') or stat.paystack_transfer_ref for stat in stats.values()):
            raise ValueError('A prize payout already exists. Reconcile it before wallet settlement.')
        for uid, amount in awards.items():
            owner = owners[uid]
            owner.wallet_balance += amount
            owner.wallet_winnings_balance += amount
            record(owner, 'prize_credit', amount, event, f'prize_{uid}')
            stat = stats.get(uid)
            if stat:
                stat.prize_status = 'paid'
                stat.prize_paid_at = datetime.utcnow()
        finance.platform_fee = revenue * finance.fee_bps // 10000
        host = owners[finance.owner_id]
        host.wallet_balance += revenue - finance.platform_fee
        host.wallet_winnings_balance += revenue - finance.platform_fee
        record(host, 'organizer_income', revenue - finance.platform_fee, event, 'income')
        finance.state = 'settled'
    finance.entry_revenue = revenue
    finance.settled_at = datetime.utcnow()
    finance.settled_by = actor_id
    finance.settlement_note = note[:500]
    draft = OrganizerDraft.query.filter_by(tournament_id=event.id).one()
    draft.status = 'completed' if awards is not None else 'cancelled'
    return finance
