"""Existing Resend/SMTP delivery, separated from Flask routes."""
import os, re, time, json, hashlib, http.client, socket, smtplib, ssl
from email.message import EmailMessage
from flask import current_app, g
EMAIL_NETWORK_TIMEOUT_SECONDS = 8


def send_email(subject, recipient, body, idempotency_key=None):
    """Send email synchronously and report only provider-accepted delivery."""
    provider = (os.environ.get('EMAIL_PROVIDER') or ('resend' if os.environ.get('RENDER') else 'auto')).strip().lower()
    resend_api_key = (os.environ.get('RESEND_API_KEY') or '').strip()
    email_from = (os.environ.get('EMAIL_FROM') or
        (os.environ.get('SMTP_USERNAME') if provider != 'resend' and not resend_api_key else None) or
        'GameArena <noreply@gamearena01.com>')
    recipient_domain = recipient.rsplit('@', 1)[-1].lower() if '@' in recipient else 'unknown'
    if not re.fullmatch(r'[a-z0-9.-]{1,253}', recipient_domain):
        recipient_domain = 'unknown'
    request_id = getattr(g, 'request_id', '-')

    def log_delivery(provider, outcome, started_at, status=None, provider_request_id=None, category=None):
        provider_request_id = re.sub(r'[^A-Za-z0-9_.:-]', '', str(provider_request_id or ''))[:100] or '-'
        details = (
            'email_delivery provider=%s recipient_domain=%s outcome=%s status=%s '
            'provider_request_id=%s request_id=%s duration_ms=%s category=%s',
            provider, recipient_domain, outcome, status if status is not None else '-',
            provider_request_id, request_id,
            round((time.perf_counter() - started_at) * 1000, 2), category or '-',
        )
        if outcome == 'success':
            current_app.logger.info(*details)
        else:
            current_app.logger.warning(*details)

    if provider not in {'auto', 'resend', 'smtp'}:
        log_delivery('none', 'failure', time.perf_counter(), category='invalid_provider')
        return False
    # Use HTTPS on Render; its free services block the standard SMTP ports.
    # Explicit SMTP remains available for environments that support it.
    if provider == 'resend' and not resend_api_key:
        log_delivery('resend', 'failure', time.perf_counter(), category='missing_api_key')
        return False

    # --- Resend (preferred) ---
    if resend_api_key and provider != 'smtp':
        started_at = time.perf_counter()
        connection = None
        try:
            payload = {
                'from': email_from,
                'to': recipient,
                'subject': subject,
                'text': body,
            }
            body_bytes = json.dumps(payload).encode('utf-8')
            connection = http.client.HTTPSConnection(
                'api.resend.com', timeout=EMAIL_NETWORK_TIMEOUT_SECONDS,
            )
            connection.request(
                'POST',
                '/emails',
                body=body_bytes,
                headers={
                    'Authorization': f'Bearer {resend_api_key}',
                    'Content-Type': 'application/json',
                    'Content-Length': str(len(body_bytes)),
                    'Idempotency-Key': idempotency_key or ('gamearena-email/' + hashlib.sha256(body_bytes).hexdigest()),
                },
            )
            response = connection.getresponse()
            provider_request_id = response.getheader('x-request-id')
            # Never log the response body: provider errors can contain addresses.
            try:
                result = json.loads(response.read(65536).decode('utf-8'))
            except (ValueError, UnicodeError):
                result = {}
            message_id = result.get('id') if isinstance(result, dict) else None
            if 200 <= response.status < 300 and isinstance(message_id, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,100}', message_id):
                log_delivery('resend', 'success', started_at, response.status, provider_request_id or message_id)
                return True
            categories = {401:'invalid_api_key', 403:'sender_or_key_not_authorized',
                422:'invalid_email_request', 429:'provider_rate_limited'}
            category = 'invalid_provider_response' if 200 <= response.status < 300 else categories.get(response.status, 'provider_rejected')
            log_delivery('resend', 'failure', started_at, response.status, provider_request_id, category)
        except Exception as error:
            category = 'timeout' if isinstance(error, (TimeoutError, socket.timeout)) else type(error).__name__
            log_delivery('resend', 'failure', started_at, category=category)
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass

    if provider == 'resend':
        # Fail promptly and truthfully; do not add a blocked SMTP timeout.
        return False

    smtp_server = os.environ.get('SMTP_SERVER')
    smtp_port = os.environ.get('SMTP_PORT')
    smtp_username = os.environ.get('SMTP_USERNAME')
    smtp_password = os.environ.get('SMTP_PASSWORD')
    smtp_use_tls = os.environ.get('SMTP_USE_TLS', 'true').lower() in ('1', 'true', 'yes')


    if smtp_server and smtp_port and smtp_username and smtp_password:
        started_at = time.perf_counter()
        try:
            msg = EmailMessage()
            msg['Subject'] = subject
            msg['From'] = email_from
            msg['To'] = recipient
            msg.set_content(body)
            if smtp_use_tls:
                context = ssl.create_default_context()
                with smtplib.SMTP(smtp_server, int(smtp_port), timeout=EMAIL_NETWORK_TIMEOUT_SECONDS) as server:
                    server.starttls(context=context)
                    server.login(smtp_username, smtp_password)
                    refused = server.send_message(msg)
            else:
                context = ssl.create_default_context()
                with smtplib.SMTP_SSL(
                    smtp_server, int(smtp_port), context=context,
                    timeout=EMAIL_NETWORK_TIMEOUT_SECONDS,
                ) as server:
                    server.login(smtp_username, smtp_password)
                    refused = server.send_message(msg)
            if recipient in refused:
                refusal = refused[recipient]
                status = refusal[0] if isinstance(refusal, tuple) and refusal else None
                log_delivery('smtp', 'failure', started_at, status, category='recipient_rejected')
                return False
            log_delivery('smtp', 'success', started_at)
            return True
        except Exception as error:
            category = 'timeout' if isinstance(error, (TimeoutError, socket.timeout)) else type(error).__name__
            log_delivery('smtp', 'failure', started_at, category=category)
            return False

    if not resend_api_key:
        started_at = time.perf_counter()
        log_delivery('none', 'failure', started_at, category='not_configured')
    return False


def account_email_content(user, purpose, verification_url=None):
    verification = purpose == 'verification'
    subject = 'Verify your GameArena email' if verification else 'Reset your GameArena password'
    code = user.verification_code if verification else user.reset_code
    action = 'verify your email address on GameArena' if verification else 'reset your GameArena password'
    body = f'Hi {user.username},\n\nUse the code below to {action}:\n\n{code}\n\n'
    if verification:
        body += f'Open the verification page: {verification_url}\n\n'
    body += 'This code expires in 15 minutes.\n\nIf you did not request this, please ignore this message.\n\nThanks,\nGameArena Team'
    return subject, body
