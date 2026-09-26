"""Small, provider-specific helpers for personal VK WorkSpace mailboxes."""

import base64
from email import message_from_bytes
from email.header import decode_header
import hashlib
import imaplib

from cryptography.fernet import Fernet
from django.conf import settings


IMAP_HOST = "imap.mail.ru"
IMAP_PORT = 993


def _cipher():
    key = base64.urlsafe_b64encode(
        hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    )
    return Fernet(key)


def encrypt_app_password(password):
    return _cipher().encrypt(password.encode("utf-8")).decode("ascii")


def decrypt_app_password(value):
    return _cipher().decrypt(value.encode("ascii")).decode("utf-8")


def verify_mailbox_access(email, app_password):
    """Authenticate with IMAP without retaining the clear-text password."""
    client = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, timeout=15)
    try:
        client.login(email, app_password)
        client.select("INBOX", readonly=True)
    finally:
        try:
            client.logout()
        except (imaplib.IMAP4.error, OSError):
            pass


def _decode_header(value):
    if not value:
        return "Без темы"
    parts = []
    for fragment, encoding in decode_header(value):
        if isinstance(fragment, bytes):
            parts.append(fragment.decode(encoding or "utf-8", errors="replace"))
        else:
            parts.append(fragment)
    return "".join(parts)


def _resolve_folder(client, folder):
    """Choose the provider's real folder name from its IMAP special-use flag."""
    expected_flag = {"inbox": "\\INBOX", "sent": "\\SENT", "drafts": "\\DRAFTS"}[folder]
    if folder == "inbox":
        return "INBOX"
    status, folders = client.list()
    if status == "OK":
        for entry in folders:
            text = entry.decode("utf-8", errors="replace") if isinstance(entry, bytes) else entry
            if expected_flag in text.upper():
                return text.rsplit('"', 2)[-2] if '"' in text else text.rsplit(" ", 1)[-1]
    return {"sent": "Sent", "drafts": "Drafts"}[folder]


def fetch_recent_inbox(email, app_password, folder="inbox", limit=20):
    """Return a personal folder preview without persisting message contents."""
    client = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, timeout=15)
    try:
        client.login(email, app_password)
        client.select(_resolve_folder(client, folder), readonly=True)
        status, data = client.search(None, "ALL")
        if status != "OK":
            return []
        message_ids = data[0].split()[-limit:]
        messages = []
        for message_id in reversed(message_ids):
            status, payload = client.fetch(message_id, "(RFC822.HEADER)")
            if status != "OK" or not payload or not payload[0]:
                continue
            message = message_from_bytes(payload[0][1])
            messages.append({
                "sender": _decode_header(message.get("From")),
                "subject": _decode_header(message.get("Subject")),
                "date": message.get("Date", ""),
            })
        return messages
    finally:
        try:
            client.logout()
        except (imaplib.IMAP4.error, OSError):
            pass
