from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.utils import timezone

from .models import (
    BankStatement,
    BankStatementLine,
    Payment,
    SettlementMovement,
    Transportation,
    TransportationInstruction,
    TransportationLink,
    TransportationNumberSequence,
    TransportationParty,
    TransportationStatusEvent,
    TransportationStop,
    TripCharge,
    Vehicle,
)


def _active_party(transportation, role):
    return transportation.parties.filter(role=role, is_active=True).select_related(
        "organization"
    ).first()


def _posting_context(transportation):
    client_party = _active_party(transportation, TransportationParty.Role.CLIENT)
    executor_link = transportation.active_execution_link()
    assignment = transportation.active_vehicle_assignment()
    return client_party, executor_link, assignment


def validate_transportation_for_posting(transportation):
    errors = {}
    client_party, executor_link, assignment = _posting_context(transportation)
    stops = list(transportation.stops.all())

    if not transportation.owner_company_id:
        errors["owner_company"] = "Выберите нашу компанию."
    if not transportation.manager_id:
        errors["manager"] = "Выберите ответственного менеджера."
    if not client_party:
        errors["client"] = "Выберите клиента."
    if transportation.customer_amount <= 0:
        errors["customer_amount"] = "Сумма клиенту должна быть больше нуля."
    if not transportation.customer_vat_rate_id:
        errors["customer_vat_rate"] = "Выберите ставку НДС клиента."
    if not transportation.cargo_name.strip():
        errors["cargo_name"] = "Укажите наименование груза."
    if not any(stop.kind == TransportationStop.Kind.PICKUP for stop in stops):
        errors["pickup_city"] = "Добавьте точку погрузки."
    if not any(stop.kind == TransportationStop.Kind.DELIVERY for stop in stops):
        errors["delivery_city"] = "Добавьте точку выгрузки."
    if (
        transportation.planned_start_date
        and transportation.planned_end_date
        and transportation.planned_end_date < transportation.planned_start_date
    ):
        errors["delivery_date"] = "Дата выгрузки не может быть раньше погрузки."

    if not executor_link:
        errors["executor"] = "Выберите исполнителя."
    else:
        if not executor_link.contract_id:
            errors["executor_contract"] = (
                "Создайте и выберите договор с исполнителем перед проведением рейса."
            )
        if transportation.executor_amount < 0:
            errors["executor_amount"] = "Сумма исполнителю не может быть отрицательной."
        if not transportation.executor_vat_rate_id:
            errors["executor_vat_rate"] = "Выберите ставку НДС исполнителя."
        if not assignment:
            errors["actual_carrier"] = "Укажите фактического перевозчика."
        else:
            executor = executor_link.contractor_party.organization
            if (
                executor_link.contractor_role
                == TransportationLink.ContractorRole.CARRIER
                and assignment.actual_carrier_id != executor.pk
            ):
                errors["actual_carrier"] = (
                    "Для прямого перевозчика исполнитель и фактический "
                    "перевозчик должны совпадать."
                )
            if not assignment.driver_id:
                errors["driver"] = "Назначьте водителя."
            if not assignment.vehicle_id:
                errors["vehicle"] = "Назначьте тягач или автомобиль."
            elif (
                assignment.vehicle.requires_trailer
                and not assignment.trailer_id
                and not assignment.trailer_registration_number
                and not assignment.vehicle.trailer_registration_number
            ):
                errors["trailer"] = "Для тягача укажите прицеп или полуприцеп."
            elif assignment.trailer_id and not assignment.vehicle.can_tow_trailer:
                errors["trailer"] = "Для этого типа автомобиля прицеп не предусмотрен."
            try:
                assignment.full_clean()
            except ValidationError as error:
                for field, messages in error.message_dict.items():
                    errors[field] = " ".join(messages)

    if errors:
        raise ValidationError(errors)
    return client_party, executor_link, assignment


def _assign_number(transportation):
    if transportation.number:
        return
    year = transportation.document_date.year
    sequence, _ = TransportationNumberSequence.objects.select_for_update().get_or_create(
        owner_company=transportation.owner_company,
        year=year,
        defaults={"last_value": 0},
    )
    sequence.last_value += 1
    sequence.save(update_fields=["last_value", "updated_at"])
    transportation.number_year = year
    transportation.number = (
        f"{transportation.document_date:%d/%m}-{sequence.last_value:04d}"
    )


