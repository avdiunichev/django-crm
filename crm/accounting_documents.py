from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import (
    AccountingSettings,
    ShipmentDocument,
    ShipmentDocumentAudit,
    ShipmentDocumentLine,
    Transportation,
    TransportationParty,
    TransportationStop,
)


def document_counterparty(transportation, direction):
    if direction == ShipmentDocument.Direction.OUTGOING:
        party = transportation.parties.filter(
            role=TransportationParty.Role.CLIENT, is_active=True
        ).select_related("organization").first()
        return party.organization if party else None
    link = transportation.active_execution_link()
    return link.contractor_party.organization if link else None


def document_contract(transportation, direction):
    if direction == ShipmentDocument.Direction.OUTGOING:
        return transportation.customer_contract
    link = transportation.active_execution_link()
    return link.contract if link else None


def last_delivery_date(transportations):
    dates = []
    for transportation in transportations:
        stop = transportation.stops.filter(
            kind=TransportationStop.Kind.DELIVERY
        ).order_by("-sequence").first()
        if stop and stop.planned_to:
            dates.append(stop.planned_to.date())
        elif stop and stop.planned_from:
            dates.append(stop.planned_from.date())
        elif transportation.planned_end_date:
            dates.append(transportation.planned_end_date)
    return max(dates) if dates else None


def validate_document_transportations(*, transportations, direction, kind, document_date, exclude_document=None):
    transportations = list(transportations)
    if not transportations:
        raise ValidationError("Выберите хотя бы один рейс.")
    counterparties = {
        party.pk if party else None
        for party in (document_counterparty(item, direction) for item in transportations)
    }
    if None in counterparties:
        raise ValidationError("В одном из выбранных рейсов не указан контрагент документа.")
    if len(counterparties) != 1:
        label = "клиентов" if direction == ShipmentDocument.Direction.OUTGOING else "исполнителей"
        raise ValidationError(f"Выбраны рейсы разных {label}. Создайте отдельный документ для каждого контрагента.")
    owner_ids = {item.owner_company_id for item in transportations}
    if len(owner_ids) != 1:
        raise ValidationError("В один документ можно включить рейсы только одной нашей компании.")
    duplicates = ShipmentDocumentLine.objects.filter(
        transportation__in=transportations,
        document__direction=direction,
        document__kind=kind,
    ).exclude(document__status=ShipmentDocument.Status.CANCELLED)
    if exclude_document:
        duplicates = duplicates.exclude(document=exclude_document)
    duplicate = duplicates.select_related("document", "transportation").first()
    if not duplicate:
        legacy_document = ShipmentDocument.objects.filter(
            transportation__in=transportations,
            direction=direction,
            kind=kind,
        ).exclude(status=ShipmentDocument.Status.CANCELLED)
        if exclude_document:
            legacy_document = legacy_document.exclude(pk=exclude_document.pk)
        legacy_document = legacy_document.select_related("transportation").first()
        if legacy_document:
            duplicate = type(
                "LegacyDocumentLink",
                (),
                {"document": legacy_document, "transportation": legacy_document.transportation},
            )()
    if duplicate:
        raise ValidationError(
            f"Рейс №{duplicate.transportation.number or duplicate.transportation_id} уже включён "
            f"в {duplicate.document.get_kind_display().lower()} №{duplicate.document.display_number}."
        )
    enforce_upd_period = not exclude_document or exclude_document.lines.exists()
    if kind == ShipmentDocument.Kind.UPD and document_date and enforce_upd_period:
        delivery_date = last_delivery_date(transportations)
        settings_record = AccountingSettings.current()
        max_days = settings_record.upd_max_days_after_delivery if settings_record else 5
        if delivery_date and not delivery_date <= document_date <= delivery_date + timedelta(days=max_days):
            raise ValidationError(
                f"Дата УПД должна быть в диапазоне {delivery_date:%d.%m.%Y}–"
                f"{delivery_date + timedelta(days=max_days):%d.%m.%Y}."
            )
    return transportations


