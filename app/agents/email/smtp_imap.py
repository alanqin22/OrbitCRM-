"""SMTP and IMAP utilities for EmailAgent.

Credentials are loaded from environment variables:
  EMAIL_ADDRESS       — info@agentorc.ca
  EMAIL_PASSWORD      — SMTP/IMAP password
  EMAIL_SMTP_HOST     — mail.agentorc.ca
  EMAIL_SMTP_PORT     — 465
  EMAIL_IMAP_HOST     — mail.agentorc.ca
  EMAIL_IMAP_PORT     — 993
"""

from __future__ import annotations

import email as email_lib
import imaplib
import logging
import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

EMAIL_ADDRESS  = os.environ.get('EMAIL_ADDRESS',   'info@agentorc.ca')
EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD',  '')
SMTP_HOST      = os.environ.get('EMAIL_SMTP_HOST', 'mail.agentorc.ca')
SMTP_PORT      = int(os.environ.get('EMAIL_SMTP_PORT', '465'))
IMAP_HOST      = os.environ.get('EMAIL_IMAP_HOST', 'mail.agentorc.ca')
IMAP_PORT      = int(os.environ.get('EMAIL_IMAP_PORT', '993'))
BCC_ADDRESS    = os.environ.get('EMAIL_BCC',        'info@agentorc.ca')


def send_email(
    to: str,
    subject: str,
    body_html: str,
    body_text: str,
    from_name: str = 'Orbit CRM Team',
    bcc: Optional[str] = None,
) -> Dict[str, Any]:
    """Send an email via SMTP SSL. Returns {success, message}."""
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From']    = f'{from_name} <{EMAIL_ADDRESS}>'
        msg['To']      = to
        if bcc or BCC_ADDRESS:
            msg['Bcc'] = bcc or BCC_ADDRESS

        msg.attach(MIMEText(body_text, 'plain', 'utf-8'))
        msg.attach(MIMEText(body_html, 'html',  'utf-8'))

        context = ssl.create_default_context()
        recipients = [to]
        if bcc or BCC_ADDRESS:
            recipients.append(bcc or BCC_ADDRESS)

        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context) as server:
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.sendmail(EMAIL_ADDRESS, recipients, msg.as_string())

        logger.info(f"Email sent → {to} | subject={subject!r}")
        return {'success': True, 'message': f'Email sent to {to}', 'to': to, 'subject': subject}

    except Exception as e:
        logger.error(f"SMTP error: {e}", exc_info=True)
        return {'success': False, 'message': str(e)}


def fetch_inbox(limit: int = 20, unseen_only: bool = False) -> List[Dict[str, Any]]:
    """Fetch emails from IMAP inbox. Returns list of email dicts."""
    try:
        context = ssl.create_default_context()
        with imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, ssl_context=context) as imap:
            imap.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            imap.select('INBOX')

            criterion = 'UNSEEN' if unseen_only else 'ALL'
            _, msg_nums = imap.search(None, criterion)
            if not msg_nums or not msg_nums[0]:
                return []

            ids = msg_nums[0].split()
            ids = ids[-limit:]  # most recent N

            emails = []
            for num in reversed(ids):
                _, data = imap.fetch(num, '(RFC822)')
                if not data or not data[0]:
                    continue
                raw = data[0][1] if isinstance(data[0], tuple) else None
                if not raw:
                    continue
                parsed = email_lib.message_from_bytes(raw)
                emails.append(_parse_email(parsed))

        logger.info(f"IMAP fetched {len(emails)} emails (limit={limit})")
        return emails

    except Exception as e:
        logger.error(f"IMAP fetch error: {e}", exc_info=True)
        return [{'error': str(e)}]


def search_inbox(query: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Search IMAP inbox by subject/body keyword."""
    try:
        context = ssl.create_default_context()
        with imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, ssl_context=context) as imap:
            imap.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            imap.select('INBOX')

            safe_query = query.replace('"', '')
            criterion = f'(OR SUBJECT "{safe_query}" BODY "{safe_query}")'
            _, msg_nums = imap.search(None, criterion)
            if not msg_nums or not msg_nums[0]:
                return []

            ids = msg_nums[0].split()
            ids = ids[-limit:]

            emails = []
            for num in reversed(ids):
                _, data = imap.fetch(num, '(RFC822)')
                if not data or not data[0]:
                    continue
                raw = data[0][1] if isinstance(data[0], tuple) else None
                if not raw:
                    continue
                parsed = email_lib.message_from_bytes(raw)
                emails.append(_parse_email(parsed))

        return emails

    except Exception as e:
        logger.error(f"IMAP search error: {e}", exc_info=True)
        return [{'error': str(e)}]


def _decode_header(value: str) -> str:
    """Decode MIME-encoded header values (=?UTF-8?B?...?= etc.)."""
    if not value:
        return ''
    parts = []
    for chunk, charset in email_lib.header.decode_header(value):
        if isinstance(chunk, bytes):
            parts.append(chunk.decode(charset or 'utf-8', errors='replace'))
        else:
            parts.append(chunk)
    return ' '.join(parts)


def _parse_email(msg) -> Dict[str, Any]:
    subject  = _decode_header(msg.get('Subject', '(no subject)'))
    from_    = _decode_header(msg.get('From', ''))
    to_      = _decode_header(msg.get('To', ''))
    date_    = msg.get('Date', '')
    msg_id   = msg.get('Message-ID', '')

    body_text = ''
    body_html = ''

    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == 'text/plain' and not body_text:
                try:
                    body_text = part.get_payload(decode=True).decode(
                        part.get_content_charset() or 'utf-8', errors='replace')
                except Exception:
                    pass
            elif ct == 'text/html' and not body_html:
                try:
                    body_html = part.get_payload(decode=True).decode(
                        part.get_content_charset() or 'utf-8', errors='replace')
                except Exception:
                    pass
    else:
        ct = msg.get_content_type()
        try:
            payload = msg.get_payload(decode=True).decode(
                msg.get_content_charset() or 'utf-8', errors='replace')
            if ct == 'text/html':
                body_html = payload
            else:
                body_text = payload
        except Exception:
            body_text = ''

    return {
        'subject':    subject,
        'from':       from_,
        'to':         to_,
        'date':       date_,
        'message_id': msg_id,
        'preview':    body_text[:200].strip(),
        'body_text':  body_text,
        'body_html':  body_html,
    }
