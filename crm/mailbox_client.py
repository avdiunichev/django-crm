"""Small, provider-specific helpers for personal VK WorkSpace mailboxes."""

import base64
from email.message import EmailMessage
from email import message_from_bytes
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime
import hashlib
from html import unescape
from html.parser import HTMLParser
import imaplib
import re
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
    expected_flag = {
        "inbox": "\\INBOX", "sent": "\\SENT", "drafts": "\\DRAFTS", "trash": "\\TRASH",
    }[folder]
    if folder == "inbox":
        return "INBOX"
    status, folders = client.list()
    if status == "OK":
        for entry in folders:
            text = entry.decode("utf-8", errors="replace") if isinstance(entry, bytes) else entry
            if expected_flag in text.upper():
                return text.rsplit('"', 2)[-2] if '"' in text else text.rsplit(" ", 1)[-1]
    return {"sent": "Sent", "drafts": "Drafts", "trash": "Trash"}[folder]


def _decode_part(part):
    payload = part.get_payload(decode=True) or b""
    return payload.decode(part.get_content_charset() or "utf-8", errors="replace")


def _message_preview(value):
    """Make a short, safe text preview from the first body bytes returned by IMAP."""
    if not value:
        return ""
    text = value.decode("utf-8", errors="replace")
    text = re.sub(r"=\r?\n", "", text)  # quoted-printable soft line break
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"(?im)^(content-[^\n]*|--[-_A-Za-z0-9=]+)\s*$", " ", text)
    text = re.sub(r"\s+", " ", unescape(text)).strip()
    return text[:600]


class _HTMLTextExtractor(HTMLParser):
    """Extract readable text from email HTML without rendering active content."""

    block_tags = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "table"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "head"}:
            self.skip_depth += 1
        elif tag in self.block_tags:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "head"} and self.skip_depth:
            self.skip_depth -= 1
        elif tag in self.block_tags:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip_depth:
            self.parts.append(data)

    def text(self):
        value = unescape("".join(self.parts)).replace("\r", "")
        value = re.sub(r"[ \t]+", " ", value)
        value = re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", value)
        return value.strip()


def _html_to_text(value):
    parser = _HTMLTextExtractor()
    parser.feed(value)
    parser.close()
    return parser.text()


def _mailbox_party(raw_value):
    """Return a clean display name and address for a mailbox table row."""
    raw_value = raw_value or ""
    raw_name, address = parseaddr(raw_value)
    display_name = _decode_header(raw_name).strip() or address or _decode_header(raw_value).strip()
    return display_name, address


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
        if not message_ids:
            return []
        # One batched IMAP command is substantially faster than a separate
        # network round trip for every visible row.
        status, payload = client.uid(
            "fetch", b",".join(message_ids),
            "(UID FLAGS BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE)] BODY.PEEK[TEXT]<0.1024>)",
        )
        if status != "OK" or not payload:
            return []

        raw_messages = {}
        current_uid = None
        for item in payload:
            if not isinstance(item, tuple) or not isinstance(item[1], bytes):
                continue
            metadata, data = item
            uid_match = re.search(rb"UID\s+(\d+)", metadata)
            if uid_match:
                current_uid = uid_match.group(1).decode("ascii")
                raw_messages[current_uid] = {"metadata": metadata, "header": data, "preview": b""}
            elif current_uid and current_uid in raw_messages:
                raw_messages[current_uid]["preview"] += data

        messages = []
        for message_id in reversed(message_ids):
            uid = message_id.decode("ascii")
            raw_message = raw_messages.get(uid)
            if not raw_message:
                continue
            message = message_from_bytes(raw_message["header"])
            try:
                received_at = parsedate_to_datetime(message.get("Date"))
            except (TypeError, ValueError, IndexError):
                received_at = None
            sender_value = message.get("To") if folder == "sent" else message.get("From")
            sender_name, sender_email = _mailbox_party(sender_value)
            messages.append({
                "uid": uid,
                "sender": _decode_header(sender_value),
                "sender_name": sender_name,
                "sender_email": sender_email if sender_email != sender_name else "",
                "subject": _decode_header(message.get("Subject")),
                "preview": _message_preview(raw_message["preview"]),
                "received_at": received_at,
                "is_unread": b"\\Seen" not in raw_message["metadata"],
            })
        return sorted(
            messages,
            key=lambda item: item["received_at"].timestamp() if item["received_at"] else 0,
            reverse=True,
        )
    finally:
        _close_client(client)


def fetch_mailbox_counts(email, app_password):
    """Return total and unread message counts for the visible mailbox folders."""
    counts = {}
    for folder in ("inbox", "sent", "drafts", "trash"):
        client = _open_folder(email, app_password, folder)
        try:
            total_status, total_data = client.uid("search", None, "ALL")
            unread_status, unread_data = client.uid("search", None, "UNSEEN")
            counts[folder] = {
                "total": len(total_data[0].split()) if total_status == "OK" and total_data else 0,
                "unread": len(unread_data[0].split()) if unread_status == "OK" and unread_data else 0,
            }
        finally:
            _close_client(client)
    return counts


def delete_messages(email, app_password, folder, uids):
    """Move selected messages to Trash, or permanently remove them from Trash."""
    message_ids = [str(uid) for uid in uids if str(uid).isdigit()]
    if not message_ids:
        return 0
    client = _open_folder(email, app_password, folder, readonly=False)
    try:
        uid_set = ",".join(message_ids)
        if folder == "trash":
            status, _ = client.uid("store", uid_set, "+FLAGS.SILENT", "(\\Deleted)")
            if status != "OK":
                raise imaplib.IMAP4.error("Messages could not be deleted")
            client.expunge()
            return len(message_ids)

        trash_folder = _resolve_folder(client, "trash")
        status, _ = client.uid("move", uid_set, trash_folder)
        if status != "OK":
            status, _ = client.uid("copy", uid_set, trash_folder)
            if status != "OK":
                raise imaplib.IMAP4.error("Messages could not be moved to Trash")
            status, _ = client.uid("store", uid_set, "+FLAGS.SILENT", "(\\Deleted)")
            if status != "OK":
                raise imaplib.IMAP4.error("Messages could not be deleted")
            client.expunge()
        return len(message_ids)
    finally:
        _close_client(client)


def mark_messages_as_read(email, app_password, folder, uids):
    """Mark selected messages as read without fetching their full bodies."""
    message_ids = [str(uid) for uid in uids if str(uid).isdigit()]
    if not message_ids:
        return 0
    client = _open_folder(email, app_password, folder, readonly=False)
    try:
        status, _ = client.uid("store", ",".join(message_ids), "+FLAGS.SILENT", "(\\Seen)")
        if status != "OK":
            raise imaplib.IMAP4.error("Messages could not be marked as read")
        return len(message_ids)
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
    return "\n\n".join(plain_parts) or _html_to_text("\n\n".join(html_parts)), attachments


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