def _due_base(transportation):
    if transportation.payment_due_basis == Transportation.PaymentDueBasis.DOCUMENT_DATE:
        return transportation.document_date
    return transportation.planned_end_date or transportation.document_date


def _reconciliation_blocker_message(movements, action):
    act_numbers = []
    for movement in movements.prefetch_related("reconciliation_lines__act"):
        for line in movement.reconciliation_lines.all():
            number = line.act.number or str(line.act)
            if number not in act_numbers:
                act_numbers.append(number)
    linked = f" Связанные акты: {', '.join(act_numbers[:5])}." if act_numbers else ""
    return (
        f"Нельзя {action}: движения взаиморасчётов уже используются в актах "
        f"сверки.{linked} Сначала удалите или аннулируйте связанные акты сверки."
    )


@transaction.atomic
def post_transportation(transportation, user=None):
    transportation = (
        Transportation.objects.select_for_update()
        .select_related("owner_company")
        .get(pk=transportation.pk)
    )
    client_party, executor_link, assignment = validate_transportation_for_posting(
        transportation
    )
    _assign_number(transportation)
    due_base = _due_base(transportation)
    transportation.customer_payment_due_date = due_base + timedelta(
        days=transportation.customer_payment_term_days
    )
    transportation.executor_payment_due_date = due_base + timedelta(
        days=transportation.executor_payment_term_days
    )

    executor = executor_link.contractor_party.organization
    TripCharge.objects.filter(transportation=transportation).delete()
    SettlementMovement.objects.filter(
        transportation=transportation,
        kind=SettlementMovement.Kind.ACCRUAL,
    ).delete()

    TripCharge.objects.bulk_create(
        [
            TripCharge(
                transportation=transportation,
                direction=TripCharge.Direction.REVENUE,
                owner_company=transportation.owner_company,
                counterparty=client_party.organization,
                contract=transportation.customer_contract,
                amount=transportation.customer_amount,
                amount_without_vat=transportation.customer_amount_without_vat,
                vat_amount=transportation.customer_vat_amount,
                vat_rate=transportation.customer_vat_rate,
                currency=transportation.currency,
                movement_date=transportation.document_date,
            ),
            TripCharge(
                transportation=transportation,
                direction=TripCharge.Direction.COST,
                owner_company=transportation.owner_company,
                counterparty=executor,
                contract=executor_link.contract,
                amount=transportation.executor_amount,
                amount_without_vat=transportation.executor_amount_without_vat,
                vat_amount=transportation.executor_vat_amount,
                vat_rate=transportation.executor_vat_rate,
                currency=transportation.currency,
                movement_date=transportation.document_date,
            ),
        ]
    )
    SettlementMovement.objects.bulk_create(
        [
            SettlementMovement(
                transportation=transportation,
                side=SettlementMovement.Side.RECEIVABLE,
                kind=SettlementMovement.Kind.ACCRUAL,
                owner_company=transportation.owner_company,
                counterparty=client_party.organization,
                contract=transportation.customer_contract,
                amount=transportation.customer_amount,
                currency=transportation.currency,
                movement_date=transportation.document_date,
                due_date=transportation.customer_payment_due_date,
            ),
            SettlementMovement(
                transportation=transportation,
                side=SettlementMovement.Side.PAYABLE,
                kind=SettlementMovement.Kind.ACCRUAL,
                owner_company=transportation.owner_company,
                counterparty=executor,
                contract=executor_link.contract,
                amount=transportation.executor_amount,
                currency=transportation.currency,
                movement_date=transportation.document_date,
                due_date=transportation.executor_payment_due_date,
            ),
        ]
    )

    if transportation.client_reference:
        TransportationInstruction.objects.update_or_create(
            transportation=transportation,
            kind=TransportationInstruction.Kind.CLIENT_ORDER,
            defaults={
                "number": transportation.client_reference,
                "document_date": transportation.document_date,
                "counterparty": client_party.organization,
                "contract": transportation.customer_contract,
                "status": TransportationInstruction.Status.READY,
            },
        )
    instruction_kind = (
        TransportationInstruction.Kind.CARRIER_APPLICATION
        if executor_link.contractor_role == TransportationLink.ContractorRole.CARRIER
        else TransportationInstruction.Kind.FORWARDER_INSTRUCTION
    )
    instruction_number = executor_link.instruction_number or f"{transportation.number}-1"
    TransportationInstruction.objects.update_or_create(
        transportation=transportation,
        kind=instruction_kind,
        defaults={
            "number": instruction_number,
            "document_date": transportation.document_date,
            "counterparty": executor,
            "contract": executor_link.contract,
            "status": TransportationInstruction.Status.DRAFT,
        },
    )
    if not executor_link.instruction_number:
        executor_link.instruction_number = instruction_number
        executor_link.instruction_status = "Черновик"
        executor_link.save(
            update_fields=["instruction_number", "instruction_status", "updated_at"]
        )

    old_posting_status = transportation.posting_status
    transportation.posting_status = Transportation.PostingStatus.POSTED
    transportation.posted_at = timezone.now()
    transportation.posted_by = user
    transportation.save(
        update_fields=[
            "number", "number_year", "customer_payment_due_date",
            "executor_payment_due_date", "posting_status", "posted_at",
            "posted_by", "updated_at",
        ]
    )
    TransportationStatusEvent.objects.create(
        transportation=transportation,
        old_status=old_posting_status,
        new_status=Transportation.PostingStatus.POSTED,
        changed_by=user,
        comment="Документ записан и проведён",
        source="posting",
        changes={
            "Состояние документа": {
                "old": dict(Transportation.PostingStatus.choices).get(
                    old_posting_status, old_posting_status
                ),
                "new": dict(Transportation.PostingStatus.choices).get(
                    Transportation.PostingStatus.POSTED,
                    Transportation.PostingStatus.POSTED,
                ),
            }
        },
    )
    return transportation


