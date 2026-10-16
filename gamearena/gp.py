"""Fixed-value GP conversion and exact withdrawal fees (integer naira/kobo)."""
import re
from decimal import Decimal
NAIRA_PER_GP = 10
WITHDRAWAL_FEE_POLICY = 'gp-withdrawal-v1'

def gp_to_naira(value):
    text = str(value).strip()
    if not re.fullmatch(r'[0-9]{1,9}(?:\.[0-9])?', text):
        raise ValueError('Enter a GP amount with at most one decimal place.')
    amount = int(Decimal(text) * NAIRA_PER_GP)
    if not 0 < amount <= 2_000_000_000:
        raise ValueError('Enter a valid GP amount.')
    return amount

def gp_label(naira):
    value = Decimal(str(naira or 0)) / NAIRA_PER_GP
    return f'{value:,.1f}'.rstrip('0').rstrip('.') + ' GP'

def withdrawal_fee_kobo(naira):
    # 1% of integer naira in kobo is exactly the same integer; cap at N200.
    return min(int(naira), 20_000)

def kobo_label(kobo):
    value = Decimal(int(kobo or 0)) / 100
    return '\u20a6' + (f'{value:,.0f}' if value == value.to_integral_value() else f'{value:,.2f}')
