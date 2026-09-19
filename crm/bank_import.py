from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError


@dataclass(frozen=True)
class ClientBankPayment:
    number: str
    payment_date: object
    amount: Decimal
    payer_name: str
    payer_tax_id: str
    payer_account: str
    recipient_name: str
    recipient_tax_id: str
    recipient_account: str
    purpose: str


def decode_client_bank_file(uploaded_file):
    raw = uploaded_file.read()
    if not raw:
        raise ValidationError("Файл банковской выписки пуст.")
    for encoding in ("utf-8-sig", "cp1251", "utf-8"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValidationError("Не удалось определить кодировку файла. Используйте UTF-8 или Windows-1251.")


def _parse_date(value):
    for pattern in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), pattern).date()
        except ValueError:
            continue
    raise ValidationError(f"Некорректная дата в выписке: {value}.")


def _normalize_account(value):
    return "".join(character for character in value if character.isdigit())


def parse_client_bank_exchange(uploaded_file):
    text = decode_client_bank_file(uploaded_file)
    lines = [line.strip() for line in text.replace("\r\n", "\n").split("\n") if line.strip()]
    if not lines or lines[0].lower() != "1cclientbankexchange":
        raise ValidationError("Файл не является выпиской в формате 1CClientBankExchange.")

    header = {}
    documents = []
    current = None
    for line in lines[1:]:
        if line.startswith("СекцияДокумент="):
            current = {"ВидДокумента": line.split("=", 1)[1].strip()}
            continue
        if line == "КонецДокумента":
            if current is not None:
                documents.append(current)
            current = None
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        (current if current is not None else header)[key.strip()] = value.strip()

    payments = []
    errors = []
    for index, row in enumerate(documents, start=1):
        try:
            amount = Decimal(row.get("Сумма", "0").replace(" ", "").replace(",", "."))
            if amount <= 0:
                raise InvalidOperation
            payments.append(
                ClientBankPayment(
                    number=row.get("Номер", "").strip(),
                    payment_date=_parse_date(row.get("Дата", "")),
                    amount=amount,
                    payer_name=row.get("Плательщик", "").strip(),
                    payer_tax_id=row.get("ПлательщикИНН", "").strip(),
                    payer_account=_normalize_account(row.get("ПлательщикСчет", "")),
                    recipient_name=row.get("Получатель", "").strip(),
                    recipient_tax_id=row.get("ПолучательИНН", "").strip(),
                    recipient_account=_normalize_account(row.get("ПолучательСчет", "")),
                    purpose=row.get("НазначениеПлатежа", "").strip(),
                )
            )
        except (InvalidOperation, ValidationError) as error:
            errors.append(f"Строка {index}: {error}")
    if not payments:
        raise ValidationError("В выписке не найдено корректных платёжных поручений.")
    return header, payments, errors
