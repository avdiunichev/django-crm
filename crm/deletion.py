from dataclasses import dataclass

from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.db.models import Q

from .models import (
    Carrier,
    CompanyProfile,
    Contract,
    Customer,
    Driver,
    Organization,
    Shipment,
    TransportOrder,
    Transportation,
    TransportationIncident,
    VehicleCombination,
    Vehicle,
)


@dataclass(frozen=True)
class DeletionExample:
    label: str
    url: str = ""


@dataclass(frozen=True)
class DeletionDependency:
    label: str
    count: int
    examples: tuple[DeletionExample, ...]


def deletion_example(item):
    getter = getattr(item, "get_absolute_url", None)
    if callable(getter):
        return DeletionExample(label=str(item), url=str(getter()))

    for parent_name in ("transportation", "shipment"):
        try:
            parent = getattr(item, parent_name)
        except (AttributeError, ObjectDoesNotExist):
            continue
        parent_getter = getattr(parent, "get_absolute_url", None)
        if callable(parent_getter):
            return DeletionExample(label=str(item), url=str(parent_getter()))

    return DeletionExample(label=str(item))


def _append_queryset(dependencies, label, queryset):
    queryset = queryset.distinct()
    count = queryset.count()
    if count:
        dependencies.append(
            DeletionDependency(
                label=label,
                count=count,
                examples=tuple(
                    deletion_example(item) for item in queryset.order_by("pk")[:3]
                ),
            )
        )


def _append_state(dependencies, label, value, url=""):
    dependencies.append(
        DeletionDependency(
            label=label,
            count=1,
            examples=(DeletionExample(label=str(value), url=str(url)),),
        )
    )


def _shipment_documents(shipment, dependencies):
    _append_queryset(dependencies, "Платежи", shipment.payments.all())
    _append_queryset(dependencies, "Первичные документы", shipment.documents.all())
    if hasattr(shipment, "forwarding_order"):
        _append_state(
            dependencies,
            "Экспедиторское поручение",
            shipment.forwarding_order,
        )


def _transportation_documents(transportation, dependencies):
    _append_queryset(dependencies, "Платежи", transportation.payments.all())
    if transportation.posting_status != Transportation.PostingStatus.DRAFT:
        _append_state(
            dependencies,
            "Состояние заявки / рейса",
            transportation.get_posting_status_display(),
            transportation.get_absolute_url(),
        )
    _append_queryset(
        dependencies,
        "Поручения и заявки исполнителям",
        transportation.instructions.all(),
    )
    _append_queryset(
        dependencies,
        "Движения доходов и расходов",
        transportation.charges.all(),
    )
    _append_queryset(
        dependencies,
        "Движения взаиморасчётов",
        transportation.settlement_movements.all(),
    )
    _append_queryset(
        dependencies,
        "Штрафы и претензии",
        transportation.incidents.all(),
    )


