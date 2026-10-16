"""Cash stays in the existing ledger unit. Callers must hold the User row lock."""
def spend_cash(owner, amount, source="combined"):
    total, winnings = owner.wallet_balance or 0, owner.wallet_winnings_balance or 0
    if amount < 0 or winnings < 0 or winnings > total:
        raise ValueError('Invalid wallet balance.')
    if amount > total:
        raise ValueError('Insufficient withdrawable GP.')
    if source not in {'combined', 'purchased', 'winnings'}:
        raise ValueError('Choose a valid wallet.')
    available = winnings if source == 'winnings' else total - winnings if source == 'purchased' else total
    if amount > available:
        raise ValueError('Insufficient GP in the selected wallet.')
    used = amount if source == 'winnings' else max(0, amount - (total - winnings))
    owner.wallet_balance = total - amount
    owner.wallet_winnings_balance = winnings - used
    return used


def refund_cash(owner, transaction):
    owner.wallet_balance = (owner.wallet_balance or 0) + transaction.amount
    owner.wallet_winnings_balance = (owner.wallet_winnings_balance or 0) + (transaction.winnings_spent or 0)
