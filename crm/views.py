from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from io import BytesIO
import json
import mimetypes
import re
from urllib.parse import urlencode
from zipfile import ZIP_DEFLATED, ZipFile

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import AccessMixin, LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Count, F, Prefetch, Q, Sum
from django.db.models.deletion import ProtectedError
from django.forms import HiddenInput
from django.http import FileResponse, Http404, JsonResponse
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from django.views.generic import (
    CreateView,
    DetailView,
    FormView,
    ListView,
    TemplateView,
    UpdateView,
    View,
    RedirectView,
)


def _crm_profile(user):
    if not user.is_authenticated:
        return None
    if user.is_staff or user.is_superuser:
        return None
    return getattr(user, "crm_profile", None)


def user_can_access_finance(user):
    if user.is_staff or user.is_superuser:
        return True
    profile = _crm_profile(user)
    return bool(profile and profile.can_access_finance)


def user_can_close_documents(user):
    if user.is_staff or user.is_superuser:
        return True
    profile = _crm_profile(user)
    return bool(profile and profile.can_close_documents)


def user_can_delete_records(user):
    if user.is_staff or user.is_superuser:
        return True
    profile = _crm_profile(user)
    return bool(profile and profile.can_delete_records)


class FinanceAccessMixin(AccessMixin):
    permission_denied_message = "У вас нет доступа к финансовым разделам."

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not user_can_access_finance(request.user):
            return self.handle_no_permission()
        return super().dispatch(request, *args, **kwargs)


def _xlsx_cell_reference(row_index, column_index):
    letters = ""
    column = column_index
    while column:
        column, remainder = divmod(column - 1, 26)
        letters = chr(65 + remainder) + letters
    return f"{letters}{row_index}"


def _xlsx_value(value):
    if value is None:
        return "", "inlineStr"
    if isinstance(value, datetime):
        return value.strftime("%d.%m.%Y %H:%M"), "inlineStr"
    if isinstance(value, date):
        return value.strftime("%d.%m.%Y"), "inlineStr"
    if isinstance(value, Decimal):
        return str(value), "n"
    if isinstance(value, (int, float)):
        return str(value), "n"
    return str(value), "inlineStr"


def _xlsx_sheet_xml(rows):
    from xml.sax.saxutils import escape

    xml_rows = []
    for row_index, row in enumerate(rows, start=1):
        cells = []
        for column_index, value in enumerate(row, start=1):
            text, cell_type = _xlsx_value(value)
            reference = _xlsx_cell_reference(row_index, column_index)
            if cell_type == "n":
                cells.append(f'<c r="{reference}"><v>{text}</v></c>')
            else:
                cells.append(
                    f'<c r="{reference}" t="inlineStr"><is><t>{escape(text)}</t></is></c>'
                )
        xml_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetData>'
        f'{"".join(xml_rows)}'
        '</sheetData>'
        '</worksheet>'
    )


def _xlsx_workbook(sheets):
    from xml.sax.saxutils import escape

    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            + "".join(
                f'<Override PartName="/xl/worksheets/sheet{index}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                for index, _sheet in enumerate(sheets, start=1)
            )
            + "</Types>",
        )
        archive.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>",
        )
        archive.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets>'
            + "".join(
                f'<sheet name="{escape(name[:31])}" sheetId="{index}" r:id="rId{index}"/>'
                for index, (name, _rows) in enumerate(sheets, start=1)
            )
            + "</sheets></workbook>",
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(
                f'<Relationship Id="rId{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{index}.xml"/>'
                for index, _sheet in enumerate(sheets, start=1)
            )
            + "</Relationships>",
        )
        for index, (_name, rows) in enumerate(sheets, start=1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", _xlsx_sheet_xml(rows))
    output.seek(0)
    return output


def _xlsx_response(filename, sheets):
    workbook = _xlsx_workbook(sheets)
    response = HttpResponse(
        workbook.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response

from .dadata import (
    DadataNotConfigured,
    DadataUnavailable,
    find_party_by_inn,
    suggest_addresses,
    suggest_fms_units,
    suggest_person_names,
)
from .deletion import (
    DeletionDependency,
    deletion_dependencies,
    deletion_example,
    perform_safe_delete,
)
from .forms import (
    AccountingDocumentForm,
    BankStatementForm,
    BankStatementLineForm,
    CarrierForm,
    ChatMessageForm,
    ChatMessageEditForm,
    CompanyProfileForm,
    ContractForm,
    CustomerForm,
    DocumentBatchForm,
    DriverForm,
    DriverEmploymentFormSet,
    DriverLicenseFormSet,
    DriverPassportFormSet,
    ForwardingOrderForm,
    OrganizationBankAccountFormSet,
    OrganizationContactFormSet,
    OrganizationForm,
    PaymentForm,
    PlannerTaskForm,
    QuickOrganizationForm,
    ShipmentDocumentForm,
    ShipmentForm,
    TransportOrderForm,
    TransportOrderStopFormSet,
    TransportationChainForm,
    TransportationDocumentForm,
    TransportationIncidentForm,
    VehicleForm,
    VehicleCombinationForm,
)
from .models import (
    BankStatement,
    BankStatementLine,
    Carrier,
    ChatMessage,
    CompanyProfile,
    Contract,
    Customer,
    DocumentBatch,
    DocumentBatchLine,
    Driver,
    DirectConversation,
    ForwardingOrder,
    Organization,
    OrganizationBankAccount,
    OrganizationChange,
    OrganizationContact,
    OrganizationGroup,
    OrganizationRole,
    Payment,
    PlannerTask,
    Shipment,
    ShipmentDocument,
    SettlementMovement,
    TransportOrder,
    TransportOrderStop,
    Transportation,
    TransportationInstruction,
    TransportationIncident,
    TransportationElectronicDocument,
    TransportationStatusEvent,
    TransportationLink,
    TransportationParty,
    TransportationStop,
    TripCharge,
    VATRate,
    VehicleAssignment,
    VehicleCombination,
    Vehicle,
)
from .accounting import (
    advance_transportation_status,
    close_transportation,
    delete_bank_statement,
    post_bank_statement,
    post_transportation,
    unpost_bank_statement,
    unpost_transportation,
    validate_transportation_for_closing,
    validate_transportation_for_posting,
)
from .epd import (
    payload_to_kontur_russian_xml,
    payload_to_kontur_userdata,
    payload_to_xml,
    prepare_documents,
)
from .kontur import KonturNotConfigured, KonturUnavailable, generate_ezz_title_xml
from .orders import assign_order_to_transportation


def parse_crm_date(value):
    """Parse the visible CRM format and legacy ISO values from saved links."""

    for date_format in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, date_format).date()
        except (TypeError, ValueError):
            continue
    return None


def _transportation_balance(transportation, side):
    """Read a settlement balance without extra queries when it was prefetched."""

    movements = getattr(transportation, "planner_settlement_movements", None)
    if movements is None:
        return max(
            transportation.receivable_balance
            if side == SettlementMovement.Side.RECEIVABLE
            else transportation.payable_balance,
            Decimal("0"),
        )
    return max(
        sum(
            (movement.amount for movement in movements if movement.side == side),
            Decimal("0"),
        ),
        Decimal("0"),
    )


def automatic_planner_tasks(transportations, today=None):
    """Build actionable control points from the current state of each trip.

    These records are intentionally not persisted: changing a contract, driver
    or payment immediately removes the corresponding notification and therefore
    cannot produce duplicate automatic tasks in the database.
    """

    today = today or timezone.localdate()
    priority_order = {
        PlannerTask.Priority.URGENT: 0,
        PlannerTask.Priority.HIGH: 1,
        PlannerTask.Priority.NORMAL: 2,
        PlannerTask.Priority.LOW: 3,
    }
    task_labels = dict(PlannerTask.Kind.choices)
    priority_labels = dict(PlannerTask.Priority.choices)
    status_labels = dict(PlannerTask.Status.choices)
    result = []

    def add(transportation, *, title, description, kind, due_date, priority, url=None):
        result.append(
            {
                "automatic": True,
                "title": title,
                "description": description,
                "kind": kind,
                "kind_label": task_labels[kind],
                "status": PlannerTask.Status.TODO,
                "status_label": status_labels[PlannerTask.Status.TODO],
                "priority": priority,
                "priority_label": priority_labels[priority],
                "due_date": due_date,
                "transportation": transportation,
                "url": url or transportation.get_absolute_url(),
            }
        )

    for transportation in transportations:
        if transportation.status == Transportation.Status.CANCELLED:
            continue
        start_date = transportation.planned_start_date
        due_date = start_date or today
        days_to_start = (start_date - today).days if start_date else None
        urgent_start = days_to_start is not None and days_to_start <= 2
        link = transportation.active_execution_link()
        assignment = transportation.active_vehicle_assignment()
        chain_url = reverse(
            "transportation-chain-update", kwargs={"pk": transportation.pk}
        )

        if not link:
            add(
                transportation,
                title="Назначить исполнителя",
                description="В рейсе не выбран перевозчик или привлечённый экспедитор.",
                kind=PlannerTask.Kind.ASSIGNMENT,
                due_date=due_date,
                priority=PlannerTask.Priority.URGENT if urgent_start else PlannerTask.Priority.HIGH,
                url=chain_url,
            )
        else:
            if not link.contract_id:
                add(
                    transportation,
                    title="Создать договор с исполнителем",
                    description="Без договора рейс нельзя безопасно передать исполнителю.",
                    kind=PlannerTask.Kind.DOCUMENT,
                    due_date=due_date,
                    priority=PlannerTask.Priority.URGENT if urgent_start else PlannerTask.Priority.HIGH,
                    url=chain_url,
                )
            if (
                link.contractor_role == TransportationLink.ContractorRole.FORWARDER
                and (not assignment or not assignment.actual_carrier_id)
            ):
                add(
                    transportation,
                    title="Указать фактического перевозчика",
                    description="Для привлечённого экспедитора нужно заполнить конечного перевозчика.",
                    kind=PlannerTask.Kind.ASSIGNMENT,
                    due_date=due_date,
                    priority=PlannerTask.Priority.URGENT if urgent_start else PlannerTask.Priority.HIGH,
                    url=chain_url,
                )
            if not assignment:
                add(
                    transportation,
                    title="Назначить водителя и транспорт",
                    description="В рейсе нет текущего назначения машины.",
                    kind=PlannerTask.Kind.ASSIGNMENT,
                    due_date=due_date,
                    priority=PlannerTask.Priority.URGENT if urgent_start else PlannerTask.Priority.HIGH,
                    url=chain_url,
                )
            else:
                if not assignment.driver_id:
                    add(
                        transportation,
                        title="Назначить водителя",
                        description="Машина назначена, но водитель ещё не выбран.",
                        kind=PlannerTask.Kind.ASSIGNMENT,
                        due_date=due_date,
                        priority=PlannerTask.Priority.URGENT if urgent_start else PlannerTask.Priority.HIGH,
                        url=chain_url,
                    )
                if not assignment.vehicle_id:
                    add(
                        transportation,
                        title="Назначить транспорт",
                        description="Не выбран тягач или автомобиль для рейса.",
                        kind=PlannerTask.Kind.ASSIGNMENT,
                        due_date=due_date,
                        priority=PlannerTask.Priority.URGENT if urgent_start else PlannerTask.Priority.HIGH,
                        url=chain_url,
                    )

        if (
            start_date
            and 0 <= days_to_start <= 3
            and transportation.status
            not in {
                Transportation.Status.LOADING,
                Transportation.Status.IN_TRANSIT,
                Transportation.Status.UNLOADING,
                Transportation.Status.DELIVERED,
                Transportation.Status.DOCUMENTS_RECEIVED,
                Transportation.Status.CUSTOMER_INVOICED,
                Transportation.Status.CLOSED,
            }
            and assignment
            and assignment.driver_id
            and assignment.vehicle_id
        ):
            add(
                transportation,
                title="Проверить готовность к погрузке",
                description="До плановой погрузки осталось не более трёх дней.",
                kind=PlannerTask.Kind.CONTROL,
                due_date=start_date,
                priority=PlannerTask.Priority.HIGH if days_to_start <= 1 else PlannerTask.Priority.NORMAL,
            )

        receivable = _transportation_balance(
            transportation, SettlementMovement.Side.RECEIVABLE
        )
        customer_due = transportation.customer_payment_due_date
        if receivable and customer_due:
            days_to_due = (customer_due - today).days
            if days_to_due < 0:
                add(
                    transportation,
                    title="Проверить просроченную оплату клиента",
                    description=f"Задолженность по рейсу: {receivable:,.2f} {transportation.currency}.",
                    kind=PlannerTask.Kind.PAYMENT,
                    due_date=customer_due,
                    priority=PlannerTask.Priority.URGENT,
                )
            elif days_to_due <= 3:
                add(
                    transportation,
                    title="Контроль срока оплаты клиента",
                    description=f"Срок оплаты наступает через {days_to_due} дн.",
                    kind=PlannerTask.Kind.PAYMENT,
                    due_date=customer_due,
                    priority=PlannerTask.Priority.HIGH if days_to_due <= 1 else PlannerTask.Priority.NORMAL,
                )

        payable = _transportation_balance(
            transportation, SettlementMovement.Side.PAYABLE
        )
        executor_due = transportation.executor_payment_due_date
        if payable and executor_due:
            days_to_due = (executor_due - today).days
            if days_to_due < 0:
                add(
                    transportation,
                    title="Проверить просроченную оплату исполнителю",
                    description=f"К оплате исполнителю: {payable:,.2f} {transportation.currency}.",
                    kind=PlannerTask.Kind.PAYMENT,
                    due_date=executor_due,
                    priority=PlannerTask.Priority.URGENT,
                )
            elif days_to_due <= 3:
                add(
                    transportation,
                    title="Контроль срока оплаты исполнителю",
                    description=f"Срок оплаты наступает через {days_to_due} дн.",
                    kind=PlannerTask.Kind.PAYMENT,
                    due_date=executor_due,
                    priority=PlannerTask.Priority.HIGH if days_to_due <= 1 else PlannerTask.Priority.NORMAL,
                )

    result.sort(
        key=lambda item: (
            item["due_date"] >= today,
            item["due_date"],
            priority_order[item["priority"]],
            item["title"],
        )
    )
    return result


def _audit_value(value):
    """Return a compact JSON-safe and human-readable value for the audit log."""

    if value in (None, ""):
        return ""
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        return value.strftime("%d.%m.%Y %H:%M")
    if isinstance(value, date):
        return value.strftime("%d.%m.%Y")
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {str(key): _audit_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_audit_value(item) for item in value]
    # ModelChoice fields expose an object in cleaned_data but may expose the
    # numeric primary key in initial.  A label is much more useful in history.
    if hasattr(value, "_meta") and hasattr(value, "pk"):
        return str(value)
    return str(value)


def _form_audit_changes(form, include_all=False):
    """Build ``label: {old, new}`` pairs for fields changed by a form."""

    field_names = (
        form.fields.keys()
        if include_all
        else form.changed_data
    )
    changes = {}
    for field_name in field_names:
        if field_name.endswith("_meta") or field_name not in form.fields:
            continue
        field = form.fields[field_name]
        old_value = form.initial.get(field_name, "")
        # Resolve an initial ModelChoice primary key to its display value.
        if (
            old_value not in (None, "")
            and hasattr(field, "queryset")
            and hasattr(field.queryset, "model")
            and not hasattr(old_value, "_meta")
        ):
            try:
                old_value = field.queryset.filter(pk=old_value).first() or old_value
            except (TypeError, ValueError):
                pass
        new_value = form.cleaned_data.get(field_name, "")
        if hasattr(field, "choices") and not hasattr(new_value, "_meta"):
            labels = dict(field.choices)
            old_value = labels.get(str(old_value), old_value)
            new_value = labels.get(str(new_value), new_value)
        if old_value in (None, "---------", ""):
            old_value = ""
        if new_value in (None, "---------", ""):
            new_value = ""
        old_value = _audit_value(old_value)
        new_value = _audit_value(new_value)
        if include_all and old_value == new_value:
            continue
        if old_value == new_value:
            continue
        changes[field.label or field_name] = {
            "old": old_value,
            "new": new_value,
        }
    return changes


def _model_audit_snapshot(instance, fields):
    """Capture selected model fields before a related object is changed."""

    return {
        field: _audit_value(getattr(instance, field, ""))
        for field in fields
    }


def _snapshot_changes(old_snapshot, new_snapshot, labels=None):
    labels = labels or {}
    changes = {}
    for field_name in old_snapshot.keys() | new_snapshot.keys():
        old_value = old_snapshot.get(field_name, "")
        new_value = new_snapshot.get(field_name, "")
        if old_value == new_value:
            continue
        changes[labels.get(field_name, field_name)] = {
            "old": old_value,
            "new": new_value,
        }
    return changes


def _payment_snapshot(payment):
    return {
        "direction": payment.get_direction_display(),
        "amount": _audit_value(payment.amount),
        "payment_date": _audit_value(payment.payment_date),
        "method": payment.get_method_display(),
        "reference": payment.reference or "",
        "notes": payment.notes or "",
    }


def _incident_snapshot(incident):
    return {
        "kind": incident.get_kind_display(),
        "status": incident.get_status_display(),
        "counterparty": str(incident.counterparty) if incident.counterparty else "",
        "occurred_on": _audit_value(incident.occurred_on),
        "title": incident.title or "",
        "description": incident.description or "",
        "financial_impact": incident.get_financial_impact_display(),
        "amount": _audit_value(incident.amount),
        "currency": incident.currency or "",
        "resolution": incident.resolution or "",
        "resolved_on": _audit_value(incident.resolved_on),
    }


def _record_transportation_audit(
    transportation,
    user,
    *,
    comment,
    source="manual",
    changes=None,
    old_status=None,
    new_status=None,
):
    """Write one event to the unified transportation history register."""

    return TransportationStatusEvent.objects.create(
        transportation=transportation,
        old_status=transportation.status if old_status is None else old_status,
        new_status=transportation.status if new_status is None else new_status,
        changed_by=user,
        comment=comment,
        source=source,
        changes=changes or {},
    )


ACTIVE_SHIPMENT_STATUSES = [
    Shipment.Status.NEW,
    Shipment.Status.PLANNED,
    Shipment.Status.LOADING,
    Shipment.Status.IN_TRANSIT,
]

SHIPMENT_SCOPE_LABELS = {
    "active": "Активные заявки",
    "unassigned": "Без перевозчика",
    "revenue": "Заявки с выручкой",
    "margin": "Заявки с положительной маржой",
    "receivables": "Дебиторская задолженность",
    "payables": "Кредиторская задолженность",
}


@login_required
@require_POST
def dadata_party_by_inn(request):
    raw_inn = request.POST.get("inn", "")
    inn = re.sub(r"[\s-]+", "", raw_inn)
    if not re.fullmatch(r"(?:\d{10}|\d{12})", inn):
        return JsonResponse(
            {"error": "Укажите ИНН из 10 цифр для организации или 12 для ИП."},
            status=400,
        )
    try:
        party = find_party_by_inn(inn)
    except DadataNotConfigured as error:
        return JsonResponse({"error": str(error)}, status=503)
    except DadataUnavailable as error:
        return JsonResponse({"error": str(error)}, status=502)
    if party is None:
        return JsonResponse(
            {"error": "Организация с таким ИНН не найдена в DaData."},
            status=404,
        )
    return JsonResponse({"party": party})


@login_required
@require_GET
def organization_defaults(request, pk):
    """Return defaults used when a counterparty is selected in a document."""
    organization = get_object_or_404(Organization, pk=pk, is_active=True)
    payload = {
        "vat_rate_id": organization.default_vat_rate_id,
        "vat_rate_label": str(organization.default_vat_rate) if organization.default_vat_rate_id else "",
        "payment_term_days": organization.payment_term_days,
        "contract_id": None,
        "contract_label": "",
    }
    owner_id = request.GET.get("owner")
    contracts = Contract.objects.filter(
        customer__organization=organization,
        kind=Contract.Kind.CLIENT_FORWARDING,
        status__in=[Contract.Status.READY, Contract.Status.SIGNED],
    ).order_by("-status", "-contract_date")
    if owner_id and owner_id.isdigit():
        contracts = contracts.filter(expeditor__organization_id=owner_id)
    contract = contracts.first()
    if contract:
        payload["contract_id"] = contract.pk
        payload["contract_label"] = str(contract)
        if contract.vat_rate_id and not payload["vat_rate_id"]:
            payload["vat_rate_id"] = contract.vat_rate_id
            payload["vat_rate_label"] = str(contract.vat_rate)
        if contract.payment_term_days and not payload["payment_term_days"]:
            payload["payment_term_days"] = contract.payment_term_days
    return JsonResponse(payload)


@login_required
@require_GET
def dadata_address_suggestions(request):
    query = " ".join(request.GET.get("q", "").split())
    city = " ".join(request.GET.get("city", "").split())
    if len(query) < 3:
        return JsonResponse({"suggestions": []})
    if len(query) > 300 or len(city) > 120:
        return JsonResponse(
            {"error": "Адресный запрос слишком длинный."},
            status=400,
        )
    try:
        suggestions = suggest_addresses(query, city=city, count=10)
    except DadataNotConfigured as error:
        return JsonResponse({"error": str(error)}, status=503)
    except DadataUnavailable as error:
        return JsonResponse({"error": str(error)}, status=502)
    return JsonResponse({"suggestions": suggestions})


@login_required
@require_GET
def dadata_fio_suggestions(request):
    query = " ".join(request.GET.get("q", "").split())
    part = request.GET.get("part", "").upper()
    if len(query) < 2:
        return JsonResponse({"suggestions": []})
    if len(query) > 300 or part not in {"SURNAME", "NAME", "PATRONYMIC"}:
        return JsonResponse({"error": "Некорректный запрос ФИО."}, status=400)
    try:
        suggestions = suggest_person_names(query, part=part, count=10)
    except DadataNotConfigured as error:
        return JsonResponse({"error": str(error)}, status=503)
    except DadataUnavailable as error:
        return JsonResponse({"error": str(error)}, status=502)
    return JsonResponse({"suggestions": suggestions})


@login_required
@require_GET
def dadata_fms_unit_suggestions(request):
    query = " ".join(request.GET.get("q", "").split())
    if len(query) < 2:
        return JsonResponse({"suggestions": []})
    if len(query) > 300:
        return JsonResponse({"error": "Запрос слишком длинный."}, status=400)
    try:
        suggestions = suggest_fms_units(query, count=10)
    except DadataNotConfigured as error:
        return JsonResponse({"error": str(error)}, status=503)
    except DadataUnavailable as error:
        return JsonResponse({"error": str(error)}, status=502)
    return JsonResponse({"suggestions": suggestions})


@login_required
@require_GET
def organization_check_inn(request):
    inn = re.sub(r"\D", "", request.GET.get("inn", ""))
    if len(inn) not in {10, 12}:
        return JsonResponse(
            {"error": "Укажите ИНН из 10 цифр для организации или 12 для ИП."},
            status=400,
        )
    organizations = Organization.objects.filter(tax_id=inn)
    exclude_id = request.GET.get("exclude", "").strip()
    if exclude_id.isdigit():
        organizations = organizations.exclude(pk=exclude_id)
    organization = organizations.first()
    if not organization:
        return JsonResponse({"exists": False, "inn": inn})
    return JsonResponse(
        {
            "exists": True,
            "inn": inn,
            "organization": {
                "id": organization.pk,
                "name": str(organization),
                "url": organization.get_absolute_url(),
            },
        }
    )


def get_expeditor_filter(request):
    expeditor_id = request.GET.get("expeditor", "").strip()
    if expeditor_id.isdigit() and CompanyProfile.objects.filter(
        pk=expeditor_id
    ).exists():
        return expeditor_id
    return ""


def get_currency_filter(request, default=""):
    currency = request.GET.get("currency", default).strip().upper()
    return currency if currency in {"RUB", "USD", "EUR"} else default


@login_required
def carrier_resources(request):
    carrier_id = request.GET.get("carrier")
    if not carrier_id or not carrier_id.isdigit():
        return JsonResponse({"drivers": [], "vehicles": []})
    drivers = Driver.objects.filter(
        Q(carrier_id=carrier_id)
        | Q(employments__carrier_id=carrier_id, employments__is_active=True),
        is_active=True,
    ).distinct()
    vehicles = Vehicle.objects.filter(carrier_id=carrier_id, is_active=True)
    return JsonResponse(
        {
            "drivers": [
                {"id": driver.pk, "label": driver.full_name} for driver in drivers
            ],
            "vehicles": [
                {
                    "id": vehicle.pk,
                    "label": f"{vehicle.registration_number} · {vehicle.make} {vehicle.model}".strip(),
                }
                for vehicle in vehicles
            ],
        }
    )


@login_required
def organization_resources(request):
    organization_id = request.GET.get("organization", "")
    if not organization_id.isdigit():
        return JsonResponse(
            {"drivers": [], "vehicles": [], "trailers": [], "combinations": []}
        )
    drivers = Driver.objects.filter(
        Q(carrier__organization_id=organization_id)
        | Q(
            employments__carrier__organization_id=organization_id,
            employments__is_active=True,
        ),
        is_active=True,
    ).distinct()
    vehicles = Vehicle.objects.filter(
        carrier__organization_id=organization_id, is_active=True
    )
    combinations = VehicleCombination.objects.filter(
        tractor__carrier__organization_id=organization_id,
        is_active=True,
    ).select_related("tractor", "trailer")
    return JsonResponse(
        {
            "drivers": [
                {"id": driver.pk, "label": driver.full_name} for driver in drivers
            ],
            "vehicles": [
                {
                    "id": vehicle.pk,
                    "label": f"{vehicle.registration_number} · {vehicle.make} {vehicle.model}".strip(),
                }
                for vehicle in vehicles.exclude(
                    kind__in=[Vehicle.Kind.TRAILER, Vehicle.Kind.SEMITRAILER]
                )
            ],
            "trailers": [
                {
                    "id": vehicle.pk,
                    "label": f"{vehicle.registration_number} · {vehicle.make} {vehicle.model}".strip(),
                }
                for vehicle in vehicles.filter(
                    kind__in=[Vehicle.Kind.TRAILER, Vehicle.Kind.SEMITRAILER]
                )
            ],
            "combinations": [
                {
                    "id": combination.pk,
                    "label": str(combination),
                    "tractor_id": combination.tractor_id,
                    "trailer_id": combination.trailer_id,
                }
                for combination in combinations
            ],
        }
    )


class QuickOrganizationCreateView(LoginRequiredMixin, View):
    template_name = "crm/includes/quick_create_form.html"

    def get_required_role(self):
        role = self.request.GET.get("role", self.request.POST.get("required_role", ""))
        return (
            role
            if role in OrganizationRole.Role.values
            else OrganizationRole.Role.CLIENT
        )

    def get_form(self, data=None):
        return QuickOrganizationForm(
            data=data,
            required_role=self.get_required_role(),
        )

    def get_context(self, form):
        role = self.get_required_role()
        return {
            "form": form,
            "quick_kind": "organization",
            "form_title": f"Новый контрагент · {OrganizationRole.Role(role).label}",
            "form_description": (
                "Контрагент будет сразу добавлен в заявку и единый справочник."
            ),
            "required_role": role,
            "action_url": f"{reverse_lazy('quick-organization-create')}?role={role}",
        }

    def get(self, request, *args, **kwargs):
        form = self.get_form()
        return render(request, self.template_name, self.get_context(form))

    def post(self, request, *args, **kwargs):
        form = self.get_form(request.POST)
        if form.is_valid():
            organization = form.save()
            OrganizationChange.objects.create(
                organization=organization,
                changed_by=request.user if request.user.is_authenticated else None,
                action=OrganizationChange.Action.CREATE,
                changes={
                    "name": {"old": None, "new": organization.name},
                    "tax_id": {"old": None, "new": organization.tax_id},
                    "roles": {"old": [], "new": sorted(organization.role_values)},
                },
            )
            return JsonResponse(
                {
                    "ok": True,
                    "item": {
                        "id": organization.pk,
                        "label": (
                            f"{organization} · ИНН {organization.tax_id}"
                            if organization.tax_id
                            else str(organization)
                        ),
                        "roles": organization.role_values,
                    },
                }
            )
        return render(
            request,
            self.template_name,
            self.get_context(form),
            status=422,
        )


class QuickCarrierResourceCreateView(LoginRequiredMixin, View):
    template_name = "crm/includes/quick_create_form.html"
    form_class = None
    quick_kind = ""
    form_title = ""
    form_description = ""

    def get_organization(self):
        organization_id = self.request.GET.get(
            "organization", self.request.POST.get("organization", "")
        )
        return get_object_or_404(
            Organization.objects.filter(
                is_active=True,
                roles__role=OrganizationRole.Role.CARRIER,
                roles__is_active=True,
            ).distinct(),
            pk=organization_id,
        )

    def get_carrier(self):
        return get_object_or_404(
            Carrier,
            organization=self.get_organization(),
            is_active=True,
        )

    def get_form(self, data=None):
        carrier = self.get_carrier()
        if data is not None:
            data = data.copy()
            data["carrier"] = str(carrier.pk)
        form = self.form_class(data=data, initial={"carrier": carrier.pk})
        form.fields["carrier"].widget = HiddenInput()
        return form

    def configure_form(self, form):
        return form

    def item_payload(self, instance):
        raise NotImplementedError

    def get_context(self, form):
        organization = self.get_organization()
        return {
            "form": self.configure_form(form),
            "quick_kind": self.quick_kind,
            "form_title": self.form_title,
            "form_description": self.form_description,
            "organization": organization,
            "organization_id": organization.pk,
            "resource_kind": self.request.GET.get("resource_kind", ""),
            "action_url": self.request.get_full_path(),
        }

    def get(self, request, *args, **kwargs):
        form = self.get_form()
        return render(request, self.template_name, self.get_context(form))

    def post(self, request, *args, **kwargs):
        form = self.configure_form(self.get_form(request.POST))
        if form.is_valid():
            instance = form.save()
            return JsonResponse({"ok": True, "item": self.item_payload(instance)})
        return render(
            request,
            self.template_name,
            self.get_context(form),
            status=422,
        )


class QuickDriverCreateView(QuickCarrierResourceCreateView):
    form_class = DriverForm
    quick_kind = "driver"
    form_title = "Новый водитель"
    form_description = "Водитель будет привязан к выбранному перевозчику."

    def configure_form(self, form):
        form.fields.pop("additional_carriers", None)
        return form

    def item_payload(self, driver):
        return {
            "id": driver.pk,
            "label": f"{driver.full_name} · В/У {driver.license_number}",
        }


class QuickVehicleCreateView(QuickCarrierResourceCreateView):
    form_class = VehicleForm
    quick_kind = "vehicle"
    form_title = "Новый транспорт"
    form_description = "Транспорт будет привязан к выбранному перевозчику."

    def configure_form(self, form):
        resource_kind = self.request.GET.get("resource_kind", "vehicle")
        if resource_kind == "trailer":
            allowed = {Vehicle.Kind.TRAILER, Vehicle.Kind.SEMITRAILER}
            form.fields["kind"].choices = [
                choice for choice in Vehicle.Kind.choices if choice[0] in allowed
            ]
            if not form.is_bound:
                form.initial["kind"] = Vehicle.Kind.SEMITRAILER
        else:
            excluded = {Vehicle.Kind.TRAILER, Vehicle.Kind.SEMITRAILER}
            form.fields["kind"].choices = [
                choice for choice in Vehicle.Kind.choices if choice[0] not in excluded
            ]
            if not form.is_bound:
                form.initial["kind"] = Vehicle.Kind.TRACTOR
        return form

    def item_payload(self, vehicle):
        vehicle_name = " ".join(
            part for part in (vehicle.make, vehicle.model) if part
        )
        return {
            "id": vehicle.pk,
            "label": " · ".join(
                part for part in (vehicle.registration_number, vehicle_name) if part
            ),
        }


def chat_user_name(user):
    return user.get_full_name() or user.username


def conversation_for_user(request, pk):
    queryset = DirectConversation.objects.select_related(
        "user_low", "user_high"
    ).filter(Q(user_low=request.user) | Q(user_high=request.user))
    return get_object_or_404(queryset, pk=pk)


def chat_message_payload(message, user):
    attachment = None
    if message.attachment:
        size = message.attachment_size
        if size >= 1024 * 1024:
            size_label = f"{size / (1024 * 1024):.1f} МБ"
        elif size >= 1024:
            size_label = f"{size / 1024:.0f} КБ"
        else:
            size_label = f"{size} Б"
        attachment = {
            "name": message.attachment_filename,
            "size": size_label,
            "url": message.get_attachment_url(),
        }
    is_mine = message.sender_id == user.pk
    return {
        "id": message.pk,
        "text": message.text,
        "sender": chat_user_name(message.sender),
        "is_mine": is_mine,
        "created_at": timezone.localtime(message.created_at).strftime("%H:%M"),
        "edited": bool(message.edited_at),
        "attachment": attachment,
        "edit_url": message.get_absolute_url() if is_mine else "",
        "delete_url": message.get_delete_url() if is_mine else "",
    }


class ChatView(LoginRequiredMixin, TemplateView):
    template_name = "crm/chat.html"

    @property
    def current_conversation(self):
        if not hasattr(self, "_current_conversation"):
            pk = self.kwargs.get("pk")
            self._current_conversation = (
                conversation_for_user(self.request, pk) if pk else None
            )
        return self._current_conversation

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        current = self.current_conversation
        if current:
            current.messages.filter(read_at__isnull=True).exclude(
                sender=self.request.user
            ).update(read_at=timezone.now())

        conversations = DirectConversation.objects.select_related(
            "user_low", "user_high"
        ).filter(Q(user_low=self.request.user) | Q(user_high=self.request.user))
        conversation_rows = []
        for conversation in conversations:
            conversation_rows.append(
                {
                    "conversation": conversation,
                    "other_user": conversation.other_participant(self.request.user),
                    "last_message": conversation.messages.select_related(
                        "sender"
                    ).last(),
                    "unread_count": conversation.messages.filter(
                        read_at__isnull=True
                    ).exclude(sender=self.request.user).count(),
                }
            )

        current_messages = []
        current_other_user = None
        if current:
            current_messages = list(
                current.messages.select_related("sender").order_by(
                    "-created_at", "-pk"
                )[:100]
            )
            current_messages.reverse()
            current_other_user = current.other_participant(self.request.user)

        context.update(
            {
                "conversation_rows": conversation_rows,
                "current_conversation": current,
                "current_messages": current_messages,
                "current_other_user": current_other_user,
                "available_users": get_user_model().objects.filter(
                    is_active=True
                ).exclude(pk=self.request.user.pk).order_by(
                    "first_name", "last_name", "username"
                ),
                "message_form": ChatMessageForm(),
            }
        )
        return context


class ChatStartView(LoginRequiredMixin, View):
    def post(self, request):
        other_user = get_object_or_404(
            get_user_model().objects.filter(is_active=True).exclude(pk=request.user.pk),
            pk=request.POST.get("user_id"),
        )
        conversation, _ = DirectConversation.get_or_create_between(
            request.user, other_user
        )
        return redirect(conversation)


class ChatSendMessageView(LoginRequiredMixin, View):
    def post(self, request, pk):
        conversation = conversation_for_user(request, pk)
        form = ChatMessageForm(request.POST, request.FILES)
        if form.is_valid():
            message = form.save(commit=False)
            message.conversation = conversation
            message.sender = request.user
            message.save()
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return JsonResponse(
                    {"message": chat_message_payload(message, request.user)}
                )
            return redirect(conversation)
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            error = next(
                (
                    errors[0]
                    for field_errors in form.errors.values()
                    if (errors := list(field_errors))
                ),
                "Не удалось отправить сообщение.",
            )
            return JsonResponse(
                {"error": error},
                status=400,
            )
        error = next(iter(form.errors.values()))[0]
        messages.error(request, error)
        return redirect(conversation)


class ChatMessagesView(LoginRequiredMixin, View):
    def get(self, request, pk):
        conversation = conversation_for_user(request, pk)
        after_raw = request.GET.get("after", "0")
        after_id = int(after_raw) if after_raw.isdigit() else 0
        conversation.messages.filter(read_at__isnull=True).exclude(
            sender=request.user
        ).update(read_at=timezone.now())
        if request.GET.get("sync") == "1":
            new_messages = list(
                conversation.messages.select_related("sender").order_by(
                    "-created_at", "-pk"
                )[:100]
            )
            new_messages.reverse()
            full_sync = True
        else:
            new_messages = conversation.messages.select_related("sender").filter(
                pk__gt=after_id
            )[:100]
            full_sync = False
        return JsonResponse(
            {
                "messages": [
                    chat_message_payload(message, request.user)
                    for message in new_messages
                ],
                "full_sync": full_sync,
            }
        )


class ChatMessageUpdateView(LoginRequiredMixin, UpdateView):
    model = ChatMessage
    form_class = ChatMessageEditForm
    template_name = "crm/chat_message_form.html"
    context_object_name = "message"

    def get_queryset(self):
        conversation_for_user(self.request, self.kwargs["conversation_pk"])
        return ChatMessage.objects.select_related(
            "conversation", "sender"
        ).filter(
            conversation_id=self.kwargs["conversation_pk"],
            sender=self.request.user,
        )

    def form_valid(self, form):
        form.instance.edited_at = timezone.now()
        messages.success(self.request, "Сообщение изменено.")
        return super().form_valid(form)

    def get_success_url(self):
        return self.object.conversation.get_absolute_url()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["conversation"] = self.object.conversation
        return context


class ChatMessageDeleteView(LoginRequiredMixin, View):
    template_name = "crm/chat_message_confirm_delete.html"

    def get_object(self):
        conversation = conversation_for_user(
            self.request, self.kwargs["conversation_pk"]
        )
        return get_object_or_404(
            ChatMessage.objects.select_related("conversation", "sender"),
            pk=self.kwargs["pk"],
            conversation=conversation,
            sender=self.request.user,
        )

    def get(self, request, *args, **kwargs):
        from django.shortcuts import render

        message = self.get_object()
        return render(
            request,
            self.template_name,
            {"message": message, "conversation": message.conversation},
        )

    def post(self, request, *args, **kwargs):
        message = self.get_object()
        conversation = message.conversation
        message.delete()
        messages.success(request, "Сообщение удалено.")
        return redirect(conversation)


class ChatMessageAttachmentView(LoginRequiredMixin, View):
    def get(self, request, conversation_pk, pk):
        conversation = conversation_for_user(request, conversation_pk)
        message = get_object_or_404(
            ChatMessage,
            pk=pk,
            conversation=conversation,
        )
        if not message.attachment:
            raise Http404("Файл не найден.")
        try:
            stream = message.attachment.open("rb")
        except FileNotFoundError as error:
            raise Http404("Файл не найден.") from error
        content_type = (
            mimetypes.guess_type(message.attachment_filename)[0]
            or "application/octet-stream"
        )
        return FileResponse(
            stream,
            as_attachment=True,
            filename=message.attachment_filename,
            content_type=content_type,
        )


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "crm/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        current_expeditor = get_expeditor_filter(self.request)
        current_currency = get_currency_filter(self.request, default="RUB")
        shipments = Shipment.objects.select_related(
            "expeditor", "customer", "carrier", "driver", "vehicle", "manager"
        ).prefetch_related("payments")
        if current_expeditor:
            shipments = shipments.filter(expeditor_id=current_expeditor)
        financial_shipments = list(
            shipments.exclude(status=Shipment.Status.CANCELLED).filter(
                currency=current_currency
            )
        )
        revenue = sum(
            (shipment.customer_price for shipment in financial_shipments),
            Decimal("0"),
        )
        costs = sum(
            (shipment.carrier_price for shipment in financial_shipments),
            Decimal("0"),
        )
        receivables = sum(
            (
                max(shipment.receivable_balance, Decimal("0"))
                for shipment in financial_shipments
            ),
            Decimal("0"),
        )
        payables = sum(
            (
                max(shipment.payable_balance, Decimal("0"))
                for shipment in financial_shipments
            ),
            Decimal("0"),
        )
        overdue_receivables = sum(
            (
                max(shipment.receivable_balance, Decimal("0"))
                for shipment in financial_shipments
                if shipment.receivable_state == Shipment.PaymentStatus.OVERDUE
            ),
            Decimal("0"),
        )
        overdue_payables = sum(
            (
                max(shipment.payable_balance, Decimal("0"))
                for shipment in financial_shipments
                if shipment.payable_state == Shipment.PaymentStatus.OVERDUE
            ),
            Decimal("0"),
        )
        planner_transportations = (
            Transportation.objects.exclude(status=Transportation.Status.CANCELLED)
            .filter(currency=current_currency)
            .select_related("manager")
            .prefetch_related(
                Prefetch(
                    "execution_links",
                    queryset=TransportationLink.objects.filter(is_active=True)
                    .select_related("contractor_party__organization", "contract")
                    .order_by("sequence"),
                ),
                Prefetch(
                    "vehicle_assignments",
                    queryset=VehicleAssignment.objects.filter(is_active=True)
                    .select_related("actual_carrier", "driver", "vehicle", "trailer", "combination")
                    .order_by("-created_at"),
                ),
                Prefetch("settlement_movements", to_attr="planner_settlement_movements"),
                "stops",
            )
        )
        if current_expeditor:
            planner_owner_id = CompanyProfile.objects.filter(
                pk=current_expeditor
            ).values_list("organization_id", flat=True).first()
            if planner_owner_id:
                planner_transportations = planner_transportations.filter(
                    owner_company_id=planner_owner_id
                )
            else:
                planner_transportations = planner_transportations.none()
        dashboard_automatic_tasks = automatic_planner_tasks(
            list(planner_transportations)
        )
        context.update(
            {
                "active_count": shipments.filter(
                    status__in=ACTIVE_SHIPMENT_STATUSES
                ).count(),
                "today_pickups": shipments.filter(pickup_date=today).count(),
                "unassigned_count": shipments.filter(
                    carrier__isnull=True, status__in=ACTIVE_SHIPMENT_STATUSES
                ).count(),
                "overdue_count": sum(
                    1
                    for shipment in financial_shipments
                    if shipment.receivable_state == Shipment.PaymentStatus.OVERDUE
                ),
                "revenue": revenue,
                "margin": revenue - costs,
                "receivables": receivables,
                "payables": payables,
                "overdue_receivables": overdue_receivables,
                "overdue_payables": overdue_payables,
                "recent_shipments": shipments[:8],
                "expeditors": CompanyProfile.objects.all(),
                "current_expeditor": current_expeditor,
                "current_currency": current_currency,
                "currency_choices": ("RUB", "USD", "EUR"),
                "status_stats": [
                    {
                        "value": status.value,
                        "label": status.label,
                        "count": shipments.filter(status=status.value).count(),
                    }
                    for status in Shipment.Status
                    if status != Shipment.Status.CANCELLED
                ],
                "dashboard_automatic_tasks": dashboard_automatic_tasks[:8],
                "dashboard_notification_count": len(dashboard_automatic_tasks),
            }
        )
        return context


class ShipmentListView(LoginRequiredMixin, ListView):
    model = Shipment
    template_name = "crm/shipment_list.html"
    context_object_name = "shipments"
    paginate_by = 20

    def get_queryset(self):
        queryset = Shipment.objects.select_related(
            "expeditor", "customer", "carrier", "driver", "vehicle", "manager"
        )
        query = self.request.GET.get("q", "").strip()
        status = self.request.GET.get("status", "").strip()
        payment = self.request.GET.get("payment", "").strip()
        scope = self.request.GET.get("scope", "").strip()
        expeditor = get_expeditor_filter(self.request)
        currency = get_currency_filter(self.request)
        if expeditor:
            queryset = queryset.filter(expeditor_id=expeditor)
        if currency:
            queryset = queryset.filter(currency=currency)
        if scope == "active":
            queryset = queryset.filter(status__in=ACTIVE_SHIPMENT_STATUSES)
        elif scope == "unassigned":
            queryset = queryset.filter(
                carrier__isnull=True, status__in=ACTIVE_SHIPMENT_STATUSES
            )
        elif scope == "revenue":
            queryset = queryset.exclude(status=Shipment.Status.CANCELLED).filter(
                customer_price__gt=0
            )
        elif scope == "margin":
            queryset = queryset.exclude(status=Shipment.Status.CANCELLED).filter(
                customer_price__gt=F("carrier_price")
            )
        elif scope in {"receivables", "payables"}:
            queryset = queryset.exclude(status=Shipment.Status.CANCELLED)
            matching_ids = [
                shipment.pk
                for shipment in queryset.prefetch_related("payments")
                if (
                    shipment.receivable_balance > 0
                    if scope == "receivables"
                    else shipment.payable_balance > 0
                )
            ]
            queryset = queryset.filter(pk__in=matching_ids)
        if query:
            queryset = queryset.filter(
                Q(number__iunicodecontains=query)
                | Q(expeditor__name__iunicodecontains=query)
                | Q(customer__name__iunicodecontains=query)
                | Q(carrier__name__iunicodecontains=query)
                | Q(pickup_city__iunicodecontains=query)
                | Q(delivery_city__iunicodecontains=query)
                | Q(cargo_name__iunicodecontains=query)
            )
        if status:
            queryset = queryset.filter(status=status)
        if payment in Shipment.PaymentStatus.values:
            matching_ids = [
                shipment.pk
                for shipment in queryset.prefetch_related("payments")
                if shipment.receivable_state == payment
            ]
            queryset = queryset.filter(pk__in=matching_ids)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "status_choices": Shipment.Status.choices,
                "payment_choices": Shipment.PaymentStatus.choices,
                "current_q": self.request.GET.get("q", ""),
                "current_status": self.request.GET.get("status", ""),
                "current_payment": (
                    self.request.GET.get("payment", "")
                    if self.request.GET.get("payment", "")
                    in Shipment.PaymentStatus.values
                    else ""
                ),
                "current_scope": (
                    self.request.GET.get("scope", "")
                    if self.request.GET.get("scope", "") in SHIPMENT_SCOPE_LABELS
                    else ""
                ),
                "current_scope_label": SHIPMENT_SCOPE_LABELS.get(
                    self.request.GET.get("scope", ""), ""
                ),
                "expeditors": CompanyProfile.objects.all(),
                "current_expeditor": get_expeditor_filter(self.request),
                "current_currency": get_currency_filter(self.request),
                "currency_choices": ("RUB", "USD", "EUR"),
            }
        )
        return context