@transaction.atomic
def unpost_transportation(transportation, user=None):
    transportation = Transportation.objects.select_for_update().get(pk=transportation.pk)
    if transportation.settlement_movements.filter(
        kind=SettlementMovement.Kind.PAYMENT
    ).exists():
        raise ValidationError(
            "Нельзя отменить проведение: по рейсу уже зарегистрированы платежи."
        )
    accrual_movements = transportation.settlement_movements.filter(
        kind=SettlementMovement.Kind.ACCRUAL
    )
    blocked_movements = accrual_movements.filter(reconciliation_lines__isnull=False).distinct()
    if blocked_movements.exists():
        raise ValidationError(
            _reconciliation_blocker_message(
                blocked_movements,
                "отменить проведение рейса",
            )
        )
    transportation.charges.all().delete()
    accrual_movements.delete()
    transportation.instructions.filter(generated_on_posting=True).delete()
    old_status = transportation.posting_status
    transportation.posting_status = Transportation.PostingStatus.DRAFT
    transportation.posted_at = None
    transportation.posted_by = None
    transportation.save(
        update_fields=["posting_status", "posted_at", "posted_by", "updated_at"]
    )
    TransportationStatusEvent.objects.create(
        transportation=transportation,
        old_status=old_status,
        new_status=Transportation.PostingStatus.DRAFT,
        changed_by=user,
        comment="Проведение отменено",
        source="unposting",
        changes={
            "Состояние документа": {
                "old": dict(Transportation.PostingStatus.choices).get(
                    old_status, old_status
                ),
                "new": dict(Transportation.PostingStatus.choices).get(
                    Transportation.PostingStatus.DRAFT,
                    Transportation.PostingStatus.DRAFT,
                ),
            }
        },
    )
    return transportation


