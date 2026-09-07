from datetime import datetime, time

from django.db import transaction
from django.utils import timezone

from .models import (
    Carrier,
    CompanyProfile,
    Contract,
    Customer,
    Organization,
    OrganizationRole,
    Shipment,
    Transportation,
    TransportationLink,
    TransportationParty,
    TransportationStop,
    VATRate,
    VehicleAssignment,
)


COMMON_FIELDS = (
    "name",
    "tax_id",
    "kpp",
    "ogrn",
    "director_name",
    "phone",
    "email",
    "bank_name",
    "bik",
    "settlement_account",
    "correspondent_account",
    "is_active",
)


def _legacy_role(instance):
    if isinstance(instance, CompanyProfile):
        return None, True
    if isinstance(instance, Customer):
        return OrganizationRole.Role.CLIENT, False
    return OrganizationRole.Role.CARRIER, False


@transaction.atomic
def sync_legacy_organization(instance):
    role, is_own_company = _legacy_role(instance)
    organization = instance.organization if instance.organization_id else None
    if organization is None and instance.tax_id:
        organization = Organization.objects.filter(tax_id=instance.tax_id).first()
    if organization is None:
        organization = Organization()

    for field in COMMON_FIELDS:
        value = getattr(instance, field, None)
        if value not in (None, ""):
            setattr(organization, field, value)
    organization.short_name = getattr(instance, "short_name", "") or organization.short_name
    organization.legal_address = (
        getattr(instance, "legal_address", "")
        or getattr(instance, "address", "")
        or organization.legal_address
    )
    organization.contact_name = (
        getattr(instance, "contact_name", "") or organization.contact_name
    )
    organization.notes = getattr(instance, "notes", "") or organization.notes
    organization.is_own_company = organization.is_own_company or is_own_company
    organization.save()

    if role:
        OrganizationRole.objects.update_or_create(
            organization=organization,
            role=role,
            defaults={"is_active": True},
        )
    instance.__class__.objects.filter(pk=instance.pk).update(
        organization=organization
    )
    instance.organization_id = organization.pk
    instance.organization = organization
    return organization


def _legacy_defaults(organization):
    return {
        "name": organization.name,
        "tax_id": organization.tax_id,
        "kpp": organization.kpp,
        "ogrn": organization.ogrn,
        "director_name": organization.director_name,
        "phone": organization.phone,
        "email": organization.email,
        "bank_name": organization.bank_name,
        "bik": organization.bik,
        "settlement_account": organization.settlement_account,
        "correspondent_account": organization.correspondent_account,
        "is_active": organization.is_active,
    }


@transaction.atomic
def sync_organization_to_legacy(organization):
    common = _legacy_defaults(organization)
    customer_defaults = {
        **common,
        "address": organization.legal_address,
        "contact_name": organization.contact_name,
        "notes": organization.notes,
        "organization": organization,
    }
    carrier_defaults = {
        **common,
        "address": organization.legal_address,
        "contact_name": organization.contact_name,
        "notes": organization.notes,
        "organization": organization,
    }
    profile_defaults = {
        **common,
        "short_name": organization.short_name,
        "legal_address": organization.legal_address,
        "organization": organization,
    }

    active_roles = set(
        organization.roles.filter(is_active=True).values_list("role", flat=True)
    )
    if OrganizationRole.Role.CLIENT in active_roles:
        customer = organization.legacy_customers.first()
        if customer:
            Customer.objects.filter(pk=customer.pk).update(**customer_defaults)
        else:
            Customer.objects.create(**customer_defaults)
    if active_roles.intersection(
        {OrganizationRole.Role.CARRIER, OrganizationRole.Role.FORWARDER}
    ):
        carrier = organization.legacy_carriers.first()
        if carrier:
            Carrier.objects.filter(pk=carrier.pk).update(**carrier_defaults)
        else:
            Carrier.objects.create(**carrier_defaults)
    if organization.is_own_company and organization.tax_id and organization.legal_address:
        profile = organization.legacy_expeditors.first()
        if profile:
            CompanyProfile.objects.filter(pk=profile.pk).update(**profile_defaults)
        else:
            CompanyProfile.objects.create(**profile_defaults)


def _planned_datetime(value):
    if not value:
        return None
    combined = datetime.combine(value, time(hour=9))
    return timezone.make_aware(combined, timezone.get_current_timezone())


SHIPMENT_STATUS_MAP = {
    Shipment.Status.NEW: Transportation.Status.NEW,
    Shipment.Status.PLANNED: Transportation.Status.EXECUTOR_SELECTED,
    Shipment.Status.LOADING: Transportation.Status.LOADING,
    Shipment.Status.IN_TRANSIT: Transportation.Status.IN_TRANSIT,
    Shipment.Status.DELIVERED: Transportation.Status.DELIVERED,
    Shipment.Status.CLOSED: Transportation.Status.CLOSED,
    Shipment.Status.CANCELLED: Transportation.Status.CANCELLED,
}


