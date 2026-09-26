"""Small, provider-specific helpers for personal VK WorkSpace mailboxes."""

import base64
from email.message import EmailMessage
from email import message_from_bytes
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime
import hashlib
import imaplib
import smtplib

from cryptography.fernet import Fernet
from django.conf import settings


IMAP_HOST = "imap.mail.ru"
IMAP_PORT = 993
SMTP_HOST = "smtp.mail.ru"
SMTP_PORT = 465


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


def _decode_part(part):
    payload = part.get_payload(decode=True) or b""
    return payload.decode(part.get_content_charset() or "utf-8", errors="replace")


def _open_folder(email, app_password, folder, readonly=True):
    client = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, timeout=15)
    client.login(email, app_password)
    status, _ = client.select(_resolve_folder(client, folder), readonly=readonly)
    if status != "OK":
        try:
            client.logout()
        except (imaplib.IMAP4.error, OSError):
            pass
        raise imaplib.IMAP4.error("Folder is unavailable")
    return client


def _close_client(client):
    try:
        client.logout()
    except (imaplib.IMAP4.error, OSError):
        pass


def fetch_recent_inbox(email, app_password, folder="inbox", limit=30):
    """Return a personal folder preview without persisting message contents."""
    client = _open_folder(email, app_password, folder)
    try:
        status, data = client.uid("search", None, "ALL")
        if status != "OK":
            return []
        message_ids = data[0].split()[-limit:]
        messages = []
        for message_id in reversed(message_ids):
            status, payload = client.uid(
                "fetch", message_id, "(FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])"
            )
            if status != "OK" or not payload or not payload[0]:
                continue
            message = message_from_bytes(payload[0][1])
            try:
                received_at = parsedate_to_datetime(message.get("Date"))
            except (TypeError, ValueError, IndexError):
                received_at = None
            messages.append({
                "uid": message_id.decode("ascii"),
                "sender": _decode_header(message.get("From")),
                "subject": _decode_header(message.get("Subject")),
                "received_at": received_at,
                "is_unread": b"\\Seen" not in payload[0][0],
            })
        return sorted(
            messages,
            key=lambda item: item["received_at"].timestamp() if item["received_at"] else 0,
            reverse=True,
        )
    finally:
        _close_client(client)


def _message_body_and_attachments(message):
    plain_parts, html_parts, attachments = [], [], []
    part_index = -1
    for part in message.walk():
        if part.is_multipart():
            continue
        part_index += 1
        filename = _decode_header(part.get_filename()) if part.get_filename() else ""
        disposition = part.get_content_disposition()
        if filename or disposition == "attachment":
            attachments.append({
                "index": part_index,
                "filename": filename or "Вложение",
                "content_type": part.get_content_type(),
                "size": len(part.get_payload(decode=True) or b""),
            })
        elif part.get_content_type() == "text/plain":
            plain_parts.append(_decode_part(part))
        elif part.get_content_type() == "text/html":
            html_parts.append(_decode_part(part))
    # HTML is intentionally not rendered in CRM to prevent remote content and scripts.
    return "\n\n".join(plain_parts) or "\n\n".join(html_parts), attachments


def fetch_message(email, app_password, folder, uid):
    client = _open_folder(email, app_password, folder, readonly=False)
    try:
        client.uid("store", str(uid), "+FLAGS.SILENT", "(\\Seen)")
        status, payload = client.uid("fetch", str(uid), "(RFC822)")
        if status != "OK" or not payload or not payload[0]:
            raise imaplib.IMAP4.error("Message was not found")
        message = message_from_bytes(payload[0][1])
        body, attachments = _message_body_and_attachments(message)
        return {
            "uid": str(uid),
            "sender": _decode_header(message.get("From")),
            "recipient": _decode_header(message.get("To")),
            "cc": _decode_header(message.get("Cc")),
            "subject": _decode_header(message.get("Subject")),
            "date": message.get("Date", ""),
            "body": body,
            "attachments": attachments,
        }
    finally:
        _close_client(client)


def fetch_attachment(email, app_password, folder, uid, attachment_index):
    client = _open_folder(email, app_password, folder)
    try:
        status, payload = client.uid("fetch", str(uid), "(RFC822)")
        if status != "OK" or not payload or not payload[0]:
            raise imaplib.IMAP4.error("Message was not found")
        message = message_from_bytes(payload[0][1])
        parts = [part for part in message.walk() if not part.is_multipart()]
        part = parts[int(attachment_index)]
        filename = _decode_header(part.get_filename()) if part.get_filename() else "Вложение"
        return filename, part.get_content_type(), part.get_payload(decode=True) or b""
    finally:
        _close_client(client)


def reply_address(message):
    return parseaddr(message.get("sender", ""))[1]


def send_message(email, app_password, recipient, subject, body, uploaded_files=()):
    message = EmailMessage()
    message["From"] = email
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    for uploaded_file in uploaded_files:
        if not uploaded_file:
            continue
        content_type = getattr(uploaded_file, "content_type", "application/octet-stream")
        maintype, subtype = content_type.split("/", 1) if "/" in content_type else ("application", "octet-stream")
        message.add_attachment(uploaded_file.read(), maintype=maintype, subtype=subtype, filename=uploaded_file.name)
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20) as client:
        client.login(email, app_password)
        client.send_message(message)