@transaction.atomic
def advance_transportation_status(transportation, target_status, user=None):
    """Advance a posted trip through the operational workflow.

    Editing a posted document remains blocked; this explicit action changes
    only the operational status and records the transition in the audit log.
    """

    transportation = (
        Transportation.objects.select_for_update()
        .select_related("owner_company")
        .get(pk=transportation.pk)
    )
    errors = transportation.status_transition_issues(target_status)
    if errors:
        raise ValidationError(errors)

    try:
        target_index = Transportation.WORKFLOW_STATUSES.index(target_status)
    except ValueError:
        target_index = -1
    loading_index = Transportation.WORKFLOW_STATUSES.index(Transportation.Status.LOADING)
    vehicle_index = Transportation.WORKFLOW_STATUSES.index(
        Transportation.Status.VEHICLE_CONFIRMED
    )

    if target_index >= vehicle_index:
        try:
            validate_transportation_for_posting(transportation)
        except ValidationError as error:
            raise ValidationError(
                [message for messages in error.message_dict.values() for message in messages]
                if hasattr(error, "message_dict")
                else error.messages
            ) from error
    if target_index >= loading_index and transportation.posting_status != Transportation.PostingStatus.POSTED:
        raise ValidationError(
            "Сначала проведите рейс, затем переводите его на операционные этапы."
        )
    if target_status == Transportation.Status.DOCUMENTS_RECEIVED:
        if not transportation.instructions.exists() and not transportation.electronic_documents.exists():
            raise ValidationError(
                "Нельзя подтвердить получение документов: по рейсу ещё нет поручения или ЭПД."
            )
    if target_status in {
        Transportation.Status.CUSTOMER_INVOICED,
        Transportation.Status.CLOSED,
    }:
        if not transportation.charges.filter(direction=TripCharge.Direction.REVENUE).exists():
            raise ValidationError(
                "Нельзя закрыть этап: по рейсу не сформирован доход клиента."
            )

    old_status = transportation.status
    transportation.status = target_status
    transportation.save(update_fields=["status", "updated_at"])
    TransportationStatusEvent.objects.create(
        transportation=transportation,
        old_status=old_status,
        new_status=target_status,
        changed_by=user,
        comment="Статус переведён вручную",
        source=TransportationStatusEvent.Source.MANUAL,
        changes={
            "Статус": {
                "old": dict(Transportation.Status.choices).get(old_status, old_status),
                "new": dict(Transportation.Status.choices).get(target_status, target_status),
            }
        },
    )
    return transportation


def validate_transportation_for_closing(transportation):
    """Return a list of business blockers for final trip closing."""

    errors = []
    try:
        validate_transportation_for_posting(transportation)
    except ValidationError as error:
        errors.extend(
            [message for messages in error.message_dict.values() for message in messages]
            if hasattr(error, "message_dict")
            else error.messages
        )

    if transportation.posting_status != Transportation.PostingStatus.POSTED:
        errors.append("Рейс должен быть проведён.")

    try:
        delivered_index = Transportation.WORKFLOW_STATUSES.index(
            Transportation.Status.DELIVERED
        )
        current_index = Transportation.WORKFLOW_STATUSES.index(transportation.status)
    except ValueError:
        current_index = -1
        delivered_index = 0
    if current_index < delivered_index:
        errors.append("Груз должен быть доставлен.")

    if transportation.status not in {
        Transportation.Status.CUSTOMER_INVOICED,
        Transportation.Status.CLOSED,
    }:
        errors.append("Клиентские документы должны быть выставлены.")

    if not transportation.instructions.exists() and not transportation.electronic_documents.exists():
        errors.append("По рейсу должны быть сформированы документы или ЭПД.")

    if not transportation.charges.filter(direction=TripCharge.Direction.REVENUE).exists():
        errors.append("По рейсу должен быть отражён доход клиента.")
    if not transportation.charges.filter(direction=TripCharge.Direction.COST).exists():
        errors.append("По рейсу должен быть отражён расход исполнителю.")

    if transportation.receivable_balance > 0:
        errors.append("Дебиторская задолженность должна быть закрыта.")
    if transportation.payable_balance > 0:
        errors.append("Кредиторская задолженность должна быть закрыта.")
    return errors


@transaction.atomic
def close_transportation(transportation, user=None):
    transportation = Transportation.objects.select_for_update().get(pk=transportation.pk)
    errors = validate_transportation_for_closing(transportation)
    if errors:
        raise ValidationError(errors)
    old_status = transportation.status
    transportation.status = Transportation.Status.CLOSED
    transportation.save(update_fields=["status", "updated_at"])
    TransportationStatusEvent.objects.create(
        transportation=transportation,
        old_status=old_status,
        new_status=Transportation.Status.CLOSED,
        changed_by=user,
        comment="Рейс закрыт",
        source=TransportationStatusEvent.Source.MANUAL,
        changes={
            "Статус": {
                "old": dict(Transportation.Status.choices).get(old_status, old_status),
                "new": dict(Transportation.Status.choices).get(
                    Transportation.Status.CLOSED, Transportation.Status.CLOSED
                ),
            }
        },
    )
    return transportation


