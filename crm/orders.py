from datetime import datetime, time

from django.db import transaction
from django.utils import timezone

from .models import (
    Contract,
    OrganizationContact,
    TransportOrder,
    TransportOrderStop,
    Transportation,
    TransportationParty,
    TransportationStop,
    TransportationStatusEvent,
    VATRate,
)


def _planned_datetime(route_stop, time_value=None, *, default_time=None):
    if not route_stop.planned_date:
        return None
    if time_value is None and default_time is None:
        return None
    value = datetime.combine(
        route_stop.planned_date,
        time_value or default_time,
    )
    return timezone.make_aware(value, timezone.get_current_timezone())


def _customer_vat_rate(order):
    rates = VATRate.objects.filter(is_active=True)
    payment_form_rates = {
        TransportOrder.PaymentForm.BANK_VAT_0: "0",
        TransportOrder.PaymentForm.BANK_VAT_5: "5",
        TransportOrder.PaymentForm.BANK_VAT_7: "7",
        TransportOrder.PaymentForm.BANK_VAT_10: "10",
        TransportOrder.PaymentForm.BANK_VAT_18: "18",
        TransportOrder.PaymentForm.BANK_VAT_20: "20",
        TransportOrder.PaymentForm.BANK_VAT_22: "22",
    }
    rate_value = payment_form_rates.get(order.payment_form)
    if rate_value:
        return rates.filter(is_without_vat=False, rate=rate_value).first()
    return rates.filter(is_without_vat=True).order_by("pk").first()


@transaction.atomic
def assign_order_to_transportation(order, user):
    """Create the operational trip once and connect it to the customer order."""

    order = (
        TransportOrder.objects.select_for_update()
        .select_related("owner_company", "client", "manager")
        .get(pk=order.pk)
    )
    if order.transportation_id:
        return order.transportation

    transportation = Transportation.objects.create(
        owner_company=order.owner_company,
        manager=order.manager,
        document_date=order.document_date,
        client_contact=OrganizationContact.objects.filter(
            organization=order.client, is_active=True
        ).order_by("-is_primary", "full_name").first(),
        status=Transportation.Status.EXECUTOR_SELECTED,
        client_reference=(
            f"{order.number} от {order.document_date.strftime('%d.%m.%Y')}"
        ),
        customer_amount=order.rate,
        customer_prepayment=order.prepayment,
        customer_payment_form=order.payment_form,
        customer_contract=order.customer_contract or Contract.objects.filter(
            kind=Contract.Kind.CLIENT_FORWARDING,
            customer__organization=order.client,
            expeditor__organization=order.owner_company,
            status__in=[Contract.Status.READY, Contract.Status.SIGNED],
        ).order_by("-contract_date", "-pk").first(),
        customer_vat_rate=_customer_vat_rate(order),
        currency=order.currency,
        executor_currency=order.currency,
        customer_payment_term_days=order.payment_term_days,
        payment_due_basis=order.payment_due_basis,
        executor_payment_due_basis=Transportation.PaymentDueBasis.DELIVERY_DATE,
        cargo_name=order.cargo_name,
        cargo_description=order.cargo_description,
        cargo_value=order.cargo_value,
        weight_kg=order.weight_kg,
        volume_m3=order.volume_m3,
        package_count=order.package_count,
        pallet_count=order.pallet_count,
        package_type=order.package_type,
        temperature_regime=order.temperature_regime,
        adr_class=order.adr_class,
        vehicle_requirements=order.vehicle_requirements,
        special_requirements=order.special_requirements,
        planned_start_date=order.planned_start_date,
        planned_end_date=order.planned_end_date,
        notes=order.notes,
    )
    TransportationParty.objects.bulk_create(
        [
            TransportationParty(
                transportation=transportation,
                organization=order.client,
                role=TransportationParty.Role.CLIENT,
                sequence=1,
                source="order",
            ),
            TransportationParty(
                transportation=transportation,
                organization=order.owner_company,
                role=TransportationParty.Role.OWN_COMPANY,
                sequence=2,
                source="order",
            ),
        ]
    )
    for route_stop in order.stops.all():
        TransportationStop.objects.create(
            transportation=transportation,
            sequence=route_stop.sequence,
            kind=(
                TransportationStop.Kind.PICKUP
                if route_stop.kind == TransportOrderStop.Kind.PICKUP
                else TransportationStop.Kind.DELIVERY
            ),
            organization=route_stop.organization,
            organization_text=route_stop.organization_text,
            city=route_stop.city,
            address=route_stop.address,
            address_fias_id=route_stop.address_fias_id,
            address_postal_code=route_stop.address_postal_code,
            address_region_code=route_stop.address_region_code,
            address_region=route_stop.address_region,
            address_area=route_stop.address_area,
            address_city=route_stop.address_city,
            address_settlement=route_stop.address_settlement,
            address_street=route_stop.address_street,
            address_house=route_stop.address_house,
            address_block=route_stop.address_block,
            address_flat=route_stop.address_flat,
            contact_name=route_stop.contact_name,
            contact_phone=route_stop.contact_phone,
            planned_from=_planned_datetime(
                route_stop, route_stop.planned_time_from, default_time=time(hour=9)
            ),
            planned_to=_planned_datetime(route_stop, route_stop.planned_time_to),
            instructions=route_stop.instructions,
        )

    order.transportation = transportation
    order.status = TransportOrder.Status.ASSIGNED
    order.assigned_at = timezone.now()
    order.assigned_by = user
    order.save(
        update_fields=[
            "transportation", "status", "assigned_at", "assigned_by", "updated_at"
        ]
    )
    TransportationStatusEvent.objects.create(
        transportation=transportation,
        old_status="",
        new_status=transportation.status,
        changed_by=user,
        comment="Рейс создан из заказа",
        source="order",
        changes={
            "Основание": {"old": "", "new": order.number or "Заказ"},
            "Маршрут": {"old": "", "new": transportation.route},
        },
    )
    return transportation