class ShipmentDetailView(LoginRequiredMixin, DetailView):
    model = Shipment
    template_name = "crm/shipment_detail.html"
    context_object_name = "shipment"
    queryset = Shipment.objects.select_related(
        "expeditor", "customer", "carrier", "driver", "vehicle", "manager",
        "transportation",
    ).prefetch_related("payments__created_by", "documents__created_by")


class UserAwareShipmentFormMixin:
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, self.success_message)
        return super().form_valid(form)


class ShipmentCreateView(
    LoginRequiredMixin, UserAwareShipmentFormMixin, CreateView
):
    model = Shipment
    form_class = ShipmentForm
    template_name = "crm/shipment_form.html"
    success_message = "Рейс создан. Данные перенесены в новую карточку."

    def get_initial(self):
        initial = super().get_initial()
        customer_id = self.request.GET.get("customer")
        if customer_id and Customer.objects.filter(pk=customer_id).exists():
            initial["customer"] = customer_id
        expeditor_id = self.request.GET.get("expeditor")
        if expeditor_id and CompanyProfile.objects.filter(pk=expeditor_id).exists():
            initial["expeditor"] = expeditor_id
        return initial

    def get_success_url(self):
        return self.object.transportation.get_absolute_url()


class ShipmentUpdateView(
    LoginRequiredMixin, UserAwareShipmentFormMixin, UpdateView
):
    model = Shipment
    form_class = ShipmentForm
    template_name = "crm/shipment_form.html"
    success_message = "Заявка обновлена."


class PaymentCreateView(LoginRequiredMixin, FinanceAccessMixin, CreateView):
    model = Payment
    form_class = PaymentForm
    template_name = "crm/payment_form.html"

    @property
    def shipment(self):
        if not hasattr(self, "_shipment"):
            self._shipment = get_object_or_404(
                Shipment.objects.select_related("customer", "carrier").prefetch_related(
                    "payments"
                ),
                pk=self.kwargs["pk"],
            )
        return self._shipment

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["shipment"] = self.shipment
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        direction = self.request.GET.get("direction")
        if direction not in Payment.Direction.values:
            direction = Payment.Direction.INCOME
        initial.update(
            {
                "direction": direction,
                "payment_date": timezone.localdate(),
                "amount": (
                    self.shipment.receivable_balance
                    if direction == Payment.Direction.INCOME
                    else self.shipment.payable_balance
                ),
            }
        )
        if initial["amount"] <= 0:
            initial["amount"] = None
        return initial

    def form_valid(self, form):
        form.instance.shipment = self.shipment
        form.instance.created_by = self.request.user
        messages.success(self.request, "Платёж зарегистрирован.")
        return super().form_valid(form)

    def get_success_url(self):
        return self.shipment.get_absolute_url()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["shipment"] = self.shipment
        context["transportation"] = None
        return context


class PaymentUpdateView(LoginRequiredMixin, FinanceAccessMixin, UpdateView):
    model = Payment
    form_class = PaymentForm
    template_name = "crm/payment_form.html"

    def get_queryset(self):
        return Payment.objects.select_related(
            "shipment", "shipment__customer", "shipment__carrier"
        ).filter(shipment_id=self.kwargs["shipment_pk"])

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["shipment"] = self.object.shipment
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, "Платёж обновлён.")
        return super().form_valid(form)

    def get_success_url(self):
        return self.object.shipment.get_absolute_url()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["shipment"] = self.object.shipment
        context["transportation"] = None
        return context


class PaymentDeleteView(LoginRequiredMixin, FinanceAccessMixin, View):
    template_name = "crm/payment_confirm_delete.html"

    def get_object(self):
        return get_object_or_404(
            Payment.objects.select_related(
                "shipment", "shipment__customer", "shipment__carrier"
            ),
            pk=self.kwargs["pk"],
            shipment_id=self.kwargs["shipment_pk"],
        )

    def get(self, request, *args, **kwargs):
        from django.shortcuts import render

        payment = self.get_object()
        return render(
            request,
            self.template_name,
            {"payment": payment, "shipment": payment.shipment, "transportation": None},
        )

    def post(self, request, *args, **kwargs):
        payment = self.get_object()
        shipment = payment.shipment
        payment.delete()
        messages.success(request, "Платёж удалён, остатки задолженности пересчитаны.")
        return redirect(shipment.get_absolute_url())


class TransportationPaymentMixin:
    """Shared parent/document handling for payments on the core ERP trip."""

    @property
    def transportation(self):
        if not hasattr(self, "_transportation"):
            self._transportation = get_object_or_404(
                Transportation.objects.select_related(
                    "owner_company", "customer_vat_rate", "executor_vat_rate"
                ),
                pk=self.kwargs["transportation_pk"],
            )
        return self._transportation

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["transportation"] = self.transportation
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["transportation"] = self.transportation
        context["shipment"] = None
        return context

    def get_success_url(self):
        return self.transportation.get_absolute_url()


class TransportationPaymentCreateView(
    LoginRequiredMixin, FinanceAccessMixin, TransportationPaymentMixin, CreateView
):
    model = Payment
    form_class = PaymentForm
    template_name = "crm/payment_form.html"

    def dispatch(self, request, *args, **kwargs):
        if self.transportation.posting_status != Transportation.PostingStatus.POSTED:
            messages.error(
                request,
                "Сначала проведите рейс — только проведённые документы участвуют во взаиморасчётах.",
            )
            return redirect(self.transportation.get_absolute_url())
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        initial = super().get_initial()
        direction = self.request.GET.get("direction")
        if direction not in Payment.Direction.values:
            direction = Payment.Direction.INCOME
        initial.update(
            {
                "direction": direction,
                "payment_date": timezone.localdate(),
                "amount": (
                    self.transportation.receivable_balance
                    if direction == Payment.Direction.INCOME
                    else self.transportation.payable_balance
                ),
            }
        )
        if initial["amount"] <= 0:
            initial["amount"] = None
        return initial

    def form_valid(self, form):
        form.instance.transportation = self.transportation
        form.instance.created_by = self.request.user
        messages.success(self.request, "Платёж по рейсу зарегистрирован.")
        response = super().form_valid(form)
        labels = {
            "direction": "Операция",
            "amount": "Сумма",
            "payment_date": "Дата платежа",
            "method": "Способ оплаты",
            "reference": "Платёжное поручение",
            "notes": "Комментарий",
        }
        new_snapshot = _payment_snapshot(self.object)
        _record_transportation_audit(
            self.transportation,
            self.request.user,
            comment="Поступление или оплата добавлены",
            source="payment",
            changes=_snapshot_changes(
                {key: "" for key in new_snapshot}, new_snapshot, labels
            ),
        )
        return response


class TransportationPaymentUpdateView(
    LoginRequiredMixin, FinanceAccessMixin, TransportationPaymentMixin, UpdateView
):
    model = Payment
    form_class = PaymentForm
    template_name = "crm/payment_form.html"

    def get_queryset(self):
        return Payment.objects.select_related(
            "transportation", "transportation__owner_company"
        ).filter(transportation_id=self.kwargs["transportation_pk"])

    def dispatch(self, request, *args, **kwargs):
        if request.method == "POST":
            self._audit_old_snapshot = _payment_snapshot(self.get_object())
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        old_snapshot = getattr(self, "_audit_old_snapshot", _payment_snapshot(self.object))
        messages.success(self.request, "Платёж по рейсу обновлён.")
        response = super().form_valid(form)
        new_snapshot = _payment_snapshot(self.object)
        changes = _snapshot_changes(
            old_snapshot,
            new_snapshot,
            {
                "direction": "Операция",
                "amount": "Сумма",
                "payment_date": "Дата платежа",
                "method": "Способ оплаты",
                "reference": "Платёжное поручение",
                "notes": "Комментарий",
            },
        )
        if changes:
            _record_transportation_audit(
                self.transportation,
                self.request.user,
                comment="Поступление или оплата изменены",
                source="payment",
                changes=changes,
            )
        return response


class TransportationPaymentDeleteView(LoginRequiredMixin, FinanceAccessMixin, View):
    template_name = "crm/payment_confirm_delete.html"

    def get_object(self):
        return get_object_or_404(
            Payment.objects.select_related(
                "transportation", "transportation__owner_company"
            ),
            pk=self.kwargs["pk"],
            transportation_id=self.kwargs["transportation_pk"],
        )

    def get(self, request, *args, **kwargs):
        payment = self.get_object()
        return render(
            request,
            self.template_name,
            {
                "payment": payment,
                "transportation": payment.transportation,
                "shipment": None,
            },
        )

    def post(self, request, *args, **kwargs):
        payment = self.get_object()
        transportation = payment.transportation
        old_snapshot = _payment_snapshot(payment)
        payment.delete()
        labels = {
            "direction": "Операция",
            "amount": "Сумма",
            "payment_date": "Дата платежа",
            "method": "Способ оплаты",
                "reference": "Платёжное поручение",
            "notes": "Комментарий",
        }
        _record_transportation_audit(
            transportation,
            request.user,
            comment="Поступление или оплата удалены",
            source="payment",
            changes=_snapshot_changes(old_snapshot, {key: "" for key in old_snapshot}, labels),
        )
        messages.success(request, "Платёж удалён, задолженность по рейсу пересчитана.")
        return redirect(transportation.get_absolute_url())


class ForwardingOrderView(LoginRequiredMixin, FormView):
    form_class = ForwardingOrderForm
    template_name = "crm/forwarding_order_form.html"

    @property
    def shipment(self):
        if not hasattr(self, "_shipment"):
            self._shipment = get_object_or_404(
                Shipment.objects.select_related("customer", "manager", "expeditor"),
                pk=self.kwargs["pk"],
            )
        return self._shipment

    @property
    def forwarding_order(self):
        if not hasattr(self, "_forwarding_order"):
            try:
                self._forwarding_order = self.shipment.forwarding_order
            except ForwardingOrder.DoesNotExist:
                self._forwarding_order = ForwardingOrder(shipment=self.shipment)
        return self._forwarding_order

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self.forwarding_order
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        if self.forwarding_order.pk:
            return initial
        customer = self.shipment.customer
        delivery_address = self.shipment.delivery_address
        if delivery_address and self.shipment.delivery_city.casefold() not in delivery_address.casefold():
            delivery_address = f"{self.shipment.delivery_city}, {delivery_address}"
        initial.update(
            {
                "order_date": timezone.localdate(),
                "shipper_name": customer.name,
                "shipper_tax_id": customer.tax_id,
                "shipper_address": customer.address,
                "shipper_contact_name": customer.contact_name,
                "shipper_phone": customer.phone,
                "consignee_address": delivery_address or self.shipment.delivery_city,
                "payer": customer.name,
                "expediter_representative": self.shipment.expeditor.director_name,
                "client_representative": customer.contact_name,
            }
        )
        return initial

    def form_valid(self, form):
        form.instance.shipment = self.shipment
        forwarding_order = form.save()
        if self.request.POST.get("action") == "download":
            from .documents import build_forwarding_order_docx

            stream = build_forwarding_order_docx(self.shipment, forwarding_order)
            return FileResponse(
                stream,
                as_attachment=True,
                filename=f"Экспедиторское_поручение_{self.shipment.number}.docx",
                content_type=(
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                ),
            )
        messages.success(self.request, "Данные экспедиторского поручения сохранены.")
        return super().form_valid(form)

    def get_success_url(self):
        return self.shipment.get_absolute_url()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["shipment"] = self.shipment
        context["has_saved_order"] = bool(self.forwarding_order.pk)
        return context