@transaction.atomic
def sync_payment_movement(payment):
    SettlementMovement.objects.filter(payment=payment).delete()
    transportation = payment.transportation
    if not transportation and payment.shipment_id:
        transportation = getattr(payment.shipment, "transportation", None)
    if not transportation:
        return None
    if transportation.posting_status != Transportation.PostingStatus.POSTED:
        return None
    client_party, executor_link, _ = _posting_context(transportation)
    if payment.direction == Payment.Direction.INCOME:
        side = SettlementMovement.Side.RECEIVABLE
        counterparty = client_party.organization if client_party else None
        contract = transportation.customer_contract
    else:
        side = SettlementMovement.Side.PAYABLE
        counterparty = (
            executor_link.contractor_party.organization if executor_link else None
        )
        contract = executor_link.contract if executor_link else None
    if not counterparty:
        return None
    return SettlementMovement.objects.create(
        transportation=transportation,
        payment=payment,
        side=side,
        kind=SettlementMovement.Kind.PAYMENT,
        owner_company=transportation.owner_company,
        counterparty=counterparty,
        contract=contract,
        amount=-payment.amount,
        currency=transportation.currency,
        movement_date=payment.payment_date,
    )


def _protected_payment_message(payment, error):
    protected_objects = list(getattr(error, "protected_objects", []) or [])
    examples = []
    for protected_object in protected_objects[:3]:
        act = getattr(protected_object, "act", None)
        examples.append(str(act or protected_object))
    reference = payment.reference or f"ID {payment.pk}"
    linked = f" Связанные документы: {', '.join(examples)}." if examples else ""
    return (
        f"Нельзя отменить платёж {reference}: он уже используется в связанных "
        f"документах, например в акте сверки.{linked} Сначала удалите или "
        "аннулируйте связанный документ, затем повторите операцию."
    )


@transaction.atomic
def post_bank_statement(statement, user=None):
    """Провести групповую банковскую выписку по выбранным рейсам.

    Одна строка выписки порождает один обычный ``Payment``. Поэтому все
    существующие отчёты, остатки задолженности и аудит рейса обновляются теми
    же механизмами, что и при ручной регистрации платежа.
    """

    statement = (
        BankStatement.objects.select_for_update()
        .select_related("owner_company")
        .get(pk=statement.pk)
    )
    if statement.status != BankStatement.Status.DRAFT:
        raise ValidationError("Провести можно только банковский документ в статусе «Черновик».")
    lines = list(
        BankStatementLine.objects.select_for_update()
        .filter(statement=statement)
        .select_related("transportation")
    )
    if not lines:
        raise ValidationError("Добавьте хотя бы один рейс в банковский документ.")
    statement.full_clean()

    locked_transportations = {}
    errors = []
    for line in lines:
        if line.payment_id:
            errors.append(f"{line.transportation}: строка уже связана с платежом.")
            continue
        transportation = (
            Transportation.objects.select_for_update()
            .select_related("owner_company")
            .get(pk=line.transportation_id)
        )
        locked_transportations[line.pk] = transportation
        if transportation.posting_status != Transportation.PostingStatus.POSTED:
            errors.append(f"{transportation}: рейс не проведён.")
            continue
        if transportation.owner_company_id != statement.owner_company_id:
            errors.append(f"{transportation}: другая наша компания.")
            continue
        if transportation.currency != statement.currency:
            errors.append(
                f"{transportation}: валюта рейса {transportation.currency}, а в выписке {statement.currency}."
            )
            continue
        balance = (
            transportation.receivable_balance
            if statement.direction == BankStatement.Direction.INCOME
            else transportation.payable_balance
        )
        if line.amount <= 0:
            errors.append(f"{transportation}: сумма должна быть больше нуля.")
        elif line.amount > balance:
            errors.append(
                f"{transportation}: сумма {line.amount} превышает остаток {balance}."
            )
        if statement.direction == BankStatement.Direction.INCOME:
            if not transportation.parties.filter(
                role=TransportationParty.Role.CLIENT, is_active=True
            ).exists():
                errors.append(f"{transportation}: не указан клиент.")
        elif not transportation.active_execution_link():
            errors.append(f"{transportation}: не указан исполнитель для расхода.")

    if errors:
        raise ValidationError(errors)

    for line in lines:
        transportation = locked_transportations[line.pk]
        payment = Payment(
            transportation=transportation,
            direction=(
                Payment.Direction.INCOME
                if statement.direction == BankStatement.Direction.INCOME
                else Payment.Direction.EXPENSE
            ),
            amount=line.amount,
            payment_date=statement.statement_date,
            method=Payment.Method.BANK,
            reference=line.payment_reference or statement.reference or statement.number,
            notes=(
                f"Банковский документ {statement.number}. "
                f"{statement.notes}".strip()
            ),
            created_by=user,
        )
        payment.full_clean()
        payment.save()
        line.payment = payment
        line.save(update_fields=["payment", "updated_at"])
        TransportationStatusEvent.objects.create(
            transportation=transportation,
            old_status=transportation.status,
            new_status=transportation.status,
            changed_by=user,
            comment=f"Проведён банковский документ {statement.number}",
            source=TransportationStatusEvent.Source.PAYMENT,
            changes={
                "Платёж": {
                    "old": "",
                    "new": f"{line.amount} {statement.currency}",
                }
            },
        )

    statement.status = BankStatement.Status.POSTED
    statement.posted_by = user
    statement.posted_at = timezone.now()
    statement.save(update_fields=["status", "posted_by", "posted_at", "updated_at"])
    return statement