@transaction.atomic
def sync_order_from_transportation(transportation):
    """Keep the source order aligned with edits made in its assignment trip."""

    try:
        order = transportation.source_order
    except TransportOrder.DoesNotExist:
        return None

    client_party = transportation.parties.filter(
        role=TransportationParty.Role.CLIENT,
        is_active=True,
    ).select_related("organization").first()
    if not client_party:
        return order

    order_fields = {
        "owner_company": transportation.owner_company,
        "manager": transportation.manager,
        "document_date": transportation.document_date,
        "client": client_party.organization,
        "rate": transportation.customer_amount,
        "prepayment": transportation.customer_prepayment,
        "currency": transportation.currency,
        "payment_form": transportation.customer_payment_form,
        "payment_term_days": transportation.customer_payment_term_days,
        "customer_contract": transportation.customer_contract,
        "payment_due_basis": transportation.payment_due_basis,
        "cargo_name": transportation.cargo_name,
        "cargo_description": transportation.cargo_description,
        "cargo_value": transportation.cargo_value,
        "weight_kg": transportation.weight_kg,
        "volume_m3": transportation.volume_m3,
        "package_count": transportation.package_count,
        "pallet_count": transportation.pallet_count,
        "package_type": transportation.package_type,
        "temperature_regime": transportation.temperature_regime,
        "adr_class": transportation.adr_class,
        "vehicle_requirements": transportation.vehicle_requirements,
        "special_requirements": transportation.special_requirements,
        "planned_start_date": transportation.planned_start_date,
        "planned_end_date": transportation.planned_end_date,
        "notes": transportation.notes,
    }
    for field_name, value in order_fields.items():
        setattr(order, field_name, value)
    order.save(update_fields=[*order_fields, "updated_at"])

    order.stops.all().delete()
    shared_stop_fields = (
        "organization", "organization_text", "city", "address",
        "address_fias_id", "address_postal_code", "address_region_code",
        "address_region", "address_area", "address_city", "address_settlement",
        "address_street", "address_house", "address_block", "address_flat",
        "contact_name", "contact_phone", "instructions",
    )
    stops = list(transportation.stops.order_by("sequence", "pk"))
    for sequence, stop in enumerate(stops, start=1):
        planned_from = stop.planned_from
        TransportOrderStop.objects.create(
            order=order,
            sequence=sequence,
            kind=(
                TransportOrderStop.Kind.DELIVERY
                if stop.kind == TransportationStop.Kind.DELIVERY
                else TransportOrderStop.Kind.PICKUP
            ),
            planned_date=planned_from.date() if planned_from else None,
            planned_time_from=planned_from.time() if planned_from else None,
            planned_time_to=stop.planned_to.time() if stop.planned_to else None,
            **{field_name: getattr(stop, field_name) for field_name in shared_stop_fields},
        )
    return order