def _service_context(transportation):
    stops = list(transportation.stops.all())
    pickup = next((item for item in stops if item.kind == TransportationStop.Kind.PICKUP), None)
    delivery = next((item for item in reversed(stops) if item.kind == TransportationStop.Kind.DELIVERY), None)
    assignment = transportation.active_vehicle_assignment()
    date_format = lambda value: value.strftime("%d.%m.%Y") if value else "не указана"
    pickup_date = pickup.planned_from.date() if pickup and pickup.planned_from else transportation.planned_start_date
    delivery_date = delivery.planned_to.date() if delivery and delivery.planned_to else transportation.planned_end_date
    return {
        "route": transportation.route,
        "pickup": pickup.city if pickup else "",
        "delivery": delivery.city if delivery else "",
        "driver": assignment.driver.full_name if assignment and assignment.driver_id else "не назначен",
        "vehicle": (
            f"{assignment.vehicle.make} {assignment.vehicle.registration_number}".strip()
            if assignment and assignment.vehicle_id else "не назначено"
        ),
        "trailer": (
            assignment.trailer.registration_number
            if assignment and assignment.trailer_id else "не назначен"
        ),
        "pickup_date": date_format(pickup_date),
        "delivery_date": date_format(delivery_date),
        "order_number": transportation.client_reference or transportation.number or transportation.pk,
        "trip_number": transportation.number or transportation.pk,
    }


def build_service_name(transportation):
    settings_record = AccountingSettings.current()
    template = settings_record.service_name_template if settings_record else AccountingSettings._meta.get_field("service_name_template").default
    try:
        return template.format_map(_service_context(transportation))
    except (KeyError, ValueError):
        return f"Организация транспортных услуг по маршруту {transportation.route}, рейс №{transportation.number or transportation.pk}."


def line_amounts(transportation, direction):
    if direction == ShipmentDocument.Direction.OUTGOING:
        total = Decimal(transportation.customer_amount or 0)
        vat = Decimal(transportation.customer_vat_amount or 0)
        vat_rate = transportation.customer_vat_rate.rate if transportation.customer_vat_rate_id else Decimal("0")
    else:
        total = Decimal(transportation.executor_amount or 0)
        vat = Decimal(transportation.executor_vat_amount or 0)
        vat_rate = transportation.executor_vat_rate.rate if transportation.executor_vat_rate_id else Decimal("0")
    return total - vat, vat, total, vat_rate


@transaction.atomic
def populate_document_lines(document, transportations, *, user=None):
    transportations = validate_document_transportations(
        transportations=transportations,
        direction=document.direction,
        kind=document.kind,
        document_date=document.document_date,
        exclude_document=document if document.pk else None,
    )
    first = transportations[0]
    document.owner_company = first.owner_company
    document.counterparty = document_counterparty(first, document.direction)
    document.contract = document_contract(first, document.direction)
    document.transportation = first if len(transportations) == 1 else None
    if not document.crm_number:
        document.crm_number = f"CRM-{timezone.localdate():%y%m}-{ShipmentDocument.objects.count() + 1:05d}"
    if not document.number:
        document.number = document.crm_number
    document.save()
    document.lines.all().delete()
    for position, transportation in enumerate(transportations, 1):
        amount, vat, total, rate = line_amounts(transportation, document.direction)
        ShipmentDocumentLine.objects.create(
            document=document,
            transportation=transportation,
            service_name=build_service_name(transportation),
            quantity=Decimal("1"),
            unit="услуга",
            price=amount,
            amount=amount,
            vat_rate=rate,
            vat_amount=vat,
            total_amount=total,
            position=position,
        )
    document.refresh_totals()
    ShipmentDocumentAudit.objects.create(
        document=document,
        action=ShipmentDocumentAudit.Action.CREATED,
        user=user,
        changes={"transportation_ids": [item.pk for item in transportations]},
    )
    return document


def _next_customer_document_number(owner_company, kind, document_date):
    prefix_label = "СЧ" if kind == ShipmentDocument.Kind.INVOICE else "УПД"
    prefix = f"{prefix_label}-{document_date.year}-"
    # Lock the legal entity so two managers cannot issue the same next number
    # for the same company at the same time.
    owner_company.__class__.objects.select_for_update().get(pk=owner_company.pk)
    issued = ShipmentDocument.objects.filter(
        owner_company=owner_company,
        number__startswith=prefix,
    ).values_list("number", flat=True)
    last_value = max(
        (
            int(number.removeprefix(prefix))
            for number in issued
            if number.removeprefix(prefix).isdigit()
        ),
        default=0,
    )
    return f"{prefix}{last_value + 1:05d}"


