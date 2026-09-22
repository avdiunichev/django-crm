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
