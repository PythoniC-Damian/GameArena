# GameArena Payment System Setup Guide

## ✅ Implemented Features

### 1. **Database Schema Updates**
- Added `payment_status` field to `UserTournament` model
- Added `transaction_ref` field for tracking Paystack transactions
- Added `amount_paid` field to store payment amounts
- Payment states: `pending`, `paid`, `failed`, `free`, `refunded`

### 2. **Paystack Integration**
- Paystack API integration for secure payment processing
- Payment initialization endpoint
- Payment verification endpoint
- Automatic tournament joining upon successful payment

### 3. **Payment Routes**
- `/pay/<tournament_id>` - Payment page (requires login)
- `/initialize-payment/<tournament_id>` - Initialize Paystack payment (POST)
- `/verify-payment` - Verify payment completion and join tournament

### 4. **Updated UI Components**
- Tournament buttons show "Pay ₦X to Join" for paid tournaments
- Tournament buttons show "Join Free Tournament" for free tournaments
- Payment page with Paystack integrated payment modal
- Success/error flash messages for payment status

### 5. **Security Features**
- CSRF protection on all forms
- Login required for payment operations
- Secure API communication with Paystack
- Duplicate payment prevention
- Tournament capacity validation

## 🚀 Quick Start

### Step 1: Get Paystack Test Keys
1. Visit [Paystack Dashboard](https://dashboard.paystack.com)
2. Sign up for a free account
3. Go to Settings → API Keys
4. Copy your **Test Public Key** (for frontend)
5. Copy your **Test Secret Key** (for backend)

### Step 2: Update .env File
```bash
PAYSTACK_PUBLIC_KEY=pk_test_your_actual_public_key
PAYSTACK_SECRET_KEY=sk_test_your_actual_secret_key
```

### Step 3: Run the App
```bash
python app.py
```

Visit `http://localhost:5000` and test the payment flow!

## 🧪 Test Payment Flow

1. **Register/Login** as a new user
2. **Browse tournaments** on the homepage
3. **Click on a tournament** (e.g., Call of Duty Mobile - ₦3,500 entry fee)
4. **Click "Pay ₦3500 to Join"** button
5. **Complete payment** with test card:
   - Number: `4084084084084081`
   - Expiry: `12/25`
   - CVV: `408`
   - PIN: `1234`
6. **Verify** you're automatically joined to the tournament

## 💳 Test Card (Paystack)

```
Card Number: 4084084084084081
Expiry: 12/25
CVV: 408
PIN: 1234
```

## 🔒 Production Checklist

- [ ] Obtain live Paystack keys from production environment
- [ ] Update .env with live keys
- [ ] Enable SSL/HTTPS (required for payments)
- [ ] Set up Paystack webhooks for instant notifications
- [ ] Implement proper error logging
- [ ] Add payment analytics dashboard
- [ ] Set up automated refund processing
- [ ] Deploy to production server

## 📊 Payment Status Guide

| Status | Meaning | Action |
|--------|---------|--------|
| `pending` | Payment initiated but not verified | User waiting for verification |
| `paid` | Payment successful, user joined | Show in dashboard |
| `failed` | Payment failed at Paystack | Allow retry |
| `free` | Free tournament, no payment needed | Direct join |
| `refunded` | Payment refunded (future use) | Remove from tournament |

## 🛠️ API Integration Points

### Initialize Payment (POST)
```
Endpoint: /initialize-payment/<tournament_id>
Method: POST
Headers: Authorization required
Response: {
  "status": "success",
  "authorization_url": "https://checkout.paystack.com/...",
  "reference": "unique_transaction_ref"
}
```

### Verify Payment (GET)
```
Endpoint: /verify-payment?reference=<transaction_ref>
Method: GET
Redirects to: /dashboard (on success) or payment page (on failure)
```

## 📝 Database Tables

### UserTournament Table
```sql
user_tournament:
  - id (PRIMARY KEY)
  - user_id (FOREIGN KEY)
  - tournament_id (FOREIGN KEY)
  - joined_at (DATETIME)
  - payment_status (VARCHAR) ← NEW
  - transaction_ref (VARCHAR) ← NEW
  - amount_paid (INTEGER) ← NEW
```

## 🐛 Troubleshooting

### "no such column: user_tournament.payment_status"
- Delete old database: `rm instance/database.db`
- Restart app: `python app.py`
- Fresh database will be created with all payment columns

### Payment modal not appearing
- Verify PAYSTACK_PUBLIC_KEY is set in .env
- Check browser console for JavaScript errors
- Ensure payment.html is properly rendered

### Payment verification fails
- Verify PAYSTACK_SECRET_KEY is correct in .env
- Check Paystack dashboard for transaction logs
- Verify network connectivity to Paystack API

## 📞 Support

For Paystack API issues:
- [Paystack Documentation](https://paystack.com/developers)
- [Paystack Support](https://support.paystack.com)

For Flask/GameArena issues:
- Check error logs in terminal
- Review database state: `python -c "from app import db; db.create_all()"`

---

**Status**: ✅ Ready for Production (once live keys are configured)
**Last Updated**: March 31, 2026