@transaction.atomic
def sync_shipment_to_transportation(shipment):
    owner = sync_legacy_organization(shipment.expeditor)
    client = sync_legacy_organization(shipment.customer)
    executor = sync_legacy_organization(shipment.carrier) if shipment.carrier_id else None
    customer_vat_rate = VATRate.objects.filter(
        code=shipment.expeditor.default_vat_rate
    ).first() or VATRate.objects.filter(code="without_vat").first()
    executor_vat_rate = VATRate.objects.filter(code="without_vat").first()
    customer_contract = Contract.objects.filter(
        expeditor=shipment.expeditor,
        customer=shipment.customer,
        kind=Contract.Kind.CLIENT_FORWARDING,
    ).exclude(status__in=[Contract.Status.TERMINATED, Contract.Status.ARCHIVED]).first()
    customer_term = (
        max((shipment.customer_payment_due_date - shipment.delivery_date).days, 0)
        if shipment.customer_payment_due_date else 0
    )
    executor_term = (
        max((shipment.carrier_payment_due_date - shipment.delivery_date).days, 0)
        if shipment.carrier_payment_due_date else 0
    )

    transportation, _ = Transportation.objects.update_or_create(
        legacy_shipment=shipment,
        defaults={
            "number": shipment.number,
            "number_year": shipment.pickup_date.year,
            "owner_company": owner,
            "manager": shipment.manager,
            "status": SHIPMENT_STATUS_MAP.get(shipment.status, Transportation.Status.NEW),
            "client_reference": shipment.customer_reference,
            "customer_contract": customer_contract,
            "customer_amount": shipment.customer_price,
            "customer_vat_rate": customer_vat_rate,
            "executor_amount": shipment.carrier_price,
            "executor_vat_rate": executor_vat_rate,
            "currency": shipment.currency,
            "customer_payment_term_days": customer_term,
            "executor_payment_term_days": executor_term,
            "customer_payment_due_date": shipment.customer_payment_due_date,
            "executor_payment_due_date": shipment.carrier_payment_due_date,
            "cargo_name": shipment.cargo_name,
            "weight_kg": shipment.weight_kg,
            "volume_m3": shipment.volume_m3,
            "vehicle_requirements": shipment.vehicle_type,
            "planned_start_date": shipment.pickup_date,
            "planned_end_date": shipment.delivery_date,
            "notes": shipment.notes,
        },
    )
    TransportationStop.objects.update_or_create(
        transportation=transportation,
        sequence=1,
        defaults={
            "kind": TransportationStop.Kind.PICKUP,
            "city": shipment.pickup_city,
            "address": shipment.pickup_address,
            "planned_from": _planned_datetime(shipment.pickup_date),
        },
    )
    TransportationStop.objects.update_or_create(
        transportation=transportation,
        sequence=2,
        defaults={
            "kind": TransportationStop.Kind.DELIVERY,
            "city": shipment.delivery_city,
            "address": shipment.delivery_address,
            "planned_from": _planned_datetime(shipment.delivery_date),
        },
    )
    own_party, _ = TransportationParty.objects.update_or_create(
        transportation=transportation,
        organization=owner,
        role=TransportationParty.Role.OWN_COMPANY,
        defaults={"sequence": 2, "source": "legacy", "is_active": True},
    )
    TransportationParty.objects.filter(
        transportation=transportation,
        role=TransportationParty.Role.CLIENT,
        source="legacy",
    ).exclude(organization=client).update(is_active=False)
    TransportationParty.objects.update_or_create(
        transportation=transportation,
        organization=client,
        role=TransportationParty.Role.CLIENT,
        defaults={"sequence": 1, "source": "legacy", "is_active": True},
    )

    if transportation.legacy_chain_sync:
        if executor:
            executor_party, _ = TransportationParty.objects.update_or_create(
                transportation=transportation,
                organization=executor,
                role=TransportationParty.Role.EXECUTOR,
                defaults={"sequence": 3, "source": "legacy", "is_active": True},
            )
            factual_party, _ = TransportationParty.objects.update_or_create(
                transportation=transportation,
                organization=executor,
                role=TransportationParty.Role.FACTUAL_CARRIER,
                defaults={"sequence": 4, "source": "legacy", "is_active": True},
            )
            TransportationParty.objects.filter(
                transportation=transportation,
                role__in=[
                    TransportationParty.Role.EXECUTOR,
                    TransportationParty.Role.FACTUAL_CARRIER,
                ],
                source="legacy",
            ).exclude(organization=executor).update(is_active=False)
            contract = Contract.objects.filter(
                expeditor=shipment.expeditor,
                carrier=shipment.carrier,
                kind=Contract.Kind.CARRIER_TRANSPORT,
            ).exclude(status__in=[Contract.Status.TERMINATED, Contract.Status.ARCHIVED]).first()
            link, _ = TransportationLink.objects.update_or_create(
                transportation=transportation,
                sequence=1,
                defaults={
                    "parent": None,
                    "principal_party": own_party,
                    "contractor_party": executor_party,
                    "contractor_role": TransportationLink.ContractorRole.CARRIER,
                    "contract": contract,
                    "source": "legacy",
                    "is_active": True,
                },
            )
            assignment = transportation.vehicle_assignments.filter(is_active=True).first()
            if not assignment:
                assignment = VehicleAssignment(transportation=transportation)
            assignment.execution_link = link
            assignment.actual_carrier = executor
            assignment.driver = shipment.driver
            assignment.vehicle = shipment.vehicle
            assignment.trailer_registration_number = (
                shipment.vehicle.trailer_registration_number if shipment.vehicle_id else ""
            )
            assignment.is_active = True
            assignment.save()
        else:
            transportation.execution_links.filter(source="legacy").update(is_active=False)
            transportation.parties.filter(
                source="legacy",
                role__in=[
                    TransportationParty.Role.EXECUTOR,
                    TransportationParty.Role.FACTUAL_CARRIER,
                ],
            ).update(is_active=False)
            transportation.vehicle_assignments.filter(is_active=True).update(is_active=False)
    return transportation


