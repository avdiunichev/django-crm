from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO
from pathlib import Path
import re

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt
from django.utils import timezone


MONTHS_GENITIVE = (
    "",
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)


def _set_run_font(run, size=10, bold=False, italic=False):
    run.font.name = "Times New Roman"
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "Times New Roman")
    run.font.size = Pt(size)
    run.bold = bold
    run.italic = italic
    return run


def _date_text(value):
    if not value:
        return "«___» ____________ 20___ г."
    return f"«{value.day:02d}» {MONTHS_GENITIVE[value.month]} {value.year} г."


def _value(value, placeholder="________________________________________"):
    if value is None or value == "":
        return placeholder
    return str(value)


def _decimal_text(value):
    if value is None:
        return "________"
    return format(value, "f").rstrip("0").rstrip(".") or "0"


def _money_text(value, currency="RUB"):
    symbols = {"RUB": "₽", "RUR": "₽", "USD": "$", "EUR": "€", "CNY": "¥"}
    try:
        amount = Decimal(value or 0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        amount = Decimal("0.00")
    formatted = f"{amount:,.2f}".replace(",", " ").replace(".", ",")
    return f"{formatted} {symbols.get(str(currency or '').upper(), currency or '')}".strip()


def _date_plain(value):
    return value.strftime("%d.%m.%Y") if value else "не указана"


def _document_number_for_title(number):
    """Keep an embedded date in a user-entered number from duplicating the title date."""
    return re.sub(
        r"\s+от\s+\d{1,2}[./-]\d{1,2}[./-]\d{2,4}(?:\s*г\.)?",
        "",
        str(number or ""),
        flags=re.IGNORECASE,
    ).strip()


def _datetime_window(start, end):
    if not start and not end:
        return "не указано"
    start = timezone.localtime(start) if start else None
    end = timezone.localtime(end) if end else None
    if start and end:
        if start.date() == end.date():
            return f"{start:%d.%m.%Y} г. время {start:%H:%M} {end:%H:%M}"
        return f"{start:%d.%m.%Y %H:%M} — {end:%d.%m.%Y %H:%M}"
    if start:
        return f"{start:%d.%m.%Y %H:%M}"
    return f"до {end:%d.%m.%Y %H:%M}"


def _full_address(city, address):
    if not address:
        return city
    if city and city.casefold() not in address.casefold():
        return f"{city}, {address}"
    return address


def _paragraph(document, text="", *, align=None, space_after=4, size=10):
    paragraph = document.add_paragraph()
    if align is not None:
        paragraph.alignment = align
    paragraph.paragraph_format.space_after = Pt(space_after)
    paragraph.paragraph_format.line_spacing = 1.0
    if text:
        _set_run_font(paragraph.add_run(text), size=size)
    return paragraph


def _section_title(document, title):
    paragraph = _paragraph(document, space_after=3)
    _set_run_font(paragraph.add_run(title), size=10.5, bold=True)
    return paragraph


def _field_row(table, label, value, *, placeholder=None):
    cells = table.add_row().cells
    cells[0].width = Cm(5.2)
    cells[1].width = Cm(12.3)
    cells[0].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    cells[1].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    label_paragraph = cells[0].paragraphs[0]
    value_paragraph = cells[1].paragraphs[0]
    for paragraph in (label_paragraph, value_paragraph):
        paragraph.paragraph_format.space_after = Pt(0)
        paragraph.paragraph_format.space_before = Pt(0)
        paragraph.paragraph_format.line_spacing = 1.0
    _set_run_font(label_paragraph.add_run(label), bold=True)
    shown_value = _value(value, placeholder) if placeholder else _value(value)
    _set_run_font(value_paragraph.add_run(shown_value))
    return cells


def _details_table(document):
    table = document.add_table(rows=0, cols=2)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    return table


def _remove_table_borders(table):
    tbl = table._tbl
    tbl_pr = tbl.tblPr
    borders = tbl_pr.first_child_found_in("w:tblBorders")
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        tbl_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        tag = f"w:{edge}"
        element = borders.find(qn(tag))
        if element is None:
            element = OxmlElement(tag)
            borders.append(element)
        element.set(qn("w:val"), "nil")


def _set_cell_text(cell, text, *, bold=False, size=9, align=None):
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    paragraph = cell.paragraphs[0]
    paragraph.paragraph_format.space_after = Pt(0)
    paragraph.paragraph_format.space_before = Pt(0)
    paragraph.paragraph_format.line_spacing = 1.0
    if align is not None:
        paragraph.alignment = align
    paragraph.clear()
    _set_run_font(paragraph.add_run(str(text or "")), size=size, bold=bold)
    return cell


def _full_organization_name(organization):
    if not organization:
        return "не указано"
    return (
        getattr(organization, "full_name", "")
        or getattr(organization, "name_for_documents", "")
        or getattr(organization, "short_name", "")
        or str(organization)
    )


def _organization_requisites(organization):
    if not organization:
        return "реквизиты не указаны"
    parts = []
    tax_id = getattr(organization, "tax_id", "")
    kpp = getattr(organization, "kpp", "")
    ogrn = getattr(organization, "ogrn", "")
    address = (
        getattr(organization, "formatted_legal_address", "")
        or getattr(organization, "legal_address", "")
        or getattr(organization, "address", "")
    )
    if tax_id:
        parts.append(f"ИНН {tax_id}")
    if kpp:
        parts.append(f"КПП {kpp}")
    if ogrn:
        parts.append(f"ОГРН {ogrn}")
    if address:
        parts.append(address)
    return ", ".join(parts) if parts else "реквизиты не указаны"


def _organization_name_with_inn(organization):
    if not organization:
        return "не указан"
    tax_id = getattr(organization, "tax_id", "")
    suffix = f", ИНН {tax_id}" if tax_id else ", ИНН не указан"
    return f"{_full_organization_name(organization)}{suffix}"


def _organization_director_name(organization):
    if not organization:
        return ""
    director = getattr(organization, "director_name", "") or ""
    if director:
        return director
    for relation_name in ("legacy_expeditors", "legacy_carriers", "legacy_customers"):
        related = getattr(organization, relation_name, None)
        if not related:
            continue
        legacy = related.first()
        if legacy and getattr(legacy, "director_name", ""):
            return legacy.director_name
    return ""


def _contract_signatory_text(contract, side, organization):
    if side == "expeditor":
        representative = (
            getattr(contract, "expeditor_representative", "") if contract else ""
        ) or _organization_director_name(organization)
        basis = (
            getattr(contract, "expeditor_authority_basis", "") if contract else ""
        ) or "Устава"
    else:
        representative = (
            getattr(contract, "counterparty_representative", "") if contract else ""
        ) or _organization_director_name(organization)
        basis = (
            getattr(contract, "counterparty_authority_basis", "") if contract else ""
        ) or "Устава"
    if representative:
        return f"{representative}, действующий(ая) на основании {basis}"
    return "________________________, действующий(ая) на основании ____________"


def _stop_organization_text(stop):
    if not stop:
        return "не указан"
    if stop.organization_id:
        return _organization_name_with_inn(stop.organization)
    return stop.organization_text or "не указан"


def _stop_address(stop):
    if not stop:
        return "не указан"
    if getattr(stop, "address_raw", None):
        return stop.full_address
    if stop.address:
        return _full_address(stop.city, stop.address)
    return stop.city or "не указан"


def _driver_passport_text(driver):
    if not driver:
        return "не указан"
    passport = getattr(driver, "current_passport", None)
    if passport:
        number = " ".join(
            part for part in (passport.series, passport.number) if part
        )
        details = " ".join(
            part
            for part in (
                number,
                passport.issued_by,
                f"от {_date_plain(passport.issue_date)}" if passport.issue_date else "",
            )
            if part
        )
        return details or "паспорт не указан"
    number = " ".join(
        part for part in (driver.passport_series, driver.passport_number) if part
    )
    details = " ".join(
        part
        for part in (
            number,
            driver.passport_issued_by,
            f"от {_date_plain(driver.passport_issue_date)}" if driver.passport_issue_date else "",
        )
        if part
    )
    return details or "паспорт не указан"


def _vehicle_name(vehicle):
    if not vehicle:
        return "не указано"
    title = " ".join(part for part in (vehicle.make, vehicle.model) if part).strip()
    kind = vehicle.get_kind_display() if hasattr(vehicle, "get_kind_display") else ""
    return ", ".join(part for part in (kind, title) if part) or str(vehicle)


def _build_executor_transportation_application_docx_legacy(transportation):
    """Build a printable DOCX application for the selected executor."""

    document = Document()
    section = document.sections[0]
    section.page_width = Cm(21)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(1.25)
    section.bottom_margin = Cm(1.2)
    section.left_margin = Cm(1.3)
    section.right_margin = Cm(1.3)

    normal_style = document.styles["Normal"]
    normal_style.font.name = "Times New Roman"
    normal_style._element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")
    normal_style.font.size = Pt(9)

    link = transportation.active_execution_link()
    assignment = transportation.active_vehicle_assignment()
    executor = link.contractor_party.organization if link else None
    contract = link.contract if link else None
    is_forwarder_instruction = bool(
        link
        and link.contractor_role == "forwarder"
    )
    document_kind = (
        "Поручение экспедитору"
        if is_forwarder_instruction
        else "Заявка на перевозку груза"
    )
    owner_label = "Клиент" if is_forwarder_instruction else "Заказчик"
    executor_label = "Экспедитор-партнёр" if is_forwarder_instruction else "Перевозчик"
    stops = list(transportation.stops.all())

    number = (
        link.instruction_number
        if link and link.instruction_number
        else transportation.number or f"рейс-{transportation.pk}"
    )
    document.core_properties.title = f"{document_kind} {number}"
    document.core_properties.subject = (
        "Поручение привлечённому экспедитору"
        if is_forwarder_instruction
        else "Заявка заказчика перевозчику на перевозку груза"
    )

    title_number = _document_number_for_title(number)
    title = _paragraph(document, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=2)
    _set_run_font(
        title.add_run(
            f"{('ПОРУЧЕНИЕ НА ПЕРЕВОЗКУ' if is_forwarder_instruction else 'ЗАЯВКА НА ПЕРЕВОЗКУ')} № {title_number} "
            f"от {_date_plain(transportation.document_date)} г."
        ),
        size=12,
        bold=True,
    )
    contract_text = (
        f"Основание: договор № {contract.number}"
        if contract
        else "Основание: договор с исполнителем не указан"
    )
    contract_paragraph = _paragraph(document, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=8)
    _set_run_font(contract_paragraph.add_run(contract_text), size=10)
    subtitle = _paragraph(document, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=8)
    _set_run_font(subtitle.add_run("ПОРУЧЕНИЕ НА ПЕРЕВОЗКУ ГРУЗА"), size=11, bold=True)

    parties_table = document.add_table(rows=2, cols=2)
    parties_table.style = "Table Grid"
    parties_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    _set_cell_text(
        parties_table.cell(0, 0),
        owner_label,
        bold=True,
    )
    _set_cell_text(parties_table.cell(0, 1), executor_label, bold=True)
    _set_cell_text(
        parties_table.cell(1, 0),
        f"{_full_organization_name(transportation.owner_company)}\n"
        f"{_organization_requisites(transportation.owner_company)}",
        size=8,
    )
    _set_cell_text(
        parties_table.cell(1, 1),
        f"{_full_organization_name(executor)}\n{_organization_requisites(executor)}",
        size=8,
    )

    _paragraph(document, space_after=4)
    cargo_heading = _paragraph(document, space_after=3)
    _set_run_font(cargo_heading.add_run("01  ИНФОРМАЦИЯ О ГРУЗЕ"), size=10, bold=True)
    cargo_table = document.add_table(rows=2, cols=5)
    cargo_table.style = "Table Grid"
    cargo_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for index, heading in enumerate(("Характер груза", "Вес", "Вид упаковки", "Кол-во", "Стоимость")):
        _set_cell_text(cargo_table.cell(0, index), heading, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
    package_type = transportation.package_type.name if transportation.package_type_id else ""
    quantity = []
    if transportation.total_package_count:
        quantity.append(f"{transportation.total_package_count} мест / паллет")
    cargo_characteristics = "\n".join(
        part for part in (transportation.cargo_name, transportation.cargo_description) if part
    )
    _set_cell_text(cargo_table.cell(1, 0), cargo_characteristics or "не указано")
    _set_cell_text(
        cargo_table.cell(1, 1),
        " · ".join(
            part for part in (
                f"{_decimal_text((transportation.weight_kg or Decimal('0')) / Decimal('1000'))} т.",
                f"{_decimal_text(transportation.volume_m3)} м³" if transportation.volume_m3 else "",
            ) if part
        ),
    )
    _set_cell_text(cargo_table.cell(1, 2), package_type or "не указано")
    _set_cell_text(cargo_table.cell(1, 3), ", ".join(quantity) or "не указано")
    _set_cell_text(
        cargo_table.cell(1, 4),
        _money_text(transportation.cargo_value, transportation.currency)
        if transportation.cargo_value is not None
        else "не указана",
    )

    _paragraph(document, space_after=4)
    route_heading = _paragraph(document, space_after=3)
    _set_run_font(route_heading.add_run("02  МАРШРУТ"), size=10, bold=True)
    route_table = document.add_table(rows=0, cols=3)
    route_table.style = "Table Grid"
    route_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    header = route_table.add_row().cells
    _set_cell_text(header[0], "Маршрут", bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
    header[0].merge(header[1]).merge(header[2])
    route_row = route_table.add_row().cells
    _set_cell_text(route_row[0], transportation.route, align=WD_ALIGN_PARAGRAPH.CENTER)
    route_row[0].merge(route_row[1]).merge(route_row[2])

    def stop_operation_text(stop):
        if stop.kind == stop.Kind.PICKUP:
            return "Погрузка"
        if stop.kind == stop.Kind.DELIVERY:
            return "Выгрузка"
        return stop.get_kind_display()

    def add_stop_rows(stop_list):
        for index, stop in enumerate(stop_list, start=1):
            operation = stop_operation_text(stop)
            spacer = route_table.add_row().cells
            spacer[0].merge(spacer[1]).merge(spacer[2])
            rows = (
                (f"Точка маршрута {index}", operation),
                ("Организация", _stop_organization_text(stop)),
                (f"Адрес ({operation.lower()})", _stop_address(stop)),
                ("Контакт / комментарий", " / ".join(part for part in (stop.contact_phone, stop.contact_name, stop.instructions) if part)),
                (f"Дата ({operation.lower()})", _datetime_window(stop.planned_from, stop.planned_to)),
            )
            for label, value in rows:
                cells = route_table.add_row().cells
                _set_cell_text(cells[0], label, bold=True)
                _set_cell_text(cells[1], value or "не указано")
                cells[1].merge(cells[2])

    add_stop_rows(stops)

    vehicle_heading = _paragraph(document, space_after=3)
    _set_run_font(vehicle_heading.add_run("03  ВОДИТЕЛЬ И ТРАНСПОРТНОЕ СРЕДСТВО"), size=10, bold=True)
    vehicle_header = route_table.add_row().cells
    _set_cell_text(vehicle_header[0], "ТС", bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
    _set_cell_text(vehicle_header[1], "Водитель", bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
    vehicle_header[1].merge(vehicle_header[2])
    vehicle = assignment.vehicle if assignment else None
    trailer = assignment.trailer if assignment else None
    driver = assignment.driver if assignment else None
    row = route_table.add_row().cells
    _set_cell_text(row[0], _vehicle_name(vehicle))
    _set_cell_text(row[1], driver.full_name if driver else "не указан")
    row[1].merge(row[2])
    row = route_table.add_row().cells
    vehicle_numbers = " / ".join(
        part
        for part in (
            vehicle.registration_number if vehicle else "",
            trailer.registration_number if trailer else (assignment.trailer_registration_number if assignment else ""),
        )
        if part
    )
    _set_cell_text(row[0], vehicle_numbers or "не указан")
    _set_cell_text(row[1], _driver_passport_text(driver))
    row[1].merge(row[2])
    row = route_table.add_row().cells
    _set_cell_text(row[0], "-")
    _set_cell_text(row[1], f"Контактный телефон: {driver.phone}" if driver and driver.phone else "Контактный телефон: не указан")
    row[1].merge(row[2])
    row = route_table.add_row().cells
    loading = transportation.loading_method.name if transportation.loading_method_id else ""
    unloading = transportation.unloading_method.name if transportation.unloading_method_id else ""
    _set_cell_text(row[0], "Вид погрузки/выгрузки", bold=True)
    _set_cell_text(row[1], " / ".join(part for part in (loading, unloading) if part) or "не указано")
    row[1].merge(row[2])

    _paragraph(document, space_after=4)
    finance_heading = _paragraph(document, space_after=3)
    _set_run_font(finance_heading.add_run("05  РАСЧЁТЫ"), size=10, bold=True)
    finance_table = document.add_table(rows=2, cols=4)
    finance_table.style = "Table Grid"
    finance_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    cost_label = "Вознаграждение экспедитора" if is_forwarder_instruction else "Стоимость перевозки"
    for index, heading in enumerate((cost_label, "Предоплата", "Форма оплаты", "Срок оплаты")):
        _set_cell_text(finance_table.cell(0, index), heading, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
    vat_text = (
        transportation.executor_vat_rate.name
        if transportation.executor_vat_rate_id
        else "НДС не облагается"
    )
    payment_terms = (
        contract.payment_terms
        if contract and contract.payment_terms
        else (
            f"{transportation.executor_payment_term_days} банковских дней "
            f"от {transportation.get_executor_payment_due_basis_display().lower()}"
            if transportation.executor_payment_term_days
            else "по согласованию сторон"
        )
    )
    _set_cell_text(finance_table.cell(1, 0), _money_text(transportation.executor_amount, transportation.currency))
    _set_cell_text(
        finance_table.cell(1, 1),
        _money_text(transportation.executor_prepayment, transportation.currency)
        if transportation.executor_prepayment is not None
        else "не предусмотрена",
    )
    _set_cell_text(
        finance_table.cell(1, 2),
        f"{transportation.get_executor_payment_form_display()}, {vat_text}",
    )
    _set_cell_text(finance_table.cell(1, 3), payment_terms)

    conditions_heading = _paragraph(document, space_after=3)
    _set_run_font(conditions_heading.add_run("04  ОСНОВНЫЕ УСЛОВИЯ"), size=10, bold=True)
    if is_forwarder_instruction:
        clauses = (
            "Клиент поручает, а Экспедитор-партнёр принимает к исполнению организацию перевозки по условиям настоящего поручения.",
            "Экспедитор-партнёр отвечает за действия привлечённых им лиц и своевременно информирует Клиента о рисках нарушения согласованных сроков.",
            "Стороны несут ответственность в соответствии с договором и законодательством Российской Федерации.",
            "Электронные копии настоящего поручения имеют силу оригинала до обмена оригиналами, если иной порядок не установлен договором.",
        )
    else:
        clauses = (
            "Заказчик поручает, а Перевозчик принимает к исполнению перевозку груза по условиям настоящей заявки.",
            "Перевозчик обеспечивает подачу исправного транспортного средства, сохранность груза и соблюдение согласованных сроков перевозки.",
            "При невозможности подачи транспорта или возникновении задержки Перевозчик незамедлительно уведомляет Заказчика.",
            "Стороны несут ответственность в соответствии с договором и законодательством Российской Федерации. Электронные копии заявки имеют силу оригинала до обмена оригиналами, если иной порядок не установлен договором.",
        )
    for clause in clauses:
        _paragraph(document, clause, size=8, space_after=2)

    signatures = document.add_table(rows=3, cols=2)
    signatures.style = "Table Grid"
    signatures.alignment = WD_TABLE_ALIGNMENT.CENTER
    _remove_table_borders(signatures)
    _set_cell_text(signatures.cell(0, 0), owner_label, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
    _set_cell_text(signatures.cell(0, 1), executor_label, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
    _set_cell_text(signatures.cell(1, 0), _full_organization_name(transportation.owner_company))
    _set_cell_text(signatures.cell(1, 1), _full_organization_name(executor))
    _set_cell_text(
        signatures.cell(2, 0),
        f"{_contract_signatory_text(contract, 'expeditor', transportation.owner_company)}\n"
        "________________ / __________________",
    )
    _set_cell_text(
        signatures.cell(2, 1),
        f"{_contract_signatory_text(contract, 'counterparty', executor)}\n"
        "________________ / __________________",
    )

    stream = BytesIO()
    document.save(stream)
    stream.seek(0)
    return stream


def build_customer_invoice_pdf(record):
    """Build a one-page 1C-style customer invoice from a saved document."""
    from html import escape
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    regular, bold = "Helvetica", "Helvetica-Bold"
    for regular_path, bold_path in (
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    ):
        if Path(regular_path).exists() and Path(bold_path).exists():
            pdfmetrics.registerFont(TTFont("InvoiceRegular", regular_path))
            pdfmetrics.registerFont(TTFont("InvoiceBold", bold_path))
            regular, bold = "InvoiceRegular", "InvoiceBold"
            break

    styles = getSampleStyleSheet()
    body = ParagraphStyle("InvoiceBody", parent=styles["Normal"], fontName=regular, fontSize=8, leading=9.5)
    small = ParagraphStyle("InvoiceSmall", parent=body, fontSize=7, leading=8)
    heading = ParagraphStyle("InvoiceHeading", parent=body, fontName=bold, fontSize=14, leading=17, alignment=1)
    label = ParagraphStyle("InvoiceLabel", parent=small, fontName=bold)

    def p(value, style=body):
        value = "—" if value is None or str(value).strip() == "" else str(value)
        return Paragraph(escape(value).replace("\n", "<br/>"), style)

    def money(value):
        amount = Decimal(value or 0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return f"{amount:,.2f}".replace(",", " ").replace(".", ",")

    def org_line(org):
        if not org:
            return "—"
        bits = [str(org), f"ИНН {org.tax_id}" if org.tax_id else "", f"КПП {org.kpp}" if org.kpp else ""]
        return ", ".join(bit for bit in bits if bit)

    def amount_words(value):
        ones = ("ноль", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять")
        teens = ("десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать", "пятнадцать", "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать")
        tens = ("", "", "двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят", "семьдесят", "восемьдесят", "девяносто")
        hundreds = ("", "сто", "двести", "триста", "четыреста", "пятьсот", "шестьсот", "семьсот", "восемьсот", "девятьсот")
        def group(number, feminine=False):
            result = []
            if number >= 100:
                result.append(hundreds[number // 100]); number %= 100
            if 10 <= number < 20:
                result.append(teens[number - 10]); return result
            if number >= 20:
                result.append(tens[number // 10]); number %= 10
            if number:
                result.append(("одна", "две")[number - 1] if feminine and number in (1, 2) else ones[number])
            return result
        amount = Decimal(value or 0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        integer, kopecks = divmod(int(amount), 100)
        parts = group(integer)
        if integer >= 1000:
            thousands, rest = divmod(integer, 1000)
            parts = group(rest) + (["тысяча"] if thousands == 1 else (["тысячи"] if 2 <= thousands % 10 <= 4 else ["тысяч"]))
        text = " ".join(parts) or "ноль"
        return f"{text.capitalize()} рублей {kopecks:02d} копеек"

    def bank_rows(org):
        account = org.bank_accounts.filter(is_active=True).order_by("-is_primary", "pk").first() if org else None
        return [
            [p("Банк получателя", label), p(account.bank_name if account else getattr(org, "bank_name", "")), p("БИК", label), p(account.bik if account else getattr(org, "bik", ""))],
            [p("Счёт получателя", label), p(account.account_number if account else getattr(org, "settlement_account", "")), p("Корр. счёт", label), p(account.correspondent_account if account else getattr(org, "correspondent_account", ""))],
        ]

    seller, buyer = record.owner_company, record.counterparty
    lines = list(record.lines.select_related("transportation").all())
    if not lines and record.transportation_id:
        lines = list(record.lines.all())
    total = record.amount or sum((line.total_amount for line in lines), Decimal("0"))
    vat = record.vat_amount or sum((line.vat_amount for line in lines), Decimal("0"))
    contract = record.contract
    contract_text = ""
    if contract:
        contract_text = f"Договор № {contract.number or '—'} от {_date_plain(getattr(contract, 'contract_date', None))}"

    stream = BytesIO()
    doc = SimpleDocTemplate(stream, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=12 * mm, bottomMargin=12 * mm)
    story = []
    story.append(Table(bank_rows(seller), colWidths=[30*mm, 75*mm, 32*mm, 48*mm], style=TableStyle([
        ("GRID", (0, 0), (-1, -1), .35, colors.black), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ])))
    story.append(Spacer(1, 6 * mm))
    date_text = record.document_date.strftime("%-d %B %Y") if record.document_date else ""
    months = ("", "января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря")
    if record.document_date:
        date_text = f"{record.document_date.day} {months[record.document_date.month]} {record.document_date.year} г."
    story.append(Paragraph(f"Счет на оплату № {escape(record.display_number or '—')} от {escape(date_text)}", heading))
    story.append(Spacer(1, 4 * mm))
    party_data = [
        [p("Поставщик", label), p(org_line(seller))],
        [p("Адрес поставщика", label), p(getattr(seller, "formatted_legal_address", "") if seller else "")],
        [p("Покупатель", label), p(org_line(buyer))],
        [p("Адрес покупателя", label), p(getattr(buyer, "formatted_legal_address", "") if buyer else "")],
        [p("Контакты", label), p("; ".join(bit for bit in (getattr(seller, "phone", ""), getattr(seller, "email", ""), getattr(buyer, "phone", ""), getattr(buyer, "email", "")) if bit) or "—")],
        [p("Основание", label), p(contract_text or "По рейсу")],
    ]
    story.append(Table(party_data, colWidths=[42*mm, 143*mm], style=TableStyle([
        ("GRID", (0, 0), (-1, -1), .35, colors.black), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ])))
    story.append(Spacer(1, 4 * mm))
    rows = [[p("№", label), p("Товары (работы, услуги)", label), p("Кол-во", label), p("Ед.", label), p("Цена", label), p("Сумма", label)]]
    for index, line in enumerate(lines, 1):
        rows.append([p(str(index)), p(line.service_name), p(money(line.quantity)), p(line.unit), p(money(line.price)), p(money(line.total_amount))])
    if len(rows) == 1:
        rows.append([p("1"), p("Организация транспортной перевозки"), p("1"), p("услуга"), p(money(total)), p(money(total))])
    table = Table(rows, colWidths=[10*mm, 83*mm, 20*mm, 20*mm, 25*mm, 27*mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), .35, colors.black), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"), ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(table)
    totals = [["", p("Итого", label), p(money(total))], ["", p("Без налога (НДС)", label), p(money(total - vat))], ["", p("Всего к оплате", label), p(money(total))]]
    story.append(Table(totals, colWidths=[105*mm, 45*mm, 35*mm], style=TableStyle([
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"), ("LINEABOVE", (1, 2), (-1, 2), .7, colors.black),
        ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2),
    ])))
    story.append(Spacer(1, 3 * mm))
    story.append(p(f"Всего к оплате: {money(total)} {record.currency or 'RUB'}"))
    story.append(p(f"Сумма прописью: {amount_words(total)}"))
    story.append(Spacer(1, 9 * mm))
    story.append(Table([[p("Руководитель ____________________", body), p("Бухгалтер ____________________", body)]], colWidths=[92.5*mm, 92.5*mm], style=TableStyle([("VALIGN", (0,0), (-1,-1), "TOP")])) )
    doc.build(story)
    stream.seek(0)
    return stream


def _build_executor_transportation_application_docx_compact(transportation):
    """Build the compact, print-oriented executor application."""
    document = Document()
    section = document.sections[0]
    section.page_width, section.page_height = Cm(21), Cm(29.7)
    section.top_margin = section.bottom_margin = Cm(1.25)
    section.left_margin = section.right_margin = Cm(1.35)
    normal = document.styles["Normal"]
    normal.font.name = "Arial"
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "Arial")
    normal.font.size = Pt(9)

    link = transportation.active_execution_link()
    assignment = transportation.active_vehicle_assignment()
    executor = link.contractor_party.organization if link else None
    contract = link.contract if link else None
    forwarder = bool(link and link.contractor_role == "forwarder")
    kind = "ПОРУЧЕНИЕ ЭКСПЕДИТОРУ" if forwarder else "ЗАЯВКА НА ПЕРЕВОЗКУ"
    owner_label = "Клиент" if forwarder else "Заказчик"
    executor_label = "Экспедитор-партнёр" if forwarder else "Перевозчик"
    number = link.instruction_number if link and link.instruction_number else transportation.number or f"рейс-{transportation.pk}"

    def heading(text):
        p = _paragraph(document, space_after=3)
        _set_run_font(p.add_run(text.upper()), size=9, bold=True)

    title = _paragraph(document, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=2)
    _set_run_font(title.add_run(f"{kind} №{_document_number_for_title(number)}"), size=14, bold=True)
    p = _paragraph(document, align=WD_ALIGN_PARAGRAPH.LEFT, space_after=10)
    _set_run_font(p.add_run(f"от {_date_plain(transportation.document_date)} г."), size=9)

    meta = document.add_table(rows=2, cols=4)
    meta.style = "Table Grid"; meta.alignment = WD_TABLE_ALIGNMENT.CENTER
    _remove_table_borders(meta)
    for i, text in enumerate(("Рейс", "Статус", "Договор", "Дата перевозки")):
        _set_cell_text(meta.cell(0, i), text, bold=True, size=8, align=WD_ALIGN_PARAGRAPH.CENTER)
    values = (number, transportation.get_status_display(), (f"{contract.number} от {_date_plain(contract.contract_date)}" if contract else "не указан"), f"{_date_plain(transportation.planned_start_date)} — {_date_plain(transportation.planned_end_date)}")
    for i, value in enumerate(values): _set_cell_text(meta.cell(1, i), value, size=8, align=WD_ALIGN_PARAGRAPH.CENTER)
    _paragraph(document, space_after=6)

    heading("Стороны")
    parties = document.add_table(rows=2, cols=2); parties.style = "Table Grid"; parties.alignment = WD_TABLE_ALIGNMENT.CENTER
    _remove_table_borders(parties)
    _set_cell_text(parties.cell(0, 0), owner_label, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
    _set_cell_text(parties.cell(0, 1), executor_label, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
    owner_contact = transportation.client_contact
    executor_contact = transportation.executor_contact
    owner_contact_text = " / ".join(x for x in (getattr(owner_contact, "full_name", ""), getattr(owner_contact, "phone", ""), getattr(owner_contact, "email", "")) if x)
    executor_contact_text = " / ".join(x for x in (getattr(executor_contact, "full_name", ""), getattr(executor_contact, "phone", ""), getattr(executor_contact, "email", "")) if x)
    _set_cell_text(parties.cell(1, 0), f"{_full_organization_name(transportation.owner_company)}\n{_organization_requisites(transportation.owner_company)}\nКонтакт: {owner_contact_text or 'не указан'}", size=8)
    _set_cell_text(parties.cell(1, 1), f"{_full_organization_name(executor)}\n{_organization_requisites(executor)}\nКонтакт: {executor_contact_text or 'не указан'}", size=8)
    _paragraph(document, space_after=6)

    heading("Маршрут и груз")
    route = document.add_table(rows=1, cols=4); route.style = "Table Grid"; route.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, text in enumerate(("Операция", "Адрес", "Дата / время", "Контакт")):
        _set_cell_text(route.cell(0, i), text, bold=True, size=8, align=WD_ALIGN_PARAGRAPH.CENTER)
    for stop in transportation.stops.all():
        row = route.add_row().cells
        handling = str(stop.handling_method) if stop.handling_method else "вид не указан"
        _set_cell_text(row[0], f"{stop.get_kind_display()} · {handling}", size=8)
        _set_cell_text(row[1], _stop_address(stop), size=8)
        _set_cell_text(row[2], _datetime_window(stop.planned_from, stop.planned_to), size=8)
        _set_cell_text(row[3], " / ".join(x for x in (stop.contact_name, stop.contact_phone) if x) or "не указан", size=8)
    cargo = route.add_row().cells
    cargo[0].merge(cargo[3]); _set_cell_text(cargo[0], "Груз: " + " · ".join(x for x in (transportation.cargo_name, transportation.cargo_description, f"{_decimal_text(transportation.weight_kg)} кг", f"{_decimal_text(transportation.volume_m3)} м³" if transportation.volume_m3 else "", f"{transportation.total_package_count} мест" if transportation.total_package_count else "", f"упаковка: {transportation.package_type}" if transportation.package_type_id else "", f"стоимость: {_money_text(transportation.cargo_value, transportation.currency)}" if transportation.cargo_value is not None else "", f"температура: {transportation.temperature_regime}" if transportation.temperature_regime else "", f"ADR: {transportation.adr_class}" if transportation.adr_class else "", f"требования: {transportation.vehicle_requirements}" if transportation.vehicle_requirements else "") if x) or "не указан", size=8)
    _paragraph(document, space_after=6)

    heading("Транспорт")
    vehicle = assignment.vehicle if assignment else None; trailer = assignment.trailer if assignment else None; driver = assignment.driver if assignment else None
    transport = document.add_table(rows=2, cols=4); transport.style = "Table Grid"; transport.alignment = WD_TABLE_ALIGNMENT.CENTER
    _remove_table_borders(transport)
    for i, text in enumerate(("Водитель", "Автомобиль", "Прицеп", "Телефон")):
        _set_cell_text(transport.cell(0, i), text, bold=True, size=8, align=WD_ALIGN_PARAGRAPH.CENTER)
    vals = (driver.full_name if driver else "не указан", _vehicle_name(vehicle), trailer.registration_number if trailer else "не указан", driver.phone if driver and driver.phone else "не указан")
    for i, value in enumerate(vals): _set_cell_text(transport.cell(1, i), value, size=8)
    _paragraph(document, space_after=6)

    heading("Финансовые условия")
    finance = document.add_table(rows=2, cols=5); finance.style = "Table Grid"; finance.alignment = WD_TABLE_ALIGNMENT.CENTER
    _remove_table_borders(finance)
    labels = ("Ставка", "НДС", "Предоплата", "Форма оплаты", "Отсрочка")
    for i, text in enumerate(labels): _set_cell_text(finance.cell(0, i), text, bold=True, size=8, align=WD_ALIGN_PARAGRAPH.CENTER)
    vat = transportation.executor_vat_rate.name if transportation.executor_vat_rate_id else "Без НДС"
    terms = contract.payment_terms if contract and contract.payment_terms else (f"{transportation.executor_payment_term_days} дней" if transportation.executor_payment_term_days else "по согласованию")
    vals = (_money_text(transportation.executor_amount, transportation.currency), vat, _money_text(transportation.executor_prepayment, transportation.currency) if transportation.executor_prepayment is not None else "нет", transportation.get_executor_payment_form_display(), terms)
    for i, value in enumerate(vals): _set_cell_text(finance.cell(1, i), value, size=8, align=WD_ALIGN_PARAGRAPH.CENTER)
    conditions = []
    if transportation.special_requirements: conditions.append("Особые условия: " + transportation.special_requirements)
    if transportation.notes: conditions.append("Основные условия: " + transportation.notes)
    conditions.append("Простои и дополнительные расходы согласовываются сторонами и подтверждаются документально.")
    for condition in conditions:
        _paragraph(document, space_after=2); _set_run_font(document.paragraphs[-1].add_run(condition), size=8)
    _paragraph(document, space_after=4)
    signatures = document.add_table(rows=3, cols=2); signatures.style = "Table Grid"; signatures.alignment = WD_TABLE_ALIGNMENT.CENTER; _remove_table_borders(signatures)
    _set_cell_text(signatures.cell(0, 0), owner_label, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
    _set_cell_text(signatures.cell(0, 1), executor_label, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
    _set_cell_text(signatures.cell(1, 0), _contract_signatory_text(contract, "expeditor", transportation.owner_company), size=8)
    _set_cell_text(signatures.cell(1, 1), _contract_signatory_text(contract, "counterparty", executor), size=8)
    _set_cell_text(signatures.cell(2, 0), "________________ / __________________", size=8)
    _set_cell_text(signatures.cell(2, 1), "________________ / __________________", size=8)
    stream = BytesIO(); document.save(stream); stream.seek(0); return stream


def build_executor_transportation_application_docx(transportation):
    """Fill the approved DOCX template while preserving its visual layout."""
    template_path = Path(__file__).resolve().parent / "assets" / "carrier_application_template.docx"
    if not template_path.exists():
        return _build_executor_transportation_application_docx_compact(transportation)
    document = Document(str(template_path))
    link = transportation.active_execution_link()
    executor = link.contractor_party.organization if link else None
    contract = link.contract if link else None
    assignment = transportation.active_vehicle_assignment()
    driver = assignment.driver if assignment else None
    vehicle = assignment.vehicle if assignment else None

    def replacement_map():
        owner = transportation.owner_company
        stops = list(transportation.stops.all())
        first, last = (stops[0] if stops else None), (stops[-1] if stops else None)
        owner_address = getattr(owner, "formatted_legal_address", "") or "не указан"
        executor_address = getattr(executor, "formatted_legal_address", "") or "не указан"
        owner_contact = transportation.client_contact
        executor_contact = transportation.executor_contact
        owner_contact_text = " / ".join(x for x in (getattr(owner_contact, "full_name", ""), getattr(owner_contact, "phone", "")) if x) or "не указан"
        executor_contact_text = " / ".join(x for x in (getattr(executor_contact, "full_name", ""), getattr(executor_contact, "phone", "")) if x) or "не указан"
        first_date = _date_plain(first.planned_from) if first and first.planned_from else "не указана"
        last_date = _date_plain(last.planned_from) if last and last.planned_from else "не указана"
        first_window = _datetime_window(first.planned_from, first.planned_to) if first else "не указан"
        last_window = _datetime_window(last.planned_from, last.planned_to) if last else "не указан"
        vehicle_name = _vehicle_name(vehicle)
        trailer = assignment.trailer if assignment else None
        vat = transportation.executor_vat_rate.name if transportation.executor_vat_rate_id else "Без НДС"
        payment_terms = contract.payment_terms if contract and contract.payment_terms else (f"{transportation.executor_payment_term_days} дней" if transportation.executor_payment_term_days else "по согласованию")
        values = {
            'ООО "ДЕМО ТРАНС"': _full_organization_name(executor),
            'ООО "НОВЫЙ ПРОЕКТ"': _full_organization_name(owner),
            '0000-000123': transportation.number or f"РС-{transportation.pk}",
            '0000-000321': contract.number if contract else "не указан",
            'Сергей Викторович Образцов': driver.full_name if driver else "не указан",
            'Volvo FH 460': _vehicle_name(vehicle),
            'А000АА 00': vehicle.registration_number if vehicle else "не указан",
            '8 400': _decimal_text(transportation.weight_kg),
            '54': _decimal_text(transportation.volume_m3),
            '24': str(transportation.total_package_count or "не указано"),
            'Бумажная упаковка: коробки и пакеты': transportation.cargo_name or "не указано",
            'Паллет 1,2 х 0,8 м': transportation.package_type.name if transportation.package_type_id else "не указано",
            'ИНН 7804496014 КПП 781401001 ОГРН 1127847212345': _organization_requisites(owner),
            'Адрес: 197349, Санкт-Петербург г., Приморский р-н, Уточкина ул., д. 3, корп. 1 лит. А, оф. 310': f"Адрес: {owner_address}",
            'Контакт: +7 921 926-20-24': f"Контакт: {owner_contact_text}",
            'E-mail: office@newproject-spb.ru': f"E-mail: {getattr(owner, 'email', '') or 'не указан'}",
            'ИНН 0000000000 КПП 000000000 ОГРН 0000000000000': _organization_requisites(executor),
            'Адрес: Санкт-Петербург, ул. Примерная, 10': f"Адрес: {executor_address}",
            'Контакт: +7 000 000-00-01': f"Контакт: {executor_contact_text}",
            'E-mail: transport@example.com': f"E-mail: {getattr(executor, 'email', '') or 'не указан'}",
            '05.10.2026': _date_plain(transportation.planned_start_date) if transportation.planned_start_date else "не указана",
            '06.10.2026': first_date,
            '07.10.2026': last_date,
            '15.10.2026': _date_plain(transportation.planned_end_date) if transportation.planned_end_date else last_date,
            '09:00 – 11:00': first_window,
            '09:00–11:00': first_window,
            'Седельный тягач, DONGFENG': vehicle_name,
            'BE598556': trailer.registration_number if trailer else "не указан",
            '650 000,00 ₽': _money_text(transportation.executor_amount, transportation.currency),
            'НДС 22%': vat,
            '400 000,00 ₽': _money_text(transportation.executor_prepayment, transportation.currency) if transportation.executor_prepayment is not None else "нет",
            '10 дней': payment_terms,
        }
        if first:
            values['Санкт-Петербург, ул. Учебная, 12, склад А, ворота 2'] = _stop_address(first)
        if last:
            values['Иван Примеров +7 000 000-00-03'] = " / ".join(x for x in (last.contact_name, last.contact_phone) if x) or "не указан"
        return {source: str(target) for source, target in values.items() if target}

    mapping = replacement_map()
    def replace_in_paragraph(paragraph):
        # Word frequently splits a visible phrase into several runs. Replace
        # against the complete paragraph text so the approved template keeps
        # its layout while still receiving the live trip values.
        original = "".join(run.text or "" for run in paragraph.runs)
        updated = original
        for source, target in mapping.items():
            updated = updated.replace(source, target)
        if updated != original and paragraph.runs:
            paragraph.runs[0].text = updated
            for run in paragraph.runs[1:]:
                run.text = ""
    for paragraph in document.paragraphs:
        replace_in_paragraph(paragraph)
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    replace_in_paragraph(paragraph)
    stream = BytesIO()
    document.save(stream)
    stream.seek(0)
    return stream


def _build_transportation_waybill_reference_pdf(transportation, data):
    """Fill the supplied two-page Form 1-T PDF without changing its grid."""
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    asset_dir = Path(__file__).resolve().parent / "assets"
    page_images = [asset_dir / "transport_waybill_reference-1.png", asset_dir / "transport_waybill_reference-2.png"]
    if not all(path.exists() for path in page_images):
        return None
    regular_font = "Helvetica"
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    if Path(font_path).exists():
        pdfmetrics.registerFont(TTFont("WaybillReference", font_path)); regular_font = "WaybillReference"
    from reportlab.lib.colors import HexColor
    buffer = BytesIO(); c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    link = transportation.active_execution_link(); executor = link.contractor_party.organization if link else None
    assignment = transportation.active_vehicle_assignment(); driver = assignment.driver if assignment else None
    vehicle = assignment.vehicle if assignment else None; trailer = assignment.trailer if assignment else None
    stops = list(transportation.stops.all()); pickup, delivery = (stops[0] if stops else None), (stops[-1] if stops else None)
    def val(v): return str(v or "—")
    def put(x, y, text, size=7, color="#111111"):
        c.setFont(regular_font, size); c.setFillColor(HexColor(color)); c.drawString(x, y, val(text))
    def multiline(x, y, text, size=6.5, leading=8, max_chars=70):
        words = val(text).split(); line = ""
        for word in words:
            if len(line) + len(word) + 1 > max_chars:
                put(x, y, line, size); y -= leading; line = word
            else: line = f"{line} {word}".strip()
        if line: put(x, y, line, size)
    owner = transportation.owner_company
    c.drawImage(ImageReader(str(page_images[0])), 0, 0, width=width, height=height)
    put(75, 752, _date_plain(data.get("document_date")), 7); put(145, 752, data.get("number"), 7); put(370, 752, _date_plain(data.get("document_date")), 7); put(445, 752, transportation.number, 7)
    multiline(45, 690, f"{_full_organization_name(owner)}, ИНН {getattr(owner, 'tax_id', '')}, {getattr(owner, 'formatted_legal_address', '')}", 6.2)
    multiline(45, 595, f"{_full_organization_name(delivery.organization if delivery and delivery.organization_id else None)} {data.get('consignee_address') or _stop_address(delivery) if delivery else ''}", 6.2)
    multiline(45, 507, f"{transportation.cargo_name}; {transportation.weight_kg or '—'} кг; {transportation.volume_m3 or '—'} м³; мест: {transportation.total_package_count or '—'}", 6.2)
    multiline(45, 394, data.get("accompanying_documents") or "—", 6.2)
    multiline(45, 315, f"{_stop_address(pickup) if pickup else '—'} — {_stop_address(delivery) if delivery else '—'}", 6.2)
    multiline(45, 220, f"{_full_organization_name(executor)}, ИНН {getattr(executor, 'tax_id', '')}; водитель: {driver.full_name if driver else '—'}", 6.2)
    multiline(45, 166, f"{_vehicle_name(vehicle)} {getattr(vehicle, 'registration_number', '')}; прицеп {getattr(trailer, 'registration_number', '')}", 6.2)
    c.showPage()
    c.drawImage(ImageReader(str(page_images[1])), 0, 0, width=width, height=height)
    multiline(45, 735, _stop_address(pickup) if pickup else "—", 6.2)
    multiline(45, 655, _stop_address(delivery) if delivery else "—", 6.2)
    multiline(45, 500, f"{transportation.executor_amount or '—'}; НДС: {transportation.executor_vat_rate.name if transportation.executor_vat_rate_id else 'Без НДС'}; форма: {transportation.get_executor_payment_form_display()}", 6.2)
    c.save(); buffer.seek(0); return buffer


def build_transportation_waybill_pdf(transportation, data):
    """Build a print copy using the structure of the current EТрН form.

    This is deliberately a form-like PDF: values that are only known during
    loading and delivery remain blank for the parties to complete.  It must
    not pretend to be an EDO operator's legally-significant EТрН.
    """
    reference_pdf = _build_transportation_waybill_reference_pdf(transportation, data)
    if reference_pdf is not None:
        return reference_pdf
    from html import escape
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    regular_font = bold_font = "Helvetica"
    for regular_path, bold_path in (
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    ):
        if Path(regular_path).exists() and Path(bold_path).exists():
            pdfmetrics.registerFont(TTFont("WaybillRegular", regular_path))
            pdfmetrics.registerFont(TTFont("WaybillBold", bold_path))
            regular_font, bold_font = "WaybillRegular", "WaybillBold"
            break

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("WaybillTitle", parent=styles["Heading1"], fontName=bold_font, fontSize=12, leading=14, alignment=1, spaceAfter=4)
    value_style = ParagraphStyle("WaybillValue", parent=styles["Normal"], fontName=regular_font, fontSize=7.3, leading=8.6)
    value_small_style = ParagraphStyle("WaybillValueSmall", parent=value_style, fontSize=6.6, leading=7.8)
    section_style = ParagraphStyle("WaybillSection", parent=styles["Heading2"], fontName=bold_font, fontSize=9.6, leading=11, alignment=1)

    def text(value, empty="—"):
        rendered = str(value).strip() if value is not None else ""
        return escape(rendered or empty).replace("\n", "<br/>")

    def as_date(value):
        return value.strftime("%d.%m.%Y") if hasattr(value, "strftime") else text(value)

    page_width = 186 * mm
    grid = colors.HexColor("#c9c9c9")

    def cell(value="", hint="", *, small=False):
        value_markup = text(value, "")
        parts = []
        if value_markup:
            parts.append(f'<font color="#111111">{value_markup}</font>')
        if hint:
            parts.append(f'<font color="#949494">{text(hint, "")}</font>')
        return Paragraph("<br/>".join(parts) or "&nbsp;", value_small_style if small else value_style)

    def boxed(rows, widths, heights=None):
        table = Table(rows, colWidths=widths, rowHeights=heights, hAlign="LEFT")
        table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.35, grid),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        return table

    def numbered_section(number, title, body, *, heights=None):
        table = boxed(
            [[Paragraph(f"{number}. {escape(title)}", section_style)] + [""] * (len(body[0]) - 1)] + body,
            [page_width / len(body[0])] * len(body[0]),
            heights=[7 * mm] + (heights or []),
        )
        table.setStyle(TableStyle([("SPAN", (0, 0), (-1, 0)), ("VALIGN", (0, 0), (-1, 0), "MIDDLE")]))
        return table

    number = data.get("number") or f"ТрН-{transportation.pk}"
    date_value = as_date(data.get("document_date"))
    cargo_volume = f"{transportation.volume_m3} м³" if transportation.volume_m3 else ""
    packages = f"{transportation.total_package_count} мест" if transportation.total_package_count else ""
    vehicle_description = " · ".join(part for part in (data.get("vehicle_registration"), data.get("trailer_registration")) if part) or ""

    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=9 * mm, bottomMargin=11 * mm,
        title=f"Транспортная накладная {number}", author="CRM.Экспедитор",
    )
    story = [
        Paragraph("ТРАНСПОРТНАЯ НАКЛАДНАЯ", title_style),
        Paragraph("Печатная форма по образцу формы 1-Т", ParagraphStyle(
            "WaybillSubtitle", parent=value_style, fontName=regular_font,
            fontSize=6.5, leading=8, alignment=1, textColor=colors.HexColor("#687385"),
            spaceAfter=3,
        )),
    ]
    header = boxed([
        [cell("Транспортная накладная", small=True), cell("Заказ (заявка)", small=True)],
        [cell(f"Дата: {date_value}\n№ {number}\nЭкземпляр № ____"), cell(f"Дата: {date_value}\n№ {transportation.number or '—'}")],
    ], [page_width / 2, page_width / 2], [6 * mm, 14 * mm])
    story.append(header)
    story.append(Spacer(1, 2 * mm))
    story.append(numbered_section("1", "Грузоотправитель", [[
        cell(f"{data.get('shipper_name') or ''}, ИНН {data.get('shipper_inn') or ''}\n{data.get('shipper_address') or ''}", "реквизиты, позволяющие идентифицировать грузоотправителя"),
        cell("", "контактные данные грузоотправителя"),
    ]], heights=[18 * mm]))
    story.append(boxed([[cell("1а. Заказчик услуг по организации перевозки груза (при наличии)", small=True), cell("является экспедитором: да / нет", small=True)], [cell("", "реквизиты заказчика услуг"), cell("", "реквизиты договора транспортной экспедиции")]], [page_width / 2, page_width / 2], [6 * mm, 13 * mm]))
    story.append(numbered_section("2", "Грузополучатель", [[
        cell(f"{data.get('consignee_name') or ''}, ИНН {data.get('consignee_inn') or ''}", "реквизиты, позволяющие идентифицировать грузополучателя"),
        cell(data.get("consignee_address"), "адрес места выгрузки"),
    ]], heights=[15 * mm]))
    story.append(numbered_section("3", "Груз", [[
        cell(data.get("cargo_name"), "наименование груза"), cell("", "состояние груза"), cell(transportation.package_type or "", "способ упаковки"), cell(f"брутто: {data.get('gross_weight_kg') or ''} кг", "масса нетто / брутто"),
    ], [cell("", "вид тары"), cell(packages, "количество грузовых мест"), cell("", "маркировка"), cell(cargo_volume, "объем груза")]], heights=[15 * mm, 14 * mm]))
    story.append(numbered_section("4", "Сопроводительные документы на груз (при наличии)", [[cell(data.get("accompanying_documents") or "", "реквизиты документов, подтверждающих отгрузку товара"), cell("", "реквизиты сопроводительной ведомости")]], heights=[18 * mm]))

    story.append(PageBreak())
    story.append(numbered_section("5", "Указания грузоотправителя по особым условиям перевозки", [[
        cell(data.get("pickup_window"), "маршрут перевозки, дата и время / сроки доставки груза"), cell("", "контактная информация о лицах для переадресовки"),
    ], [cell(data.get("special_conditions") or "", "указания для выполнения фитосанитарных, санитарных и иных требований"), cell("", "температурный режим, пломбирование, запрет перегрузки")]], heights=[16 * mm, 17 * mm]))
    story.append(numbered_section("6", "Перевозчик", [[
        cell(f"{data.get('carrier_name') or ''}, ИНН {data.get('carrier_inn') or ''}\n{data.get('carrier_address') or ''}", "реквизиты, позволяющие идентифицировать перевозчика"),
        cell(f"{data.get('driver_name') or ''}, тел.: {data.get('driver_phone') or ''}", "реквизиты водителя"),
    ]], heights=[18 * mm]))
    story.append(numbered_section("7", "Транспортное средство", [[
        cell(vehicle_description, "тип, марка, грузоподъемность, вместимость"), cell(data.get("vehicle_registration"), "регистрационный номер транспортного средства"),
    ], [cell("", "тип владения и основание владения"), cell(data.get("waybill_number") or "", "номер путевого листа (при наличии)")]], heights=[18 * mm, 14 * mm]))
    story.append(numbered_section("8", "Прием груза", [[
        cell(data.get("shipper_name"), "реквизиты лица, осуществившего погрузку"), cell(data.get("pickup_address"), "наименование владельца инфраструктуры пункта погрузки"),
    ], [cell(data.get("pickup_address"), "адрес места погрузки"), cell(data.get("pickup_window"), "заявленные дата и время подачи транспортного средства"),
    ], [cell("", "фактические дата и время прибытия под погрузку"), cell("", "фактические дата и время убытия"),
    ], [cell(f"{data.get('gross_weight_kg') or ''} кг", "масса груза брутто и метод определения"), cell(packages, "количество грузовых мест, тара и упаковка")]], heights=[14 * mm, 14 * mm, 13 * mm, 14 * mm]))

    story.append(PageBreak())
    story.append(numbered_section("9", "Переадресовка (при наличии)", [[cell("", "дата, вид переадресовки и реквизиты указания"), cell("", "адрес нового пункта выгрузки, новые дата и время")], [cell("", "реквизиты лица, от которого получено указание"), cell("", "реквизиты нового грузополучателя")]], heights=[16 * mm, 14 * mm]))
    story.append(numbered_section("10", "Выдача груза", [[cell(data.get("delivery_address"), "адрес места выгрузки"), cell(data.get("delivery_window"), "заявленные дата и время подачи транспортного средства")], [cell("", "фактические дата и время прибытия"), cell("", "фактические дата и время убытия")], [cell("", "фактическое состояние груза, тары, упаковки, маркировки"), cell(packages, "количество грузовых мест")], [cell("", "масса груза брутто / нетто, плотность груза"), cell("", "оговорки и замечания перевозчика")], [cell("", "должность, подпись, расшифровка подписи грузополучателя"), cell("", "подпись, расшифровка подписи водителя")]], heights=[13 * mm, 12 * mm, 14 * mm, 14 * mm, 14 * mm]))
    story.append(numbered_section("11", "Отметки грузоотправителей, грузополучателей, перевозчиков (при необходимости)", [[cell("", "отметки сторон")]], heights=[16 * mm]))
    story.append(numbered_section("12", "Стоимость перевозки груза (установленная плата) в рублях (при необходимости)", [[cell("", "стоимость перевозки без налога"), cell("", "сумма налога"), cell("", "стоимость перевозки с налогом — всего")], [cell("", "порядок расчета (исчислений) платы") , cell("", "реквизиты составителя первичного учетного документа"), cell("", "реквизиты лица, от которого поступают денежные средства")]], heights=[15 * mm, 18 * mm]))
    story.append(Spacer(1, 3 * mm))
    story.append(boxed([[cell("Грузоотправитель: __________________ / __________________"), cell("Перевозчик: __________________ / __________________")], [cell("Дата и основание полномочий: __________________"), cell("Дата и основание полномочий: __________________")]], [page_width / 2, page_width / 2], [10 * mm, 10 * mm]))

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(regular_font, 6.5)
        canvas.setFillColor(colors.HexColor("#687385"))
        canvas.drawString(12 * mm, 7 * mm, "Печатная форма транспортной накладной · CRM.Экспедитор")
        canvas.drawRightString(A4[0] - 12 * mm, 7 * mm, f"Страница {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    buffer.seek(0)
    return buffer


def _insurance_text(value):
    if value == "yes":
        return "ДА / нет"
    if value == "no":
        return "да / НЕТ"
    return "да / нет (нужное подчеркнуть)"


def build_forwarding_order_docx(shipment, order):
    document = Document()
    section = document.sections[0]
    section.page_width = Cm(21)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(1.35)
    section.bottom_margin = Cm(1.35)
    section.left_margin = Cm(1.55)
    section.right_margin = Cm(1.35)

    normal_style = document.styles["Normal"]
    normal_style.font.name = "Times New Roman"
    normal_style._element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")
    normal_style.font.size = Pt(10)

    document.core_properties.title = f"Экспедиторское поручение {shipment.number}"
    document.core_properties.subject = "Поручение экспедитору"

    contract_number = _value(order.contract_number, "__________")
    header = _paragraph(document, align=WD_ALIGN_PARAGRAPH.RIGHT, space_after=10)
    _set_run_font(header.add_run("Приложение № 3\n"), size=9)
    _set_run_font(
        header.add_run(
            f"к договору транспортной экспедиции № {contract_number}\n"
            f"от {_date_text(order.contract_date)}"
        ),
        size=9,
    )

    title = _paragraph(document, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=2)
    _set_run_font(title.add_run("ПОРУЧЕНИЕ ЭКСПЕДИТОРУ"), size=14, bold=True)
    subtitle = _paragraph(document, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=9)
    _set_run_font(
        subtitle.add_run(
            f"по договору № {contract_number} от {_date_text(order.contract_date)}"
        ),
        size=10,
    )

    _section_title(document, "Грузоотправитель")
    table = _details_table(document)
    _field_row(table, "Наименование", order.shipper_name)
    _field_row(table, "ИНН", order.shipper_tax_id)
    _field_row(table, "Адрес", order.shipper_address)
    _field_row(table, "Контактное лицо", order.shipper_contact_name)
    _field_row(table, "Телефон", order.shipper_phone)

    _section_title(document, "Грузополучатель")
    table = _details_table(document)
    _field_row(table, "Наименование", order.consignee_name)
    _field_row(table, "Адрес", order.consignee_address)
    _field_row(table, "Контактное лицо", order.consignee_contact_name)
    _field_row(table, "Телефон", order.consignee_phone)

    _section_title(document, "Маршрут и время")
    table = _details_table(document)
    _field_row(
        table,
        "Адрес забора груза",
        _full_address(shipment.pickup_city, shipment.pickup_address),
    )
    _field_row(
        table,
        "Адрес доставки груза",
        _full_address(shipment.delivery_city, shipment.delivery_address),
    )
    _field_row(table, "Дата забора груза", _date_text(shipment.pickup_date))
    _field_row(table, "Плановая дата доставки", _date_text(shipment.delivery_date))
    _field_row(table, "Часы работы", order.pickup_hours)

    _section_title(document, "Сведения о грузе")
    table = _details_table(document)
    _field_row(table, "Наименование груза", shipment.cargo_name)
    _field_row(table, "Вид упаковки", order.packaging_type)
    _field_row(table, "Количество мест", order.package_count)
    _field_row(
        table,
        "Вес груза",
        f"{_decimal_text(shipment.weight_kg / 1000)} тонн",
    )
    _field_row(table, "Объём груза", f"{_decimal_text(shipment.volume_m3)} м³")
    dimensions = " × ".join(
        _decimal_text(value)
        for value in (order.cargo_length_m, order.cargo_width_m, order.cargo_height_m)
    )
    _field_row(table, "Габариты груза (Д × Ш × В)", f"{dimensions} м")
    _field_row(table, "Требуемый транспорт", shipment.vehicle_type)
    _field_row(table, "Особые условия и требования", order.special_conditions)
    _field_row(table, "Страхование груза", _insurance_text(order.cargo_insurance))
    _field_row(table, "Плательщик", order.payer)
    _field_row(table, "Место оплаты", order.payment_place)

    _section_title(document, "Важные примечания")
    _paragraph(
        document,
        "Приём поручений осуществляется с 09:00 до 16:00 с понедельника по "
        "пятницу, но не позднее чем за сутки до даты отправки груза.",
        space_after=3,
        size=9,
    )
    duties = (
        "обеспечить надлежащую упаковку груза для его сохранности;",
        "контролировать вес и количество грузовых мест;",
        "надёжно закрепить груз и правильно его разместить;",
        "убедиться, что в грузе отсутствуют запрещённые к перевозке вещества "
        "(едкие, ядовитые, самовозгорающиеся и т. п.).",
    )
    lead = _paragraph(document, space_after=1, size=9)
    _set_run_font(lead.add_run("Грузоотправитель обязан:"), size=9, bold=True)
    for duty in duties:
        paragraph = document.add_paragraph(style="List Bullet")
        paragraph.paragraph_format.left_indent = Cm(0.65)
        paragraph.paragraph_format.space_after = Pt(1)
        paragraph.paragraph_format.line_spacing = 1.0
        _set_run_font(paragraph.add_run(duty), size=9)
    _paragraph(
        document,
        "Грузоотправитель подтверждает, что ознакомлен с действующими тарифами "
        "и несёт ответственность за достоверность указанных сведений.",
        space_after=5,
        size=9,
    )

    _section_title(document, "Подписи сторон")
    signatures = document.add_table(rows=2, cols=2)
    signatures.style = "Table Grid"
    signatures.alignment = WD_TABLE_ALIGNMENT.CENTER
    signature_data = (
        (f"Экспедитор: {shipment.expeditor}", order.expediter_representative),
        ("Клиент (грузоотправитель)", order.client_representative),
    )
    for index, (label, representative) in enumerate(signature_data):
        cell = signatures.cell(0, index)
        paragraph = cell.paragraphs[0]
        _set_run_font(paragraph.add_run(label), bold=True)
        value_cell = signatures.cell(1, index)
        value_paragraph = value_cell.paragraphs[0]
        value_paragraph.paragraph_format.space_after = Pt(0)
        _set_run_font(
            value_paragraph.add_run(
                f"{_value(representative, '________________________')} / "
                "________________________\n(Ф. И. О., должность)                         (подпись)"
            ),
            size=9,
        )

    date_paragraph = _paragraph(document, space_after=5)
    _set_run_font(date_paragraph.add_run("Дата: "), bold=True)
    _set_run_font(date_paragraph.add_run(_date_text(order.order_date)))

    notes = _paragraph(document, space_after=1, size=8)
    _set_run_font(notes.add_run("Примечания по заполнению. "), size=8, bold=True)
    _set_run_font(
        notes.add_run(
            "При бумажном оформлении документ заполняется в двух экземплярах: оригинал передаётся "
            "экспедитору, копия остаётся у клиента. Формы экспедиторских "
            "документов утверждены приказом Минтранса России от 11.02.2008 № 23."
        ),
        size=8,
    )
    electronic = _paragraph(document, space_after=0, size=8)
    _set_run_font(
        electronic.add_run(
            "С 01.09.2026 экспедиторские документы формируются в электронном виде, "
            "кроме установленных случаев бумажного оформления. Сведения из этого "
            "проекта переносятся в применяемый оператором ЭДО формат и подписываются "
            "электронной подписью."
        ),
        size=8,
        italic=True,
    )

    stream = BytesIO()
    document.save(stream)
    stream.seek(0)
    return stream


def _accounting_document(title):
    document = Document()
    section = document.sections[0]
    section.page_width = Cm(21)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(1.35)
    section.bottom_margin = Cm(1.35)
    section.left_margin = Cm(1.45)
    section.right_margin = Cm(1.35)
    normal_style = document.styles["Normal"]
    normal_style.font.name = "Times New Roman"
    normal_style._element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")
    normal_style.font.size = Pt(10)
    document.core_properties.title = title
    return document


def _money(value):
    quantized = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{quantized:,.2f}".replace(",", " ").replace(".", ",")


def _vat_values(total, rate_value):
    total = Decimal(total).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if rate_value == "without_vat":
        return total, Decimal("0"), "Без НДС"
    rate = Decimal(rate_value)
    vat = (
        total * rate / (Decimal("100") + rate)
        if rate
        else Decimal("0")
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return total - vat, vat, f"{rate_value}%"


def _party_details(name, tax_id, kpp, address):
    tax_details = f"ИНН {tax_id or '__________'}"
    if kpp:
        tax_details += f", КПП {kpp}"
    return f"{name}, {tax_details}, адрес: {address or '____________________'}"


def _add_title(document, title, number, document_date):
    paragraph = _paragraph(document, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=9)
    _set_run_font(
        paragraph.add_run(f"{title} № {number} от {_date_text(document_date)}"),
        size=14,
        bold=True,
    )


def _set_table_cell(cell, text, *, bold=False, size=9, align=None):
    paragraph = cell.paragraphs[0]
    paragraph.paragraph_format.space_after = Pt(0)
    paragraph.paragraph_format.space_before = Pt(0)
    if align is not None:
        paragraph.alignment = align
    _set_run_font(paragraph.add_run(str(text)), size=size, bold=bold)


def _add_simple_item_table(document, data, net_amount, vat_amount, vat_label):
    table = document.add_table(rows=2, cols=6)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    headings = ("№", "Наименование услуги", "Кол-во", "Ед.", "Цена", "Сумма")
    for index, heading in enumerate(headings):
        _set_table_cell(
            table.cell(0, index), heading, bold=True, size=8, align=WD_ALIGN_PARAGRAPH.CENTER
        )
    quantity = Decimal(data["quantity"])
    unit_price = (net_amount / quantity).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    values = (
        "1",
        data["service_name"],
        _decimal_text(quantity),
        data["unit"],
        _money(unit_price),
        _money(net_amount),
    )
    for index, value in enumerate(values):
        _set_table_cell(table.cell(1, index), value, size=8)
    total_paragraph = _paragraph(document, align=WD_ALIGN_PARAGRAPH.RIGHT, space_after=1)
    _set_run_font(total_paragraph.add_run(f"Итого без налога: {_money(net_amount)}"), bold=True)
    vat_paragraph = _paragraph(document, align=WD_ALIGN_PARAGRAPH.RIGHT, space_after=1)
    vat_text = "Без НДС" if vat_label == "Без НДС" else f"НДС {vat_label}: {_money(vat_amount)}"
    _set_run_font(vat_paragraph.add_run(vat_text), bold=True)
    final_paragraph = _paragraph(document, align=WD_ALIGN_PARAGRAPH.RIGHT, space_after=7)
    _set_run_font(
        final_paragraph.add_run(f"Всего к оплате: {_money(data['amount'])} {data['currency']}"),
        size=11,
        bold=True,
    )


def _add_tax_item_table(document, data, net_amount, vat_amount, vat_label):
    table = document.add_table(rows=2, cols=9)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    headings = (
        "№",
        "Наименование работ, услуг",
        "Ед.",
        "Кол-во",
        "Цена без НДС",
        "Стоимость без НДС",
        "Ставка",
        "Сумма НДС",
        "Всего",
    )
    for index, heading in enumerate(headings):
        _set_table_cell(
            table.cell(0, index), heading, bold=True, size=6.5,
            align=WD_ALIGN_PARAGRAPH.CENTER,
        )
    quantity = Decimal(data["quantity"])
    unit_price = (net_amount / quantity).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    values = (
        "1",
        data["service_name"],
        data["unit"],
        _decimal_text(quantity),
        _money(unit_price),
        _money(net_amount),
        vat_label,
        "—" if vat_label == "Без НДС" else _money(vat_amount),
        _money(data["amount"]),
    )
    for index, value in enumerate(values):
        _set_table_cell(table.cell(1, index), value, size=6.8)


def _add_signatures(document, profile, *, include_buyer=True):
    table = document.add_table(rows=2, cols=2 if include_buyer else 1)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    headers = ["Исполнитель"]
    values = [profile.director_name]
    if include_buyer:
        headers.append("Заказчик")
        values.append("")
    for index, header in enumerate(headers):
        _set_table_cell(table.cell(0, index), header, bold=True)
        representative = values[index] or "________________________"
        _set_table_cell(
            table.cell(1, index),
            f"{representative} / ________________________\n"
            "               (Ф. И. О.)                         (подпись)",
            size=8,
        )


def build_saved_document_docx(record):
    """Print recorded values without recalculating them from current trip prices."""
    from .accounting_documents import document_counterparty
    from .models import ShipmentDocument

    lines = list(record.lines.select_related("transportation").all())
    trip = record.transportation or (lines[0].transportation if lines else None)
    owner = record.owner_company or (trip.owner_company if trip else None)
    counterparty = record.counterparty or (document_counterparty(trip, record.direction) if trip else None)
    if record.shipment_id:
        owner = owner or record.shipment.expeditor.organization
        counterparty = counterparty or (
            record.shipment.customer.organization if record.direction == "outgoing"
            else getattr(record.shipment.carrier, "organization", None)
        )
    seller, buyer = (owner, counterparty) if record.direction == "outgoing" else (counterparty, owner)
    document = _accounting_document(str(record.display_number))
    title = "СЧЁТ НА ОПЛАТУ" if record.kind == "invoice" else "УНИВЕРСАЛЬНЫЙ ПЕРЕДАТОЧНЫЙ ДОКУМЕНТ"
    _add_title(document, title, record.display_number, record.document_date)
    details = _details_table(document)
    for label, party in (("Поставщик", seller), ("Покупатель", buyer)):
        _field_row(details, label, _party_details(party.name, party.tax_id, party.kpp, party.formatted_legal_address) if party else "Не указан")
    if seller and record.kind == "invoice":
        for label, attr in (("Банк", "bank_name"), ("БИК", "bik"), ("Расчётный счёт", "settlement_account"), ("Корр. счёт", "correspondent_account")):
            _field_row(details, label, getattr(seller, attr, ""))
    if record.contract_id:
        _field_row(details, "Договор", f"№ {record.contract.number} от {_date_text(record.contract.contract_date)}")
    table = document.add_table(rows=1, cols=6)
    table.style = "Table Grid"
    for cell, label in zip(table.rows[0].cells, ("№", "Услуга / рейс", "Количество", "Без НДС", "НДС", "Всего")):
        _set_table_cell(cell, label, bold=True, size=8)
    entries = [(line.service_name + f"\nРейс № {line.transportation.number} · {line.transportation.route}", line.quantity, line.unit, line.amount, line.vat_amount, line.total_amount) for line in lines]
    if not entries:
        total, vat = record.amount or Decimal("0"), record.vat_amount or Decimal("0")
        entries = [(f"Транспортно-экспедиционные услуги · {record.source_number}\n{record.source_route}", 1, "услуга", total - vat, vat, total)]
    for index, (service, quantity, unit, net, vat, total) in enumerate(entries, 1):
        for cell, value in zip(table.add_row().cells, (index, service, f"{quantity} {unit}", _money(net), _money(vat), _money(total))):
            _set_table_cell(cell, str(value), size=8)
    _paragraph(document, f"Всего: {_money(record.amount or Decimal('0'))} {record.currency}. В том числе НДС: {_money(record.vat_amount or Decimal('0'))}.")
    if record.kind == ShipmentDocument.Kind.UPD:
        _paragraph(document, f"Дата передачи услуг: {_date_text(record.document_date)}")
    if seller:
        _add_signatures(document, seller, include_buyer=record.kind == "upd")
    if record.notes:
        _paragraph(document, record.notes)
    stream = BytesIO()
    document.save(stream)
    stream.seek(0)
    return stream


def build_accounting_document_docx(shipment, profile, data):
    kind = data["kind"]
    titles = {
        "invoice": "СЧЁТ НА ОПЛАТУ",
        "act": "АКТ ОКАЗАННЫХ УСЛУГ",
        "upd": "УНИВЕРСАЛЬНЫЙ ПЕРЕДАТОЧНЫЙ ДОКУМЕНТ",
        "vat_invoice": "СЧЁТ-ФАКТУРА",
    }
    title = titles[kind]
    document = _accounting_document(
        f"{title.title()} {data['number']} · {shipment.number}"
    )
    net_amount, vat_amount, vat_label = _vat_values(
        data["amount"], data["vat_rate"]
    )
    currency_code = {"RUB": "643", "USD": "840", "EUR": "978"}[
        data["currency"]
    ]
    seller = _party_details(profile.name, profile.tax_id, profile.kpp, profile.legal_address)
    buyer = _party_details(
        data["buyer_name"], data["buyer_tax_id"], data["buyer_kpp"], data["buyer_address"]
    )

    if kind == "invoice":
        bank_table = _details_table(document)
        _field_row(bank_table, "Банк получателя", profile.bank_name)
        _field_row(bank_table, "БИК", profile.bik)
        _field_row(bank_table, "Корр. счёт", profile.correspondent_account)
        _field_row(bank_table, "Получатель", seller)
        _field_row(bank_table, "Расчётный счёт", profile.settlement_account)
        _add_title(document, title, data["number"], data["document_date"])
        parties = _details_table(document)
        _field_row(parties, "Поставщик", seller)
        _field_row(parties, "Покупатель", buyer)
        _add_simple_item_table(document, data, net_amount, vat_amount, vat_label)
        _paragraph(
            document,
            f"Основание: договор № {_value(data['contract_number'], '________')} "
            f"от {_date_text(data['contract_date'])}; заявка {shipment.number}.",
            space_after=8,
        )
        _add_signatures(document, profile, include_buyer=False)

    elif kind == "act":
        _add_title(document, title, data["number"], data["document_date"])
        details = _details_table(document)
        _field_row(details, "Исполнитель", seller)
        _field_row(details, "Заказчик", buyer)
        _field_row(
            details,
            "Основание",
            f"Договор № {_value(data['contract_number'], '________')} "
            f"от {_date_text(data['contract_date'])}, заявка {shipment.number}",
        )
        _add_simple_item_table(document, data, net_amount, vat_amount, vat_label)
        _paragraph(
            document,
            "Услуги оказаны в полном объёме и в установленный срок. Заказчик "
            "претензий по объёму, качеству и срокам оказания услуг не имеет.",
            space_after=9,
        )
        _add_signatures(document, profile)

    else:
        if kind == "upd":
            function_text = (
                "счёт-фактура и передаточный документ"
                if data["upd_status"] == "1"
                else "передаточный документ"
            )
            function_paragraph = _paragraph(
                document, align=WD_ALIGN_PARAGRAPH.RIGHT, space_after=2
            )
            _set_run_font(
                function_paragraph.add_run(
                    f"Статус: {data['upd_status']} — {function_text}"
                ),
                size=9,
                bold=True,
            )
        _add_title(document, title, data["number"], data["document_date"])
        details = _details_table(document)
        _field_row(details, "Продавец", seller)
        _field_row(details, "Покупатель", buyer)
        _field_row(
            details,
            "Валюта",
            f"{data['currency']} (код {currency_code})",
        )
        _field_row(
            details,
            "Основание передачи",
            f"Договор № {_value(data['contract_number'], '________')} "
            f"от {_date_text(data['contract_date'])}, заявка {shipment.number}",
        )
        _add_tax_item_table(document, data, net_amount, vat_amount, vat_label)
        totals = _paragraph(document, align=WD_ALIGN_PARAGRAPH.RIGHT, space_after=8)
        vat_text = "Без НДС" if vat_label == "Без НДС" else f"в том числе НДС {_money(vat_amount)}"
        _set_run_font(
            totals.add_run(
                f"Всего: {_money(data['amount'])} {data['currency']}, {vat_text}."
            ),
            bold=True,
        )
        if kind == "upd":
            _paragraph(
                document,
                "Содержание факта хозяйственной жизни: услуги оказаны по заявке "
                f"{shipment.number}. Дата оказания услуг: {_date_text(shipment.delivery_date)}.",
                space_after=8,
            )
        _add_signatures(document, profile, include_buyer=kind == "upd")

    if data.get("notes"):
        note = _paragraph(document, space_after=4)
        _set_run_font(note.add_run("Дополнительные сведения: "), bold=True)
        _set_run_font(note.add_run(data["notes"]))
    warning = _paragraph(document, space_after=0, size=8)
    _set_run_font(
        warning.add_run(
            "Редактируемый проект документа. Перед подписанием необходимо проверить "
            "реквизиты, налоговую ставку и применимость формы. Для юридически значимого "
            "электронного обмена используется установленный формат оператора ЭДО."
        ),
        size=8,
        italic=True,
    )

    stream = BytesIO()
    document.save(stream)
    stream.seek(0)
    return stream