class CompanyProfileView(LoginRequiredMixin, RedirectView):
    pattern_name = "expeditor-list"
    permanent = False


class AccountingDocumentCreateView(LoginRequiredMixin, FormView):
    form_class = AccountingDocumentForm
    template_name = "crm/accounting_document_form.html"

    @property
    def shipment(self):
        if not hasattr(self, "_shipment"):
            self._shipment = get_object_or_404(
                Shipment.objects.select_related("customer", "manager", "expeditor"),
                pk=self.kwargs["pk"],
            )
        return self._shipment

    @property
    def company_profile(self):
        return self.shipment.expeditor

    def get_initial(self):
        initial = super().get_initial()
        kind = self.request.GET.get("kind", ShipmentDocument.Kind.INVOICE)
        allowed_kinds = dict(AccountingDocumentForm.DOCUMENT_KIND_CHOICES)
        if kind not in allowed_kinds:
            kind = ShipmentDocument.Kind.INVOICE
        contract_number = ""
        contract_date = None
        try:
            contract_number = self.shipment.forwarding_order.contract_number
            contract_date = self.shipment.forwarding_order.contract_date
        except ForwardingOrder.DoesNotExist:
            pass
        profile = self.company_profile
        default_vat_rate = (
            profile.default_vat_rate
            if profile
            else CompanyProfile.VATRate.WITHOUT_VAT
        )
        initial.update(
            {
                "kind": kind,
                "number": f"{self.shipment.number}-{timezone.localdate():%d%m%y}",
                "document_date": timezone.localdate(),
                "contract_number": contract_number,
                "contract_date": contract_date,
                "service_name": (
                    "Транспортно-экспедиционные услуги по маршруту "
                    f"{self.shipment.route}, заявка {self.shipment.number}"
                ),
                "quantity": Decimal("1"),
                "unit": "усл.",
                "amount": self.shipment.customer_price,
                "currency": self.shipment.currency,
                "vat_rate": default_vat_rate,
                "upd_status": (
                    "2"
                    if default_vat_rate == CompanyProfile.VATRate.WITHOUT_VAT
                    else "1"
                ),
                "buyer_name": self.shipment.customer.name,
                "buyer_tax_id": self.shipment.customer.tax_id,
                "buyer_kpp": self.shipment.customer.kpp,
                "buyer_address": self.shipment.customer.address,
            }
        )
        return initial

    def form_valid(self, form):
        profile = self.company_profile
        if not profile:
            form.add_error(
                None,
                "Сначала заполните реквизиты компании-экспедитора.",
            )
            return self.form_invalid(form)
        data = form.cleaned_data
        from .documents import build_accounting_document_docx

        stream = build_accounting_document_docx(self.shipment, profile, data)
        content = stream.getvalue()
        prefixes = {
            ShipmentDocument.Kind.INVOICE: "Счет",
            ShipmentDocument.Kind.ACT: "Акт",
            ShipmentDocument.Kind.UPD: "УПД",
            ShipmentDocument.Kind.VAT_INVOICE: "Счет-фактура",
        }
        safe_number = re.sub(r"[^0-9A-Za-zА-Яа-я_-]+", "_", data["number"])
        filename = f"{prefixes[data['kind']]}_{safe_number}.docx"
        document_record = ShipmentDocument(
            shipment=self.shipment,
            kind=data["kind"],
            party=ShipmentDocument.Party.CUSTOMER,
            status=ShipmentDocument.Status.ISSUED,
            number=data["number"],
            document_date=data["document_date"],
            amount=data["amount"],
            currency=data["currency"],
            notes="Сформирован из карточки заявки.",
            created_by=self.request.user,
        )
        document_record.file.save(filename, ContentFile(content), save=False)
        document_record.save()
        return FileResponse(
            BytesIO(content),
            as_attachment=True,
            filename=filename,
            content_type=(
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["shipment"] = self.shipment
        context["company_profile"] = self.company_profile
        return context


class ShipmentDocumentListView(LoginRequiredMixin, ListView):
    model = ShipmentDocument
    template_name = "crm/shipment_document_list.html"
    context_object_name = "documents"
    paginate_by = 30

    def get_queryset(self):
        queryset = ShipmentDocument.objects.select_related(
            "shipment", "shipment__expeditor", "shipment__customer",
            "shipment__carrier", "transportation", "transportation__owner_company",
            "counterparty", "created_by"
        )
        query = self.request.GET.get("q", "").strip()
        direction = self.request.GET.get("direction", "").strip()
        kind = self.request.GET.get("kind", "").strip()
        status = self.request.GET.get("status", "").strip()
        party = self.request.GET.get("party", "").strip()
        expeditor = get_expeditor_filter(self.request)
        if expeditor:
            queryset = queryset.filter(
                Q(shipment__expeditor_id=expeditor)
                | Q(transportation__owner_company_id=expeditor)
            )
        if query:
            queryset = queryset.filter(
                Q(number__iunicodecontains=query)
                | Q(shipment__number__iunicodecontains=query)
                | Q(shipment__customer__name__iunicodecontains=query)
                | Q(shipment__carrier__name__iunicodecontains=query)
                | Q(transportation__number__iunicodecontains=query)
                | Q(counterparty__name__iunicodecontains=query)
                | Q(counterparty__tax_id__iunicodecontains=query)
            )
        if direction in ShipmentDocument.Direction.values:
            queryset = queryset.filter(direction=direction)
        if kind in ShipmentDocument.Kind.values:
            queryset = queryset.filter(kind=kind)
        if status in ShipmentDocument.Status.values:
            queryset = queryset.filter(status=status)
        if party in ShipmentDocument.Party.values:
            queryset = queryset.filter(party=party)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        all_documents = ShipmentDocument.objects.all()
        current_expeditor = get_expeditor_filter(self.request)
        if current_expeditor:
            all_documents = all_documents.filter(
                Q(shipment__expeditor_id=current_expeditor)
                | Q(transportation__owner_company_id=current_expeditor)
            )
        context.update(
            {
                "kind_choices": ShipmentDocument.Kind.choices,
                "direction_choices": ShipmentDocument.Direction.choices,
                "status_choices": ShipmentDocument.Status.choices,
                "party_choices": ShipmentDocument.Party.choices,
                "current_q": self.request.GET.get("q", ""),
                "current_direction": self.request.GET.get("direction", ""),
                "current_kind": self.request.GET.get("kind", ""),
                "current_status": self.request.GET.get("status", ""),
                "current_party": self.request.GET.get("party", ""),
                "expeditors": CompanyProfile.objects.all(),
                "current_expeditor": current_expeditor,
                "document_count": all_documents.count(),
                "expected_count": all_documents.filter(
                    status=ShipmentDocument.Status.EXPECTED
                ).count(),
                "incoming_count": all_documents.filter(
                    direction=ShipmentDocument.Direction.INCOMING
                ).count(),
                "outgoing_count": all_documents.filter(
                    direction=ShipmentDocument.Direction.OUTGOING
                ).count(),
                "overdue_count": all_documents.filter(
                    status=ShipmentDocument.Status.EXPECTED,
                    expected_date__lt=today,
                ).count(),
                "original_count": all_documents.filter(
                    status=ShipmentDocument.Status.ORIGINAL
                ).count(),
            }
        )
        return context


class ShipmentDocumentShipmentMixin:
    @property
    def shipment(self):
        if not hasattr(self, "_shipment"):
            self._shipment = get_object_or_404(
                Shipment.objects.select_related("customer", "carrier"),
                pk=self.kwargs["shipment_pk"],
            )
        return self._shipment

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["shipment"] = self.shipment
        return context

    def get_success_url(self):
        return self.shipment.get_absolute_url()


class ShipmentDocumentCreateView(
    LoginRequiredMixin, ShipmentDocumentShipmentMixin, CreateView
):
    model = ShipmentDocument
    form_class = ShipmentDocumentForm
    template_name = "crm/shipment_document_form.html"

    @property
    def shipment(self):
        if "shipment_pk" not in self.kwargs:
            return None
        return super().shipment

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if self.shipment:
            kwargs["shipment"] = self.shipment
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        if self.shipment:
            initial["currency"] = self.shipment.currency
        initial["direction"] = self.request.GET.get(
            "direction", ShipmentDocument.Direction.OUTGOING
        )
        initial["kind"] = self.request.GET.get("kind", ShipmentDocument.Kind.INVOICE)
        return initial

    def form_valid(self, form):
        if self.shipment:
            form.instance.shipment = self.shipment
        form.instance.created_by = self.request.user
        messages.success(self.request, "Документ добавлен в реестр.")
        return super().form_valid(form)

    def get_success_url(self):
        if self.shipment:
            return self.shipment.get_absolute_url()
        return reverse("shipment-document-list")


class ShipmentDocumentUpdateView(LoginRequiredMixin, UpdateView):
    model = ShipmentDocument
    form_class = ShipmentDocumentForm
    template_name = "crm/shipment_document_form.html"
    context_object_name = "document_record"

    def form_valid(self, form):
        messages.success(self.request, "Данные документа обновлены.")
        return super().form_valid(form)

    def get_success_url(self):
        return self.object.shipment.get_absolute_url()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["shipment"] = self.object.shipment
        return context


class ShipmentDocumentDeleteView(LoginRequiredMixin, View):
    template_name = "crm/shipment_document_confirm_delete.html"

    def get_object(self):
        return get_object_or_404(
            ShipmentDocument.objects.select_related("shipment", "counterparty"),
            pk=self.kwargs["pk"],
        )

    def get(self, request, *args, **kwargs):
        document_record = self.get_object()
        return render(
            request,
            self.template_name,
            {"document_record": document_record, "shipment": document_record.shipment},
        )

    def post(self, request, *args, **kwargs):
        document_record = self.get_object()
        shipment = document_record.shipment
        document_record.delete()
        messages.success(request, "Документ удалён из реестра.")
        return redirect(shipment.get_absolute_url())


class ShipmentDocumentDownloadView(LoginRequiredMixin, View):
    def get(self, request, pk):
        document_record = get_object_or_404(ShipmentDocument, pk=pk)
        if not document_record.file:
            raise Http404("Файл к документу не прикреплён.")
        try:
            file_handle = document_record.file.open("rb")
        except FileNotFoundError as error:
            raise Http404("Файл не найден в хранилище.") from error
        content_type = (
            mimetypes.guess_type(document_record.file_name)[0]
            or "application/octet-stream"
        )
        return FileResponse(
            file_handle,
            as_attachment=True,
            filename=document_record.file_name,
            content_type=content_type,
        )


def _document_batch_candidates(direction, owner_id=None, currency="RUB", delivered_only=False):
    queryset = (
        Transportation.objects.all()
        .select_related("owner_company", "legacy_shipment")
        .prefetch_related(
            Prefetch(
                "parties",
                queryset=TransportationParty.objects.filter(is_active=True).select_related("organization"),
                to_attr="document_batch_parties",
            ),
            Prefetch(
                "execution_links",
                queryset=TransportationLink.objects.filter(is_active=True).select_related(
                    "contractor_party__organization"
                ).order_by("sequence"),
                to_attr="document_batch_execution_links",
            ),
        )
        .order_by("-planned_start_date", "-created_at")
    )
    if delivered_only and direction == DocumentBatch.Direction.OUTGOING:
        queryset = queryset.filter(
            status__in=[
                Transportation.Status.DELIVERED,
                Transportation.Status.DOCUMENTS_RECEIVED,
                Transportation.Status.CUSTOMER_INVOICED,
                Transportation.Status.CLOSED,
            ]
        )
    if owner_id:
        queryset = queryset.filter(owner_company_id=owner_id)
    if currency:
        queryset = queryset.filter(currency=currency)
    candidates = []
    for transportation in queryset[:200]:
        parties = getattr(transportation, "document_batch_parties", ())
        execution_links = getattr(transportation, "document_batch_execution_links", ())
        if direction == DocumentBatch.Direction.OUTGOING:
            counterparty = next(
                (
                    party.organization
                    for party in parties
                    if party.role == TransportationParty.Role.CLIENT
                ),
                None,
            )
            amount = transportation.customer_amount
            vat_amount = transportation.customer_vat_amount
        else:
            first_link = execution_links[0] if execution_links else None
            counterparty = (
                first_link.contractor_party.organization
                if first_link and first_link.contractor_party_id
                else None
            )
            amount = transportation.executor_amount
            vat_amount = transportation.executor_vat_amount
        candidates.append(
            {
                "transportation": transportation,
                "shipment": transportation.legacy_shipment,
                "counterparty": counterparty,
                "amount": amount,
                "vat_amount": vat_amount,
            }
        )
    return candidates


def _post_document_batch(batch, user):
    for line in batch.lines.select_related("transportation__legacy_shipment", "counterparty"):
        document = line.shipment_document or ShipmentDocument()
        document.shipment = line.transportation.legacy_shipment
        document.transportation = line.transportation
        document.direction = batch.direction
        document.counterparty = line.counterparty
        document.kind = line.kind
        document.party = (
            ShipmentDocument.Party.CUSTOMER
            if batch.direction == DocumentBatch.Direction.OUTGOING
            else ShipmentDocument.Party.CARRIER
        )
        document.status = batch.default_status
        document.number = line.document_number
        document.document_date = line.document_date or batch.document_date
        document.amount = line.amount
        document.vat_amount = line.vat_amount
        document.currency = batch.currency
        document.notes = batch.notes
        if not document.pk:
            document.created_by = user
        document.save()
        if line.shipment_document_id != document.pk:
            line.shipment_document = document
            line.save(update_fields=["shipment_document", "updated_at"])
    batch.status = DocumentBatch.Status.POSTED
    batch.posted_by = user
    batch.posted_at = timezone.now()
    batch.save(update_fields=["status", "posted_by", "posted_at", "updated_at"])
    return batch


def _unpost_document_batch(batch):
    for line in batch.lines.select_related("shipment_document"):
        if line.shipment_document_id:
            line.shipment_document.delete()
            line.shipment_document = None
            line.save(update_fields=["shipment_document", "updated_at"])
    batch.status = DocumentBatch.Status.DRAFT
    batch.posted_by = None
    batch.posted_at = None
    batch.save(update_fields=["status", "posted_by", "posted_at", "updated_at"])
    return batch


class DocumentBatchEditorMixin:
    model = DocumentBatch
    form_class = DocumentBatchForm
    template_name = "crm/document_batch_form.html"

    def is_primary_registry_mode(self):
        return str(self.request.resolver_match.url_name or "").startswith(
            "primary-document-registry"
        )

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        direction = self.request.GET.get("direction", "").strip()
        if direction in DocumentBatch.Direction.values:
            initial["direction"] = direction
        initial.setdefault("document_date", timezone.localdate())
        initial.setdefault("default_status", ShipmentDocument.Status.ISSUED)
        return initial

    def _selected_state(self):
        selected = set(self.request.POST.getlist("transportation_ids"))
        values = {"kind": {}, "number": {}, "date": {}, "amount": {}, "vat": {}}
        for key, value in self.request.POST.items():
            for prefix, bucket in (
                ("kind_", "kind"),
                ("number_", "number"),
                ("date_", "date"),
                ("amount_", "amount"),
                ("vat_", "vat"),
            ):
                if key.startswith(prefix):
                    values[bucket][key.removeprefix(prefix)] = value.strip()
        if self.request.method != "POST" and getattr(self, "object", None):
            for line in self.object.lines.all():
                raw_id = str(line.transportation_id)
                selected.add(raw_id)
                values["kind"][raw_id] = line.kind
                values["number"][raw_id] = line.document_number
                values["date"][raw_id] = line.document_date.isoformat() if line.document_date else ""
                values["amount"][raw_id] = str(line.amount)
                values["vat"][raw_id] = str(line.vat_amount)
        return selected, values

    def _candidate_context(self, form):
        direction = form.data.get("direction") if form.is_bound else form.initial.get("direction", DocumentBatch.Direction.OUTGOING)
        if direction not in DocumentBatch.Direction.values:
            direction = DocumentBatch.Direction.OUTGOING
        owner_id = form.data.get("owner_company") if form.is_bound else form.initial.get("owner_company") or getattr(self.object, "owner_company_id", None)
        owner_id = getattr(owner_id, "pk", owner_id)
        currency = (form.data.get("currency", "RUB") if form.is_bound else form.initial.get("currency", "RUB")).upper()
        if currency not in {"RUB", "USD", "EUR"}:
            currency = "RUB"
        selected, values = self._selected_state()
        candidates = _document_batch_candidates(
            direction,
            owner_id=owner_id,
            currency=currency,
            delivered_only=self.is_primary_registry_mode(),
        )
        default_kind = form.data.get("default_kind") if form.is_bound else form.initial.get("default_kind", ShipmentDocument.Kind.UPD)
        default_date = form.data.get("document_date") if form.is_bound else form.initial.get("document_date", timezone.localdate())
        default_date_value = default_date.isoformat() if hasattr(default_date, "isoformat") else str(default_date or "")
        for candidate in candidates:
            raw_id = str(candidate["transportation"].pk)
            candidate["selected"] = raw_id in selected
            candidate["entered_kind"] = values["kind"].get(raw_id, default_kind)
            candidate["entered_number"] = values["number"].get(raw_id, "")
            candidate["entered_date"] = values["date"].get(raw_id, default_date_value)
            candidate["entered_amount"] = values["amount"].get(raw_id, candidate["amount"])
            candidate["entered_vat"] = values["vat"].get(raw_id, candidate["vat_amount"])
        return {
            "document_batch_candidates": candidates,
            "document_kind_choices": ShipmentDocument.Kind.choices,
            "cancel_url": reverse_lazy("document-batch-list"),
            "is_primary_registry_mode": self.is_primary_registry_mode(),
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(self._candidate_context(context["form"]))
        return context

    def _parse_selected_lines(self, form):
        direction = form.cleaned_data["direction"]
        owner_id = form.cleaned_data["owner_company"].pk
        currency = form.cleaned_data["currency"]
        candidate_map = {
            str(item["transportation"].pk): item
            for item in _document_batch_candidates(
                direction,
                owner_id,
                currency,
                delivered_only=self.is_primary_registry_mode(),
            )
        }
        selected_ids = self.request.POST.getlist("transportation_ids")
        if not selected_ids:
            return [], ["Выберите хотя бы один рейс."]
        lines = []
        errors = []
        seen = set()
        for raw_id in selected_ids:
            if raw_id in seen:
                continue
            seen.add(raw_id)
            candidate = candidate_map.get(raw_id)
            if not candidate:
                errors.append("Один из выбранных рейсов недоступен для этого реестра.")
                continue
            kind = self.request.POST.get(f"kind_{raw_id}", form.cleaned_data["default_kind"])
            if kind not in ShipmentDocument.Kind.values:
                errors.append(f"{candidate['transportation']}: выберите тип документа.")
                continue
            try:
                amount = Decimal(self.request.POST.get(f"amount_{raw_id}", "0").replace(" ", "").replace(",", "."))
                vat_amount = Decimal(self.request.POST.get(f"vat_{raw_id}", "0").replace(" ", "").replace(",", "."))
            except (InvalidOperation, AttributeError):
                errors.append(f"{candidate['transportation']}: проверьте сумму и НДС.")
                continue
            if amount < 0 or vat_amount < 0:
                errors.append(f"{candidate['transportation']}: сумма и НДС не могут быть отрицательными.")
                continue
            lines.append(
                {
                    "transportation": candidate["transportation"],
                    "counterparty": candidate["counterparty"],
                    "kind": kind,
                    "document_number": self.request.POST.get(f"number_{raw_id}", "").strip()[:100],
                    "document_date": parse_crm_date(self.request.POST.get(f"date_{raw_id}", "").strip()),
                    "amount": amount,
                    "vat_amount": vat_amount,
                }
            )
        return lines, errors

    def _save_batch(self, form, lines):
        batch = form.save(commit=False)
        if not batch.pk:
            batch.created_by = self.request.user
        batch.save()
        if batch.status == DocumentBatch.Status.POSTED:
            _unpost_document_batch(batch)
        batch.lines.all().delete()
        DocumentBatchLine.objects.bulk_create([DocumentBatchLine(batch=batch, **line) for line in lines])
        return batch

    def post(self, request, *args, **kwargs):
        self.object = self.get_object() if kwargs.get("pk") else None
        form = self.get_form()
        valid = form.is_valid()
        lines, errors = (self._parse_selected_lines(form) if valid else ([], []))
        for error in errors:
            form.add_error(None, error)
        if valid and not errors:
            with transaction.atomic():
                self.object = self._save_batch(form, lines)
                if request.POST.get("action") == "post":
                    _post_document_batch(self.object, request.user)
                    messages.success(request, f"Реестр документов {self.object.number} проведён.")
                else:
                    messages.success(request, f"Реестр документов {self.object.number} сохранён как черновик.")
            return redirect(self.object.get_absolute_url())
        return self.render_to_response(self.get_context_data(form=form))


class DocumentBatchListView(LoginRequiredMixin, FinanceAccessMixin, ListView):
    model = DocumentBatch
    template_name = "crm/document_batch_list.html"
    context_object_name = "document_batches"
    paginate_by = 30

    def get_queryset(self):
        queryset = DocumentBatch.objects.select_related("owner_company").annotate(
            line_total=Count("lines"), amount_total=Sum("lines__amount")
        )
        direction = self.request.GET.get("direction", "")
        status = self.request.GET.get("status", "")
        if direction in DocumentBatch.Direction.values:
            queryset = queryset.filter(direction=direction)
        if status in DocumentBatch.Status.values:
            queryset = queryset.filter(status=status)
        return queryset.order_by("-document_date", "-created_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "direction_choices": DocumentBatch.Direction.choices,
                "status_choices": DocumentBatch.Status.choices,
                "current_direction": self.request.GET.get("direction", ""),
                "current_status": self.request.GET.get("status", ""),
                "draft_count": DocumentBatch.objects.filter(status=DocumentBatch.Status.DRAFT).count(),
                "posted_count": DocumentBatch.objects.filter(status=DocumentBatch.Status.POSTED).count(),
            }
        )
        return context


class DocumentBatchCreateView(LoginRequiredMixin, FinanceAccessMixin, DocumentBatchEditorMixin, CreateView):
    pass


class DocumentBatchUpdateView(LoginRequiredMixin, FinanceAccessMixin, DocumentBatchEditorMixin, UpdateView):
    def get_queryset(self):
        return DocumentBatch.objects.exclude(status=DocumentBatch.Status.VOIDED)


class DocumentBatchDetailView(LoginRequiredMixin, FinanceAccessMixin, DetailView):
    model = DocumentBatch
    template_name = "crm/document_batch_detail.html"
    context_object_name = "document_batch"

    def get_queryset(self):
        return DocumentBatch.objects.select_related("owner_company", "created_by", "posted_by").prefetch_related(
            "lines__transportation",
            "lines__counterparty",
            "lines__shipment_document",
        )


class DocumentBatchPostView(LoginRequiredMixin, FinanceAccessMixin, View):
    def post(self, request, pk):
        batch = get_object_or_404(DocumentBatch, pk=pk)
        if batch.status == DocumentBatch.Status.POSTED:
            messages.info(request, f"{batch.number} уже проведена.")
            return redirect(batch.get_absolute_url())
        if not batch.lines.exists():
            messages.error(request, "В реестре нет строк.")
            return redirect(batch.get_absolute_url())
        with transaction.atomic():
            _post_document_batch(batch, request.user)
        messages.success(request, f"Реестр документов {batch.number} проведён.")
        return redirect(batch.get_absolute_url())


class DocumentBatchUnpostView(LoginRequiredMixin, FinanceAccessMixin, View):
    def post(self, request, pk):
        batch = get_object_or_404(DocumentBatch, pk=pk)
        if batch.status == DocumentBatch.Status.POSTED:
            with transaction.atomic():
                _unpost_document_batch(batch)
            messages.success(request, f"{batch.number} возвращена в черновик.")
            return redirect("document-batch-update", pk=batch.pk)
        return redirect(batch.get_absolute_url())


class DocumentBatchDeleteView(LoginRequiredMixin, FinanceAccessMixin, View):
    template_name = "crm/document_batch_confirm_delete.html"

    def get_object(self):
        return get_object_or_404(DocumentBatch, pk=self.kwargs["pk"])

    def get(self, request, pk):
        return render(request, self.template_name, {"document_batch": self.get_object()})

    def post(self, request, pk):
        batch = self.get_object()
        number = batch.number
        with transaction.atomic():
            if batch.status == DocumentBatch.Status.POSTED:
                _unpost_document_batch(batch)
            batch.delete()
        messages.success(request, f"Реестр документов {number} удалён.")
        return redirect("document-batch-list")


class ReportsView(LoginRequiredMixin, FinanceAccessMixin, TemplateView):
    template_name = "crm/reports.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        date_from_raw = self.request.GET.get("date_from", "").strip()
        date_to_raw = self.request.GET.get("date_to", "").strip()
        currency = self.request.GET.get("currency", "RUB").strip().upper()
        current_expeditor = get_expeditor_filter(self.request)
        if currency not in {"RUB", "USD", "EUR"}:
            currency = "RUB"

        date_from = parse_crm_date(date_from_raw) if date_from_raw else None
        date_to = parse_crm_date(date_to_raw) if date_to_raw else None
        trip_status = self.request.GET.get("trip_status", "").strip()
        valid_trip_statuses = {
            value
            for value, _label in Transportation.Status.choices
            if value != Transportation.Status.CANCELLED
        }
        if trip_status not in valid_trip_statuses:
            trip_status = ""
        trip_manager = self.request.GET.get("trip_manager", "").strip()
        if not trip_manager.isdigit() or not get_user_model().objects.filter(
            pk=trip_manager
        ).exists():
            trip_manager = ""
        trip_client = self.request.GET.get("trip_client", "").strip()
        trip_executor = self.request.GET.get("trip_executor", "").strip()
        trip_carrier = self.request.GET.get("trip_carrier", "").strip()
        queryset = (
            Shipment.objects.exclude(status=Shipment.Status.CANCELLED)
            .filter(currency=currency)
            .select_related("expeditor", "customer", "carrier")
            .prefetch_related("payments")
        )
        if current_expeditor:
            queryset = queryset.filter(expeditor_id=current_expeditor)
        if date_from:
            queryset = queryset.filter(pickup_date__gte=date_from)
        if date_to:
            queryset = queryset.filter(pickup_date__lte=date_to)
        shipments = list(queryset)

        tax_queryset = (
            Transportation.objects.exclude(status=Transportation.Status.CANCELLED)
            .exclude(posting_status=Transportation.PostingStatus.VOIDED)
            .filter(currency=currency)
            .select_related(
                "owner_company", "customer_vat_rate", "executor_vat_rate", "manager"
            )
            .prefetch_related(
                "stops",
                Prefetch(
                    "parties",
                    queryset=TransportationParty.objects.filter(
                        role=TransportationParty.Role.CLIENT, is_active=True
                    ).select_related("organization"),
                    to_attr="report_client_parties",
                ),
                Prefetch(
                    "execution_links",
                    queryset=TransportationLink.objects.filter(is_active=True)
                    .select_related("contractor_party__organization")
                    .order_by("sequence"),
                    to_attr="report_execution_links",
                ),
                Prefetch(
                    "vehicle_assignments",
                    queryset=VehicleAssignment.objects.filter(is_active=True)
                    .select_related("actual_carrier")
                    .order_by("-created_at"),
                    to_attr="report_vehicle_assignments",
                ),
                Prefetch(
                    "settlement_movements",
                    queryset=SettlementMovement.objects.all(),
                    to_attr="report_settlement_movements",
                ),
            )
        )
        if current_expeditor:
            owner_id = CompanyProfile.objects.filter(
                pk=current_expeditor
            ).values_list("organization_id", flat=True).first()
            tax_queryset = (
                tax_queryset.filter(owner_company_id=owner_id)
                if owner_id
                else tax_queryset.none()
            )
        if date_from:
            tax_queryset = tax_queryset.filter(planned_start_date__gte=date_from)
        if date_to:
            tax_queryset = tax_queryset.filter(planned_start_date__lte=date_to)
        if trip_status:
            tax_queryset = tax_queryset.filter(status=trip_status)
        if trip_manager:
            tax_queryset = tax_queryset.filter(manager_id=trip_manager)
        if trip_client.isdigit():
            tax_queryset = tax_queryset.filter(
                parties__role=TransportationParty.Role.CLIENT,
                parties__is_active=True,
                parties__organization_id=trip_client,
            )
        if trip_executor.isdigit():
            tax_queryset = tax_queryset.filter(
                execution_links__is_active=True,
                execution_links__contractor_party__is_active=True,
                execution_links__contractor_party__organization_id=trip_executor,
            )
        if trip_carrier.isdigit():
            tax_queryset = tax_queryset.filter(
                vehicle_assignments__is_active=True,
                vehicle_assignments__actual_carrier_id=trip_carrier,
            )
        tax_transportations = list(tax_queryset.distinct())

        totals = {
            "revenue": Decimal("0"),
            "costs": Decimal("0"),
            "margin": Decimal("0"),
            "received": Decimal("0"),
            "carrier_paid": Decimal("0"),
            "receivables": Decimal("0"),
            "payables": Decimal("0"),
            "overdue_receivables": Decimal("0"),
            "overdue_payables": Decimal("0"),
        }
        receivables = []
        payables = []
        monthly = defaultdict(
            lambda: {
                "shipment_count": 0,
                "revenue": Decimal("0"),
                "costs": Decimal("0"),
                "margin": Decimal("0"),
            }
        )
        by_expeditor = defaultdict(
            lambda: {
                "shipment_count": 0,
                "revenue": Decimal("0"),
                "costs": Decimal("0"),
                "margin": Decimal("0"),
                "receivables": Decimal("0"),
                "payables": Decimal("0"),
            }
        )

        for shipment in shipments:
            receivable = max(shipment.receivable_balance, Decimal("0"))
            payable = max(shipment.payable_balance, Decimal("0"))
            totals["revenue"] += shipment.customer_price
            totals["costs"] += shipment.carrier_price
            totals["margin"] += shipment.margin
            totals["received"] += shipment.received_amount
            totals["carrier_paid"] += shipment.paid_to_carrier_amount
            totals["receivables"] += receivable
            totals["payables"] += payable

            expeditor_values = by_expeditor[shipment.expeditor]
            expeditor_values["shipment_count"] += 1
            expeditor_values["revenue"] += shipment.customer_price
            expeditor_values["costs"] += shipment.carrier_price
            expeditor_values["margin"] += shipment.margin
            expeditor_values["receivables"] += receivable
            expeditor_values["payables"] += payable

            if receivable > 0:
                item = {
                    "shipment": shipment,
                    "balance": receivable,
                    "state": shipment.receivable_state,
                    "state_label": shipment.receivable_state_label,
                    "due_date": shipment.customer_payment_due_date,
                }
                receivables.append(item)
                if shipment.receivable_state == Shipment.PaymentStatus.OVERDUE:
                    totals["overdue_receivables"] += receivable
            if payable > 0:
                item = {
                    "shipment": shipment,
                    "balance": payable,
                    "state": shipment.payable_state,
                    "state_label": shipment.payable_state_label,
                    "due_date": shipment.carrier_payment_due_date,
                }
                payables.append(item)
                if shipment.payable_state == Shipment.PaymentStatus.OVERDUE:
                    totals["overdue_payables"] += payable

            month = shipment.pickup_date.replace(day=1)
            monthly[month]["shipment_count"] += 1
            monthly[month]["revenue"] += shipment.customer_price
            monthly[month]["costs"] += shipment.carrier_price
            monthly[month]["margin"] += shipment.margin

        def debt_sort_key(item):
            return (item["state"] != Shipment.PaymentStatus.OVERDUE, -item["balance"])

        receivables.sort(key=debt_sort_key)
        payables.sort(key=debt_sort_key)
        monthly_rows = [
            {"month": month, **values}
            for month, values in sorted(monthly.items(), reverse=True)
        ]
        expeditor_rows = [
            {"expeditor": expeditor, **values}
            for expeditor, values in sorted(
                by_expeditor.items(), key=lambda item: item[0].name.casefold()
            )
        ]

        tax_by_company = defaultdict(
            lambda: {
                "trip_count": 0,
                "posted_count": 0,
                "sales_vat": Decimal("0.00"),
                "purchase_vat": Decimal("0.00"),
                "profit": Decimal("0.00"),
            }
        )
        tax_trip_rows = []
        for transportation in tax_transportations:
            company_values = tax_by_company[transportation.owner_company]
            company_values["trip_count"] += 1
            if transportation.posting_status == Transportation.PostingStatus.POSTED:
                company_values["posted_count"] += 1
            company_values["sales_vat"] += transportation.customer_vat_amount
            company_values["purchase_vat"] += transportation.executor_vat_amount
            company_values["profit"] += transportation.profit
            tax_trip_rows.append(
                {
                    "transportation": transportation,
                    "sales_vat": transportation.customer_vat_amount,
                    "purchase_vat": transportation.executor_vat_amount,
                    "vat_payable": transportation.vat_payable,
                    "profit": transportation.profit,
                    "profit_tax": transportation.profit_tax_amount,
                    "net_profit": transportation.net_profit,
                }
            )

        tax_totals = {
            "sales_vat": Decimal("0.00"),
            "purchase_vat": Decimal("0.00"),
            "vat_payable": Decimal("0.00"),
            "profit": Decimal("0.00"),
            "profit_tax": Decimal("0.00"),
            "net_profit": Decimal("0.00"),
        }
        tax_company_rows = []
        for company, values in sorted(
            tax_by_company.items(), key=lambda item: item[0].name.casefold()
        ):
            vat_balance = values["sales_vat"] - values["purchase_vat"]
            vat_payable = max(vat_balance, Decimal("0.00"))
            profit_tax = (
                max(values["profit"], Decimal("0.00"))
                * Decimal(company.profit_tax_rate or 0)
                / Decimal("100")
            ).quantize(Decimal("0.01"))
            net_profit = values["profit"] - profit_tax
            row = {
                "company": company,
                **values,
                "vat_balance": vat_balance,
                "vat_payable": vat_payable,
                "profit_tax": profit_tax,
                "net_profit": net_profit,
            }
            tax_company_rows.append(row)
            for key in tax_totals:
                tax_totals[key] += row[key]

        # Управленческая аналитика строится по основной сущности ERP — рейсу.
        # Она использует те же отфильтрованные перевозки, что и налоговый блок,
        # поэтому показатели не расходятся при смене периода или компании.
        def new_trip_bucket(**extra):
            return {
                "trip_count": 0,
                "revenue": Decimal("0.00"),
                "cost": Decimal("0.00"),
                "margin": Decimal("0.00"),
                **extra,
            }

        trip_totals = new_trip_bucket(
            active_count=0,
            closed_count=0,
            posted_count=0,
            vat_payable=Decimal("0.00"),
            profit=Decimal("0.00"),
            net_profit=Decimal("0.00"),
            receivable=Decimal("0.00"),
            payable=Decimal("0.00"),
            overdue_receivable=Decimal("0.00"),
            overdue_payable=Decimal("0.00"),
        )
        status_buckets = {
            value: new_trip_bucket(value=value, label=label)
            for value, label in Transportation.Status.choices
            if value != Transportation.Status.CANCELLED
        }
        client_buckets = {}
        executor_buckets = {}
        carrier_buckets = {}
        trip_aging = {
            "overdue": {"label": "Просрочено", "receivable": Decimal("0.00"), "payable": Decimal("0.00")},
            "seven_days": {"label": "До 7 дней", "receivable": Decimal("0.00"), "payable": Decimal("0.00")},
            "thirty_days": {"label": "8–30 дней", "receivable": Decimal("0.00"), "payable": Decimal("0.00")},
            "later": {"label": "Более 30 дней", "receivable": Decimal("0.00"), "payable": Decimal("0.00")},
            "without_due_date": {"label": "Срок не указан", "receivable": Decimal("0.00"), "payable": Decimal("0.00")},
        }
        trip_receivables = []
        trip_payables = []
        today = timezone.localdate()

        def ensure_group(bucket_map, entity, fallback_label):
            key = entity.pk if entity else fallback_label
            if key not in bucket_map:
                bucket_map[key] = new_trip_bucket(
                    entity=entity,
                    label=str(entity) if entity else fallback_label,
                )
            return bucket_map[key]

        def add_trip_to_group(group, transportation):
            group["trip_count"] += 1
            group["revenue"] += transportation.revenue
            group["cost"] += transportation.cost
            group["margin"] += transportation.margin

        def movement_balances(transportation):
            movements = getattr(transportation, "report_settlement_movements", ())
            receivable = sum(
                (
                    movement.amount
                    for movement in movements
                    if movement.side == SettlementMovement.Side.RECEIVABLE
                ),
                Decimal("0.00"),
            )
            payable = sum(
                (
                    movement.amount
                    for movement in movements
                    if movement.side == SettlementMovement.Side.PAYABLE
                ),
                Decimal("0.00"),
            )
            due_dates = {
                SettlementMovement.Side.RECEIVABLE: next(
                    (
                        movement.due_date
                        for movement in movements
                        if movement.side == SettlementMovement.Side.RECEIVABLE
                        and movement.kind == SettlementMovement.Kind.ACCRUAL
                    ),
                    None,
                ),
                SettlementMovement.Side.PAYABLE: next(
                    (
                        movement.due_date
                        for movement in movements
                        if movement.side == SettlementMovement.Side.PAYABLE
                        and movement.kind == SettlementMovement.Kind.ACCRUAL
                    ),
                    None,
                ),
            }
            return max(receivable, Decimal("0.00")), max(payable, Decimal("0.00")), due_dates

        def add_aging(side, balance, due_date):
            if balance <= 0:
                return
            if not due_date:
                bucket = trip_aging["without_due_date"]
            else:
                days_to_due = (due_date - today).days
                if days_to_due < 0:
                    bucket = trip_aging["overdue"]
                elif days_to_due <= 7:
                    bucket = trip_aging["seven_days"]
                elif days_to_due <= 30:
                    bucket = trip_aging["thirty_days"]
                else:
                    bucket = trip_aging["later"]
            bucket[side] += balance

        for transportation in tax_transportations:
            trip_totals["trip_count"] += 1
            trip_totals["revenue"] += transportation.revenue
            trip_totals["cost"] += transportation.cost
            trip_totals["margin"] += transportation.margin
            trip_totals["vat_payable"] += transportation.vat_payable
            trip_totals["profit"] += transportation.profit
            trip_totals["net_profit"] += transportation.net_profit
            if transportation.status == Transportation.Status.CLOSED:
                trip_totals["closed_count"] += 1
            else:
                trip_totals["active_count"] += 1
            if transportation.posting_status == Transportation.PostingStatus.POSTED:
                trip_totals["posted_count"] += 1

            status_group = status_buckets.get(transportation.status)
            if status_group:
                add_trip_to_group(status_group, transportation)
            client_party = getattr(transportation, "report_client_parties", ())
            client = client_party[0].organization if client_party else None
            add_trip_to_group(
                ensure_group(client_buckets, client, "Клиент не указан"), transportation
            )
            execution_links = getattr(transportation, "report_execution_links", ())
            executor = (
                execution_links[0].contractor_party.organization
                if execution_links
                else None
            )
            add_trip_to_group(
                ensure_group(executor_buckets, executor, "Исполнитель не указан"),
                transportation,
            )
            assignments = getattr(transportation, "report_vehicle_assignments", ())
            actual_carrier = assignments[0].actual_carrier if assignments else None
            add_trip_to_group(
                ensure_group(carrier_buckets, actual_carrier, "Перевозчик не указан"),
                transportation,
            )

            receivable, payable, due_dates = movement_balances(transportation)
            trip_totals["receivable"] += receivable
            trip_totals["payable"] += payable
            add_aging(
                "receivable", receivable, due_dates[SettlementMovement.Side.RECEIVABLE]
            )
            add_aging("payable", payable, due_dates[SettlementMovement.Side.PAYABLE])
            if due_dates[SettlementMovement.Side.RECEIVABLE] and due_dates[
                SettlementMovement.Side.RECEIVABLE
            ] < today and receivable > 0:
                trip_totals["overdue_receivable"] += receivable
            if due_dates[SettlementMovement.Side.PAYABLE] and due_dates[
                SettlementMovement.Side.PAYABLE
            ] < today and payable > 0:
                trip_totals["overdue_payable"] += payable
            if receivable > 0:
                trip_receivables.append(
                    {
                        "transportation": transportation,
                        "counterparty": client,
                        "balance": receivable,
                        "due_date": due_dates[SettlementMovement.Side.RECEIVABLE],
                        "overdue": bool(
                            due_dates[SettlementMovement.Side.RECEIVABLE]
                            and due_dates[SettlementMovement.Side.RECEIVABLE] < today
                        ),
                    }
                )
            if payable > 0:
                trip_payables.append(
                    {
                        "transportation": transportation,
                        "counterparty": executor,
                        "balance": payable,
                        "due_date": due_dates[SettlementMovement.Side.PAYABLE],
                        "overdue": bool(
                            due_dates[SettlementMovement.Side.PAYABLE]
                            and due_dates[SettlementMovement.Side.PAYABLE] < today
                        ),
                    }
                )

        trip_totals["average_margin"] = (
            (trip_totals["margin"] / trip_totals["trip_count"]).quantize(Decimal("0.01"))
            if trip_totals["trip_count"]
            else Decimal("0.00")
        )
        trip_totals["margin_percent"] = (
            (trip_totals["margin"] / trip_totals["revenue"] * Decimal("100")).quantize(
                Decimal("0.01")
            )
            if trip_totals["revenue"]
            else Decimal("0.00")
        )
        for bucket in status_buckets.values():
            bucket["margin_percent"] = (
                (bucket["margin"] / bucket["revenue"] * Decimal("100")).quantize(
                    Decimal("0.01")
                )
                if bucket["revenue"]
                else Decimal("0.00")
            )
        trip_status_rows = [
            bucket
            for value, _label in Transportation.Status.choices
            if value != Transportation.Status.CANCELLED
            for bucket in [status_buckets[value]]
            if bucket["trip_count"]
        ]

        def sorted_group_rows(bucket_map):
            rows = list(bucket_map.values())
            for row in rows:
                row["margin_percent"] = (
                    (row["margin"] / row["revenue"] * Decimal("100")).quantize(
                        Decimal("0.01")
                    )
                    if row["revenue"]
                    else Decimal("0.00")
                )
            return sorted(rows, key=lambda row: (-row["margin"], row["label"].casefold()))

        trip_client_rows = sorted_group_rows(client_buckets)
        trip_executor_rows = sorted_group_rows(executor_buckets)
        trip_carrier_rows = sorted_group_rows(carrier_buckets)
        trip_aging_rows = list(trip_aging.values())
        trip_receivables.sort(key=lambda row: (not row["overdue"], -row["balance"]))
        trip_payables.sort(key=lambda row: (not row["overdue"], -row["balance"]))

        context.update(
            {
                "totals": totals,
                "receivables": receivables,
                "payables": payables,
                "monthly_rows": monthly_rows,
                "expeditor_rows": expeditor_rows,
                "shipment_count": len(shipments),
                "current_currency": currency,
                "current_date_from": (
                    date_from.strftime("%d.%m.%Y") if date_from else date_from_raw
                ),
                "current_date_to": (
                    date_to.strftime("%d.%m.%Y") if date_to else date_to_raw
                ),
                "currency_choices": ("RUB", "USD", "EUR"),
                "expeditors": CompanyProfile.objects.all(),
                "current_expeditor": current_expeditor,
                "tax_totals": tax_totals,
                "tax_company_rows": tax_company_rows,
                "tax_trip_rows": tax_trip_rows,
                "tax_transportation_count": len(tax_transportations),
                "tax_posted_count": sum(
                    row["posted_count"] for row in tax_company_rows
                ),
                "trip_totals": trip_totals,
                "trip_status_rows": trip_status_rows,
                "trip_client_rows": trip_client_rows,
                "trip_executor_rows": trip_executor_rows,
                "trip_carrier_rows": trip_carrier_rows,
                "trip_aging_rows": trip_aging_rows,
                "trip_receivables": trip_receivables,
                "trip_payables": trip_payables,
                "trip_status_choices": tuple(
                    (value, label)
                    for value, label in Transportation.Status.choices
                    if value != Transportation.Status.CANCELLED
                ),
                "trip_managers": get_user_model()
                .objects.filter(transportations__isnull=False)
                .distinct()
                .order_by("last_name", "first_name", "username"),
                "trip_clients": Organization.objects.filter(
                    transportation_participations__role=TransportationParty.Role.CLIENT,
                    transportation_participations__is_active=True,
                )
                .distinct()
                .order_by("name"),
                "trip_executors": Organization.objects.filter(
                    transportation_participations__role=TransportationParty.Role.EXECUTOR,
                    transportation_participations__is_active=True,
                )
                .distinct()
                .order_by("name"),
                "trip_carriers": Organization.objects.filter(
                    factual_transportations__isnull=False,
                )
                .distinct()
                .order_by("name"),
                "current_trip_status": trip_status,
                "current_trip_manager": trip_manager,
                "current_trip_client": trip_client,
                "current_trip_executor": trip_executor,
                "current_trip_carrier": trip_carrier,
            }
        )
        return context


class TaxReportExportView(ReportsView):
    def get(self, request, *args, **kwargs):
        context = self.get_context_data()
        company_rows = [
            [
                "Наша компания", "ИНН", "Рейсы", "Проведено", "НДС продажи",
                "Входной НДС", "Сальдо НДС", "НДС к уплате",
                "Прибыль без НДС", "Налог на прибыль", "Чистая прибыль",
                "Валюта",
            ]
        ]
        for row in context["tax_company_rows"]:
            company_rows.append(
                [
                    row["company"].short_name or row["company"].name,
                    row["company"].tax_id,
                    row["trip_count"],
                    row["posted_count"],
                    row["sales_vat"],
                    row["purchase_vat"],
                    row["vat_balance"],
                    row["vat_payable"],
                    row["profit"],
                    row["profit_tax"],
                    row["net_profit"],
                    context["current_currency"],
                ]
            )
        trip_rows = [
            [
                "Рейс", "Наша компания", "Дата", "Маршрут", "Проведение",
                "НДС продажи", "Входной НДС", "НДС к уплате",
                "Прибыль без НДС", "Налог", "Чистая прибыль", "Валюта",
            ]
        ]
        for row in context["tax_trip_rows"]:
            transportation = row["transportation"]
            trip_rows.append(
                [
                    transportation.number or "Черновик",
                    transportation.owner_company.short_name or transportation.owner_company.name,
                    transportation.planned_start_date,
                    transportation.route,
                    transportation.get_posting_status_display(),
                    row["sales_vat"],
                    row["purchase_vat"],
                    row["vat_payable"],
                    row["profit"],
                    row["profit_tax"],
                    row["net_profit"],
                    context["current_currency"],
                ]
            )
        return _xlsx_response(
            f"tax-report-{timezone.localdate():%Y%m%d}.xlsx",
            (("Компании", company_rows), ("Рейсы", trip_rows)),
        )


class DebtReportView(LoginRequiredMixin, FinanceAccessMixin, TemplateView):
    template_name = "crm/debt_report.html"

    def _filtered_transportations(self):
        queryset = (
            Transportation.objects.exclude(status=Transportation.Status.CANCELLED)
            .exclude(posting_status=Transportation.PostingStatus.VOIDED)
            .filter(posting_status=Transportation.PostingStatus.POSTED)
            .select_related("owner_company", "manager")
            .prefetch_related(
                "stops",
                Prefetch(
                    "parties",
                    queryset=TransportationParty.objects.filter(
                        role=TransportationParty.Role.CLIENT, is_active=True
                    ).select_related("organization"),
                    to_attr="debt_client_parties",
                ),
                Prefetch(
                    "execution_links",
                    queryset=TransportationLink.objects.filter(is_active=True)
                    .select_related("contractor_party__organization", "contract")
                    .order_by("sequence"),
                    to_attr="debt_execution_links",
                ),
                Prefetch("settlement_movements", to_attr="debt_movements"),
            )
            .order_by("-planned_start_date", "-document_date", "-pk")
        )
        currency = get_currency_filter(self.request, default="RUB")
        if currency:
            queryset = queryset.filter(currency=currency)
        owner = self.request.GET.get("owner", "").strip()
        side = self.request.GET.get("side", "").strip()
        state = self.request.GET.get("state", "").strip()
        q = self.request.GET.get("q", "").strip()
        if owner.isdigit():
            queryset = queryset.filter(owner_company_id=owner)
        if q:
            queryset = queryset.filter(
                Q(number__iunicodecontains=q)
                | Q(owner_company__name__iunicodecontains=q)
                | Q(parties__organization__name__iunicodecontains=q)
                | Q(parties__organization__tax_id__iunicodecontains=q)
                | Q(execution_links__contractor_party__organization__name__iunicodecontains=q)
                | Q(execution_links__contractor_party__organization__tax_id__iunicodecontains=q)
                | Q(stops__city__iunicodecontains=q)
            ).distinct()
        if side not in {"", SettlementMovement.Side.RECEIVABLE, SettlementMovement.Side.PAYABLE}:
            side = ""
        if state not in {"", "overdue", "due", "no_due_date"}:
            state = ""
        return queryset, currency, owner, side, state, q

    @staticmethod
    def _balances(transportation):
        receivable = sum(
            (
                movement.amount
                for movement in getattr(transportation, "debt_movements", ())
                if movement.side == SettlementMovement.Side.RECEIVABLE
            ),
            Decimal("0.00"),
        )
        payable = sum(
            (
                movement.amount
                for movement in getattr(transportation, "debt_movements", ())
                if movement.side == SettlementMovement.Side.PAYABLE
            ),
            Decimal("0.00"),
        )
        return max(receivable, Decimal("0.00")), max(payable, Decimal("0.00"))

    @staticmethod
    def _due_dates(transportation):
        return {
            SettlementMovement.Side.RECEIVABLE: next(
                (
                    movement.due_date
                    for movement in getattr(transportation, "debt_movements", ())
                    if movement.side == SettlementMovement.Side.RECEIVABLE
                    and movement.kind == SettlementMovement.Kind.ACCRUAL
                ),
                transportation.customer_payment_due_date,
            ),
            SettlementMovement.Side.PAYABLE: next(
                (
                    movement.due_date
                    for movement in getattr(transportation, "debt_movements", ())
                    if movement.side == SettlementMovement.Side.PAYABLE
                    and movement.kind == SettlementMovement.Kind.ACCRUAL
                ),
                transportation.executor_payment_due_date,
            ),
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        queryset, currency, owner, side_filter, state_filter, query = self._filtered_transportations()
        today = timezone.localdate()
        rows = []
        totals = {
            "receivable": Decimal("0.00"),
            "payable": Decimal("0.00"),
            "overdue_receivable": Decimal("0.00"),
            "overdue_payable": Decimal("0.00"),
            "net_position": Decimal("0.00"),
        }
        by_counterparty = {}

        for transportation in queryset:
            receivable, payable = self._balances(transportation)
            due_dates = self._due_dates(transportation)
            client_party = getattr(transportation, "debt_client_parties", ())
            client = client_party[0].organization if client_party else None
            links = getattr(transportation, "debt_execution_links", ())
            executor = links[0].contractor_party.organization if links else None
            sides = (
                (SettlementMovement.Side.RECEIVABLE, "Дебиторка", client, receivable, due_dates[SettlementMovement.Side.RECEIVABLE]),
                (SettlementMovement.Side.PAYABLE, "Кредиторка", executor, payable, due_dates[SettlementMovement.Side.PAYABLE]),
            )
            for side, side_label, counterparty, balance, due_date in sides:
                if balance <= 0:
                    continue
                overdue = bool(due_date and due_date < today)
                state = "overdue" if overdue else "no_due_date" if not due_date else "due"
                if side_filter and side != side_filter:
                    continue
                if state_filter and state != state_filter:
                    continue
                if side == SettlementMovement.Side.RECEIVABLE:
                    totals["receivable"] += balance
                    if overdue:
                        totals["overdue_receivable"] += balance
                else:
                    totals["payable"] += balance
                    if overdue:
                        totals["overdue_payable"] += balance
                key = (counterparty.pk if counterparty else f"empty-{side}", side)
                if key not in by_counterparty:
                    by_counterparty[key] = {
                        "counterparty": counterparty,
                        "side": side,
                        "side_label": side_label,
                        "balance": Decimal("0.00"),
                        "overdue": Decimal("0.00"),
                        "trip_count": 0,
                    }
                by_counterparty[key]["balance"] += balance
                by_counterparty[key]["trip_count"] += 1
                if overdue:
                    by_counterparty[key]["overdue"] += balance
                rows.append(
                    {
                        "transportation": transportation,
                        "owner_company": transportation.owner_company,
                        "counterparty": counterparty,
                        "side": side,
                        "side_label": side_label,
                        "balance": balance,
                        "due_date": due_date,
                        "days_overdue": (today - due_date).days if overdue else 0,
                        "state": state,
                        "state_label": "Просрочено" if overdue else "Без срока" if not due_date else "К оплате",
                    }
                )

        rows.sort(key=lambda row: (row["state"] != "overdue", row["due_date"] or date.max, -row["balance"]))
        counterparty_rows = sorted(
            by_counterparty.values(),
            key=lambda row: (-row["balance"], str(row["counterparty"] or "").casefold()),
        )
        totals["net_position"] = totals["receivable"] - totals["payable"]
        context.update(
            {
                "debt_rows": rows,
                "counterparty_rows": counterparty_rows,
                "debt_totals": totals,
                "current_currency": currency,
                "currency_choices": ("RUB", "USD", "EUR"),
                "owners": Organization.objects.filter(is_own_company=True, is_active=True),
                "current_owner": owner,
                "current_side": side_filter,
                "current_state": state_filter,
                "current_q": query,
                "side_choices": SettlementMovement.Side.choices,
                "state_choices": (
                    ("overdue", "Просрочено"),
                    ("due", "К оплате"),
                    ("no_due_date", "Без срока"),
                ),
            }
        )
        return context


class DebtReportExportView(DebtReportView):
    def get(self, request, *args, **kwargs):
        context = self.get_context_data()
        debt_rows = [
            [
                "Рейс", "Маршрут", "Наша компания", "Контрагент", "ИНН",
                "Сторона", "Срок", "Состояние", "Дней просрочки", "Остаток",
                "Валюта",
            ]
        ]
        for row in context["debt_rows"]:
            counterparty = row["counterparty"]
            debt_rows.append(
                [
                    row["transportation"].number or "Черновик",
                    row["transportation"].route,
                    row["owner_company"].short_name or row["owner_company"].name,
                    counterparty.short_name or counterparty.name if counterparty else "Не указан",
                    counterparty.tax_id if counterparty else "",
                    row["side_label"],
                    row["due_date"],
                    row["state_label"],
                    row["days_overdue"],
                    row["balance"],
                    context["current_currency"],
                ]
            )
        counterparty_rows = [
            ["Контрагент", "ИНН", "Сторона", "Рейсы", "Просрочено", "Остаток", "Валюта"]
        ]
        for row in context["counterparty_rows"]:
            counterparty = row["counterparty"]
            counterparty_rows.append(
                [
                    counterparty.short_name or counterparty.name if counterparty else "Не указан",
                    counterparty.tax_id if counterparty else "",
                    row["side_label"],
                    row["trip_count"],
                    row["overdue"],
                    row["balance"],
                    context["current_currency"],
                ]
            )
        return _xlsx_response(
            f"debts-{timezone.localdate():%Y%m%d}.xlsx",
            (("Рейсы", debt_rows), ("Контрагенты", counterparty_rows)),
        )


class ProfitabilityReportView(LoginRequiredMixin, FinanceAccessMixin, TemplateView):
    template_name = "crm/profitability_report.html"

    def _filtered_transportations(self):
        queryset = (
            Transportation.objects.exclude(status=Transportation.Status.CANCELLED)
            .exclude(posting_status=Transportation.PostingStatus.VOIDED)
            .select_related("owner_company", "manager", "customer_vat_rate", "executor_vat_rate")
            .prefetch_related(
                "stops",
                Prefetch(
                    "parties",
                    queryset=TransportationParty.objects.filter(
                        role=TransportationParty.Role.CLIENT, is_active=True
                    ).select_related("organization"),
                    to_attr="profit_client_parties",
                ),
                Prefetch(
                    "execution_links",
                    queryset=TransportationLink.objects.filter(is_active=True)
                    .select_related("contractor_party__organization")
                    .order_by("sequence"),
                    to_attr="profit_execution_links",
                ),
            )
            .order_by("-planned_start_date", "-document_date", "-pk")
        )
        currency = get_currency_filter(self.request, default="RUB")
        if currency:
            queryset = queryset.filter(currency=currency)
        date_from_raw = self.request.GET.get("date_from", "").strip()
        date_to_raw = self.request.GET.get("date_to", "").strip()
        date_from = parse_crm_date(date_from_raw) if date_from_raw else None
        date_to = parse_crm_date(date_to_raw) if date_to_raw else None
        owner = self.request.GET.get("owner", "").strip()
        status = self.request.GET.get("status", "").strip()
        manager = self.request.GET.get("manager", "").strip()
        client = self.request.GET.get("client", "").strip()
        executor = self.request.GET.get("executor", "").strip()
        query = self.request.GET.get("q", "").strip()
        low_margin_raw = self.request.GET.get("low_margin_percent", "").strip().replace(",", ".")
        low_margin_percent = None
        if low_margin_raw:
            try:
                low_margin_percent = Decimal(low_margin_raw)
            except InvalidOperation:
                low_margin_percent = None

        if date_from:
            queryset = queryset.filter(planned_start_date__gte=date_from)
        if date_to:
            queryset = queryset.filter(planned_start_date__lte=date_to)
        if owner.isdigit():
            queryset = queryset.filter(owner_company_id=owner)
        if status in Transportation.Status.values:
            queryset = queryset.filter(status=status)
        else:
            status = ""
        if manager.isdigit():
            queryset = queryset.filter(manager_id=manager)
        if client.isdigit():
            queryset = queryset.filter(
                parties__role=TransportationParty.Role.CLIENT,
                parties__is_active=True,
                parties__organization_id=client,
            )
        if executor.isdigit():
            queryset = queryset.filter(
                execution_links__is_active=True,
                execution_links__contractor_party__is_active=True,
                execution_links__contractor_party__organization_id=executor,
            )
        if query:
            queryset = queryset.filter(
                Q(number__iunicodecontains=query)
                | Q(owner_company__name__iunicodecontains=query)
                | Q(manager__username__iunicodecontains=query)
                | Q(parties__organization__name__iunicodecontains=query)
                | Q(parties__organization__tax_id__iunicodecontains=query)
                | Q(execution_links__contractor_party__organization__name__iunicodecontains=query)
                | Q(execution_links__contractor_party__organization__tax_id__iunicodecontains=query)
                | Q(stops__city__iunicodecontains=query)
            )
        return (
            queryset.distinct(),
            {
                "currency": currency,
                "date_from": date_from,
                "date_to": date_to,
                "date_from_raw": date_from_raw,
                "date_to_raw": date_to_raw,
                "owner": owner,
                "status": status,
                "manager": manager,
                "client": client,
                "executor": executor,
                "query": query,
                "loss_only": self.request.GET.get("loss_only") == "1",
                "low_margin_percent": low_margin_percent,
                "low_margin_raw": low_margin_raw,
            },
        )

    @staticmethod
    def _group_add(groups, key, label, entity, transportation):
        if key not in groups:
            groups[key] = {
                "label": label,
                "entity": entity,
                "trip_count": 0,
                "revenue": Decimal("0.00"),
                "cost": Decimal("0.00"),
                "margin": Decimal("0.00"),
                "net_profit": Decimal("0.00"),
            }
        group = groups[key]
        group["trip_count"] += 1
        group["revenue"] += transportation.revenue
        group["cost"] += transportation.cost
        group["margin"] += transportation.margin
        group["net_profit"] += transportation.net_profit

    @staticmethod
    def _finalize_groups(groups):
        rows = list(groups.values())
        for row in rows:
            row["margin_percent"] = (
                (row["margin"] / row["revenue"] * Decimal("100")).quantize(Decimal("0.01"))
                if row["revenue"]
                else Decimal("0.00")
            )
        return sorted(rows, key=lambda row: (-row["margin"], row["label"].casefold()))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        queryset, filters = self._filtered_transportations()
        totals = {
            "trip_count": 0,
            "posted_count": 0,
            "revenue": Decimal("0.00"),
            "cost": Decimal("0.00"),
            "margin": Decimal("0.00"),
            "vat_payable": Decimal("0.00"),
            "profit": Decimal("0.00"),
            "profit_tax": Decimal("0.00"),
            "net_profit": Decimal("0.00"),
            "loss_count": 0,
        }
        rows = []
        owner_groups = {}
        client_groups = {}
        executor_groups = {}
        manager_groups = {}

        for transportation in queryset:
            if filters["loss_only"] and transportation.margin >= 0:
                continue
            if (
                filters["low_margin_percent"] is not None
                and transportation.margin_percent > filters["low_margin_percent"]
            ):
                continue
            client_party = getattr(transportation, "profit_client_parties", ())
            client = client_party[0].organization if client_party else None
            links = getattr(transportation, "profit_execution_links", ())
            executor = links[0].contractor_party.organization if links else None
            rows.append(
                {
                    "transportation": transportation,
                    "client": client,
                    "executor": executor,
                    "manager": transportation.manager,
                }
            )
            totals["trip_count"] += 1
            if transportation.posting_status == Transportation.PostingStatus.POSTED:
                totals["posted_count"] += 1
            totals["revenue"] += transportation.revenue
            totals["cost"] += transportation.cost
            totals["margin"] += transportation.margin
            totals["vat_payable"] += transportation.vat_payable
            totals["profit"] += transportation.profit
            totals["profit_tax"] += transportation.profit_tax_amount
            totals["net_profit"] += transportation.net_profit
            if transportation.margin < 0:
                totals["loss_count"] += 1

            self._group_add(owner_groups, transportation.owner_company_id, str(transportation.owner_company), transportation.owner_company, transportation)
            self._group_add(client_groups, client.pk if client else "empty-client", str(client) if client else "Клиент не указан", client, transportation)
            self._group_add(executor_groups, executor.pk if executor else "empty-executor", str(executor) if executor else "Исполнитель не указан", executor, transportation)
            self._group_add(manager_groups, transportation.manager_id, transportation.manager.get_full_name() or transportation.manager.username, None, transportation)

        totals["margin_percent"] = (
            (totals["margin"] / totals["revenue"] * Decimal("100")).quantize(Decimal("0.01"))
            if totals["revenue"]
            else Decimal("0.00")
        )
        context.update(
            {
                "profit_rows": rows,
                "profit_totals": totals,
                "owner_rows": self._finalize_groups(owner_groups),
                "client_rows": self._finalize_groups(client_groups),
                "executor_rows": self._finalize_groups(executor_groups),
                "manager_rows": self._finalize_groups(manager_groups),
                "current_currency": filters["currency"],
                "currency_choices": ("RUB", "USD", "EUR"),
                "current_date_from": filters["date_from"].strftime("%d.%m.%Y") if filters["date_from"] else filters["date_from_raw"],
                "current_date_to": filters["date_to"].strftime("%d.%m.%Y") if filters["date_to"] else filters["date_to_raw"],
                "current_owner": filters["owner"],
                "current_status": filters["status"],
                "current_manager": filters["manager"],
                "current_client": filters["client"],
                "current_executor": filters["executor"],
                "current_q": filters["query"],
                "loss_only": filters["loss_only"],
                "low_margin_percent": filters["low_margin_raw"],
                "owners": Organization.objects.filter(is_own_company=True, is_active=True),
                "status_choices": tuple(
                    (value, label)
                    for value, label in Transportation.Status.choices
                    if value != Transportation.Status.CANCELLED
                ),
                "managers": get_user_model().objects.filter(
                    transportations__isnull=False
                ).distinct().order_by("last_name", "first_name", "username"),
                "clients": Organization.objects.filter(
                    transportation_participations__role=TransportationParty.Role.CLIENT,
                    transportation_participations__is_active=True,
                ).distinct().order_by("name"),
                "executors": Organization.objects.filter(
                    transportation_participations__role=TransportationParty.Role.EXECUTOR,
                    transportation_participations__is_active=True,
                ).distinct().order_by("name"),
            }
        )
        return context


class ProfitabilityReportExportView(ProfitabilityReportView):
    def get(self, request, *args, **kwargs):
        context = self.get_context_data()
        trip_rows = [
            [
                "Рейс", "Маршрут", "Наша компания", "Клиент", "Исполнитель",
                "Менеджер", "Статус", "Проведение", "Выручка", "Расход",
                "Маржа", "Маржинальность, %", "НДС к уплате",
                "Прибыль без НДС", "Налог", "Чистая прибыль", "Валюта",
            ]
        ]
        for row in context["profit_rows"]:
            transportation = row["transportation"]
            trip_rows.append(
                [
                    transportation.number or "Черновик",
                    transportation.route,
                    transportation.owner_company.short_name or transportation.owner_company.name,
                    str(row["client"] or "Не указан"),
                    str(row["executor"] or "Не указан"),
                    row["manager"].get_full_name() or row["manager"].username,
                    transportation.get_status_display(),
                    transportation.get_posting_status_display(),
                    transportation.revenue,
                    transportation.cost,
                    transportation.margin,
                    transportation.margin_percent,
                    transportation.vat_payable,
                    transportation.profit,
                    transportation.profit_tax_amount,
                    transportation.net_profit,
                    context["current_currency"],
                ]
            )

        def grouped_rows(title, rows):
            data = [
                [
                    title, "Рейсы", "Выручка", "Расход", "Маржа",
                    "Маржинальность, %", "Чистая прибыль", "Валюта",
                ]
            ]
            for row in rows:
                data.append(
                    [
                        row["label"],
                        row["trip_count"],
                        row["revenue"],
                        row["cost"],
                        row["margin"],
                        row["margin_percent"],
                        row["net_profit"],
                        context["current_currency"],
                    ]
                )
            return data

        return _xlsx_response(
            f"profitability-{timezone.localdate():%Y%m%d}.xlsx",
            (
                ("Рейсы", trip_rows),
                ("Клиенты", grouped_rows("Клиент", context["client_rows"])),
                ("Исполнители", grouped_rows("Исполнитель", context["executor_rows"])),
                ("Менеджеры", grouped_rows("Менеджер", context["manager_rows"])),
                ("Наши компании", grouped_rows("Наша компания", context["owner_rows"])),
            ),
        )


class PlannerView(LoginRequiredMixin, TemplateView):
    """Agenda of transportation milestones and manually assigned tasks."""

    template_name = "crm/planner.html"

    @staticmethod
    def _month_bounds(value):
        first = value.replace(day=1)
        if first.month == 12:
            next_month = first.replace(year=first.year + 1, month=1)
        else:
            next_month = first.replace(month=first.month + 1)
        return first, next_month - timedelta(days=1)

    def _date_filter(self):
        today = timezone.localdate()
        month_start, month_end = self._month_bounds(today)
        date_from = parse_crm_date(self.request.GET.get("date_from", "").strip())
        date_to = parse_crm_date(self.request.GET.get("date_to", "").strip())
        if not date_from:
            date_from = month_start
        if not date_to:
            date_to = month_end
        if date_from > date_to:
            date_from, date_to = date_to, date_from
        return date_from, date_to

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        date_from, date_to = self._date_filter()
        task_status = self.request.GET.get("task_status", "").strip()
        if task_status not in {value for value, _label in PlannerTask.Status.choices}:
            task_status = ""
        assignee = self.request.GET.get("assignee", "").strip()
        if not assignee.isdigit() or not get_user_model().objects.filter(
            pk=assignee, is_active=True
        ).exists():
            assignee = ""

        transportations = list(
            Transportation.objects.exclude(status=Transportation.Status.CANCELLED)
            .select_related("manager")
            .prefetch_related(
                "stops",
                Prefetch(
                    "execution_links",
                    queryset=TransportationLink.objects.filter(is_active=True)
                    .select_related("contractor_party__organization", "contract")
                    .order_by("sequence"),
                ),
                Prefetch(
                    "vehicle_assignments",
                    queryset=VehicleAssignment.objects.filter(is_active=True)
                    .select_related("actual_carrier", "driver", "vehicle", "trailer", "combination")
                    .order_by("-created_at"),
                ),
                Prefetch("settlement_movements", to_attr="planner_settlement_movements"),
            )
            .order_by("planned_start_date", "pk")
        )
        automatic_tasks = automatic_planner_tasks(transportations)
        event_items = []

        def add_event(event_date, kind, label, transportation, title):
            if not event_date or not date_from <= event_date <= date_to:
                return
            event_items.append(
                {
                    "date": event_date,
                    "kind": kind,
                    "label": label,
                    "title": title,
                    "transportation": transportation,
                    "url": transportation.get_absolute_url(),
                }
            )

        for transportation in transportations:
            route = transportation.route
            add_event(
                transportation.planned_start_date,
                "loading",
                "Погрузка",
                transportation,
                f"Погрузка · {route}",
            )
            add_event(
                transportation.planned_end_date,
                "unloading",
                "Выгрузка",
                transportation,
                f"Выгрузка · {route}",
            )
            add_event(
                transportation.customer_payment_due_date,
                "receivable",
                "Оплата клиента",
                transportation,
                f"Срок оплаты клиента · {transportation.number or 'Черновик'}",
            )
            add_event(
                transportation.executor_payment_due_date,
                "payable",
                "Оплата исполнителю",
                transportation,
                f"Срок оплаты исполнителю · {transportation.number or 'Черновик'}",
            )
            for stop in transportation.stops.all():
                stop_date = (
                    timezone.localtime(stop.planned_from).date()
                    if stop.planned_from and timezone.is_aware(stop.planned_from)
                    else stop.planned_from.date()
                    if stop.planned_from
                    else None
                )
                add_event(
                    stop_date,
                    "stop",
                    stop.get_kind_display(),
                    transportation,
                    f"{stop.get_kind_display()} · {stop.city or stop.address}",
                )

        event_items.sort(key=lambda item: (item["date"], item["kind"], item["title"]))
        weekday_labels = {
            0: "понедельник",
            1: "вторник",
            2: "среда",
            3: "четверг",
            4: "пятница",
            5: "суббота",
            6: "воскресенье",
        }
        events_by_date = []
        for event in event_items:
            if not events_by_date or events_by_date[-1]["date"] != event["date"]:
                events_by_date.append(
                    {
                        "date": event["date"],
                        "label": event["date"].strftime("%d.%m.%Y"),
                        "weekday": weekday_labels[event["date"].weekday()],
                        "events": [],
                    }
                )
            events_by_date[-1]["events"].append(event)

        tasks = PlannerTask.objects.select_related(
            "transportation", "assignee"
        ).order_by("due_date", "-priority", "-created_at")
        if task_status:
            tasks = tasks.filter(status=task_status)
        if assignee:
            tasks = tasks.filter(assignee_id=assignee)
        tasks = tasks.filter(
            Q(due_date__range=(date_from, date_to)) | Q(due_date__isnull=True)
        )
        tasks = list(tasks)
        open_tasks = [
            task
            for task in tasks
            if task.status in {PlannerTask.Status.TODO, PlannerTask.Status.IN_PROGRESS}
        ]
        overdue_tasks = [task for task in open_tasks if task.is_overdue]
        context.update(
            {
                "events_by_date": events_by_date,
                "event_count": len(event_items),
                "automatic_tasks": automatic_tasks,
                "automatic_task_count": len(automatic_tasks),
                "tasks": tasks,
                "task_count": len(tasks),
                "open_task_count": len(open_tasks),
                "overdue_task_count": len(overdue_tasks),
                "date_from": date_from,
                "date_to": date_to,
                "current_date_from": date_from.strftime("%d.%m.%Y"),
                "current_date_to": date_to.strftime("%d.%m.%Y"),
                "current_task_status": task_status,
                "current_assignee": assignee,
                "task_status_choices": PlannerTask.Status.choices,
                "assignees": get_user_model()
                .objects.filter(is_active=True)
                .order_by("last_name", "first_name", "username"),
                "today": timezone.localdate(),
            }
        )
        return context


class PlannerTaskCreateView(LoginRequiredMixin, CreateView):
    model = PlannerTask
    form_class = PlannerTaskForm
    template_name = "crm/planner_task_form.html"
    success_url = reverse_lazy("planner")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        transportation_id = self.request.GET.get("transportation", "").strip()
        if transportation_id.isdigit():
            initial["transportation"] = transportation_id
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "entity_title": "Задача планировщика",
                "entity_description": "Назначьте поручение ответственному менеджеру и, при необходимости, свяжите его с рейсом.",
                "cancel_url": reverse_lazy("planner"),
            }
        )
        return context

    def form_valid(self, form):
        if form.cleaned_data.get("status") == PlannerTask.Status.DONE:
            form.instance.completed_at = timezone.now()
            form.instance.completed_by = self.request.user
        messages.success(self.request, "Задача добавлена в планировщик.")
        return super().form_valid(form)


class PlannerTaskUpdateView(LoginRequiredMixin, UpdateView):
    model = PlannerTask
    form_class = PlannerTaskForm
    template_name = "crm/planner_task_form.html"
    success_url = reverse_lazy("planner")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "entity_title": "Задача планировщика",
                "entity_description": "Измените срок, ответственного или статус поручения.",
                "cancel_url": reverse_lazy("planner"),
            }
        )
        return context

    def form_valid(self, form):
        if form.cleaned_data.get("status") == PlannerTask.Status.DONE:
            if self.object.status != PlannerTask.Status.DONE:
                form.instance.completed_at = timezone.now()
                form.instance.completed_by = self.request.user
        else:
            form.instance.completed_at = None
            form.instance.completed_by = None
        messages.success(self.request, "Задача планировщика обновлена.")
        return super().form_valid(form)


class PlannerTaskCompleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        task = get_object_or_404(PlannerTask, pk=pk)
        task.status = PlannerTask.Status.DONE
        task.completed_at = timezone.now()
        task.completed_by = request.user
        task.save(update_fields=["status", "completed_at", "completed_by", "updated_at"])
        messages.success(request, "Задача отмечена выполненной.")
        return redirect(request.POST.get("next") or reverse("planner"))


class SearchableDirectoryListView(LoginRequiredMixin, ListView):
    paginate_by = 20
    search_fields = ()
    ordering_field = "name"

    def get_queryset(self):
        queryset = (
            super().get_queryset()
            .annotate(shipment_count=Count("shipments"))
            .order_by(self.ordering_field)
        )
        query = self.request.GET.get("q", "").strip()
        if query:
            condition = Q()
            for field in self.search_fields:
                condition |= Q(**{f"{field}__iunicodecontains": query})
            queryset = queryset.filter(condition)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["current_q"] = self.request.GET.get("q", "")
        return context


class SuccessMessageMixin:
    success_message = "Сохранено."

    def form_valid(self, form):
        messages.success(self.request, self.success_message)
        return super().form_valid(form)


class SafeDeleteView(LoginRequiredMixin, View):
    model = None
    entity_label = "запись"
    list_url_name = None
    template_name = "crm/safe_delete_confirm.html"

    def get_object(self):
        return get_object_or_404(self.model, pk=self.kwargs["pk"])

    def get_context(self, instance, dependencies=None):
        dependencies = (
            deletion_dependencies(instance)
            if dependencies is None
            else dependencies
        )
        return {
            "object": instance,
            "entity_label": self.entity_label,
            "dependencies": dependencies,
            "can_delete": not dependencies,
            "cancel_url": instance.get_absolute_url(),
            "list_url": reverse_lazy(self.list_url_name),
        }

    def get(self, request, *args, **kwargs):
        instance = self.get_object()
        return self.render(request, instance)

    def render(self, request, instance, dependencies=None, status=200):
        from django.shortcuts import render

        return render(
            request,
            self.template_name,
            self.get_context(instance, dependencies),
            status=status,
        )

    def post(self, request, *args, **kwargs):
        if not user_can_delete_records(request.user):
            messages.error(request, "У вас нет прав на удаление записей.")
            return redirect(self.get_object().get_absolute_url())
        instance = self.get_object()
        dependencies = deletion_dependencies(instance)
        if dependencies:
            messages.error(
                request,
                "Удаление запрещено: запись используется в других документах.",
            )
            return self.render(request, instance, dependencies, status=409)
        title = str(instance)
        try:
            perform_safe_delete(instance)
        except ProtectedError as error:
            protected = tuple(error.protected_objects)
            dependencies = [
                DeletionDependency(
                    label="Связанные защищённые записи",
                    count=len(protected),
                    examples=tuple(
                        deletion_example(item) for item in protected[:3]
                    ),
                )
            ]
            messages.error(
                request,
                "Удаление остановлено: появились новые связанные записи.",
            )
            return self.render(request, instance, dependencies, status=409)
        messages.success(request, f"Удалено: {title}.")
        return redirect(self.list_url_name)