def deletion_dependencies(instance):
    dependencies = []
    if isinstance(instance, Shipment):
        _shipment_documents(instance, dependencies)
        transportation = Transportation.objects.filter(legacy_shipment=instance).first()
        if transportation:
            _transportation_documents(transportation, dependencies)
    elif isinstance(instance, Transportation):
        _transportation_documents(instance, dependencies)
        if instance.legacy_shipment_id:
            _shipment_documents(instance.legacy_shipment, dependencies)
    elif isinstance(instance, TransportOrder):
        if instance.transportation_id:
            _append_state(
                dependencies,
                "Созданный рейс",
                instance.transportation,
                instance.transportation.get_absolute_url(),
            )
    elif isinstance(instance, Organization):
        _append_queryset(
            dependencies,
            "Заказы",
            TransportOrder.objects.filter(
                Q(owner_company=instance) | Q(client=instance)
            ),
        )
        _append_queryset(
            dependencies,
            "Заявки / рейсы",
            Transportation.objects.filter(
                Q(owner_company=instance)
                | Q(stops__organization=instance)
                | Q(parties__organization=instance)
                | Q(vehicle_assignments__actual_carrier=instance)
                | Q(instructions__counterparty=instance)
                | Q(charges__owner_company=instance)
                | Q(charges__counterparty=instance)
                | Q(settlement_movements__owner_company=instance)
                | Q(settlement_movements__counterparty=instance)
                | Q(incidents__counterparty=instance)
            ),
        )
        _append_queryset(
            dependencies,
            "Заявки старого журнала",
            Shipment.objects.filter(
                Q(expeditor__organization=instance)
                | Q(customer__organization=instance)
                | Q(carrier__organization=instance)
            ),
        )
        _append_queryset(
            dependencies,
            "Договоры",
            Contract.objects.filter(
                Q(expeditor__organization=instance)
                | Q(customer__organization=instance)
                | Q(carrier__organization=instance)
            ),
        )
        _append_queryset(
            dependencies,
            "Водители перевозчика",
            Driver.objects.filter(
                Q(carrier__organization=instance)
                | Q(employments__carrier__organization=instance)
            ).distinct(),
        )
        _append_queryset(
            dependencies,
            "Транспорт перевозчика",
            Vehicle.objects.filter(carrier__organization=instance),
        )
    elif isinstance(instance, Driver):
        _append_queryset(dependencies, "Заявки", instance.shipments.all())
        _append_queryset(
            dependencies,
            "Назначения в рейсах",
            instance.transportation_assignments.all(),
        )
    elif isinstance(instance, Vehicle):
        _append_queryset(dependencies, "Заявки", instance.shipments.all())
        _append_queryset(
            dependencies,
            "Сцепки",
            VehicleCombination.objects.filter(
                Q(tractor=instance) | Q(trailer=instance)
            ),
        )
        _append_queryset(
            dependencies,
            "Назначения тягачом / автомобилем",
            instance.transportation_assignments.all(),
        )
        _append_queryset(
            dependencies,
            "Назначения прицепом",
            instance.trailer_transportation_assignments.all(),
        )
    elif isinstance(instance, VehicleCombination):
        _append_queryset(
            dependencies,
            "Назначения в рейсах",
            instance.vehicle_assignments.all(),
        )
    return dependencies


@transaction.atomic
def perform_safe_delete(instance):
    def delete_transportation(transportation):
        # Рейс, созданный назначением заказа, можно удалить, пока он остаётся
        # черновиком и не породил учётных движений. В этом случае исходный
        # заказ не удаляем: снимаем назначение и возвращаем его в работу.
        source_order = (
            TransportOrder.objects.select_for_update()
            .filter(transportation=transportation)
            .first()
        )
        if source_order:
            source_order.transportation = None
            source_order.status = TransportOrder.Status.NEW
            source_order.assigned_at = None
            source_order.assigned_by = None
            source_order.save(
                update_fields=[
                    "transportation",
                    "status",
                    "assigned_at",
                    "assigned_by",
                    "updated_at",
                ]
            )
        # Эти строки являются составными частями документа, но ссылаются на
        # его участников через PROTECT. Удаляем их до каскада самого рейса.
        transportation.vehicle_assignments.all().delete()
        transportation.execution_links.all().delete()
        transportation.delete()

    if isinstance(instance, Shipment):
        transportation = Transportation.objects.filter(legacy_shipment=instance).first()
        if transportation:
            delete_transportation(transportation)
        instance.delete()
        return
    if isinstance(instance, Transportation):
        shipment = instance.legacy_shipment if instance.legacy_shipment_id else None
        delete_transportation(instance)
        if shipment:
            shipment.delete()
        return
    if isinstance(instance, Organization):
        CompanyProfile.objects.filter(organization=instance).delete()
        Customer.objects.filter(organization=instance).delete()
        Carrier.objects.filter(organization=instance).delete()
        instance.delete()
        return
    instance.delete()
