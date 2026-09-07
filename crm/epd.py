"""Canonical payloads and draft files for electronic transport documents.

The XML generated here is an internal, lossless draft for review/download. It
is intentionally not presented as the operator's production schema: Kontur and
Saby adapters can serialize the same canonical payload to their current API
format once credentials and the operator contract are configured.
"""

from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4
from xml.etree.ElementTree import Element, SubElement, tostring

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.timezone import localtime

from .models import (
    Transportation,
    TransportationElectronicDocument,
    TransportationLink,
    TransportationParty,
    TransportationStop,
)


def _value(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _party(transportation, role):
    return transportation.parties.filter(
        role=role, is_active=True
    ).select_related("organization").first()


def epd_validation_errors(transportation, kind=None):
    """Return blocking errors before an EPD draft is generated.

    The sender's EZZ title is prepared before a driver and vehicle are known;
    the operator adds them while confirming the document. When ``kind`` is
    omitted, retain strict validation for callers that validate a complete
    EPD package. ETRN keeps the same strict vehicle checks.
    """

    errors = []
    if not transportation.owner_company_id:
        errors.append("Не выбрана наша компания.")
    client = _party(transportation, TransportationParty.Role.CLIENT)
    if not client:
        errors.append("Не выбран клиент.")
    link = transportation.active_execution_link()
    if not link:
        errors.append("Не выбран исполнитель.")
    assignment = transportation.active_vehicle_assignment()
    requires_vehicle = (
        kind is None or kind == TransportationElectronicDocument.Kind.ETRN
    )
    if requires_vehicle:
        if not assignment:
            errors.append("Не назначены водитель и транспорт.")
        else:
            if not assignment.actual_carrier_id:
                errors.append("Не указан фактический перевозчик.")
            if not assignment.driver_id:
                errors.append("Не назначен водитель.")
            if not assignment.vehicle_id:
                errors.append("Не назначен тягач или автомобиль.")
    if not transportation.cargo_name.strip():
        errors.append("Не указано наименование груза.")
    if transportation.weight_kg <= 0:
        errors.append("Укажите вес груза больше нуля.")

    stops = list(transportation.stops.all())
    pickups = [stop for stop in stops if stop.kind == TransportationStop.Kind.PICKUP]
    deliveries = [stop for stop in stops if stop.kind == TransportationStop.Kind.DELIVERY]
    if not pickups:
        errors.append("Не добавлена точка погрузки.")
    if not deliveries:
        errors.append("Не добавлена точка выгрузки.")
    for stop in pickups + deliveries:
        if not stop.city.strip():
            errors.append(f"У точки №{stop.sequence} не указан город.")
        if not stop.address.strip():
            errors.append(f"У точки №{stop.sequence} не указан полный адрес.")
        if not stop.planned_from:
            errors.append(f"У точки №{stop.sequence} не указана дата и время.")
    if (
        requires_vehicle
        and link
        and link.contractor_role == TransportationLink.ContractorRole.FORWARDER
    ):
        if not assignment or not assignment.actual_carrier_id:
            errors.append(
                "Для исполнителя-экспедитора обязательно укажите фактического перевозчика."
            )
    return errors


def _stop_payload(stop):
    return {
        "sequence": stop.sequence,
        "kind": stop.get_kind_display(),
        "city": stop.city,
        "address": stop.address,
        "address_data": {
            key.removeprefix("address_"): getattr(stop, key, "")
            for key in (
                "address_fias_id", "address_postal_code", "address_region_code",
                "address_region", "address_area", "address_city",
                "address_settlement", "address_street", "address_house",
                "address_block", "address_flat",
            )
            if getattr(stop, key, "")
        },
        "contact_name": stop.contact_name,
        "contact_phone": stop.contact_phone,
        "planned_from": _value(stop.planned_from),
        "planned_to": _value(stop.planned_to),
        "instructions": stop.instructions,
    }


def build_epd_payload(transportation, kind, stop=None):
    """Build a provider-neutral payload from a transportation card."""

    client = _party(transportation, TransportationParty.Role.CLIENT)
    shipper = _party(transportation, TransportationParty.Role.SHIPPER)
    consignee = _party(transportation, TransportationParty.Role.CONSIGNEE)
    link = transportation.active_execution_link()
    assignment = transportation.active_vehicle_assignment()
    executor = link.contractor_party if link else None

    routes = list(transportation.stops.all())
    if kind == TransportationElectronicDocument.Kind.ETRN and stop:
        # One ETrN is issued for each delivery point. Keep all loading points
        # and the selected delivery point in that document's payload.
        routes = [
            item for item in routes
            if item.kind == TransportationStop.Kind.PICKUP or item.pk == stop.pk
        ]

    def org_data(party):
        if not party:
            return None
        organization = party.organization
        return {
            "role": party.get_role_display(),
            "name": organization.name,
            "short_name": organization.short_name,
            "tax_id": organization.tax_id,
            "kpp": organization.kpp,
            "ogrn": organization.ogrn,
            "legal_address": organization.legal_address,
            "address_data": _organization_address_data(organization),
            "edo_operator": organization.edo_operator,
            "edo_id": getattr(organization, "edo_id", ""),
        }

    payload = {
        "document": {
            "kind": kind,
            "kind_label": TransportationElectronicDocument.Kind(kind).label,
            "transportation_id": transportation.pk,
            "transportation_number": transportation.number or "",
            "document_date": _value(transportation.document_date),
            "currency": transportation.currency,
        },
        "participants": {
            "owner_company": {
                "name": transportation.owner_company.name,
                "short_name": transportation.owner_company.short_name,
                "tax_id": transportation.owner_company.tax_id,
                "kpp": transportation.owner_company.kpp,
                "ogrn": transportation.owner_company.ogrn,
                "legal_address": transportation.owner_company.legal_address,
                "address_data": _organization_address_data(transportation.owner_company),
                "edo_operator": transportation.owner_company.edo_operator,
                "edo_id": getattr(transportation.owner_company, "edo_id", ""),
            },
            "client": org_data(client),
            "shipper": org_data(shipper),
            "consignee": org_data(consignee),
            "executor": org_data(executor),
            "actual_carrier": (
                {
                    "name": assignment.actual_carrier.name,
                    "tax_id": assignment.actual_carrier.tax_id,
                    "kpp": assignment.actual_carrier.kpp,
                    "ogrn": assignment.actual_carrier.ogrn,
                    "legal_address": assignment.actual_carrier.legal_address,
                    "address_data": _organization_address_data(assignment.actual_carrier),
                    "edo_operator": assignment.actual_carrier.edo_operator,
                    "edo_id": getattr(assignment.actual_carrier, "edo_id", ""),
                }
                if assignment and assignment.actual_carrier_id
                else None
            ),
        },
        "route": [_stop_payload(item) for item in routes],
        "cargo": {
            "name": transportation.cargo_name,
            "description": transportation.cargo_description,
            "weight_kg": _value(transportation.weight_kg),
            "volume_m3": _value(transportation.volume_m3),
            "package_count": transportation.package_count,
            "pallet_count": transportation.pallet_count,
            "package_type": str(transportation.package_type or ""),
            "temperature_regime": transportation.temperature_regime,
            "vehicle_requirements": transportation.vehicle_requirements,
            "special_requirements": transportation.special_requirements,
        },
        "vehicle": {
            "driver": assignment.driver.full_name if assignment and assignment.driver_id else "",
            "driver_phone": assignment.driver.phone if assignment and assignment.driver_id else "",
            "driver_tax_id": assignment.driver.tax_id if assignment and assignment.driver_id else "",
            "driver_passport": (
                {
                    "series": assignment.driver.current_passport.series,
                    "number": assignment.driver.current_passport.number,
                    "issued_by": assignment.driver.current_passport.issued_by,
                    "issue_date": _value(assignment.driver.current_passport.issue_date),
                }
                if assignment and assignment.driver_id and assignment.driver.current_passport
                else None
            ),
            "driver_license": (
                {
                    "number": assignment.driver.current_license.number,
                    "categories": assignment.driver.current_license.categories,
                    "issue_date": _value(assignment.driver.current_license.issue_date),
                    "expiry_date": _value(assignment.driver.current_license.expiry_date),
                }
                if assignment and assignment.driver_id and assignment.driver.current_license
                else None
            ),
            "vehicle": assignment.vehicle.registration_number if assignment and assignment.vehicle_id else "",
            "vehicle_make": (
                " ".join(part for part in (assignment.vehicle.make, assignment.vehicle.model) if part)
                if assignment and assignment.vehicle_id
                else ""
            ),
            "vehicle_vin": assignment.vehicle.vin if assignment and assignment.vehicle_id else "",
            "vehicle_capacity_kg": (
                _value(assignment.vehicle.capacity_kg)
                if assignment and assignment.vehicle_id
                else ""
            ),
            "trailer": (
                assignment.trailer.registration_number
                if assignment and assignment.trailer_id
                else (assignment.trailer_registration_number if assignment else "")
            ),
        },
        "finance": {
            "customer_amount": _value(transportation.customer_amount),
            "customer_vat": _value(transportation.customer_vat_amount),
            "executor_amount": _value(transportation.executor_amount),
            "executor_vat": _value(transportation.executor_vat_amount),
            "revenue": _value(transportation.revenue),
            "cost": _value(transportation.cost),
            "margin": _value(transportation.margin),
            "vat_payable": _value(transportation.vat_payable),
            "receivable": _value(transportation.receivable_balance),
            "payable": _value(transportation.payable_balance),
            "customer_due_date": _value(transportation.customer_payment_due_date),
            "executor_due_date": _value(transportation.executor_payment_due_date),
            "customer_vat_rate": (
                _value(transportation.customer_vat_rate.rate)
                if transportation.customer_vat_rate_id
                else ""
            ),
            "executor_vat_rate": (
                _value(transportation.executor_vat_rate.rate)
                if transportation.executor_vat_rate_id
                else ""
            ),
            "customer_payment_term_days": transportation.customer_payment_term_days,
            "executor_payment_term_days": transportation.executor_payment_term_days,
        },
    }
    return payload


def _append_value(parent, key, value):
    if value is None:
        return
    if isinstance(value, dict):
        node = SubElement(parent, key)
        for child_key, child_value in value.items():
            _append_value(node, child_key, child_value)
    elif isinstance(value, list):
        node = SubElement(parent, key)
        for item in value:
            item_node = SubElement(node, "item")
            if isinstance(item, dict):
                for child_key, child_value in item.items():
                    _append_value(item_node, child_key, child_value)
            else:
                item_node.text = str(_value(item))
    else:
        node = SubElement(parent, key)
        node.text = str(_value(value))


def payload_to_xml(payload):
    root = Element("crm-epd", {"version": "1", "format": "canonical-draft"})
    for key, value in payload.items():
        _append_value(root, key, value)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(
        root, encoding="unicode"
    )


def _split_name(value):
    parts = [part for part in (value or "").split() if part]
    return {
        "LastName": parts[0] if parts else "",
        "FirstName": parts[1] if len(parts) > 1 else "",
        "MiddleName": " ".join(parts[2:]) if len(parts) > 2 else "",
    }


def _kontur_date(value):
    return value.strftime("%d.%m.%Y") if value else ""


def _kontur_datetime(value):
    if not value:
        return ""
    return localtime(value).isoformat(timespec="seconds")


def _org_type(organization):
    kind = getattr(organization, "kind", "")
    return {"legal_entity": "2", "entrepreneur": "1", "individual": "3"}.get(
        kind, "2"
    )


def _organization_address_data(organization):
    return {
        key.removeprefix("legal_address_"): getattr(organization, key, "")
        for key in (
            "legal_address_fias_id", "legal_address_postal_code",
            "legal_address_region_code", "legal_address_region",
            "legal_address_area", "legal_address_city",
            "legal_address_settlement", "legal_address_street",
            "legal_address_house", "legal_address_block", "legal_address_flat",
        )
        if getattr(organization, key, "")
    }


def _organization_details(parent, tag, organization):
    details = SubElement(parent, tag)
    attrs = {
        "OrgName": organization.name,
        "Inn": organization.tax_id,
        "Kpp": organization.kpp,
        "Ogrn": organization.ogrn,
        "OrgType": _org_type(organization),
    }
    fns_id = getattr(organization, "edo_id", "")
    if fns_id:
        attrs["FnsParticipantId"] = fns_id
    organization_details = SubElement(details, "OrganizationDetails")
    for key, value in attrs.items():
        if value:
            organization_details.set(key, str(value))
    phones = [organization.phone] if organization.phone else []
    if phones:
        phones_node = SubElement(organization_details, "Phones")
        for phone in phones:
            SubElement(phones_node, "Phone").text = phone
    if organization.legal_address:
        address = SubElement(organization_details, "Address")
        address_attrs = {
            "Region": getattr(organization, "legal_address_region_code", ""),
            "ZipCode": getattr(organization, "legal_address_postal_code", ""),
            "Territory": getattr(organization, "legal_address_area", ""),
            "City": getattr(organization, "legal_address_city", "")
            or getattr(organization, "legal_address_settlement", ""),
            "Street": getattr(organization, "legal_address_street", ""),
            "Building": getattr(organization, "legal_address_house", ""),
        }
        # Keep legacy/manual addresses available when no structured DaData
        # parts exist. RussianAddress accepts the compact representation.
        if not any(address_attrs.values()):
            address_attrs["City"] = organization.legal_address
        SubElement(
            address,
            "RussianAddress",
            {key: str(value) for key, value in address_attrs.items() if value},
        )
    return details


def _append_address(parent, stop):
    address = SubElement(parent, "Address")
    russian = SubElement(address, "Address")
    fias_id = getattr(stop, "address_fias_id", "")
    if fias_id:
        # Kontur's UserDataXsd uses GarAddress for route points.  The FIAS
        # identifier is authoritative; municipal/locality nodes are optional
        # context and are emitted when DaData supplied them.
        gar = SubElement(
            russian,
            "GarAddress",
            {
                key: str(value)
                for key, value in {
                    "AddressCode": fias_id,
                    "Region": getattr(stop, "address_region_code", ""),
                }.items()
                if value
            },
        )
        area = getattr(stop, "address_area", "")
        if area:
            SubElement(gar, "MunicipalTerritory", Type="1", NameOrNumber=area)
        locality = (
            getattr(stop, "address_city", "")
            or getattr(stop, "address_settlement", "")
            or stop.city
        )
        if locality:
            SubElement(gar, "UrbanSettlement", Type="1", NameOrNumber=locality)
        return

    # Manual addresses remain valid UserDataXml through RussianAddress.
    attrs = {
        "Region": getattr(stop, "address_region_code", ""),
        "ZipCode": getattr(stop, "address_postal_code", ""),
        "City": getattr(stop, "address_city", "") or stop.city,
        "Street": getattr(stop, "address_street", "") or stop.address,
        "Building": getattr(stop, "address_house", ""),
    }
    SubElement(russian, "RussianAddress", {k: str(v) for k, v in attrs.items() if v})


def payload_to_kontur_userdata(transportation):
    """Serialize an EZZ sender title to Kontur/Diadoc UserDataXml.

    This is the simplified XML accepted by Diadoc's GenerateTitleXml method;
    the operator then returns the final ``Файл ... ON_ZAKZVGO`` document.
    """

    client = _party(transportation, TransportationParty.Role.CLIENT)
    shipper = _party(transportation, TransportationParty.Role.SHIPPER) or client
    link = transportation.active_execution_link()
    assignment = transportation.active_vehicle_assignment()
    carrier = (
        assignment.actual_carrier
        if assignment and assignment.actual_carrier_id
        else (link.contractor_party.organization if link else None)
    )
    root = Element(
        "LogisticsOrderRequestSenderTitle",
        {
            "Number": transportation.number or f"CRM-{transportation.pk}",
            "Date": _kontur_date(transportation.document_date),
            "Function": "Application",
            "DocumentCreator": (
                f"{transportation.owner_company.name}, ИНН "
                f"{transportation.owner_company.tax_id}, КПП {transportation.owner_company.kpp}"
            ),
        },
    )
    contract = transportation.customer_contract or (link.contract if link else None)
    if contract:
        contract_node = SubElement(
            root,
            "TransportContract",
            {
                "DocumentName": contract.get_kind_display(),
                "DocumentNumber": contract.number,
                "DocumentDate": _kontur_date(contract.contract_date),
            },
        )
        parties = SubElement(contract_node, "PartiesRequisites")
        counterparty = contract.counterparty
        if counterparty:
            SubElement(
                parties,
                "PartiesRequisite",
                {"Inn": counterparty.tax_id, "OrgName": counterparty.name},
            )

    order = SubElement(
        root,
        "OrderRequest",
        {"SanitaryRequirements": "Отсутствует", "FoodRequirements": "Отсутствует"},
    )
    if shipper:
        _organization_details(order, "Shipper", shipper.organization)
    if carrier:
        _organization_details(order, "Carrier", carrier)

    stops = list(transportation.stops.all())
    pickups = [item for item in stops if item.kind == TransportationStop.Kind.PICKUP]
    deliveries = [item for item in stops if item.kind == TransportationStop.Kind.DELIVERY]
    if pickups:
        pickup = pickups[0]
        supply = SubElement(
            order,
            "SupplyPoint",
            {
                "SupplyDateTimeZone": "Specified",
                "DateTime": _kontur_datetime(pickup.planned_from),
                "MaxSupplyingTimeTimeZone": "Specified",
            },
        )
        _append_address(supply, pickup)

    points = SubElement(order, "AddressPoints")
    for stop in stops:
        attrs = {
            "PointOrder": str(stop.sequence),
            "OperationDateTimeZone": "Specified",
            "OperationDate": _kontur_datetime(stop.planned_from),
            "CoordinationTime": "1",
            "OperationAtPoint": (
                "Loading"
                if stop.kind == TransportationStop.Kind.PICKUP
                else "Unloading"
            ),
        }
        point = SubElement(points, "AddressPoint", attrs)
        _append_address(point, stop)

    cargo_attrs = {
        "Name": transportation.cargo_name,
        "Condition": "Стандартные условия",
        "PlaceCount": str(transportation.package_count or 0),
        "WeighingMethod": "01",
        "Volume": str(transportation.volume_m3 or 0),
        "DistributionAlongPlatform": "NotPossible",
        "Divisibility": "Divisible",
    }
    cargoes = SubElement(order, "Cargoes")
    cargo = SubElement(cargoes, "Cargo", cargo_attrs)
    SubElement(cargo, "PlacesWeight", Gross=str(transportation.weight_kg or 0))
    delivery_points = SubElement(cargo, "DeliveryPoints")
    for pickup in pickups:
        for delivery in deliveries:
            SubElement(
                delivery_points,
                "DeliveryPoint",
                {
                    "LoadingPoint": str(pickup.sequence),
                    "UnloadingPoint": str(delivery.sequence),
                    "PlaceCount": str(transportation.package_count or 0),
                },
            )

    vehicle = assignment.vehicle if assignment and assignment.vehicle_id else None
    vehicle_attrs = {
        "Type": transportation.vehicle_requirements
        or (vehicle.get_kind_display() if vehicle else ""),
        "WeightCapacity": (
            str((vehicle.capacity_kg / 1000) if vehicle and vehicle.capacity_kg else "")
        ),
        "VolumeCapacity": str(vehicle.volume_m3 if vehicle else ""),
    }
    SubElement(order, "VehicleRequirements", vehicle_attrs)

    signer_attrs = {}
    owner_edo_id = getattr(transportation.owner_company, "edo_id", "")
    if owner_edo_id:
        signer_attrs["BoxId"] = str(owner_edo_id)
    signers = SubElement(root, "Signers", signer_attrs)
    signer = SubElement(signers, "Signer", {"SignerPowersConfirmationMethod": "5"})
    fio = _split_name(transportation.owner_company.director_name)
    SubElement(signer, "Fio", fio)
    SubElement(signer, "Position", {"PositionSource": "Manual"}).text = "Руководитель"
    return '<?xml version="1.0" encoding="utf-8"?>\n' + tostring(
        root, encoding="unicode"
    )


def _russian_fio(parent, value):
    if not value:
        return
    fio = _split_name(value)
    attrs = {
        "Фамилия": fio["LastName"],
        "Имя": fio["FirstName"],
        "Отчество": fio["MiddleName"],
    }
    SubElement(parent, "ФИО", {key: value for key, value in attrs.items() if value})


def _russian_address(parent, obj, prefix=""):
    """Append the Russian FIAS/address branch used by ON_ZAKZVGO."""

    def value(name):
        return getattr(obj, f"{prefix}{name}", "") or ""

    address = SubElement(parent, "Адрес")
    fias_id = value("fias_id")
    if fias_id:
        attrs = {"ИдНом": str(fias_id)}
        if value("postal_code"):
            attrs["Индекс"] = str(value("postal_code"))
        fias = SubElement(address, "АдрФИАС", attrs)
        if value("region_code"):
            SubElement(fias, "Регион").text = str(value("region_code"))
        if value("area"):
            SubElement(
                fias,
                "МуниципРайон",
                {"ВидКод": "1", "Наим": str(value("area"))},
            )
        locality = value("city") or value("settlement")
        if locality:
            SubElement(
                fias,
                "НаселенПункт",
                {"Вид": "г.", "Наим": str(locality)},
            )
        if value("street"):
            SubElement(
                fias,
                "ЭлУлДорСети",
                {"Тип": "ул.", "Наим": str(value("street"))},
            )
        if value("house"):
            SubElement(
                fias,
                "Здание",
                {"Тип": "д", "Номер": str(value("house"))},
            )
        if value("block"):
            SubElement(
                fias,
                "Здание",
                {"Тип": "корпус", "Номер": str(value("block"))},
            )
        return address

    attrs = {
        "Индекс": value("postal_code"),
        "КодРегион": value("region_code"),
        "Город": value("city") or value("settlement"),
        "Улица": value("street") or value("address") or getattr(obj, "legal_address", ""),
        "Дом": value("house"),
    }
    SubElement(address, "АдрРФ", {key: str(item) for key, item in attrs.items() if item})
    return address


def _russian_org_party(parent, tag, organization):
    party = SubElement(parent, tag)
    identifiers = SubElement(party, "ИдСв")
    kind = getattr(organization, "kind", "")
    if kind == "entrepreneur":
        individual = SubElement(
            identifiers,
            "СвИП",
            {
                "ИННФЛ": str(organization.tax_id or ""),
                "ОГРНИП": str(organization.ogrn or ""),
            },
        )
        _russian_fio(individual, organization.director_name)
    else:
        attrs = {
            "НаимОрг": organization.name,
            "ИННЮЛ": organization.tax_id,
            "КПП": organization.kpp,
        }
        SubElement(
            identifiers,
            "СвЮЛУч",
            {key: str(value) for key, value in attrs.items() if value},
        )
    _russian_address(party, organization, "legal_address_")
    if organization.phone:
        contact = SubElement(party, "Конт")
        SubElement(contact, "Тлф").text = organization.phone
    return party


def _russian_inn(parent, organization):
    if not organization or not organization.tax_id:
        return
    SubElement(
        parent,
        "ИННФЛ" if getattr(organization, "kind", "") == "entrepreneur" else "ИННЮЛ",
    ).text = organization.tax_id


def _russian_xml_decimal(value):
    if value in (None, ""):
        return ""
    return format(Decimal(value), "f").rstrip("0").rstrip(".") or "0"


def _russian_operation_datetime(value):
    return _kontur_datetime(value) if value else ""


def _russian_operation_time(value):
    if not value:
        return ""
    rendered = localtime(value).isoformat(timespec="seconds")
    return rendered.split("T", 1)[1]


def payload_to_kontur_russian_xml(transportation):
    """Build a Russian ON_ZAKZVGO-shaped file for local preview/download.

    Kontur normally creates this exact Russian title from UserDataXml through
    ``GenerateTitleXml``.  The local serializer is intentionally used only
    when API credentials are not configured, so the CRM never presents its
    English UserDataXml as the final operator document.
    """

    client = _party(transportation, TransportationParty.Role.CLIENT)
    shipper = _party(transportation, TransportationParty.Role.SHIPPER) or client
    link = transportation.active_execution_link()
    assignment = transportation.active_vehicle_assignment()
    carrier = (
        assignment.actual_carrier
        if assignment and assignment.actual_carrier_id
        else (link.contractor_party.organization if link else None)
    )
    owner = transportation.owner_company
    owner_box = getattr(owner, "edo_id", "") or owner.tax_id or f"CRM{transportation.pk}"
    carrier_box = (
        getattr(carrier, "edo_id", "") or carrier.tax_id if carrier else "CRM"
    )
    now = timezone.localtime(timezone.now())
    file_id = (
        f"ON_ZAKZVGO_{carrier_box}_{owner_box}_0_"
        f"{now:%Y%m%d}_{uuid4().hex}"
    )
    root = Element(
        "Файл",
        {"ИдФайл": file_id, "ВерсПрог": "Diadoc 1.0", "ВерсФорм": "5.01"},
    )
    creator = owner.name
    if owner.tax_id:
        creator += f", ИНН {owner.tax_id}"
    if owner.kpp:
        creator += f", КПП {owner.kpp}"
    document = SubElement(
        root,
        "Документ",
        {
            "КНД": "1110361",
            "ДатИнфГО": now.strftime("%d.%m.%Y"),
            "ВрИнфГО": now.strftime("%H:%M:%S"),
            "НаимЭкСубСост": creator,
            "Функция": "Заявка",
        },
    )

    contract = transportation.customer_contract or (link.contract if link else None)
    if contract:
        contract_node = SubElement(
            document,
            "ДогОргПрвз",
            {
                "НаимДок": contract.get_kind_display(),
                "НомерДок": contract.number,
                "ДатаДок": _kontur_date(contract.contract_date),
            },
        )
        _russian_inn(SubElement(contract_node, "ИдРекСост"), owner)
        if carrier:
            _russian_inn(SubElement(contract_node, "ИдРекСост"), carrier)

    content = SubElement(
        document,
        "СодИнфГО",
        {
            "СодОпер": "Предоставление заказа и заявки на перевозку груза автомобильным транспортом",
            "НомЗак": transportation.number or f"CRM-{transportation.pk}",
            "ДатаЗак": _kontur_date(transportation.document_date),
            "УкНормПрвз": "Отсутствует",
            "ПрвзПищПрод": "Отсутствует",
        },
    )
    if shipper:
        _russian_org_party(content, "СвГО", shipper.organization)
    if carrier:
        _russian_org_party(content, "СвПрв", carrier)

    stops = list(transportation.stops.all())
    pickups = [stop for stop in stops if stop.kind == TransportationStop.Kind.PICKUP]
    deliveries = [stop for stop in stops if stop.kind == TransportationStop.Kind.DELIVERY]
    if pickups:
        pickup = pickups[0]
        pickup_attrs = {}
        if pickup.planned_from:
            pickup_attrs["ДатВрПод"] = _russian_operation_datetime(pickup.planned_from)
            pickup_attrs["НалКоорТочВрПод"] = "1"
        if pickup.planned_to:
            pickup_attrs["ПредВрПод"] = _russian_operation_time(pickup.planned_to)
            pickup_attrs["НалКоорТочПредВрПод"] = "1"
        supply = SubElement(content, "ПунктПод", pickup_attrs)
        supply_address = SubElement(supply, "АдрПунктПод")
        _russian_address(supply_address, pickup, "address_")

    for stop in stops:
        operation = {
            TransportationStop.Kind.PICKUP: "Погрузка",
            TransportationStop.Kind.DELIVERY: "Выгрузка",
        }.get(stop.kind, "Промежуточная точка")
        attrs = {
            "Опер": operation,
            "ПорНомПункт": str(stop.sequence),
        }
        if stop.planned_from:
            attrs["ДатВрОпер"] = _russian_operation_datetime(stop.planned_from)
            attrs["НалКоорТочВрОпер"] = "1"
        if stop.planned_to:
            attrs["ПредВрОпер"] = _russian_operation_time(stop.planned_to)
            attrs["НалКоорТочПредВрОпер"] = "1"
        point = SubElement(content, "АдрПункт", attrs)
        point_address = SubElement(point, "АдресПункт")
        _russian_address(point_address, stop, "address_")
        if stop.organization:
            SubElement(
                point,
                "ОргВладИнфр",
                {
                    "НаимВладИнфр": stop.organization.name,
                    "ИННВладИнфр": stop.organization.tax_id,
                },
            )

    cargo_attrs = {
        "НаимГруз": transportation.cargo_name,
        "СостГруз": "Новый",
        "Объем": _russian_xml_decimal(transportation.volume_m3),
        "КолГрМест": str(transportation.package_count or 0),
        "МетОпрМасс": "01",
        "РаспрГр": "0",
        "ДелГр": "1",
    }
    if transportation.package_type:
        cargo_attrs["ВидТар"] = str(transportation.package_type)
    cargo = SubElement(content, "ОпГруз", {key: value for key, value in cargo_attrs.items() if value})
    SubElement(cargo, "МасГруз", {"МасБрутЗнач": _russian_xml_decimal(transportation.weight_kg)})
    if pickups and deliveries:
        SubElement(
            cargo,
            "Пункт",
            {
                "Погр": str(pickups[0].sequence),
                "Выгр": str(deliveries[-1].sequence),
                "КолГрМест": str(transportation.package_count or 0),
            },
        )

    vehicle_attrs = {
        "Тип": transportation.vehicle_requirements or "Грузовой",
    }
    vehicle = assignment.vehicle if assignment and assignment.vehicle_id else None
    if vehicle and vehicle.capacity_kg:
        vehicle_attrs["Грузопод"] = _russian_xml_decimal(vehicle.capacity_kg / 1000)
    if transportation.volume_m3:
        vehicle_attrs["Вместим"] = _russian_xml_decimal(transportation.volume_m3)
    SubElement(content, "ПарТСПрвз", vehicle_attrs)

    signature_attrs = {"СпосПодтПолном": ""}
    signature = SubElement(document, "ПодпИнфГО", signature_attrs)
    _russian_fio(signature, owner.director_name)
    raw = tostring(root, encoding="cp1251", xml_declaration=True).decode("cp1251")
    raw = raw.replace("<?xml version='1.0' encoding='cp1251'?>", "<?xml version=\"1.0\" encoding=\"windows-1251\"?>")
    return raw


def document_title_statuses(kind):
    if kind == TransportationElectronicDocument.Kind.ETRN:
        return {str(number): "draft" for number in range(1, 5)}
    return {"1": "draft"}


def prepare_documents(transportation, user=None):
    """Create/update all internal EPD drafts for a transportation."""

    # ЭЗЗ можно отправить до назначения фактического перевозчика, водителя и
    # автомобиля. Остальные документы готовим по мере появления этих данных;
    # в частности, ЭТрН не создаём, пока обязательная машина не подтверждена.
    errors = epd_validation_errors(
        transportation, kind=TransportationElectronicDocument.Kind.EZZ
    )
    if errors:
        raise ValidationError(errors)

    link = transportation.active_execution_link()
    kinds = [TransportationElectronicDocument.Kind.EZZ]
    if link and link.contractor_role == TransportationLink.ContractorRole.FORWARDER:
        kinds.extend(
            [
                TransportationElectronicDocument.Kind.EPE,
                TransportationElectronicDocument.Kind.EER,
            ]
        )
    if not epd_validation_errors(
        transportation, kind=TransportationElectronicDocument.Kind.ETRN
    ):
        kinds.append(TransportationElectronicDocument.Kind.ETRN)
    deliveries = list(
        transportation.stops.filter(kind=TransportationStop.Kind.DELIVERY).order_by("sequence")
    )
    prepared = []
    for kind in kinds:
        targets = deliveries if kind == TransportationElectronicDocument.Kind.ETRN else [None]
        for stop in targets:
            payload = build_epd_payload(transportation, kind, stop=stop)
            document, _ = TransportationElectronicDocument.objects.get_or_create(
                transportation=transportation,
                kind=kind,
                stop=stop,
                defaults={
                    "provider": TransportationElectronicDocument.Provider.INTERNAL,
                    "status": TransportationElectronicDocument.Status.READY,
                    "created_by": user,
                },
            )
            if document.status in {
                TransportationElectronicDocument.Status.DRAFT,
                TransportationElectronicDocument.Status.READY,
                TransportationElectronicDocument.Status.ERROR,
            }:
                document.status = TransportationElectronicDocument.Status.READY
                document.provider = TransportationElectronicDocument.Provider.INTERNAL
                document.payload = payload
                document.raw_xml = payload_to_xml(payload)
                document.operator_xml = (
                    payload_to_kontur_userdata(transportation)
                    if kind == TransportationElectronicDocument.Kind.EZZ
                    else ""
                )
                # Если карточка рейса изменилась, старый ответ Контур больше
                # не соответствует данным и должен быть сгенерирован заново.
                document.generated_xml = ""
                document.title_statuses = document_title_statuses(kind)
                document.last_error = ""
                document.created_by = user or document.created_by
                document.save(
                    update_fields=[
                        "status", "provider", "payload", "raw_xml", "title_statuses",
                        "operator_xml", "generated_xml", "last_error", "created_by",
                        "updated_at",
                    ]
                )
            prepared.append(document)
    return prepared
