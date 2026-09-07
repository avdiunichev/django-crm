"""Импорт заказов из реестра реализации в формате XLSX.

Команда намеренно не зависит от openpyxl: XLSX — это ZIP-архив с XML-файлами,
поэтому импорт доступен и в минимальном окружении приложения.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
from zipfile import ZipFile
from xml.etree import ElementTree

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from crm.models import Organization, OrganizationRole, TransportOrder


XML_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PACKAGE_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def _column_number(cell_ref: str) -> int:
    letters = re.match(r"[A-Za-z]+", cell_ref or "")
    if not letters:
        return 0
    value = 0
    for letter in letters.group(0).upper():
        value = value * 26 + ord(letter) - ord("A") + 1
    return value


def _shared_strings(archive: ZipFile) -> list[str]:
    try:
        root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    values = []
    for item in root.findall(f"{XML_NS}si"):
        values.append("".join(node.text or "" for node in item.iter(f"{XML_NS}t")))
    return values


def _sheet_path(archive: ZipFile) -> str:
    """Возвращает путь первой страницы, не полагаясь на имя листа."""
    try:
        workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        relationships = ElementTree.fromstring(
            archive.read("xl/_rels/workbook.xml.rels")
        )
    except KeyError as exc:
        raise ValueError("В XLSX не найден workbook.xml") from exc
    rel_targets = {
        rel.attrib.get("Id"): rel.attrib.get("Target")
        for rel in relationships.findall(f"{PACKAGE_REL_NS}Relationship")
    }
    sheet = workbook.find(f"{XML_NS}sheets/{XML_NS}sheet")
    if sheet is None:
        raise ValueError("В XLSX нет листов")
    target = rel_targets.get(sheet.attrib.get(f"{REL_NS}id"))
    if not target:
        raise ValueError("Не удалось определить файл первого листа XLSX")
    target = target.lstrip("/")
    if not target.startswith("xl/"):
        target = f"xl/{target}"
    return target


def read_xlsx_rows(path: Path) -> list[tuple[int, list[object]]]:
    """Читает строки первого листа, сохраняя номер строки Excel."""
    with ZipFile(path) as archive:
        strings = _shared_strings(archive)
        root = ElementTree.fromstring(archive.read(_sheet_path(archive)))
    rows = []
    for row in root.findall(f".//{XML_NS}row"):
        row_number = int(row.attrib.get("r", len(rows) + 1))
        values: list[object] = [None] * 7
        for cell in row.findall(f"{XML_NS}c"):
            column = _column_number(cell.attrib.get("r", ""))
            if not 1 <= column <= len(values):
                continue
            cell_type = cell.attrib.get("t")
            value_node = cell.find(f"{XML_NS}v")
            raw = value_node.text if value_node is not None else None
            if cell_type == "s" and raw is not None:
                try:
                    value: object = strings[int(raw)]
                except (IndexError, ValueError):
                    value = raw
            elif cell_type == "inlineStr":
                value = "".join(
                    node.text or "" for node in cell.iter(f"{XML_NS}t")
                )
            elif cell_type == "e":
                value = None
            else:
                value = raw
                if raw is not None:
                    try:
                        value = Decimal(raw) if "." in raw else int(raw)
                    except (InvalidOperation, ValueError):
                        value = raw
            values[column - 1] = value
        rows.append((row_number, values))
    return rows


def _normal_name(value: str) -> str:
    value = (value or "").upper().replace("Ё", "Е")
    value = re.sub(r"[^0-9A-ZА-Я]+", " ", value)
    return " ".join(value.split())


LEGAL_FORM_WORDS = {
    "ООО", "ОАО", "ЗАО", "АО", "ПАО", "ЧУЗ", "АНО", "ИП", "ГУП", "МУП",
}


def _search_name(value: str) -> str:
    return " ".join(
        token for token in _normal_name(value).split() if token not in LEGAL_FORM_WORDS
    )


def _parse_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    for pattern in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            pass
    # Excel serial date (система 1900, с поправкой на ошибочный 29.02.1900).
    try:
        serial = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if serial > 1:
        return date(1899, 12, 30) + timedelta(days=int(serial))
    return None


def _as_amount(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace(" ", "").replace(",", ".")).quantize(
            Decimal("0.01")
        )
    except (InvalidOperation, ValueError):
        return None


class Command(BaseCommand):
    help = "Создаёт заказы из реестра реализации XLSX."

    def add_arguments(self, parser):
        parser.add_argument("path", type=Path, help="Путь к XLSX-файлу")
        parser.add_argument(
            "--owner",
            type=int,
            help="ID нашей компании; по умолчанию определяется среди активных компаний",
        )
        parser.add_argument(
            "--manager",
            type=int,
            help="ID ответственного менеджера; по умолчанию первый активный staff-пользователь",
        )
        parser.add_argument(
            "--create-missing-clients",
            action="store_true",
            help="Создавать организации с ролью клиента, если их нет в справочнике",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Только проверить строки и сопоставление, не менять базу",
        )

    def _owner(self, owner_id: int | None, title: str) -> Organization:
        if owner_id:
            owner = Organization.objects.filter(
                pk=owner_id, is_own_company=True, is_active=True
            ).first()
            if owner is None:
                raise CommandError("Указанный owner не найден среди активных наших компаний")
            return owner
        title_key = _search_name(title)
        candidates = Organization.objects.filter(is_own_company=True, is_active=True)
        exact = next((item for item in candidates if _search_name(item.name) == title_key), None)
        if exact:
            return exact
        if candidates.count() == 1:
            return candidates.first()
        names = ", ".join(str(item) for item in candidates)
        raise CommandError(
            f"Не удалось однозначно определить нашу компанию ({names}). Используйте --owner."
        )

    def _manager(self, manager_id: int | None):
        User = get_user_model()
        if manager_id:
            manager = User.objects.filter(pk=manager_id, is_active=True).first()
            if manager is None:
                raise CommandError("Указанный manager не найден среди активных пользователей")
            return manager
        manager = User.objects.filter(is_active=True, is_staff=True).order_by("pk").first()
        if manager is None:
            manager = User.objects.filter(is_active=True).order_by("pk").first()
        if manager is None:
            raise CommandError("В системе нет активного пользователя для ответственного")
        return manager

    def _client(self, source_name: str, create_missing: bool, cache: dict[str, Organization]):
        key = _search_name(source_name)
        if not key:
            return None, False
        if key in cache:
            return cache[key], False
        organizations = list(Organization.objects.filter(is_active=True).prefetch_related("roles"))
        exact = next((org for org in organizations if _search_name(org.name) == key), None)
        if exact is None:
            # Разные порядки слов и сокращения (например, «СУРТ ООО» и «ООО "СУРТ"»).
            source_tokens = set(key.split())
            scored = []
            for org in organizations:
                org_tokens = set(_search_name(org.name).split())
                overlap = len(source_tokens & org_tokens)
                if overlap and source_tokens <= org_tokens:
                    scored.append((overlap / len(org_tokens), org))
            exact = max(scored, key=lambda item: item[0])[1] if scored else None
        if exact is None and create_missing:
            exact = Organization.objects.create(
                name=source_name.strip(),
                short_name=source_name.strip(),
                notes="Создано автоматически при импорте реестра реализации XLSX; заполните ИНН и реквизиты.",
                is_active=True,
            )
            OrganizationRole.objects.get_or_create(
                organization=exact,
                role=OrganizationRole.Role.CLIENT,
                defaults={"is_active": True},
            )
        elif exact is not None:
            role, _ = OrganizationRole.objects.get_or_create(
                organization=exact,
                role=OrganizationRole.Role.CLIENT,
                defaults={"is_active": True},
            )
            if not role.is_active:
                role.is_active = True
                role.save(update_fields=["is_active", "updated_at"])
        if exact is not None:
            cache[key] = exact
        return exact, exact is not None and exact.pk not in {
            org.pk for org in organizations
        }

    def handle(self, *args, **options):
        path: Path = options["path"]
        if not path.exists() or path.suffix.lower() != ".xlsx":
            raise CommandError("Укажите существующий файл с расширением .xlsx")
        try:
            rows = read_xlsx_rows(path)
        except (OSError, ValueError, ElementTree.ParseError, KeyError) as exc:
            raise CommandError(f"Не удалось прочитать XLSX: {exc}") from exc
        if len(rows) < 6:
            raise CommandError("В XLSX нет строки заголовков (ожидается строка 6)")

        title = str(rows[0][1][0] or "")
        owner = self._owner(options.get("owner"), title)
        manager = self._manager(options.get("manager"))
        self.stdout.write(f"Наша компания: {owner} (ID {owner.pk}); менеджер: {manager}")

        cache: dict[str, Organization] = {}
        created = skipped = duplicates = missing_clients = invalid = 0
        total = Decimal("0")
        for row_number, values in rows:
            if row_number <= 6:
                continue
            source_no, raw_date, document, raw_document_number, raw_amount, source_name, comment = values
            document_date = _parse_date(raw_date)
            amount = _as_amount(raw_amount)
            source_name = str(source_name or "").strip()
            # Итоги и строки для подписи не являются документами реализации.
            if not source_no or not document_date or amount is None or not source_name:
                invalid += 1
                continue
            try:
                document_number = str(int(raw_document_number))
            except (TypeError, ValueError):
                document_number = str(raw_document_number or "").strip()
            client, was_created = self._client(
                source_name, options["create_missing_clients"] and not options["dry_run"], cache
            )
            if client is None:
                missing_clients += 1
                continue
            if was_created:
                self.stdout.write(self.style.WARNING(f"Строка {row_number}: создан клиент {client}"))
            natural_key = f"{document_date.isoformat()}|{document_number}|{_search_name(source_name)}|{amount}"
            marker = f"Импорт XLSX: {path.name}; ключ: {natural_key}"
            if TransportOrder.objects.filter(notes__contains=marker).exists():
                duplicates += 1
                continue
            note_lines = [
                marker,
                f"Документ источника: {document or 'Реализация'} № {document_number}",
                f"Контрагент в реестре: {source_name}",
                "Маршрут, груз, форма оплаты и ставка НДС в исходном реестре не указаны.",
            ]
            if comment and str(comment).strip():
                note_lines.append(f"Комментарий из реестра: {str(comment).strip()}")
            if options["dry_run"]:
                created += 1
                total += amount
                continue
            with transaction.atomic():
                order = TransportOrder.objects.create(
                    document_date=document_date,
                    owner_company=owner,
                    client=client,
                    manager=manager,
                    rate=amount,
                    currency="RUB",
                    payment_form=TransportOrder.PaymentForm.BANK_WITH_VAT,
                    cargo_name="Услуги по перевозке (импорт из реестра)",
                    notes="\n".join(note_lines),
                )
            created += 1
            total += order.rate

        if missing_clients:
            self.stdout.write(
                self.style.WARNING(
                    f"Строки без сопоставленного клиента: {missing_clients}. "
                    "Повторите с --create-missing-clients."
                )
            )
        prefix = "Проверка завершена" if options["dry_run"] else "Импорт завершён"
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}: заказов {'к созданию' if options['dry_run'] else 'создано'} {created}; "
                f"сумма {total:,.2f} ₽; дублей пропущено {duplicates}; "
                f"некорректных/служебных строк {invalid}."
            )
        )