class ShipmentDeleteView(SafeDeleteView):
    model = Shipment
    entity_label = "заявку"
    list_url_name = "shipment-list"


class TransportationDeleteView(SafeDeleteView):
    model = Transportation
    entity_label = "заявку / рейс"
    list_url_name = "transportation-list"


class TransportOrderDeleteView(SafeDeleteView):
    model = TransportOrder
    entity_label = "заказ"
    list_url_name = "order-list"


class OrganizationDeleteView(SafeDeleteView):
    model = Organization
    entity_label = "контрагента"
    list_url_name = "organization-list"


class DriverDeleteView(SafeDeleteView):
    model = Driver
    entity_label = "водителя"
    list_url_name = "driver-list"


class VehicleDeleteView(SafeDeleteView):
    model = Vehicle
    entity_label = "транспорт"
    list_url_name = "vehicle-list"


class VehicleCombinationDeleteView(SafeDeleteView):
    model = VehicleCombination
    entity_label = "сцепку"
    list_url_name = "vehicle-list"


class OrganizationListView(LoginRequiredMixin, ListView):
    model = Organization
    template_name = "crm/organization_list.html"
    context_object_name = "organizations"
    paginate_by = 30

    def get_queryset(self):
        queryset = Organization.objects.select_related("group").prefetch_related(
            Prefetch(
                "roles",
                queryset=OrganizationRole.objects.filter(is_active=True),
                to_attr="active_roles",
            ),
            "bank_accounts", "contact_people"
        )
        query = self.request.GET.get("q", "").strip()
        role = self.request.GET.get("role", "").strip()
        group = self.request.GET.get("group", "").strip()
        if query:
            queryset = queryset.filter(
                Q(name__iunicodecontains=query)
                | Q(short_name__iunicodecontains=query)
                | Q(tax_id__iunicodecontains=query)
                | Q(contact_name__iunicodecontains=query)
            )
        if role in OrganizationRole.Role.values:
            queryset = queryset.filter(roles__role=role, roles__is_active=True)
        if self.request.GET.get("own") == "1":
            queryset = queryset.filter(is_own_company=True)
        if group.isdigit():
            queryset = queryset.filter(group_id=group)
        return queryset.distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        all_organizations = Organization.objects.all()
        context.update(
            {
                "current_q": self.request.GET.get("q", ""),
                "current_role": self.request.GET.get("role", ""),
                "current_own": self.request.GET.get("own", ""),
                "current_group": self.request.GET.get("group", ""),
                "organization_groups": OrganizationGroup.objects.filter(
                    is_active=True
                ).select_related("parent"),
                "role_choices": OrganizationRole.Role.choices,
                "organization_count": all_organizations.count(),
                "client_count": all_organizations.filter(
                    roles__role=OrganizationRole.Role.CLIENT,
                    roles__is_active=True,
                ).distinct().count(),
                "forwarder_count": all_organizations.filter(
                    roles__role=OrganizationRole.Role.FORWARDER,
                    roles__is_active=True,
                ).distinct().count(),
                "carrier_count": all_organizations.filter(
                    roles__role=OrganizationRole.Role.CARRIER,
                    roles__is_active=True,
                ).distinct().count(),
            }
        )
        return context