@transaction.atomic
def set_transportation_chain(
    *,
    transportation,
    user,
    executor,
    executor_role,
    contract,
    instruction_number,
    instruction_status,
    actual_carrier,
    driver,
    vehicle,
    trailer,
    trailer_registration_number,
    combination=None,
):
    if combination:
        vehicle = combination.tractor
        trailer = combination.trailer
        trailer_registration_number = combination.trailer.registration_number
    own_party, _ = TransportationParty.objects.update_or_create(
        transportation=transportation,
        organization=transportation.owner_company,
        role=TransportationParty.Role.OWN_COMPANY,
        defaults={"sequence": 2, "source": "manual", "is_active": True},
    )
    transportation.vehicle_assignments.update(is_active=False, execution_link=None)
    for existing_link in transportation.execution_links.order_by("-sequence"):
        existing_link.delete()
    transportation.parties.filter(
        role__in=[
            TransportationParty.Role.EXECUTOR,
            TransportationParty.Role.FORWARDER,
            TransportationParty.Role.FACTUAL_CARRIER,
        ]
    ).update(is_active=False)

    executor_party, _ = TransportationParty.objects.update_or_create(
        transportation=transportation,
        organization=executor,
        role=TransportationParty.Role.EXECUTOR,
        defaults={"sequence": 3, "source": "manual", "is_active": True},
    )
    factual_party, _ = TransportationParty.objects.update_or_create(
        transportation=transportation,
        organization=actual_carrier,
        role=TransportationParty.Role.FACTUAL_CARRIER,
        defaults={"sequence": 5, "source": "manual", "is_active": True},
    )
    first_link = TransportationLink.objects.create(
        transportation=transportation,
        principal_party=own_party,
        contractor_party=executor_party,
        contractor_role=executor_role,
        sequence=1,
        contract=contract,
        instruction_number=instruction_number,
        instruction_status=instruction_status,
        source="manual",
    )
    final_link = first_link
    if executor_role == TransportationLink.ContractorRole.FORWARDER:
        final_link = TransportationLink.objects.create(
            transportation=transportation,
            parent=first_link,
            principal_party=executor_party,
            contractor_party=factual_party,
            contractor_role=TransportationLink.ContractorRole.CARRIER,
            sequence=2,
            source="manual",
        )
    VehicleAssignment.objects.create(
        transportation=transportation,
        execution_link=final_link,
        actual_carrier=actual_carrier,
        driver=driver,
        vehicle=vehicle,
        combination=combination,
        trailer=trailer,
        trailer_registration_number=trailer_registration_number,
        confirmed_by=user if driver and vehicle else None,
        confirmed_at=timezone.now() if driver and vehicle else None,
    )
    transportation.legacy_chain_sync = False
    transportation.save(update_fields=["legacy_chain_sync", "updated_at"])

    if transportation.legacy_shipment_id:
        legacy_carrier = executor.legacy_carriers.first()
        direct = executor_role == TransportationLink.ContractorRole.CARRIER
        Shipment.objects.filter(pk=transportation.legacy_shipment_id).update(
            carrier=legacy_carrier,
            driver=driver if direct else None,
            vehicle=vehicle if direct else None,
        )
    return transportation