@transaction.atomic
def issue_customer_document_pair(transportations, *, invoice_date, user=None):
    transportations = list(transportations)
    if not transportations:
        raise ValidationError("Выберите хотя бы один рейс.")

    def missing_for(kind):
        covered_ids = set(
            ShipmentDocument.objects.filter(
                direction=ShipmentDocument.Direction.OUTGOING,
                kind=kind,
                transportation__in=transportations,
            ).values_list("transportation_id", flat=True)
        )
        covered_ids.update(
            ShipmentDocumentLine.objects.filter(
                document__direction=ShipmentDocument.Direction.OUTGOING,
                document__kind=kind,
                transportation__in=transportations,
            ).values_list("transportation_id", flat=True)
        )
        return [item for item in transportations if item.pk not in covered_ids]

    invoice_transportations = missing_for(ShipmentDocument.Kind.INVOICE)
    upd_transportations = missing_for(ShipmentDocument.Kind.UPD)
    first = transportations[0]
    invoice = None
    if invoice_transportations:
        validate_document_transportations(
            transportations=invoice_transportations,
            direction=ShipmentDocument.Direction.OUTGOING,
            kind=ShipmentDocument.Kind.INVOICE,
            document_date=invoice_date,
        )
        invoice = ShipmentDocument.objects.create(
            direction=ShipmentDocument.Direction.OUTGOING,
            kind=ShipmentDocument.Kind.INVOICE,
            party=ShipmentDocument.Party.CUSTOMER,
            status=ShipmentDocument.Status.ISSUED,
            document_date=invoice_date,
            currency=first.currency,
            owner_company=first.owner_company,
            counterparty=document_counterparty(first, ShipmentDocument.Direction.OUTGOING),
            contract=document_contract(first, ShipmentDocument.Direction.OUTGOING),
            created_by=user,
        )
        invoice.number = _next_customer_document_number(
            first.owner_company, invoice.kind, invoice_date
        )
        invoice.crm_number = invoice.number
        invoice.save(update_fields=["number", "crm_number", "updated_at"])
        populate_document_lines(invoice, invoice_transportations, user=user)

    upd = None
    if upd_transportations:
        upd_date = last_delivery_date(upd_transportations) or invoice_date
        validate_document_transportations(
            transportations=upd_transportations,
            direction=ShipmentDocument.Direction.OUTGOING,
            kind=ShipmentDocument.Kind.UPD,
            document_date=upd_date,
        )
        upd = ShipmentDocument.objects.create(
            direction=ShipmentDocument.Direction.OUTGOING,
            kind=ShipmentDocument.Kind.UPD,
            party=ShipmentDocument.Party.CUSTOMER,
            status=ShipmentDocument.Status.ISSUED,
            document_date=upd_date,
            currency=first.currency,
            owner_company=first.owner_company,
            counterparty=document_counterparty(first, ShipmentDocument.Direction.OUTGOING),
            contract=document_contract(first, ShipmentDocument.Direction.OUTGOING),
            based_on=invoice,
            created_by=user,
        )
        upd.number = _next_customer_document_number(first.owner_company, upd.kind, upd_date)
        upd.crm_number = upd.number
        upd.save(update_fields=["number", "crm_number", "updated_at"])
        populate_document_lines(upd, upd_transportations, user=user)

    Transportation.objects.filter(
        pk__in=[item.pk for item in transportations],
        status__in=[
            Transportation.Status.DELIVERED,
            Transportation.Status.DOCUMENTS_RECEIVED,
            Transportation.Status.DOCUMENTS_SENT,
            Transportation.Status.DOCUMENT_FLOW_COMPLETED,
        ],
    ).update(status=Transportation.Status.CUSTOMER_INVOICED, updated_at=timezone.now())
    return invoice, upd
