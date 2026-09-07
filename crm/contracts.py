from io import BytesIO
from pathlib import Path
import re

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH

from .models import Contract


TEMPLATE_DIRECTORY = Path(__file__).resolve().parent / "contract_templates"
TEMPLATE_FILES = {
    Contract.Kind.CLIENT_FORWARDING: "client_forwarding.docx",
    Contract.Kind.CARRIER_TRANSPORT: "carrier_transport.docx",
    Contract.Kind.SUBCONTRACTOR_FORWARDING: "subcontractor_forwarding.docx",
}

MONTHS = (
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


def russian_date(value):
    return f"«{value.day:02d}» {MONTHS[value.month]} {value.year} г."


def short_date(value):
    return value.strftime("%d.%m.%Y")


def value_or_dash(value):
    return str(value).strip() if value else "—"


def party_address(party):
    return getattr(party, "legal_address", "") or getattr(party, "address", "")


def party_requisites(heading, party, representative):
    inn_kpp = value_or_dash(getattr(party, "tax_id", ""))
    if getattr(party, "kpp", ""):
        inn_kpp += f" / {party.kpp}"
    return "\n".join(
        (
            heading,
            value_or_dash(party.name),
            f"ИНН/КПП: {inn_kpp}",
            f"ОГРН: {value_or_dash(getattr(party, 'ogrn', ''))}",
            f"Адрес: {value_or_dash(party_address(party))}",
            f"р/с: {value_or_dash(getattr(party, 'settlement_account', ''))}",
            f"Банк: {value_or_dash(getattr(party, 'bank_name', ''))}",
            f"БИК: {value_or_dash(getattr(party, 'bik', ''))}",
            f"к/с: {value_or_dash(getattr(party, 'correspondent_account', ''))}",
            f"E-mail: {value_or_dash(getattr(party, 'email', ''))}",
            "",
            f"________________ / {value_or_dash(representative)} /",
        )
    )


def _remove_paragraph(paragraph):
    element = paragraph._element
    element.getparent().remove(element)
    paragraph._p = paragraph._element = None


def _set_paragraph(paragraph, text, bold=False):
    paragraph.clear()
    run = paragraph.add_run(text)
    run.bold = bold


def _contract_roles(contract):
    if contract.kind == Contract.Kind.CLIENT_FORWARDING:
        return {
            "left": "ЭКСПЕДИТОР",
            "right": "КЛИЕНТ",
            "left_role": "Экспедитор",
            "right_role": "Клиент",
            "subtitle": (
                f"{contract.expeditor} — Экспедитор / "
                f"{contract.counterparty_name} — Клиент"
            ),
        }
    if contract.kind == Contract.Kind.CARRIER_TRANSPORT:
        return {
            "left": "ЗАКАЗЧИК",
            "right": "ПЕРЕВОЗЧИК",
            "left_role": "Заказчик",
            "right_role": "Перевозчик",
            "subtitle": (
                f"{contract.expeditor} — Заказчик / "
                f"{contract.counterparty_name} — Перевозчик"
            ),
        }
    return {
        "left": "КЛИЕНТ",
        "right": "ЭКСПЕДИТОР",
        "left_role": "Клиент",
        "right_role": "Экспедитор",
        "subtitle": (
            f"{contract.expeditor} — Клиент / "
            f"{contract.counterparty_name} — привлечённый Экспедитор"
        ),
    }


def _intro_text(contract, roles):
    left_representative = value_or_dash(contract.expeditor_representative)
    right_representative = value_or_dash(contract.counterparty_representative)
    return (
        f"{contract.expeditor.name}, именуемое в дальнейшем «{roles['left_role']}», "
        f"в лице {left_representative}, действующего на основании "
        f"{value_or_dash(contract.expeditor_authority_basis)}, с одной стороны, и "
        f"{contract.counterparty_name}, именуемое в дальнейшем "
        f"«{roles['right_role']}», в лице {right_representative}, действующего на "
        f"основании {value_or_dash(contract.counterparty_authority_basis)}, с другой "
        "стороны, совместно именуемые «Стороны», заключили настоящий Договор."
    )


def build_contract_docx(contract):
    template_path = TEMPLATE_DIRECTORY / TEMPLATE_FILES[contract.kind]
    document = Document(template_path)
    roles = _contract_roles(contract)

    title = document.paragraphs[0]
    title_text = re.sub(r"№\s*_+", f"№ {contract.number}", title.text)
    _set_paragraph(title, title_text, bold=True)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    if len(document.paragraphs) > 1:
        _set_paragraph(document.paragraphs[1], roles["subtitle"])
        document.paragraphs[1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    if len(document.paragraphs) > 2:
        _set_paragraph(document.paragraphs[2], _intro_text(contract, roles))

    if document.tables:
        header_table = document.tables[0]
        header_table.cell(0, 0).text = f"г. {contract.city}"
        header_table.cell(0, 1).text = russian_date(contract.contract_date)

    if len(document.tables) > 1:
        requisites_table = document.tables[1]
        requisites_table.cell(0, 0).text = party_requisites(
            roles["left"], contract.expeditor, contract.expeditor_representative
        )
        requisites_table.cell(0, 1).text = party_requisites(
            roles["right"], contract.counterparty, contract.counterparty_representative
        )

    if contract.valid_until:
        for paragraph in document.paragraphs:
            if "Договор действует" in paragraph.text or "Договор вступает" in paragraph.text:
                text = re.sub(
                    r"до\s+(?:«?_+»?\s+_+\s+20_+\s*г\.|_+)",
                    f"до {short_date(contract.valid_until)}",
                    paragraph.text,
                )
                _set_paragraph(paragraph, text)

    # Служебное примечание из клиентского шаблона не является частью договора.
    for paragraph in list(document.paragraphs):
        if paragraph.text.strip().startswith("Примечание к шаблону") or paragraph.text.strip().startswith(
            "Шаблон подготовлен как коммерческий"
        ):
            _remove_paragraph(paragraph)

    properties = document.core_properties
    properties.title = f"Договор № {contract.number}"
    properties.subject = contract.get_kind_display()
    properties.comments = "Сформирован в Экспедитор CRM из утверждённого шаблона."

    stream = BytesIO()
    document.save(stream)
    stream.seek(0)
    return stream
