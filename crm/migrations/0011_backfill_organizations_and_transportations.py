from datetime import datetime, time

from django.db import migrations
from django.utils import timezone


def backfill(apps, schema_editor):
    Organization = apps.get_model("crm", "Organization")
    OrganizationRole = apps.get_model("crm", "OrganizationRole")
    CompanyProfile = apps.get_model("crm", "CompanyProfile")
    Customer = apps.get_model("crm", "Customer")
    Carrier = apps.get_model("crm", "Carrier")
    Contract = apps.get_model("crm", "Contract")
    Shipment = apps.get_model("crm", "Shipment")
    Transportation = apps.get_model("crm", "Transportation")
    TransportationStop = apps.get_model("crm", "TransportationStop")
    TransportationParty = apps.get_model("crm", "TransportationParty")
    TransportationLink = apps.get_model("crm", "TransportationLink")
    VehicleAssignment = apps.get_model("crm", "VehicleAssignment")

    def organization_for(instance, *, role=None, own=False, address_field="address"):
        organization = None
        if instance.organization_id:
            organization = Organization.objects.filter(pk=instance.organization_id).first()
        if organization is None and instance.tax_id:
            organization = Organization.objects.filter(tax_id=instance.tax_id).first()
        if organization is None:
            organization = Organization()
        values = {
            "name": instance.name,
            "short_name": getattr(instance, "short_name", ""),
            "tax_id": instance.tax_id,
            "kpp": instance.kpp,
            "ogrn": instance.ogrn,
            "legal_address": getattr(instance, address_field, ""),
            "contact_name": getattr(instance, "contact_name", ""),
            "director_name": instance.director_name,
            "phone": instance.phone,
            "email": instance.email,
            "bank_name": instance.bank_name,
            "bik": instance.bik,
            "settlement_account": instance.settlement_account,
            "correspondent_account": instance.correspondent_account,
            "notes": getattr(instance, "notes", ""),
            "is_active": instance.is_active,
        }
        for field, value in values.items():
            if value not in (None, ""):
                setattr(organization, field, value)
        organization.is_own_company = organization.is_own_company or own
        organization.save()
        instance.__class__.objects.filter(pk=instance.pk).update(
            organization_id=organization.pk
        )
        if role:
            OrganizationRole.objects.update_or_create(
                organization_id=organization.pk,
                role=role,
                defaults={"is_active": True},
            )
        return organization

    expeditor_organizations = {}
    for profile in CompanyProfile.objects.all():
        expeditor_organizations[profile.pk] = organization_for(
            profile, own=True, address_field="legal_address"
        )
    customer_organizations = {}
    for customer in Customer.objects.all():
        customer_organizations[customer.pk] = organization_for(
            customer, role="client"
        )
    carrier_organizations = {}
    for carrier in Carrier.objects.all():
        carrier_organizations[carrier.pk] = organization_for(
            carrier, role="carrier"
        )

    status_map = {
        "new": "new",
        "planned": "executor_selected",
        "loading": "loading",
        "in_transit": "in_transit",
        "delivered": "delivered",
        "closed": "closed",
        "cancelled": "cancelled",
    }

    def planned(value):
        if not value:
            return None
        result = datetime.combine(value, time(hour=9))
        return timezone.make_aware(result, timezone.get_current_timezone())

    for shipment in Shipment.objects.all().iterator():
        owner = expeditor_organizations[shipment.expeditor_id]
        client = customer_organizations[shipment.customer_id]
        executor = carrier_organizations.get(shipment.carrier_id)
        transportation = Transportation.objects.create(
            legacy_shipment_id=shipment.pk,
            number=shipment.number,
            owner_company_id=owner.pk,
            manager_id=shipment.manager_id,
            status=status_map.get(shipment.status, "new"),
            cargo_name=shipment.cargo_name,
            weight_kg=shipment.weight_kg,
            volume_m3=shipment.volume_m3,
            vehicle_requirements=shipment.vehicle_type,
            planned_start_date=shipment.pickup_date,
            planned_end_date=shipment.delivery_date,
            notes=shipment.notes,
        )
        TransportationStop.objects.create(
            transportation_id=transportation.pk,
            sequence=1,
            kind="pickup",
            city=shipment.pickup_city,
            address=shipment.pickup_address,
            planned_from=planned(shipment.pickup_date),
        )
        TransportationStop.objects.create(
            transportation_id=transportation.pk,
            sequence=2,
            kind="delivery",
            city=shipment.delivery_city,
            address=shipment.delivery_address,
            planned_from=planned(shipment.delivery_date),
        )
        client_party = TransportationParty.objects.create(
            transportation_id=transportation.pk,
            organization_id=client.pk,
            role="client",
            sequence=1,
            source="legacy",
        )
        own_party = TransportationParty.objects.create(
            transportation_id=transportation.pk,
            organization_id=owner.pk,
            role="own_company",
            sequence=2,
            source="legacy",
        )
        if not executor:
            continue
        executor_party = TransportationParty.objects.create(
            transportation_id=transportation.pk,
            organization_id=executor.pk,
            role="executor",
            sequence=3,
            source="legacy",
        )
        TransportationParty.objects.create(
            transportation_id=transportation.pk,
            organization_id=executor.pk,
            role="factual_carrier",
            sequence=4,
            source="legacy",
        )
        contract = Contract.objects.filter(
            expeditor_id=shipment.expeditor_id,
            carrier_id=shipment.carrier_id,
            kind="carrier_transport",
        ).exclude(status__in=["terminated", "archived"]).first()
        link = TransportationLink.objects.create(
            transportation_id=transportation.pk,
            principal_party_id=own_party.pk,
            contractor_party_id=executor_party.pk,
            contractor_role="carrier",
            sequence=1,
            contract_id=contract.pk if contract else None,
            source="legacy",
        )
        VehicleAssignment.objects.create(
            transportation_id=transportation.pk,
            execution_link_id=link.pk,
            actual_carrier_id=executor.pk,
            driver_id=shipment.driver_id,
            vehicle_id=shipment.vehicle_id,
            trailer_registration_number=(
                shipment.vehicle.trailer_registration_number
                if shipment.vehicle_id
                else ""
            ),
        )


class Migration(migrations.Migration):
    dependencies = [("crm", "0010_organization_carrier_organization_and_more")]

    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