class OrganizationDetailView(LoginRequiredMixin, DetailView):
    model = Organization
    template_name = "crm/organization_detail.html"
    context_object_name = "organization"
    queryset = Organization.objects.prefetch_related(
        "roles", "legacy_customers", "legacy_carriers", "legacy_expeditors"
    )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        organization = self.object
        context["active_roles"] = organization.roles.filter(is_active=True)
        context["participations"] = organization.transportation_participations.filter(
            is_active=True
        ).select_related("transportation")[:12]
        context["factual_transportations"] = organization.factual_transportations.filter(
            is_active=True
        ).select_related("transportation", "driver", "vehicle")[:10]
        context["contacts"] = organization.contact_people.filter(is_active=True)
        context["bank_accounts"] = organization.bank_accounts.filter(is_active=True)
        context["contracts"] = Contract.objects.filter(
            Q(customer__organization=organization)
            | Q(carrier__organization=organization)
            | Q(expeditor__organization=organization)
        ).select_related("expeditor", "customer", "carrier", "vat_rate").distinct()
        context["history"] = organization.change_history.select_related("changed_by")[:30]
        context["transportation_count"] = Transportation.objects.filter(
            parties__organization=organization,
            parties__is_active=True,
        ).distinct().count()
        revenue = TripCharge.objects.filter(
            counterparty=organization, direction=TripCharge.Direction.REVENUE
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
        costs = TripCharge.objects.filter(
            counterparty=organization, direction=TripCharge.Direction.COST
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
        context["revenue_total"] = revenue
        context["cost_total"] = costs
        context["margin_total"] = revenue - costs
        context["average_margin"] = (
            (revenue - costs) / context["transportation_count"]
            if context["transportation_count"]
            else Decimal("0")
        )
        context["receivable_total"] = SettlementMovement.objects.filter(
            counterparty=organization,
            side=SettlementMovement.Side.RECEIVABLE,
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
        context["payable_total"] = SettlementMovement.objects.filter(
            counterparty=organization,
            side=SettlementMovement.Side.PAYABLE,
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
        context["overdue_receivable_total"] = SettlementMovement.objects.filter(
            counterparty=organization,
            side=SettlementMovement.Side.RECEIVABLE,
            due_date__lt=timezone.localdate(),
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
        context["overdue_payable_total"] = SettlementMovement.objects.filter(
            counterparty=organization,
            side=SettlementMovement.Side.PAYABLE,
            due_date__lt=timezone.localdate(),
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
        return context


class OrganizationWorkspaceMixin:
    bank_formset_class = OrganizationBankAccountFormSet
    contact_formset_class = OrganizationContactFormSet

    def get_formset(self, formset_class, prefix, data=None, instance=None):
        return formset_class(
            data=data,
            instance=instance if instance is not None else self.object,
            prefix=prefix,
        )

    def get_workspace_context(self, organization):
        if not organization or not organization.pk:
            return {
                "contracts": Contract.objects.none(),
                "organization_documents": ShipmentDocument.objects.none(),
                "settlement_rows": [],
                "receivable_total": Decimal("0"),
                "payable_total": Decimal("0"),
                "active_trip_count": 0,
            }

        customer_shipments = list(
            Shipment.objects.filter(customer__organization=organization)
            .select_related("customer", "carrier", "expeditor")
            .prefetch_related("payments")
            .order_by("-pickup_date")
        )
        carrier_shipments = list(
            Shipment.objects.filter(carrier__organization=organization)
            .select_related("customer", "carrier", "expeditor")
            .prefetch_related("payments")
            .order_by("-pickup_date")
        )
        shipment_ids = {shipment.pk for shipment in customer_shipments + carrier_shipments}
        settlement_rows = []
        seen_rows = set()
        for shipment in customer_shipments:
            key = (shipment.pk, "customer")
            if key not in seen_rows:
                settlement_rows.append(
                    {
                        "shipment": shipment,
                        "side": "Покупатель",
                        "accrued": shipment.customer_price,
                        "paid": shipment.received_amount,
                        "balance": shipment.receivable_balance,
                        "state": shipment.receivable_state_label,
                        "direction": "receivable",
                    }
                )
                seen_rows.add(key)
        for shipment in carrier_shipments:
            key = (shipment.pk, "supplier")
            if key not in seen_rows:
                settlement_rows.append(
                    {
                        "shipment": shipment,
                        "side": "Поставщик",
                        "accrued": shipment.carrier_price,
                        "paid": shipment.paid_to_carrier_amount,
                        "balance": shipment.payable_balance,
                        "state": shipment.payable_state_label,
                        "direction": "payable",
                    }
                )
                seen_rows.add(key)

        contracts = Contract.objects.filter(
            Q(customer__organization=organization)
            | Q(carrier__organization=organization)
            | Q(expeditor__organization=organization)
        ).select_related("expeditor", "customer", "carrier").distinct()
        documents = ShipmentDocument.objects.filter(
            shipment_id__in=shipment_ids
        ).select_related("shipment").order_by("-document_date", "-created_at")
        active_trip_count = Transportation.objects.filter(
            parties__organization=organization,
            parties__is_active=True,
        ).exclude(
            status__in=[Transportation.Status.CLOSED, Transportation.Status.CANCELLED]
        ).distinct().count()
        return {
            "contracts": contracts,
            "organization_documents": documents,
            "settlement_rows": settlement_rows,
            "receivable_total": sum(
                (max(shipment.receivable_balance, Decimal("0")) for shipment in customer_shipments),
                Decimal("0"),
            ),
            "payable_total": sum(
                (max(shipment.payable_balance, Decimal("0")) for shipment in carrier_shipments),
                Decimal("0"),
            ),
            "active_trip_count": active_trip_count,
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = context.get("form")
        instance = form.instance if form else self.object
        context.setdefault(
            "bank_formset",
            self.get_formset(self.bank_formset_class, "bank_accounts", instance=instance),
        )
        context.setdefault(
            "contact_formset",
            self.get_formset(self.contact_formset_class, "contact_people", instance=instance),
        )
        context.update(self.get_workspace_context(self.object))
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object() if kwargs.get("pk") else None
        form = self.get_form()
        instance = form.instance
        bank_submitted = "bank_accounts-TOTAL_FORMS" in request.POST
        contact_submitted = "contact_people-TOTAL_FORMS" in request.POST
        bank_formset = self.get_formset(
            self.bank_formset_class,
            "bank_accounts",
            data=request.POST if bank_submitted else None,
            instance=instance,
        )
        contact_formset = self.get_formset(
            self.contact_formset_class,
            "contact_people",
            data=request.POST if contact_submitted else None,
            instance=instance,
        )
        formsets_valid = (
            (not bank_submitted or bank_formset.is_valid())
            and (not contact_submitted or contact_formset.is_valid())
        )
        if form.is_valid() and formsets_valid:
            before_bank = list(
                instance.bank_accounts.values(
                    "account_number", "bank_name", "bik", "correspondent_account",
                    "currency", "is_primary", "is_active", "notes",
                )
            ) if instance.pk else []
            before_contacts = list(
                instance.contact_people.values(
                    "full_name", "position", "phone", "email", "is_primary",
                    "is_active", "notes",
                )
            ) if instance.pk else []
            self.object = form.save()
            if bank_submitted:
                bank_formset.instance = self.object
                bank_formset.save()
            if contact_submitted:
                contact_formset.instance = self.object
                contact_formset.save()
            self.sync_primary_registers()
            audit_changes = dict(getattr(form, "audit_changes", {}))
            if bank_submitted:
                after_bank = list(
                    self.object.bank_accounts.values(
                        "account_number", "bank_name", "bik", "correspondent_account",
                        "currency", "is_primary", "is_active", "notes",
                    )
                )
                if before_bank != after_bank:
                    audit_changes["bank_accounts"] = {"old": before_bank, "new": after_bank}
            if contact_submitted:
                after_contacts = list(
                    self.object.contact_people.values(
                        "full_name", "position", "phone", "email", "is_primary",
                        "is_active", "notes",
                    )
                )
                if before_contacts != after_contacts:
                    audit_changes["contact_people"] = {"old": before_contacts, "new": after_contacts}
            if audit_changes:
                audit_action = getattr(
                    form, "audit_action", OrganizationChange.Action.UPDATE
                )
                if "fns_status" in audit_changes or (
                    "legal_address" in audit_changes and "tax_id" in audit_changes
                ):
                    audit_action = OrganizationChange.Action.FNS_SYNC
                OrganizationChange.objects.create(
                    organization=self.object,
                    changed_by=request.user if request.user.is_authenticated else None,
                    action=audit_action,
                    changes=audit_changes,
                )
            messages.success(self.request, self.success_message)
            if request.POST.get("action") == "save_close":
                return redirect("organization-list")
            return redirect(self.object.get_absolute_url())
        return self.render_to_response(
            self.get_context_data(
                form=form,
                bank_formset=bank_formset,
                contact_formset=contact_formset,
            )
        )

    def sync_primary_registers(self):
        organization = self.object
        primary_bank = organization.bank_accounts.filter(is_active=True).order_by(
            "-is_primary", "pk"
        ).first()
        if primary_bank:
            organization.bank_name = primary_bank.bank_name
            organization.bik = primary_bank.bik
            organization.settlement_account = primary_bank.account_number
            organization.correspondent_account = primary_bank.correspondent_account
        elif "bank_accounts-TOTAL_FORMS" in self.request.POST:
            organization.bank_name = ""
            organization.bik = ""
            organization.settlement_account = ""
            organization.correspondent_account = ""

        primary_contact = organization.contact_people.filter(is_active=True).order_by(
            "-is_primary", "pk"
        ).first()
        if primary_contact:
            organization.contact_name = primary_contact.full_name
            organization.phone = primary_contact.phone
            organization.email = primary_contact.email
        elif "contact_people-TOTAL_FORMS" in self.request.POST:
            organization.contact_name = ""
            organization.phone = ""
            organization.email = ""
        organization.save(
            update_fields=[
                "bank_name", "bik", "settlement_account", "correspondent_account",
                "contact_name", "phone", "email", "updated_at",
            ]
        )
        from .sync import sync_organization_to_legacy

        sync_organization_to_legacy(organization)


class OrganizationCreateView(
    LoginRequiredMixin, OrganizationWorkspaceMixin, CreateView
):
    model = Organization
    form_class = OrganizationForm
    template_name = "crm/organization_form.html"
    success_message = "Организация добавлена в единый справочник."


class OrganizationUpdateView(
    LoginRequiredMixin, OrganizationWorkspaceMixin, UpdateView
):
    model = Organization
    form_class = OrganizationForm
    template_name = "crm/organization_form.html"
    success_message = "Карточка организации и её роли обновлены."


class TransportOrderListView(LoginRequiredMixin, ListView):
    model = TransportOrder
    template_name = "crm/order_list.html"
    context_object_name = "orders"
    paginate_by = 30

    def get_queryset(self):
        queryset = TransportOrder.objects.select_related(
            "owner_company", "client", "manager", "transportation"
        ).prefetch_related("stops")
        query = self.request.GET.get("q", "").strip()
        status = self.request.GET.get("status", "").strip()
        owner = self.request.GET.get("owner", "").strip()
        if query:
            queryset = queryset.filter(
                Q(number__iunicodecontains=query)
                | Q(client__name__iunicodecontains=query)
                | Q(client__tax_id__iunicodecontains=query)
                | Q(cargo_name__iunicodecontains=query)
                | Q(stops__city__iunicodecontains=query)
                | Q(stops__address__iunicodecontains=query)
            ).distinct()
        if status in TransportOrder.Status.values:
            queryset = queryset.filter(status=status)
        if owner.isdigit():
            queryset = queryset.filter(owner_company_id=owner)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        all_orders = TransportOrder.objects.all()
        current_owner = self.request.GET.get("owner", "").strip()
        if current_owner.isdigit():
            all_orders = all_orders.filter(owner_company_id=current_owner)
        context.update(
            {
                "current_q": self.request.GET.get("q", ""),
                "current_status": self.request.GET.get("status", ""),
                "current_owner": current_owner,
                "status_choices": TransportOrder.Status.choices,
                "owners": Organization.objects.filter(
                    is_own_company=True, is_active=True
                ),
                "order_count": all_orders.count(),
                "new_count": all_orders.filter(
                    status=TransportOrder.Status.NEW
                ).count(),
                "assigned_count": all_orders.filter(
                    status=TransportOrder.Status.ASSIGNED
                ).count(),
                "total_rate": all_orders.exclude(
                    status=TransportOrder.Status.CANCELLED
                ).aggregate(total=Sum("rate"))["total"]
                or Decimal("0"),
            }
        )
        return context


class TransportOrderEditMixin:
    model = TransportOrder
    form_class = TransportOrderForm
    template_name = "crm/order_form.html"
    stop_prefix = "route_stops"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_stop_formset(self, form, data=None):
        kwargs = {
            "data": data,
            "instance": form.instance,
            "prefix": self.stop_prefix,
        }
        if not form.instance.pk and data is None:
            kwargs["initial"] = [
                {"sequence": 1, "kind": TransportOrderStop.Kind.PICKUP},
                {"sequence": 2, "kind": TransportOrderStop.Kind.DELIVERY},
            ]
        formset = TransportOrderStopFormSet(**kwargs)
        if not form.instance.pk and data is None:
            formset.extra = 2
        return formset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.setdefault(
            "stop_formset", self.get_stop_formset(context["form"])
        )
        order = self.object
        missing_client_contract = False
        client_contract_create_url = ""
        if order and order.pk:
            owner_profile = order.owner_company.legacy_expeditors.filter(
                is_active=True
            ).first()
            customer = order.client.legacy_customers.filter(is_active=True).first()
            if owner_profile and customer:
                has_client_contract = Contract.objects.exclude(
                    status__in=[Contract.Status.TERMINATED, Contract.Status.ARCHIVED]
                ).filter(
                    kind=Contract.Kind.CLIENT_FORWARDING,
                    expeditor=owner_profile,
                    customer=customer,
                ).exists()
                missing_client_contract = not has_client_contract
                params = urlencode(
                    {
                        "kind": Contract.Kind.CLIENT_FORWARDING,
                        "expeditor": owner_profile.pk,
                        "customer": customer.pk,
                        "organization": order.client_id,
                    }
                )
                client_contract_create_url = f"{reverse('contract-create')}?{params}"
        context.update(
            {
                "missing_client_contract": missing_client_contract,
                "client_contract_create_url": client_contract_create_url,
            }
        )
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object() if kwargs.get("pk") else None
        form = self.get_form()
        stop_formset = self.get_stop_formset(form, data=request.POST)
        form_valid = form.is_valid()
        stops_valid = stop_formset.is_valid()
        if form_valid and stops_valid:
            start_date, end_date = stop_formset.route_bounds()
            form.instance.planned_start_date = start_date
            form.instance.planned_end_date = end_date
            with transaction.atomic():
                self.object = form.save()
                stop_formset.instance = self.object
                stop_formset.save()
            action = request.POST.get("action", "save")
            if action == "assign":
                transportation = assign_order_to_transportation(
                    self.object, request.user
                )
                messages.success(
                    request,
                    f"Заказ {self.object.number} сохранён и передан в назначение.",
                )
                return redirect("transportation-update", pk=transportation.pk)
            messages.success(request, f"Заказ {self.object.number} сохранён.")
            return redirect("order-list")
        return self.render_to_response(
            self.get_context_data(form=form, stop_formset=stop_formset)
        )


class TransportOrderCreateView(
    LoginRequiredMixin, TransportOrderEditMixin, CreateView
):
    pass


class TransportOrderUpdateView(
    LoginRequiredMixin, TransportOrderEditMixin, UpdateView
):
    pass


class TransportOrderAssignView(LoginRequiredMixin, View):
    def post(self, request, pk):
        order = get_object_or_404(TransportOrder, pk=pk)
        transportation = assign_order_to_transportation(order, request.user)
        messages.success(
            request,
            f"Заказ {order.number} передан в назначение исполнителя.",
        )
        return redirect("transportation-update", pk=transportation.pk)


class TransportationListView(LoginRequiredMixin, ListView):
    model = Transportation
    template_name = "crm/transportation_list.html"
    context_object_name = "transportations"
    paginate_by = 25

    def get_queryset(self):
        queryset = Transportation.objects.select_related(
            "owner_company", "manager", "legacy_shipment", "legacy_shipment__customer"
        ).prefetch_related(
            "stops",
            Prefetch(
                "parties",
                queryset=TransportationParty.objects.filter(
                    role=TransportationParty.Role.CLIENT, is_active=True
                ).select_related("organization"),
                to_attr="client_parties",
            ),
            Prefetch(
                "execution_links",
                queryset=TransportationLink.objects.filter(is_active=True).select_related(
                    "contractor_party__organization", "contract"
                ),
            ),
            Prefetch(
                "vehicle_assignments",
                queryset=VehicleAssignment.objects.filter(is_active=True).select_related(
                    "actual_carrier", "driver", "vehicle", "trailer", "combination"
                ),
            ),
        )
        query = self.request.GET.get("q", "").strip()
        status = self.request.GET.get("status", "").strip()
        owner = self.request.GET.get("owner", "").strip()
        if query:
            queryset = queryset.filter(
                Q(number__iunicodecontains=query)
                | Q(cargo_name__iunicodecontains=query)
                | Q(parties__organization__name__iunicodecontains=query)
                | Q(parties__organization__tax_id__iunicodecontains=query)
                | Q(stops__city__iunicodecontains=query)
            ).distinct()
        if status in Transportation.Status.values:
            queryset = queryset.filter(status=status)
        if owner.isdigit():
            queryset = queryset.filter(owner_company_id=owner)
        scope = self.request.GET.get("scope", "").strip()
        if scope == "active":
            queryset = queryset.exclude(
                status__in=[Transportation.Status.CLOSED, Transportation.Status.CANCELLED]
            )
        elif scope == "in_transit":
            queryset = queryset.filter(status=Transportation.Status.IN_TRANSIT)
        elif scope == "draft":
            queryset = queryset.filter(posting_status=Transportation.PostingStatus.DRAFT)
        elif scope == "closed":
            queryset = queryset.filter(status=Transportation.Status.CLOSED)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        all_transportations = Transportation.objects.all()
        current_owner = self.request.GET.get("owner", "").strip()
        if current_owner.isdigit():
            all_transportations = all_transportations.filter(
                owner_company_id=current_owner
            )
        context.update(
            {
                "current_q": self.request.GET.get("q", ""),
                "current_status": self.request.GET.get("status", ""),
                "current_owner": current_owner,
                "current_scope": self.request.GET.get("scope", ""),
                "status_choices": Transportation.Status.choices,
                "owners": Organization.objects.filter(is_own_company=True),
                "transportation_count": all_transportations.count(),
                "active_count": all_transportations.exclude(
                    status__in=[Transportation.Status.CLOSED, Transportation.Status.CANCELLED]
                ).count(),
                "in_transit_count": all_transportations.filter(
                    status=Transportation.Status.IN_TRANSIT
                ).count(),
                "draft_count": all_transportations.filter(
                    posting_status=Transportation.PostingStatus.DRAFT
                ).count(),
                "closed_count": all_transportations.filter(
                    status=Transportation.Status.CLOSED
                ).count(),
                "chain_issue_count": sum(
                    1 for transportation in all_transportations if transportation.chain_issues()
                ),
            }
        )
        return context


class TransportationAccountingView(TransportationListView):
    """Financial and EPD register for all transportation documents."""

    template_name = "crm/transportation_accounting.html"

    def get_queryset(self):
        queryset = super().get_queryset().prefetch_related(
            Prefetch(
                "electronic_documents",
                queryset=TransportationElectronicDocument.objects.select_related("stop"),
            )
        )
        currency = get_currency_filter(self.request, default="RUB")
        if currency:
            queryset = queryset.filter(currency=currency)
        epd_status = self.request.GET.get("epd_status", "").strip()
        if epd_status in TransportationElectronicDocument.Status.values:
            queryset = queryset.filter(
                electronic_documents__status=epd_status
            ).distinct()
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        filtered = self.get_queryset()
        totals = {
            "revenue": Decimal("0"),
            "cost": Decimal("0"),
            "margin": Decimal("0"),
            "profit": Decimal("0"),
            "profit_tax": Decimal("0"),
            "net_profit": Decimal("0"),
            "vat_payable": Decimal("0"),
            "receivable": Decimal("0"),
            "payable": Decimal("0"),
            "overdue_receivable": Decimal("0"),
            "overdue_payable": Decimal("0"),
        }
        today = timezone.localdate()
        for transportation in filtered:
            totals["revenue"] += transportation.revenue
            totals["cost"] += transportation.cost
            totals["margin"] += transportation.margin
            totals["profit"] += transportation.profit
            totals["profit_tax"] += transportation.profit_tax_amount
            totals["net_profit"] += transportation.net_profit
            totals["vat_payable"] += transportation.vat_payable
            receivable = max(transportation.receivable_balance, Decimal("0"))
            payable = max(transportation.payable_balance, Decimal("0"))
            totals["receivable"] += receivable
            totals["payable"] += payable
            if (
                receivable > 0
                and transportation.customer_payment_due_date
                and transportation.customer_payment_due_date < today
            ):
                totals["overdue_receivable"] += receivable
            if (
                payable > 0
                and transportation.executor_payment_due_date
                and transportation.executor_payment_due_date < today
            ):
                totals["overdue_payable"] += payable
        context["accounting_totals"] = totals
        context["epd_status_choices"] = TransportationElectronicDocument.Status.choices
        context["current_epd_status"] = self.request.GET.get("epd_status", "")
        context["current_currency"] = get_currency_filter(self.request, default="RUB")
        context["currency_choices"] = ("RUB", "USD", "EUR")
        return context


def _bank_statement_candidates(direction, owner_id=None, currency="RUB"):
    """Подбор проведённых рейсов с непогашенным остатком."""

    queryset = (
        Transportation.objects.filter(
            posting_status=Transportation.PostingStatus.POSTED,
            currency=currency,
        )
        .exclude(status=Transportation.Status.CANCELLED)
        .select_related("owner_company")
        .prefetch_related(
            "stops",
            Prefetch(
                "parties",
                queryset=TransportationParty.objects.filter(
                    role=TransportationParty.Role.CLIENT, is_active=True
                ).select_related("organization"),
                to_attr="bank_statement_client_parties",
            ),
            Prefetch(
                "execution_links",
                queryset=TransportationLink.objects.filter(is_active=True)
                .select_related("contractor_party__organization")
                .order_by("sequence"),
                to_attr="bank_statement_execution_links",
            ),
            Prefetch("settlement_movements", to_attr="bank_statement_movements"),
        )
        .order_by("-document_date", "-pk")
    )
    if str(owner_id or "").isdigit():
        queryset = queryset.filter(owner_company_id=owner_id)

    candidates = []
    for transportation in queryset:
        movements = getattr(transportation, "bank_statement_movements", ())
        side = (
            SettlementMovement.Side.RECEIVABLE
            if direction == BankStatement.Direction.INCOME
            else SettlementMovement.Side.PAYABLE
        )
        balance = sum(
            (movement.amount for movement in movements if movement.side == side),
            Decimal("0.00"),
        )
        if balance <= 0:
            continue
        if direction == BankStatement.Direction.INCOME:
            party = getattr(transportation, "bank_statement_client_parties", [None])[0]
            if not party:
                continue
            counterparty = party.organization
        else:
            link = getattr(transportation, "bank_statement_execution_links", [None])[0]
            if not link:
                continue
            counterparty = link.contractor_party.organization
        candidates.append(
            {
                "transportation": transportation,
                "balance": balance,
                "counterparty": counterparty,
            }
        )
    return candidates


class BankStatementEditorMixin:
    model = BankStatement
    form_class = BankStatementForm
    template_name = "crm/bank_statement_form.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        direction = self.request.GET.get("direction", "").strip()
        if direction in BankStatement.Direction.values:
            initial["direction"] = direction
        currency = self.request.GET.get("currency", "").strip().upper()
        if currency in {"RUB", "USD", "EUR"}:
            initial["currency"] = currency
        owner = self.request.GET.get("owner", "").strip()
        if owner.isdigit():
            initial["owner_company"] = owner
        initial.setdefault("statement_date", timezone.localdate())
        return initial

    def _selected_state(self):
        selected = set(self.request.POST.getlist("transportation_ids"))
        amounts = {
            key.removeprefix("amount_"): value
            for key, value in self.request.POST.items()
            if key.startswith("amount_")
        }
        references = {
            key.removeprefix("reference_"): value.strip()
            for key, value in self.request.POST.items()
            if key.startswith("reference_")
        }
        if self.request.method != "POST" and getattr(self, "object", None):
            for line in self.object.lines.all():
                selected.add(str(line.transportation_id))
                amounts[str(line.transportation_id)] = str(line.amount)
                references[str(line.transportation_id)] = line.payment_reference
        return selected, amounts, references

    def _candidate_context(self, form):
        direction = (
            form.data.get("direction")
            if form.is_bound
            else form.initial.get("direction", BankStatement.Direction.INCOME)
        )
        if direction not in BankStatement.Direction.values:
            direction = BankStatement.Direction.INCOME
        owner_id = (
            form.data.get("owner_company")
            if form.is_bound
            else form.initial.get("owner_company") or getattr(self.object, "owner_company_id", None)
        )
        owner_id = getattr(owner_id, "pk", owner_id)
        currency = (
            form.data.get("currency", "RUB")
            if form.is_bound
            else form.initial.get("currency", "RUB")
        ).upper()
        if currency not in {"RUB", "USD", "EUR"}:
            currency = "RUB"
        selected, amounts, references = self._selected_state()
        result = {
            "current_bank_direction": direction,
            "current_bank_owner": str(owner_id or ""),
            "current_bank_currency": currency,
            "bank_income_candidates": [],
            "bank_expense_candidates": [],
            "bank_selected_ids": selected,
            "bank_entered_amounts": amounts,
            "bank_entered_references": references,
        }
        for key, candidate_direction in (
            ("bank_income_candidates", BankStatement.Direction.INCOME),
            ("bank_expense_candidates", BankStatement.Direction.EXPENSE),
        ):
            candidates = _bank_statement_candidates(
                candidate_direction, owner_id=owner_id, currency=currency
            )
            for candidate in candidates:
                transportation_id = str(candidate["transportation"].pk)
                candidate["selected"] = transportation_id in selected
                candidate["entered_amount"] = amounts.get(
                    transportation_id, candidate["balance"]
                )
                candidate["entered_reference"] = references.get(transportation_id, "")
            result[key] = candidates
        return result

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = context["form"]
        context.update(self._candidate_context(form))
        context["entity_title"] = "Банковский приход / расход"
        context["cancel_url"] = reverse_lazy("bank-statement-list")
        return context

    def _parse_selected_lines(self, form):
        direction = form.cleaned_data["direction"]
        owner_id = form.cleaned_data["owner_company"].pk
        currency = form.cleaned_data["currency"]
        candidates = _bank_statement_candidates(direction, owner_id, currency)
        candidate_map = {str(item["transportation"].pk): item for item in candidates}
        selected_ids = self.request.POST.getlist("transportation_ids")
        if not selected_ids:
            return [], ["Выберите хотя бы один рейс для проведения."]
        lines = []
        errors = []
        seen = set()
        for raw_id in selected_ids:
            if raw_id in seen:
                continue
            seen.add(raw_id)
            candidate = candidate_map.get(raw_id)
            if not candidate:
                errors.append("Один из выбранных рейсов уже не имеет задолженности или недоступен.")
                continue
            raw_amount = self.request.POST.get(f"amount_{raw_id}", "").strip()
            payment_reference = self.request.POST.get(
                f"reference_{raw_id}", ""
            ).strip()[:100]
            try:
                amount = Decimal(raw_amount.replace(" ", "").replace(",", "."))
            except (InvalidOperation, AttributeError):
                amount = Decimal("0")
            if amount <= 0:
                errors.append(f"{candidate['transportation']}: укажите сумму больше нуля.")
                continue
            if amount > candidate["balance"]:
                errors.append(
                    f"{candidate['transportation']}: сумма не может быть больше остатка "
                    f"{candidate['balance']}."
                )
                continue
            lines.append((candidate["transportation"], amount, payment_reference))
        return lines, errors

    def _save_statement(self, form, lines):
        statement = form.save(commit=False)
        if not statement.pk:
            statement.created_by = self.request.user
        statement.save()
        statement.lines.all().delete()
        BankStatementLine.objects.bulk_create(
            [
                BankStatementLine(
                    statement=statement,
                    transportation=transportation,
                    amount=amount,
                    payment_reference=payment_reference,
                )
                for transportation, amount, payment_reference in lines
            ]
        )
        return statement

    def post(self, request, *args, **kwargs):
        self.object = self.get_object() if kwargs.get("pk") else None
        form = self.get_form()
        valid = form.is_valid()
        lines, errors = (self._parse_selected_lines(form) if valid else ([], []))
        for error in errors:
            form.add_error(None, error)
        if valid and not errors:
            with transaction.atomic():
                self.object = self._save_statement(form, lines)
            if request.POST.get("action") == "post":
                try:
                    self.object = post_bank_statement(self.object, request.user)
                except ValidationError as error:
                    for message in getattr(error, "messages", [str(error)]):
                        messages.error(request, message)
                    messages.warning(
                        request,
                        "Документ сохранён как черновик. Исправьте строки и проведите его повторно.",
                    )
                    return redirect(self.object.get_absolute_url())
                messages.success(
                    request,
                    f"{self.object.get_direction_display()} {self.object.number} проведён.",
                )
            else:
                messages.success(request, f"Банковский документ {self.object.number} сохранён как черновик.")
            return redirect(self.object.get_absolute_url())
        return self.render_to_response(
            self.get_context_data(form=form)
        )


class BankStatementListView(LoginRequiredMixin, FinanceAccessMixin, ListView):
    model = BankStatement
    template_name = "crm/bank_statement_list.html"
    context_object_name = "bank_statements"
    paginate_by = 30

    def get_queryset(self):
        queryset = (
            BankStatement.objects.select_related("owner_company", "bank_account")
            .annotate(total_sum=Sum("lines__amount"), line_total=Count("lines"))
            .order_by("-statement_date", "-created_at")
        )
        status = self.request.GET.get("status", "").strip()
        direction = self.request.GET.get("direction", "").strip()
        owner = self.request.GET.get("owner", "").strip()
        if status in BankStatement.Status.values:
            queryset = queryset.filter(status=status)
        if direction in BankStatement.Direction.values:
            queryset = queryset.filter(direction=direction)
        if owner.isdigit():
            queryset = queryset.filter(owner_company_id=owner)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "owners": Organization.objects.filter(is_own_company=True, is_active=True),
                "status_choices": BankStatement.Status.choices,
                "direction_choices": BankStatement.Direction.choices,
                "current_status": self.request.GET.get("status", ""),
                "current_direction": self.request.GET.get("direction", ""),
                "current_owner": self.request.GET.get("owner", ""),
                "draft_count": BankStatement.objects.filter(
                    status=BankStatement.Status.DRAFT
                ).count(),
                "posted_count": BankStatement.objects.filter(
                    status=BankStatement.Status.POSTED
                ).count(),
            }
        )
        return context


class BankStatementCreateView(LoginRequiredMixin, FinanceAccessMixin, BankStatementEditorMixin, CreateView):
    pass


class BankStatementUpdateView(LoginRequiredMixin, FinanceAccessMixin, BankStatementEditorMixin, UpdateView):
    def get_queryset(self):
        return BankStatement.objects.filter(status=BankStatement.Status.DRAFT)


class BankStatementDetailView(LoginRequiredMixin, FinanceAccessMixin, DetailView):
    model = BankStatement
    template_name = "crm/bank_statement_detail.html"
    context_object_name = "bank_statement"

    def get_queryset(self):
        return BankStatement.objects.select_related(
            "owner_company", "bank_account", "created_by", "posted_by"
        ).prefetch_related(
            "lines__transportation", "lines__payment"
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        lines = list(context["bank_statement"].lines.all())
        for line in lines:
            transportation = line.transportation
            if context["bank_statement"].direction == BankStatement.Direction.INCOME:
                party = transportation.parties.filter(
                    role=TransportationParty.Role.CLIENT, is_active=True
                ).select_related("organization").first()
                line.display_counterparty = party.organization if party else None
            else:
                link = transportation.execution_links.filter(is_active=True).select_related(
                    "contractor_party__organization"
                ).order_by("sequence").first()
                line.display_counterparty = (
                    link.contractor_party.organization if link else None
                )
        context["bank_statement_lines"] = lines
        return context


def _bank_statement_line_available_balance(line, statement):
    side = (
        SettlementMovement.Side.RECEIVABLE
        if statement.direction == BankStatement.Direction.INCOME
        else SettlementMovement.Side.PAYABLE
    )
    balance = (
        line.transportation.receivable_balance
        if side == SettlementMovement.Side.RECEIVABLE
        else line.transportation.payable_balance
    )
    if line.payment_id:
        balance += line.payment.amount
    return balance


class BankStatementLineUpdateView(LoginRequiredMixin, FinanceAccessMixin, UpdateView):
    model = BankStatementLine
    form_class = BankStatementLineForm
    template_name = "crm/bank_statement_line_form.html"
    context_object_name = "bank_statement_line"

    def get_queryset(self):
        return BankStatementLine.objects.select_related(
            "statement", "statement__owner_company", "transportation", "payment"
        )

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["statement"] = self.object.statement
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["bank_statement"] = self.object.statement
        context["transportation"] = self.object.transportation
        return context

    def form_valid(self, form):
        line = self.object
        statement = line.statement
        if statement.status not in {
            BankStatement.Status.DRAFT,
            BankStatement.Status.POSTED,
        }:
            form.add_error(None, "Аннулированную выписку изменять нельзя.")
            return self.form_invalid(form)

        amount = form.cleaned_data["amount"]
        available = _bank_statement_line_available_balance(line, statement)
        if amount > available:
            form.add_error(
                "amount",
                f"Сумма не может быть больше доступного остатка {available}.",
            )
            return self.form_invalid(form)
        if statement.status == BankStatement.Status.POSTED and not line.payment_id:
            form.add_error(None, "У проведённой строки не найден созданный платёж.")
            return self.form_invalid(form)

        payment_reference = form.cleaned_data.get("payment_reference", "").strip()
        with transaction.atomic():
            if line.payment_id:
                payment = line.payment
                old_snapshot = _payment_snapshot(payment)
                payment.amount = amount
                payment.reference = (
                    payment_reference or statement.reference or statement.number
                )
                try:
                    payment.full_clean()
                except ValidationError as error:
                    for message in getattr(error, "messages", [str(error)]):
                        form.add_error(None, message)
                    return self.form_invalid(form)
                payment.save()
                new_snapshot = _payment_snapshot(payment)
                changes = _snapshot_changes(
                    old_snapshot,
                    new_snapshot,
                    {
                        "direction": "Операция",
                        "amount": "Сумма",
                        "payment_date": "Дата платежа",
                        "method": "Способ оплаты",
                        "reference": "Платёжное поручение",
                        "notes": "Комментарий",
                    },
                )
                if changes:
                    _record_transportation_audit(
                        line.transportation,
                        self.request.user,
                        comment="Строка банковской выписки изменена",
                        source="payment",
                        changes=changes,
                    )
            line.amount = amount
            line.payment_reference = payment_reference
            line.save(update_fields=["amount", "payment_reference", "updated_at"])
        messages.success(self.request, "Строка банковской выписки изменена.")
        return redirect(statement.get_absolute_url())


class BankStatementLineDeleteView(LoginRequiredMixin, FinanceAccessMixin, View):
    template_name = "crm/bank_statement_line_confirm_delete.html"

    def get_object(self):
        return get_object_or_404(
            BankStatementLine.objects.select_related(
                "statement", "transportation", "payment"
            ),
            pk=self.kwargs["pk"],
            statement_id=self.kwargs["statement_pk"],
        )

    def get(self, request, statement_pk, pk):
        return render(
            request,
            self.template_name,
            {"bank_statement_line": self.get_object()},
        )

    def post(self, request, statement_pk, pk):
        with transaction.atomic():
            line = get_object_or_404(
                BankStatementLine.objects.select_for_update().select_related(
                    "statement", "transportation", "payment"
                ),
                pk=pk,
                statement_id=statement_pk,
            )
            statement = line.statement
            if line.payment_id:
                payment = line.payment
                TransportationStatusEvent.objects.create(
                    transportation=line.transportation,
                    old_status=line.transportation.status,
                    new_status=line.transportation.status,
                    changed_by=request.user,
                    comment=f"Строка банковского документа {statement.number} удалена",
                    source=TransportationStatusEvent.Source.PAYMENT,
                    changes={
                        "Платёж": {
                            "old": f"{payment.amount} {statement.currency}",
                            "new": "Строка удалена",
                        }
                    },
                )
                payment.delete()
            line.delete()
        messages.success(request, "Строка банковской выписки удалена.")
        return redirect(statement.get_absolute_url())


class BankStatementUnpostView(LoginRequiredMixin, FinanceAccessMixin, View):
    def post(self, request, pk):
        statement = get_object_or_404(BankStatement, pk=pk)
        try:
            statement = unpost_bank_statement(statement, request.user)
        except ValidationError as error:
            for message in getattr(error, "messages", [str(error)]):
                messages.error(request, message)
            return redirect(statement.get_absolute_url())
        messages.success(request, f"{statement.number} возвращён в черновик.")
        return redirect("bank-statement-update", pk=statement.pk)


class BankStatementDeleteView(LoginRequiredMixin, FinanceAccessMixin, View):
    template_name = "crm/bank_statement_confirm_delete.html"

    def get_object(self):
        return get_object_or_404(BankStatement, pk=self.kwargs["pk"])

    def get(self, request, pk):
        return render(request, self.template_name, {"bank_statement": self.get_object()})

    def post(self, request, pk):
        statement = self.get_object()
        number = statement.number
        delete_bank_statement(statement, request.user)
        messages.success(request, f"Банковский документ {number} удалён, платежи отменены.")
        return redirect("bank-statement-list")


class BankStatementPostView(LoginRequiredMixin, FinanceAccessMixin, View):
    def post(self, request, pk):
        statement = get_object_or_404(BankStatement, pk=pk)
        try:
            post_bank_statement(statement, request.user)
        except ValidationError as error:
            for message in getattr(error, "messages", [str(error)]):
                messages.error(request, message)
        else:
            messages.success(request, f"Банковский документ {statement.number} проведён.")
        return redirect(statement.get_absolute_url())


class TransportationDocumentEditMixin:
    model = Transportation
    form_class = TransportationDocumentForm
    template_name = "crm/transportation_form.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["vat_rate_map"] = {
            str(rate.pk): str(rate.rate)
            for rate in VATRate.objects.filter(is_active=True)
        }
        context["owner_tax_rate_map"] = {
            str(owner.pk): str(owner.profit_tax_rate)
            for owner in Organization.objects.filter(
                is_own_company=True, is_active=True
            )
        }
        return context

    @staticmethod
    def validation_messages(error):
        if hasattr(error, "message_dict"):
            return [
                message
                for field_messages in error.message_dict.values()
                for message in field_messages
            ]
        return list(error.messages)

    def form_valid(self, form):
        action = self.request.POST.get("action", "save")
        is_create = not bool(getattr(getattr(self, "object", None), "pk", None))
        previous_status = (
            getattr(self, "_audit_previous_status", None)
            if getattr(self, "_audit_previous_status", None) is not None
            else (
                self.object.status
                if getattr(self, "object", None) is not None and self.object.pk
                else ""
            )
        )
        changes = _form_audit_changes(form, include_all=is_create)
        with transaction.atomic():
            self.object = form.save()
            form.save_related(self.request.user)
            if previous_status != self.object.status:
                changes.setdefault(
                    "Статус",
                    {
                        "old": dict(Transportation.Status.choices).get(
                            previous_status, previous_status
                        ),
                        "new": dict(Transportation.Status.choices).get(
                            self.object.status, self.object.status
                        ),
                    },
                )
            if changes or is_create:
                _record_transportation_audit(
                    self.object,
                    self.request.user,
                    comment="Документ создан" if is_create else "Реквизиты документа изменены",
                    source="document",
                    changes=changes,
                    old_status=previous_status,
                    new_status=self.object.status,
                )
        if action == "post":
            try:
                self.object = post_transportation(self.object, self.request.user)
            except ValidationError as error:
                for message in self.validation_messages(error):
                    messages.error(self.request, message)
                messages.warning(
                    self.request,
                    "Заявка сохранена как черновик. Заполните недостающие данные и проведите её повторно.",
                )
                return redirect("transportation-update", pk=self.object.pk)
            messages.success(
                self.request,
                f"Заявка {self.object.number} записана и проведена.",
            )
            return redirect(self.object.get_absolute_url())
        messages.success(self.request, "Черновик заявки сохранён.")
        if action == "save_close":
            return redirect("transportation-list")
        return redirect(self.object.get_absolute_url())


class TransportationCreateView(
    LoginRequiredMixin, TransportationDocumentEditMixin, CreateView
):
    pass


class TransportationUpdateView(
    LoginRequiredMixin, TransportationDocumentEditMixin, UpdateView
):
    def dispatch(self, request, *args, **kwargs):
        self.object = self.get_object()
        if request.method == "POST":
            # ModelForm validation mutates ``self.object`` before form_valid;
            # preserve the actual persisted status for the audit event.
            self._audit_previous_status = self.object.status
        if self.object.posting_status == Transportation.PostingStatus.POSTED:
            messages.warning(
                request,
                "Проведённый документ защищён от изменения. Сначала отмените проведение.",
            )
            return redirect(self.object.get_absolute_url())
        return super().dispatch(request, *args, **kwargs)


class TransportationPostView(LoginRequiredMixin, View):
    def post(self, request, pk):
        transportation = get_object_or_404(Transportation, pk=pk)
        try:
            transportation = post_transportation(transportation, request.user)
        except ValidationError as error:
            error_messages = (
                [item for values in error.message_dict.values() for item in values]
                if hasattr(error, "message_dict")
                else error.messages
            )
            for message in error_messages:
                messages.error(request, message)
            return redirect("transportation-update", pk=pk)
        messages.success(request, f"Заявка {transportation.number} проведена.")
        return redirect(transportation.get_absolute_url())


class TransportationUnpostView(LoginRequiredMixin, View):
    def post(self, request, pk):
        transportation = get_object_or_404(Transportation, pk=pk)
        try:
            transportation = unpost_transportation(transportation, request.user)
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
            return redirect(transportation.get_absolute_url())
        messages.success(request, "Проведение отменено. Документ снова доступен для изменения.")
        return redirect("transportation-update", pk=transportation.pk)


class TransportationStatusAdvanceView(LoginRequiredMixin, View):
    def post(self, request, pk):
        transportation = get_object_or_404(Transportation, pk=pk)
        target_status = request.POST.get("target_status", "").strip()
        if not target_status:
            target_status = transportation.next_workflow_status
        if not target_status:
            messages.info(request, "Для этого рейса больше нет следующих этапов.")
            return redirect(transportation.get_absolute_url())
        try:
            transportation = advance_transportation_status(
                transportation, target_status, request.user
            )
        except ValidationError as error:
            error_messages = (
                [item for values in error.message_dict.values() for item in values]
                if hasattr(error, "message_dict")
                else error.messages
            )
            for message in error_messages:
                messages.error(request, message)
            return redirect(transportation.get_absolute_url())
        messages.success(
            request,
            f"Рейс переведён на этап «{transportation.get_status_display()}».",
        )
        return redirect(transportation.get_absolute_url())


class TransportationCloseView(LoginRequiredMixin, View):
    def post(self, request, pk):
        transportation = get_object_or_404(Transportation, pk=pk)
        if not user_can_close_documents(request.user):
            messages.error(request, "У вас нет прав на закрытие рейса.")
            return redirect(transportation.get_absolute_url())
        try:
            transportation = close_transportation(transportation, request.user)
        except ValidationError as error:
            error_messages = (
                [item for values in error.message_dict.values() for item in values]
                if hasattr(error, "message_dict")
                else error.messages
            )
            for message in error_messages:
                messages.error(request, message)
            return redirect(transportation.get_absolute_url())
        messages.success(request, f"Рейс {transportation.number} закрыт.")
        return redirect(transportation.get_absolute_url())


class TransportationEpdPrepareView(LoginRequiredMixin, View):
    """Generate canonical drafts for the EPD documents of a transportation."""

    def post(self, request, pk):
        transportation = get_object_or_404(
            Transportation.objects.select_related("owner_company"), pk=pk
        )
        try:
            documents = prepare_documents(transportation, request.user)
        except ValidationError as error:
            error_messages = (
                [item for values in error.message_dict.values() for item in values]
                if hasattr(error, "message_dict")
                else error.messages
            )
            for message in error_messages:
                messages.error(request, message)
            return redirect(transportation.get_absolute_url())
        messages.success(
            request,
            f"Подготовлено ЭПД: {len(documents)}. Файлы можно скачать из карточки рейса.",
        )
        _record_transportation_audit(
            transportation,
            request.user,
            comment="ЭПД подготовлены",
            source="epd",
            changes={
                "ЭПД": {
                    "old": "",
                    "new": f"Подготовлено документов: {len(documents)}",
                }
            },
        )
        return redirect(transportation.get_absolute_url())


class TransportationEpdDownloadView(LoginRequiredMixin, View):
    @staticmethod
    def _xml_response(xml, filename):
        """Return XML with bytes matching the declaration in the document."""

        declared = re.search(r'encoding=["\']([^"\']+)["\']', xml[:300], re.I)
        encoding = "cp1251" if declared and declared.group(1).lower() in {
            "windows-1251", "cp1251"
        } else "utf-8"
        response = HttpResponse(
            xml.encode(encoding, errors="xmlcharrefreplace"),
            content_type="application/xml",
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    def get(self, request, transportation_pk, pk):
        document = get_object_or_404(
            TransportationElectronicDocument.objects.select_related("transportation"),
            pk=pk,
            transportation_id=transportation_pk,
        )
        if request.GET.get("format") == "json":
            response = JsonResponse(
                document.payload or {},
                json_dumps_params={"ensure_ascii": False, "indent": 2},
            )
            response["Content-Disposition"] = (
                f'attachment; filename="transportation-{transportation_pk}-epd-{document.pk}.json"'
            )
            return response
        requested_format = request.GET.get("format")
        if document.kind == TransportationElectronicDocument.Kind.EZZ and requested_format in {
            None, "", "kontur", "userdata"
        }:
            userdata_xml = document.operator_xml or payload_to_kontur_userdata(
                document.transportation
            )
            # The operator XML is derived data.  Rebuild it on download when
            # a draft was changed outside the «Обновить черновики» action
            # (for example, after setting the company's boxId).
            if document.status in {
                TransportationElectronicDocument.Status.DRAFT,
                TransportationElectronicDocument.Status.READY,
                TransportationElectronicDocument.Status.ERROR,
            }:
                current_userdata_xml = payload_to_kontur_userdata(
                    document.transportation
                )
                if current_userdata_xml != userdata_xml:
                    userdata_xml = current_userdata_xml
                    document.operator_xml = userdata_xml
                    document.generated_xml = ""
                    document.provider = TransportationElectronicDocument.Provider.INTERNAL
                    document.last_error = ""
                    document.save(
                        update_fields=[
                            "operator_xml", "generated_xml", "provider",
                            "last_error", "updated_at",
                        ]
                    )
            # ``userdata`` is deliberately exposed for diagnostics and for
            # installations that call GenerateTitleXml outside the CRM.
            if requested_format == "userdata":
                return self._xml_response(
                    userdata_xml,
                    f"ON_ZAKZVGO-UserData-{transportation_pk}-{document.pk}.xml",
                )

            # A generated response is the final ON_ZAKZVGO file and can be
            # downloaded repeatedly without another API call.  A local
            # preview is reused only while the API is not configured; once
            # credentials appear, regenerate it through Kontur.
            owner = document.transportation.owner_company
            has_any_kontur_config = bool(
                getattr(settings, "KONTUR_DIADOC_API_TOKEN", "")
                or getattr(owner, "edo_id", "")
            )
            if document.generated_xml and (
                document.provider == TransportationElectronicDocument.Provider.KONTUR
                or not has_any_kontur_config
            ):
                return self._xml_response(
                    document.generated_xml,
                    f"ON_ZAKZVGO-{transportation_pk}-{document.pk}.xml",
                )

            # GenerateTitleXml is the step that turns UserDataXml into the
            # operator's loadable title.  Do not return the intermediate XML
            # here: it is not a file that Kontur can import directly.
            generated_provider = TransportationElectronicDocument.Provider.KONTUR
            try:
                generated_xml = generate_ezz_title_xml(
                    document.transportation, userdata_xml
                )
            except KonturNotConfigured:
                # Keep the local result in Russian for development and
                # offline review, but mark it as internal so it is replaced
                # automatically as soon as the API is configured.
                generated_xml = payload_to_kontur_russian_xml(
                    document.transportation
                )
                generated_provider = TransportationElectronicDocument.Provider.INTERNAL
            except KonturUnavailable as error:
                document.last_error = str(error)
                document.save(update_fields=["last_error", "updated_at"])
                return HttpResponse(
                    "Не удалось получить финальный XML от Контур.Диадок: "
                    f"{error}",
                    status=502,
                    content_type="text/plain; charset=utf-8",
                )

            document.generated_xml = generated_xml
            document.provider = generated_provider
            document.last_error = ""
            document.save(update_fields=["generated_xml", "provider", "last_error", "updated_at"])
            return self._xml_response(
                generated_xml,
                f"ON_ZAKZVGO-{transportation_pk}-{document.pk}.xml",
            )
        xml = document.raw_xml or payload_to_xml(document.payload or {})
        return self._xml_response(
            xml,
            f"transportation-{transportation_pk}-epd-{document.pk}.xml",
        )


class TransportationEpdSendView(LoginRequiredMixin, View):
    """Generate a final EZZ title; signing and sending remain an EDO step."""

    def post(self, request, transportation_pk, pk):
        document = get_object_or_404(
            TransportationElectronicDocument,
            pk=pk,
            transportation_id=transportation_pk,
        )
        if document.kind != TransportationElectronicDocument.Kind.EZZ:
            messages.info(
                request,
                "Для этого вида ЭПД пока доступно только скачивание XML.",
            )
            return redirect(document.transportation.get_absolute_url())
        userdata_xml = payload_to_kontur_userdata(document.transportation)
        if document.status in {
            TransportationElectronicDocument.Status.DRAFT,
            TransportationElectronicDocument.Status.READY,
            TransportationElectronicDocument.Status.ERROR,
        } and document.operator_xml != userdata_xml:
            document.operator_xml = userdata_xml
            document.generated_xml = ""
            document.provider = TransportationElectronicDocument.Provider.INTERNAL
            document.last_error = ""
            document.save(
                update_fields=[
                    "operator_xml", "generated_xml", "provider", "last_error",
                    "updated_at",
                ]
            )
        if document.generated_xml:
            messages.success(request, "Финальный XML Контур уже подготовлен.")
            return redirect(document.transportation.get_absolute_url())

        generated_provider = TransportationElectronicDocument.Provider.KONTUR
        try:
            generated_xml = generate_ezz_title_xml(
                document.transportation, userdata_xml
            )
        except KonturNotConfigured:
            generated_xml = payload_to_kontur_russian_xml(document.transportation)
            generated_provider = TransportationElectronicDocument.Provider.INTERNAL
        except KonturUnavailable as error:
            document.last_error = str(error)
            document.save(update_fields=["last_error", "updated_at"])
            messages.error(request, f"Контур не сформировал XML: {error}")
            return redirect(document.transportation.get_absolute_url())

        document.generated_xml = generated_xml
        document.provider = generated_provider
        document.status = TransportationElectronicDocument.Status.READY
        document.last_error = ""
        document.save(
            update_fields=[
                "generated_xml", "provider", "status", "last_error", "updated_at"
            ]
        )
        _record_transportation_audit(
            document.transportation,
            request.user,
            comment="Финальный XML ЭЗЗ получен от Контур",
            source="epd",
            changes={
                "ЭПД": {
                    "old": "UserDataXml",
                    "new": "ON_ZAKZVGO",
                }
            },
        )
        if generated_provider == TransportationElectronicDocument.Provider.KONTUR:
            messages.success(
                request,
                "Финальный ON_ZAKZVGO получен. Подпишите и отправьте его через ЭДО.",
            )
        else:
            messages.warning(
                request,
                "Русскоязычная копия ON_ZAKZVGO сформирована локально. "
                "Для гарантированной загрузки настройте API Контур.",
            )
        return redirect(document.transportation.get_absolute_url())


class TransportationIncidentCreateView(LoginRequiredMixin, CreateView):
    model = TransportationIncident
    form_class = TransportationIncidentForm
    template_name = "crm/transportation_incident_form.html"

    def dispatch(self, request, *args, **kwargs):
        self.transportation = get_object_or_404(
            Transportation, pk=kwargs["transportation_pk"]
        )
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["transportation"] = self.transportation
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["transportation"] = self.transportation
        return context

    def form_valid(self, form):
        form.instance.transportation = self.transportation
        form.instance.created_by = self.request.user
        messages.success(self.request, "Событие по рейсу добавлено.")
        response = super().form_valid(form)
        _record_transportation_audit(
            self.transportation,
            self.request.user,
            comment="Штраф или претензия добавлены",
            source="incident",
            changes=_snapshot_changes(
                {key: "" for key in _incident_snapshot(self.object)},
                _incident_snapshot(self.object),
                {
                    "kind": "Вид события",
                    "status": "Статус",
                    "counterparty": "Контрагент",
                    "occurred_on": "Дата события",
                    "title": "Описание",
                    "description": "Подробности",
                    "financial_impact": "Финансовый эффект",
                    "amount": "Сумма",
                    "currency": "Валюта",
                    "resolution": "Результат",
                    "resolved_on": "Дата закрытия",
                },
            ),
        )
        return response

    def get_success_url(self):
        return reverse_lazy("transportation-detail", kwargs={"pk": self.transportation.pk})


class TransportationIncidentUpdateView(LoginRequiredMixin, UpdateView):
    model = TransportationIncident
    form_class = TransportationIncidentForm
    template_name = "crm/transportation_incident_form.html"
    context_object_name = "incident"

    def get_queryset(self):
        return TransportationIncident.objects.filter(
            transportation_id=self.kwargs["transportation_pk"]
        ).select_related("transportation", "counterparty")

    def dispatch(self, request, *args, **kwargs):
        if request.method == "POST":
            self._audit_old_snapshot = _incident_snapshot(self.get_object())
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["transportation"] = self.object.transportation
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["transportation"] = self.object.transportation
        return context

    def form_valid(self, form):
        old_snapshot = getattr(self, "_audit_old_snapshot", _incident_snapshot(self.object))
        messages.success(self.request, "Событие по рейсу обновлено.")
        response = super().form_valid(form)
        changes = _snapshot_changes(
            old_snapshot,
            _incident_snapshot(self.object),
            {
                "kind": "Вид события",
                "status": "Статус",
                "counterparty": "Контрагент",
                "occurred_on": "Дата события",
                "title": "Описание",
                "description": "Подробности",
                "financial_impact": "Финансовый эффект",
                "amount": "Сумма",
                "currency": "Валюта",
                "resolution": "Результат",
                "resolved_on": "Дата закрытия",
            },
        )
        if changes:
            _record_transportation_audit(
                self.object.transportation,
                self.request.user,
                comment="Штраф или претензия изменены",
                source="incident",
                changes=changes,
            )
        return response

    def get_success_url(self):
        return reverse_lazy("transportation-detail", kwargs={"pk": self.object.transportation_id})


class TransportationIncidentDeleteView(LoginRequiredMixin, View):
    def post(self, request, transportation_pk, pk):
        incident = get_object_or_404(
            TransportationIncident, pk=pk, transportation_id=transportation_pk
        )
        old_snapshot = _incident_snapshot(incident)
        transportation = incident.transportation
        incident.delete()
        _record_transportation_audit(
            transportation,
            request.user,
            comment="Штраф или претензия удалены",
            source="incident",
            changes=_snapshot_changes(
                old_snapshot,
                {key: "" for key in old_snapshot},
                {
                    "kind": "Вид события",
                    "status": "Статус",
                    "counterparty": "Контрагент",
                    "occurred_on": "Дата события",
                    "title": "Описание",
                    "description": "Подробности",
                    "financial_impact": "Финансовый эффект",
                    "amount": "Сумма",
                    "currency": "Валюта",
                    "resolution": "Результат",
                    "resolved_on": "Дата закрытия",
                },
            ),
        )
        messages.success(request, "Событие по рейсу удалено.")
        return redirect("transportation-detail", pk=transportation_pk)


class TransportationDetailView(LoginRequiredMixin, DetailView):
    model = Transportation
    template_name = "crm/transportation_detail.html"
    context_object_name = "transportation"
    queryset = Transportation.objects.select_related(
        "owner_company",
        "manager",
        "customer_vat_rate",
        "executor_vat_rate",
        "legacy_shipment",
        "legacy_shipment__customer",
        "legacy_shipment__carrier",
    ).prefetch_related(
        "stops",
        Prefetch(
            "payments",
            queryset=Payment.objects.select_related("created_by"),
        ),
        Prefetch(
            "parties",
            queryset=TransportationParty.objects.filter(is_active=True).select_related(
                "organization"
            ),
        ),
        Prefetch(
            "execution_links",
            queryset=TransportationLink.objects.filter(is_active=True).select_related(
                "principal_party__organization",
                "contractor_party__organization",
                "contract",
            ),
        ),
        Prefetch(
            "vehicle_assignments",
                queryset=VehicleAssignment.objects.filter(is_active=True).select_related(
                    "actual_carrier", "driver", "vehicle", "trailer", "combination"
                ),
        ),
        Prefetch(
            "charges",
            queryset=TripCharge.objects.select_related(
                "counterparty", "contract", "vat_rate"
            ),
        ),
        Prefetch(
            "settlement_movements",
            queryset=SettlementMovement.objects.select_related(
                "counterparty", "contract", "payment"
            ),
        ),
        Prefetch(
            "status_events",
            queryset=TransportationStatusEvent.objects.select_related("changed_by"),
        ),
        Prefetch(
            "instructions",
            queryset=TransportationInstruction.objects.select_related(
                "counterparty", "contract"
            ),
        ),
        Prefetch(
            "electronic_documents",
            queryset=TransportationElectronicDocument.objects.select_related("stop"),
        ),
        Prefetch(
            "incidents",
            queryset=TransportationIncident.objects.select_related(
                "counterparty", "created_by"
            ),
        ),
    )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        transportation = self.object
        parties = list(transportation.parties.all())
        links = list(transportation.execution_links.all())
        assignment = transportation.active_vehicle_assignment()
        incidents = list(transportation.incidents.all())
        incident_income = sum(
            (item.amount for item in incidents if item.financial_impact == TransportationIncident.FinancialImpact.INCOME),
            Decimal("0"),
        )
        incident_expense = sum(
            (item.amount for item in incidents if item.financial_impact == TransportationIncident.FinancialImpact.EXPENSE),
            Decimal("0"),
        )
        client_party = next(
            (p for p in parties if p.role == TransportationParty.Role.CLIENT), None
        )
        chain_nodes = []
        if client_party:
            chain_nodes.append(
                {"organization": client_party.organization, "role": "Клиент", "link": None}
            )
        chain_nodes.append(
            {
                "organization": transportation.owner_company,
                "role": "Наша компания / экспедитор",
                "link": None,
            }
        )
        seen = {transportation.owner_company_id}
        if client_party:
            seen.add(client_party.organization_id)
        for link in links:
            organization = link.contractor_party.organization
            chain_nodes.append(
                {
                    "organization": organization,
                    "role": link.get_contractor_role_display(),
                    "link": link,
                }
            )
            seen.add(organization.pk)
        if assignment and assignment.actual_carrier_id not in seen:
            chain_nodes.append(
                {
                    "organization": assignment.actual_carrier,
                    "role": "Фактический перевозчик",
                    "link": None,
                }
            )
        posting_issues = []
        try:
            validate_transportation_for_posting(transportation)
        except ValidationError as error:
            if hasattr(error, "message_dict"):
                posting_issues = [
                    message
                    for messages in error.message_dict.values()
                    for message in messages
                ]
            else:
                posting_issues = list(error.messages)
        closing_issues = validate_transportation_for_closing(transportation)
        context.update(
            {
                "client_party": client_party,
                "execution_links": links,
                "assignment": assignment,
                "chain_nodes": chain_nodes,
                "chain_issues": transportation.chain_issues(),
                "posting_issues": posting_issues,
                "can_post_transportation": not posting_issues,
                "closing_issues": closing_issues,
                "can_close_transportation": not closing_issues,
                "next_workflow_status": transportation.next_workflow_status,
                "next_workflow_status_label": (
                    dict(Transportation.Status.choices).get(
                        transportation.next_workflow_status,
                        transportation.next_workflow_status,
                    )
                    if transportation.next_workflow_status
                    else ""
                ),
                "next_workflow_issues": (
                    transportation.status_transition_issues(
                        transportation.next_workflow_status
                    )
                    if transportation.next_workflow_status
                    else []
                ),
                "legacy_documents": (
                    transportation.legacy_shipment.documents.all()[:8]
                    if transportation.legacy_shipment_id
                    else []
                ),
                "charges": list(transportation.charges.all()),
                "settlement_movements": list(
                    transportation.settlement_movements.all()
                ),
                "status_events": list(transportation.status_events.all()),
                "payments": list(transportation.payments.all()),
                "instructions": list(transportation.instructions.all()),
                "epd_documents": list(transportation.electronic_documents.all()),
                "incidents": incidents,
                "incident_income": incident_income,
                "incident_expense": incident_expense,
                "adjusted_margin": transportation.margin + incident_income - incident_expense,
            }
        )
        return context


class TransportationExecutorApplicationDownloadView(LoginRequiredMixin, View):
    def get(self, request, pk):
        transportation = get_object_or_404(
            Transportation.objects.select_related(
                "owner_company",
                "executor_vat_rate",
                "package_type",
                "loading_method",
                "unloading_method",
            ).prefetch_related(
                "stops__organization",
                "execution_links__contract",
                "execution_links__contractor_party__organization",
                "vehicle_assignments__driver__passports",
                "vehicle_assignments__vehicle",
                "vehicle_assignments__trailer",
            ),
            pk=pk,
        )
        from .documents import build_executor_transportation_application_docx

        stream = build_executor_transportation_application_docx(transportation)
        safe_number = re.sub(
            r"[^0-9A-Za-zА-Яа-я_-]+",
            "_",
            transportation.number or f"рейс_{transportation.pk}",
        )
        return FileResponse(
            stream,
            as_attachment=True,
            filename=f"Заявка_исполнителю_{safe_number}.docx",
            content_type=(
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
        )


class TransportationChainUpdateView(LoginRequiredMixin, FormView):
    form_class = TransportationChainForm
    template_name = "crm/transportation_chain_form.html"

    @property
    def transportation(self):
        if not hasattr(self, "_transportation"):
            self._transportation = get_object_or_404(
                Transportation.objects.select_related(
                    "owner_company", "legacy_shipment"
                ),
                pk=self.kwargs["pk"],
            )
        return self._transportation

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["transportation"] = self.transportation
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        contract_id = self.request.GET.get("contract", "").strip()
        if contract_id.isdigit():
            contract = Contract.objects.filter(
                pk=contract_id,
            ).exclude(
                status__in=[Contract.Status.TERMINATED, Contract.Status.ARCHIVED]
            ).first()
            if contract:
                initial["contract"] = contract.pk
        return initial

    def form_valid(self, form):
        changes = _form_audit_changes(form)
        form.save(self.request.user)
        if changes:
            _record_transportation_audit(
                self.transportation,
                self.request.user,
                comment="Цепочка исполнения изменена",
                source="chain",
                changes=changes,
            )
        messages.success(
            self.request,
            "Цепочка обновлена. Исполнитель и фактический перевозчик теперь учитываются отдельно.",
        )
        return super().form_valid(form)

    def get_success_url(self):
        return self.transportation.get_absolute_url()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["transportation"] = self.transportation
        return context


class ContractListView(LoginRequiredMixin, ListView):
    model = Contract
    template_name = "crm/contract_list.html"
    context_object_name = "contracts"
    paginate_by = 30

    def get_queryset(self):
        queryset = Contract.objects.select_related(
            "expeditor", "customer", "carrier", "created_by"
        )
        query = self.request.GET.get("q", "").strip()
        kind = self.request.GET.get("kind", "").strip()
        status = self.request.GET.get("status", "").strip()
        expeditor = get_expeditor_filter(self.request)
        if expeditor:
            queryset = queryset.filter(expeditor_id=expeditor)
        if query:
            queryset = queryset.filter(
                Q(number__iunicodecontains=query)
                | Q(customer__name__iunicodecontains=query)
                | Q(customer__tax_id__iunicodecontains=query)
                | Q(carrier__name__iunicodecontains=query)
                | Q(carrier__tax_id__iunicodecontains=query)
            )
        if kind in Contract.Kind.values:
            queryset = queryset.filter(kind=kind)
        if status in Contract.Status.values:
            queryset = queryset.filter(status=status)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        all_contracts = Contract.objects.all()
        current_expeditor = get_expeditor_filter(self.request)
        if current_expeditor:
            all_contracts = all_contracts.filter(expeditor_id=current_expeditor)
        context.update(
            {
                "current_q": self.request.GET.get("q", ""),
                "current_kind": self.request.GET.get("kind", ""),
                "current_status": self.request.GET.get("status", ""),
                "current_expeditor": current_expeditor,
                "kind_choices": Contract.Kind.choices,
                "status_choices": Contract.Status.choices,
                "expeditors": CompanyProfile.objects.all(),
                "contract_count": all_contracts.count(),
                "draft_count": all_contracts.filter(
                    status=Contract.Status.DRAFT
                ).count(),
                "ready_count": all_contracts.filter(
                    status=Contract.Status.READY
                ).count(),
                "signed_count": all_contracts.filter(
                    status=Contract.Status.SIGNED
                ).count(),
            }
        )
        return context


class ContractDetailView(LoginRequiredMixin, DetailView):
    model = Contract
    template_name = "crm/contract_detail.html"
    context_object_name = "contract"
    queryset = Contract.objects.select_related(
        "expeditor", "customer", "carrier", "created_by", "vat_rate"
    )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        checks = (
            (self.object.expeditor, "нашей компании"),
            (self.object.counterparty, "контрагента"),
        )
        missing = []
        for party, label in checks:
            address = getattr(party, "legal_address", "") or getattr(
                party, "address", ""
            )
            fields = (
                (getattr(party, "tax_id", ""), "ИНН"),
                (address, "юридический адрес"),
                (getattr(party, "director_name", ""), "руководитель"),
                (getattr(party, "settlement_account", ""), "расчётный счёт"),
                (getattr(party, "bank_name", ""), "банк"),
                (getattr(party, "bik", ""), "БИК"),
            )
            for value, name in fields:
                if not value:
                    missing.append(f"{name} {label}")
        context["missing_requisites"] = missing
        return context


class ContractCreateView(LoginRequiredMixin, SuccessMessageMixin, CreateView):
    model = Contract
    form_class = ContractForm
    template_name = "crm/contract_form.html"
    success_message = "Договор создан. DOCX уже можно скачать."

    def get_initial(self):
        initial = super().get_initial()
        initial["contract_date"] = timezone.localdate()
        kind = self.request.GET.get("kind")
        if kind in Contract.Kind.values:
            initial["kind"] = kind
        organization_id = self.request.GET.get("organization", "")
        if organization_id.isdigit():
            organization = Organization.objects.filter(pk=organization_id).first()
            if organization:
                own_profile = organization.legacy_expeditors.filter(is_active=True).first()
                if own_profile:
                    initial["expeditor"] = own_profile.pk
                if organization.default_vat_rate_id:
                    initial["vat_rate"] = organization.default_vat_rate_id
                if organization.payment_term_days:
                    initial["payment_term_days"] = organization.payment_term_days
                if organization.credit_limit:
                    initial["debt_limit"] = organization.credit_limit
                if organization.roles.filter(
                    role=OrganizationRole.Role.CLIENT, is_active=True
                ).exists():
                    customer = organization.legacy_customers.filter(is_active=True).first()
                    if customer:
                        initial["customer"] = customer.pk
                        initial.setdefault("kind", Contract.Kind.CLIENT_FORWARDING)
                elif organization.roles.filter(
                    role__in=[OrganizationRole.Role.CARRIER, OrganizationRole.Role.FORWARDER],
                    is_active=True,
                ).exists():
                    carrier = organization.legacy_carriers.filter(is_active=True).first()
                    if carrier:
                        initial["carrier"] = carrier.pk
                        initial.setdefault("kind", Contract.Kind.CARRIER_TRANSPORT)
        for field, model in (
            ("expeditor", CompanyProfile),
            ("customer", Customer),
            ("carrier", Carrier),
        ):
            value = self.request.GET.get(field, "")
            if value.isdigit() and model.objects.filter(pk=value).exists():
                initial[field] = value

        # A contract created from a transportation chain carries the unified
        # organization ids in the query string.  Resolve them to the legacy
        # contract parties used by the document register so the user only has
        # to check the prefilled requisites.
        owner_organization_id = self.request.GET.get("owner_organization", "")
        if owner_organization_id.isdigit():
            owner_organization = Organization.objects.filter(
                pk=owner_organization_id,
                is_own_company=True,
                is_active=True,
            ).first()
            if owner_organization:
                profile = owner_organization.legacy_expeditors.filter(
                    is_active=True
                ).first()
                if profile:
                    initial["expeditor"] = profile.pk

        counterparty_organization_id = self.request.GET.get(
            "counterparty_organization", ""
        )
        if counterparty_organization_id.isdigit():
            counterparty_organization = Organization.objects.filter(
                pk=counterparty_organization_id,
                is_active=True,
            ).first()
            if counterparty_organization:
                carrier = counterparty_organization.legacy_carriers.filter(
                    is_active=True
                ).first()
                if carrier:
                    initial["carrier"] = carrier.pk
        return initial

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        return super().form_valid(form)

    def get_success_url(self):
        transportation_id = self.request.GET.get("return_transportation", "").strip()
        if transportation_id.isdigit() and Transportation.objects.filter(
            pk=transportation_id
        ).exists():
            chain_url = str(
                reverse_lazy(
                    "transportation-chain-update",
                    kwargs={"pk": transportation_id},
                )
            )
            return f"{chain_url}?contract={self.object.pk}"
        return self.object.get_absolute_url()


class ContractUpdateView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    model = Contract
    form_class = ContractForm
    template_name = "crm/contract_form.html"
    success_message = "Договор обновлён. При скачивании будет сформирована новая версия."


class ContractDownloadView(LoginRequiredMixin, View):
    def get(self, request, pk):
        contract = get_object_or_404(
            Contract.objects.select_related("expeditor", "customer", "carrier"),
            pk=pk,
        )
        from .contracts import build_contract_docx

        stream = build_contract_docx(contract)
        safe_number = re.sub(r"[^0-9A-Za-zА-Яа-я_-]+", "_", contract.number)
        return FileResponse(
            stream,
            as_attachment=True,
            filename=f"Договор_{safe_number}.docx",
            content_type=(
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
        )


class CarrierInitialMixin:
    def get_initial(self):
        initial = super().get_initial()
        carrier_id = self.request.GET.get("carrier")
        if carrier_id and Carrier.objects.filter(pk=carrier_id).exists():
            initial["carrier"] = carrier_id
        return initial


class ExpeditorListView(SearchableDirectoryListView):
    model = CompanyProfile
    template_name = "crm/expeditor_list.html"
    context_object_name = "expeditors"
    search_fields = ("name", "short_name", "tax_id", "kpp", "legal_address")


class ExpeditorDetailView(LoginRequiredMixin, DetailView):
    model = CompanyProfile
    template_name = "crm/expeditor_detail.html"
    context_object_name = "expeditor"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["shipments"] = self.object.shipments.select_related(
            "customer", "carrier", "manager"
        )[:10]
        return context


class ExpeditorCreateView(LoginRequiredMixin, SuccessMessageMixin, CreateView):
    model = CompanyProfile
    form_class = CompanyProfileForm
    template_name = "crm/company_profile_form.html"
    success_message = "Экспедитор добавлен."


class ExpeditorUpdateView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    model = CompanyProfile
    form_class = CompanyProfileForm
    template_name = "crm/company_profile_form.html"
    success_message = "Реквизиты экспедитора обновлены."


class CustomerListView(SearchableDirectoryListView):
    model = Customer
    template_name = "crm/customer_list.html"
    context_object_name = "customers"
    search_fields = ("name", "tax_id", "contact_name", "phone")


class CustomerDetailView(LoginRequiredMixin, DetailView):
    model = Customer
    template_name = "crm/customer_detail.html"
    context_object_name = "customer"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["shipments"] = self.object.shipments.select_related("carrier", "manager")[:10]
        return context


class CustomerCreateView(LoginRequiredMixin, SuccessMessageMixin, CreateView):
    model = Customer
    form_class = CustomerForm
    template_name = "crm/directory_form.html"
    success_message = "Клиент добавлен."
    extra_context = {
        "entity_title": "Клиент",
        "cancel_url": reverse_lazy("customer-list"),
        "dadata_mode": "customer",
    }


class CustomerUpdateView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    model = Customer
    form_class = CustomerForm
    template_name = "crm/directory_form.html"
    success_message = "Данные клиента обновлены."
    extra_context = {
        "entity_title": "Клиент",
        "cancel_url": reverse_lazy("customer-list"),
        "dadata_mode": "customer",
    }


class CarrierListView(SearchableDirectoryListView):
    model = Carrier
    template_name = "crm/carrier_list.html"
    context_object_name = "carriers"
    search_fields = ("name", "tax_id", "contact_name", "phone", "vehicle_types")


class CarrierDetailView(LoginRequiredMixin, DetailView):
    model = Carrier
    template_name = "crm/carrier_detail.html"
    context_object_name = "carrier"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["shipments"] = self.object.shipments.select_related("customer", "manager")[:10]
        context["drivers"] = Driver.objects.filter(
            Q(carrier=self.object)
            | Q(employments__carrier=self.object, employments__is_active=True)
        ).distinct()[:8]
        context["vehicles"] = self.object.vehicles.all()[:8]
        return context


class CarrierCreateView(LoginRequiredMixin, SuccessMessageMixin, CreateView):
    model = Carrier
    form_class = CarrierForm
    template_name = "crm/directory_form.html"
    success_message = "Перевозчик добавлен."
    extra_context = {
        "entity_title": "Перевозчик",
        "cancel_url": reverse_lazy("carrier-list"),
        "dadata_mode": "carrier",
    }


class CarrierUpdateView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    model = Carrier
    form_class = CarrierForm
    template_name = "crm/directory_form.html"
    success_message = "Данные перевозчика обновлены."
    extra_context = {
        "entity_title": "Перевозчик",
        "cancel_url": reverse_lazy("carrier-list"),
        "dadata_mode": "carrier",
    }


class DriverListView(SearchableDirectoryListView):
    model = Driver
    template_name = "crm/driver_list.html"
    context_object_name = "drivers"
    search_fields = (
        "last_name", "first_name", "middle_name", "phone", "tax_id", "license_number",
        "license_categories", "licenses__number", "licenses__categories",
        "carrier__name", "employments__carrier__name",
    )
    ordering_field = "last_name"

    def get_queryset(self):
        queryset = (
            super()
            .get_queryset()
            .select_related("carrier")
            .prefetch_related("employments__carrier")
            .distinct()
        )
        active = self.request.GET.get("active", "").strip()
        if active == "1":
            queryset = queryset.filter(is_active=True)
        elif active == "0":
            queryset = queryset.filter(is_active=False)
        carrier = self.request.GET.get("carrier", "").strip()
        if carrier.isdigit():
            queryset = queryset.filter(
                Q(carrier_id=carrier)
                | Q(employments__carrier_id=carrier, employments__is_active=True)
            )
        return queryset.distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        all_drivers = Driver.objects.all()
        active_drivers = all_drivers.filter(is_active=True)
        context.update(
            {
                "driver_total": all_drivers.count(),
                "driver_active_total": active_drivers.count(),
                "driver_documents_attention": active_drivers.filter(
                    Q(license_expiry_date__isnull=True)
                    | Q(license_expiry_date__lt=today)
                ).count(),
                "driver_companies_total": Driver.objects.filter(
                    employments__is_active=True
                ).values("employments__carrier_id").distinct().count(),
                "current_active": self.request.GET.get("active", ""),
                "current_carrier": self.request.GET.get("carrier", ""),
                "driver_carriers": Carrier.objects.filter(is_active=True).order_by(
                    "name"
                ),
            }
        )
        return context


class DriverDetailView(LoginRequiredMixin, DetailView):
    model = Driver
    template_name = "crm/driver_detail.html"
    context_object_name = "driver"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["shipments"] = self.object.shipments.select_related(
            "customer", "carrier", "vehicle", "manager"
        ).order_by("-pickup_date", "-created_at")[:12]
        context["employments"] = self.object.employments.select_related(
            "carrier"
        ).filter(is_active=True)
        context["passports"] = self.object.passports.all()
        context["licenses"] = self.object.licenses.all()
        context["transportation_assignments"] = (
            self.object.transportation_assignments.filter(is_active=True)
            .select_related("transportation", "actual_carrier", "vehicle", "trailer")
            .prefetch_related("transportation__stops")[:12]
        )
        context["shipment_count"] = self.object.shipments.count()
        context["transportation_count"] = self.object.transportation_assignments.filter(
            is_active=True
        ).values("transportation_id").distinct().count()
        context["employment_count"] = self.object.employments.filter(
            is_active=True
        ).count()
        context["passport_count"] = self.object.passports.count()
        context["license_count"] = self.object.licenses.count()
        context["current_passport"] = self.object.current_passport
        context["current_license"] = self.object.current_license
        history = [
            {
                "created_at": self.object.created_at,
                "action": "Карточка создана",
                "details": "Водитель добавлен в справочник",
            }
        ]
        if self.object.updated_at != self.object.created_at:
            history.insert(
                0,
                {
                    "created_at": self.object.updated_at,
                    "action": "Карточка изменена",
                    "details": "Последнее сохранение данных водителя",
                },
            )
        context["driver_history"] = history
        return context


class DriverRegistersFormSetMixin:
    passport_prefix = "passports"
    license_prefix = "licenses"
    employment_prefix = "employments"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["register_mode"] = True
        return kwargs

    def get_passport_formset(self, form, data=None):
        instance = form.instance
        return DriverPassportFormSet(
            data=data,
            instance=instance,
            prefix=self.passport_prefix,
        )

    def get_license_formset(self, form, data=None):
        return DriverLicenseFormSet(
            data=data,
            instance=form.instance,
            prefix=self.license_prefix,
        )

    def get_employment_formset(self, form, data=None):
        instance = form.instance
        queryset = (
            instance.employments.filter(is_active=True)
            if instance.pk
            else None
        )
        kwargs = {
            "data": data,
            "instance": instance,
            "prefix": self.employment_prefix,
        }
        if queryset is not None:
            kwargs["queryset"] = queryset
        elif data is None and form.initial.get("carrier"):
            carrier = form.initial["carrier"]
            kwargs["initial"] = [
                {
                    "carrier": getattr(carrier, "pk", carrier),
                    "is_primary": True,
                }
            ]
        return DriverEmploymentFormSet(**kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if "passport_formset" not in context:
            context["passport_formset"] = self.get_passport_formset(
                context["form"]
            )
        if "license_formset" not in context:
            context["license_formset"] = self.get_license_formset(
                context["form"]
            )
        if "employment_formset" not in context:
            context["employment_formset"] = self.get_employment_formset(
                context["form"]
            )
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object() if self.kwargs.get("pk") else None
        form = self.get_form()
        passport_formset = self.get_passport_formset(form, data=request.POST)
        license_formset = self.get_license_formset(form, data=request.POST)
        employment_formset = self.get_employment_formset(form, data=request.POST)
        form_valid = form.is_valid()
        passport_valid = passport_formset.is_valid()
        license_valid = license_formset.is_valid()
        employment_valid = employment_formset.is_valid()
        if form_valid and passport_valid and license_valid and employment_valid:
            current_license = license_formset.current_data()
            form.instance.carrier = employment_formset.primary_carrier()
            form.instance.license_number = current_license["number"]
            form.instance.license_categories = current_license["categories"]
            form.instance.license_issue_date = current_license.get("issue_date")
            form.instance.license_expiry_date = current_license["expiry_date"]
            with transaction.atomic():
                self.object = form.save()
                employment_formset.save_register(self.object)
                passport_formset.instance = self.object
                passport_formset.save()
                license_formset.save_register(self.object)
            messages.success(request, self.success_message)
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return JsonResponse(
                    {
                        "ok": True,
                        "item": {
                            "id": self.object.pk,
                            "label": self.object.full_name,
                        },
                        "url": self.object.get_absolute_url(),
                    }
                )
            return redirect(self.get_success_url())
        return self.render_to_response(
            self.get_context_data(
                form=form,
                passport_formset=passport_formset,
                license_formset=license_formset,
                employment_formset=employment_formset,
            )
        )


class DriverCreateView(
    LoginRequiredMixin,
    CarrierInitialMixin,
    DriverRegistersFormSetMixin,
    SuccessMessageMixin,
    CreateView,
):
    model = Driver
    form_class = DriverForm
    template_name = "crm/driver_form.html"
    success_message = "Водитель добавлен."
    extra_context = {
        "entity_title": "Водитель",
        "entity_description": "Личные данные, документы и сроки действия.",
        "cancel_url": reverse_lazy("driver-list"),
        "delete_url_name": "driver-delete",
    }


class DriverUpdateView(
    LoginRequiredMixin,
    DriverRegistersFormSetMixin,
    SuccessMessageMixin,
    UpdateView,
):
    model = Driver
    form_class = DriverForm
    template_name = "crm/driver_form.html"
    success_message = "Данные водителя обновлены."
    extra_context = {
        "entity_title": "Водитель",
        "entity_description": "Личные данные, документы и сроки действия.",
        "cancel_url": reverse_lazy("driver-list"),
        "delete_url_name": "driver-delete",
    }


class VehicleListView(SearchableDirectoryListView):
    model = Vehicle
    template_name = "crm/vehicle_list.html"
    context_object_name = "vehicles"
    search_fields = (
        "registration_number", "trailer_registration_number", "vin", "make",
        "model", "body_type", "carrier__name",
    )
    ordering_field = "registration_number"

    def get_queryset(self):
        queryset = super().get_queryset().select_related(
            "carrier", "carrier__organization"
        ).prefetch_related(
            Prefetch(
                "combinations_as_tractor",
                queryset=VehicleCombination.objects.filter(is_active=True).select_related(
                    "trailer"
                ),
                to_attr="active_combinations",
            )
        )
        active = self.request.GET.get("active", "").strip()
        if active == "1":
            queryset = queryset.filter(is_active=True)
        elif active == "0":
            queryset = queryset.filter(is_active=False)
        kind = self.request.GET.get("kind", "").strip()
        if kind in Vehicle.Kind.values:
            queryset = queryset.filter(kind=kind)
        carrier = self.request.GET.get("carrier", "").strip()
        if carrier.isdigit():
            queryset = queryset.filter(carrier_id=carrier)
        return queryset.distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        all_vehicles = Vehicle.objects.all()
        active_vehicles = all_vehicles.filter(is_active=True)
        today = timezone.localdate()
        context.update(
            {
                "vehicle_total": all_vehicles.count(),
                "vehicle_active_total": active_vehicles.count(),
                "vehicle_documents_attention": active_vehicles.filter(
                    Q(insurance_expiry_date__isnull=True)
                    | Q(inspection_expiry_date__isnull=True)
                    | Q(insurance_expiry_date__lt=today)
                    | Q(inspection_expiry_date__lt=today)
                ).count(),
                "vehicle_combinations_total": VehicleCombination.objects.filter(
                    is_active=True
                ).count(),
                "current_active": self.request.GET.get("active", ""),
                "current_kind": self.request.GET.get("kind", ""),
                "current_carrier": self.request.GET.get("carrier", ""),
                "vehicle_kinds": Vehicle.Kind.choices,
                "vehicle_carriers": Carrier.objects.filter(is_active=True).order_by(
                    "name"
                ),
            }
        )
        return context


class VehicleDetailView(LoginRequiredMixin, DetailView):
    model = Vehicle
    template_name = "crm/vehicle_detail.html"
    context_object_name = "vehicle"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["shipments"] = self.object.shipments.select_related(
            "customer", "carrier", "driver", "manager"
        ).order_by("-pickup_date", "-created_at")[:12]
        context["combinations"] = VehicleCombination.objects.filter(
            Q(tractor=self.object) | Q(trailer=self.object)
        ).select_related("tractor", "trailer")
        context["transportation_assignments"] = (
            self.object.transportation_assignments.filter(is_active=True)
            .select_related("transportation", "driver", "actual_carrier", "trailer", "combination")
            .prefetch_related("transportation__stops")[:12]
        )
        context["shipment_count"] = self.object.shipments.count()
        context["transportation_count"] = self.object.transportation_assignments.filter(
            is_active=True
        ).values("transportation_id").distinct().count()
        context["combination_count"] = VehicleCombination.objects.filter(
            Q(tractor=self.object) | Q(trailer=self.object)
        ).count()
        context["assignment_driver_count"] = self.object.transportation_assignments.filter(
            is_active=True, driver__isnull=False
        ).values("driver_id").distinct().count()
        context["current_combination"] = (
            VehicleCombination.objects.filter(
                Q(tractor=self.object) | Q(trailer=self.object), is_active=True
            )
            .select_related("tractor", "trailer")
            .first()
        )
        history = [
            {
                "created_at": self.object.created_at,
                "action": "Карточка создана",
                "details": "Единица транспорта добавлена в автопарк",
            }
        ]
        if self.object.updated_at != self.object.created_at:
            history.insert(
                0,
                {
                    "created_at": self.object.updated_at,
                    "action": "Карточка изменена",
                    "details": "Последнее сохранение данных транспорта",
                },
            )
        context["vehicle_history"] = history
        return context


class VehicleCreateView(
    LoginRequiredMixin, CarrierInitialMixin, SuccessMessageMixin, CreateView
):
    model = Vehicle
    form_class = VehicleForm
    template_name = "crm/resource_form.html"
    success_message = "Транспорт добавлен."
    extra_context = {
        "entity_title": "Транспорт",
        "entity_description": "Регистрационные данные, характеристики и документы.",
        "cancel_url": reverse_lazy("vehicle-list"),
        "delete_url_name": "vehicle-delete",
    }


class VehicleUpdateView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    model = Vehicle
    form_class = VehicleForm
    template_name = "crm/resource_form.html"
    success_message = "Данные транспорта обновлены."
    extra_context = {
        "entity_title": "Транспорт",
        "entity_description": "Регистрационные данные, характеристики и документы.",
        "cancel_url": reverse_lazy("vehicle-list"),
        "delete_url_name": "vehicle-delete",
    }


class VehicleCombinationCreateView(
    LoginRequiredMixin, SuccessMessageMixin, CreateView
):
    model = VehicleCombination
    form_class = VehicleCombinationForm
    template_name = "crm/resource_form.html"
    success_message = "Сцепка добавлена."
    extra_context = {
        "entity_title": "Сцепка",
        "entity_description": "Свяжите тягач или грузовой автомобиль с прицепом. Сцепку можно менять между рейсами.",
        "cancel_url": reverse_lazy("vehicle-list"),
        "delete_url_name": "vehicle-combination-delete",
    }

    def get_initial(self):
        initial = super().get_initial()
        tractor_id = self.request.GET.get("tractor", "")
        if tractor_id.isdigit():
            tractor = Vehicle.objects.filter(
                pk=tractor_id,
                is_active=True,
                kind__in=[Vehicle.Kind.TRACTOR, Vehicle.Kind.TRUCK],
            ).first()
            if tractor:
                initial["tractor"] = tractor.pk
        return initial


class VehicleCombinationUpdateView(
    LoginRequiredMixin, SuccessMessageMixin, UpdateView
):
    model = VehicleCombination
    form_class = VehicleCombinationForm
    template_name = "crm/resource_form.html"
    success_message = "Сцепка обновлена."
    extra_context = {
        "entity_title": "Сцепка",
        "entity_description": "Связь основного автомобиля и прицепа с историей действия.",
        "cancel_url": reverse_lazy("vehicle-list"),
        "delete_url_name": "vehicle-combination-delete",
    }
