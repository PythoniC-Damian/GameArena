"""Generate local VAPID settings without printing private keys or changing hosting."""
import argparse
import base64
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization

parser=argparse.ArgumentParser();parser.add_argument('--contact',required=True,help='Your support email address');args=parser.parse_args()
if '@' not in args.contact or any(c in args.contact for c in '\r\n'):
    raise SystemExit('Use a valid support email address.')
destination=Path(__file__).resolve().parent.parent/'.local-test/webpush.env'
if destination.exists():raise SystemExit('Existing keys were preserved. Do not rotate VAPID keys without a subscription migration plan.')
private=ec.generate_private_key(ec.SECP256R1())
encode=lambda data:base64.urlsafe_b64encode(data).decode().rstrip('=')
public=encode(private.public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint))
secret=encode(private.private_numbers().private_value.to_bytes(32,'big'))
destination.parent.mkdir(parents=True,exist_ok=True)
destination.write_text(f'VAPID_PUBLIC_KEY={public}\nVAPID_PRIVATE_KEY={secret}\nVAPID_SUBJECT=mailto:{args.contact}\n',encoding='utf-8')
print(f'Settings saved privately to {destination}. Configure these server-side; never commit or share the private key.')