@transaction.atomic
def unpost_bank_statement(statement, user=None):
    """Отменить проведение выписки и вернуть её строки в черновик."""

    statement = BankStatement.objects.select_for_update().get(pk=statement.pk)
    if statement.status != BankStatement.Status.POSTED:
        raise ValidationError("Отменить проведение можно только у проведённой выписки.")
    lines = list(
        BankStatementLine.objects.select_for_update()
        .filter(statement=statement)
        .select_related("transportation")
    )
    for line in lines:
        if line.payment_id:
            payment = line.payment
            TransportationStatusEvent.objects.create(
                transportation=line.transportation,
                old_status=line.transportation.status,
                new_status=line.transportation.status,
                changed_by=user,
                comment=f"Проведение банковского документа {statement.number} отменено",
                source=TransportationStatusEvent.Source.PAYMENT,
                changes={
                    "Платёж": {
                        "old": f"{payment.amount} {statement.currency}",
                        "new": "Проведение отменено",
                    }
                },
            )
            try:
                payment.delete()
            except ProtectedError as error:
                raise ValidationError(_protected_payment_message(payment, error)) from error
    statement.status = BankStatement.Status.DRAFT
    statement.posted_by = None
    statement.posted_at = None
    statement.save(update_fields=["status", "posted_by", "posted_at", "updated_at"])
    return statement


@transaction.atomic
def delete_bank_statement(statement, user=None):
    """Удалить выписку вместе с созданными по ней платежами."""

    statement = BankStatement.objects.select_for_update().get(pk=statement.pk)
    lines = list(
        BankStatementLine.objects.select_for_update()
        .filter(statement=statement)
        .select_related("transportation")
    )
    for line in lines:
        if line.payment_id:
            payment = line.payment
            TransportationStatusEvent.objects.create(
                transportation=line.transportation,
                old_status=line.transportation.status,
                new_status=line.transportation.status,
                changed_by=user,
                comment=f"Банковский документ {statement.number} удалён",
                source=TransportationStatusEvent.Source.PAYMENT,
                changes={
                    "Платёж": {
                        "old": f"{payment.amount} {statement.currency}",
                        "new": "Документ удалён",
                    }
                },
            )
            try:
                payment.delete()
            except ProtectedError as error:
                raise ValidationError(_protected_payment_message(payment, error)) from error
    statement.delete()
