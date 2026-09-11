from datetime import datetime, time

from django.db import transaction
from django.utils import timezone

from .models import (
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
        TransportOrder.PaymentForm.BANK_VAT_5: "5",
        TransportOrder.PaymentForm.BANK_VAT_7: "7",
        TransportOrder.PaymentForm.BANK_VAT_10: "10",
        TransportOrder.PaymentForm.BANK_VAT_20: "20",
        TransportOrder.PaymentForm.BANK_VAT_22: "22",
    }
    rate_value = payment_form_rates.get(order.payment_form)
    if rate_value:
        return rates.filter(is_without_vat=False, rate=rate_value).first()
    if order.payment_form == TransportOrder.PaymentForm.BANK_WITH_VAT:
        return rates.filter(is_without_vat=False).order_by("-rate", "pk").first()
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
        status=Transportation.Status.EXECUTOR_SELECTED,
        customer_amount=order.rate,
        customer_vat_rate=_customer_vat_rate(order),
        currency=order.currency,
        customer_payment_term_days=order.payment_term_days,
        payment_due_basis=Transportation.PaymentDueBasis.DELIVERY_DATE,
        cargo_name=order.cargo_name,
        cargo_description=order.cargo_description,
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
