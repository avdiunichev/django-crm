from decimal import Decimal
from pathlib import Path
import re
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import (
    FileExtensionValidator,
    MaxValueValidator,
    MinValueValidator,
    RegexValidator,
)
from django.db import models, transaction
from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone


ORDER_PAYMENT_FORM_CHOICES = (
    ("bank_vat_0", "НДС 0%"),
    ("bank_vat_5", "НДС 5%"),
    ("bank_vat_7", "НДС 7%"),
    ("bank_vat_10", "НДС 10%"),
    ("bank_vat_18", "НДС 18%"),
    ("bank_vat_20", "НДС 20%"),
    ("bank_vat_22", "НДС 22%"),
    ("bank_not_taxable", "НДС не облагается"),
    ("cash", "Наличные"),
)


class TimestampedModel(models.Model):
    created_at = models.DateTimeField("Создано", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        abstract = True


class UserProfile(TimestampedModel):
    class Role(models.TextChoices):
        ADMIN = "admin", "Администратор"
        DIRECTOR = "director", "Руководитель"
        LOGISTICIAN = "logistician", "Логист"
        ACCOUNTANT = "accountant", "Бухгалтер"
        MANAGER = "manager", "Менеджер"
        DRIVER = "driver", "Водитель / внешний пользователь"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name="Пользователь",
        related_name="crm_profile",
        on_delete=models.CASCADE,
    )
    role = models.CharField(
        "Роль",
        max_length=20,
        choices=Role.choices,
        default=Role.MANAGER,
    )
    can_see_all_records = models.BooleanField("Видит все записи", default=True)

    class Meta:
        verbose_name = "профиль пользователя CRM"
        verbose_name_plural = "профили пользователей CRM"

    def __str__(self):
        return f"{self.user} · {self.get_role_display()}"

    @property
    def is_admin_role(self):
        return self.role == self.Role.ADMIN

    @property
    def can_access_finance(self):
        return self.role in {
            self.Role.ADMIN,
            self.Role.DIRECTOR,
            self.Role.ACCOUNTANT,
        }

    @property
    def can_close_documents(self):
        return self.role in {self.Role.ADMIN, self.Role.DIRECTOR, self.Role.ACCOUNTANT}

    @property
    def can_delete_records(self):
        return self.role in {self.Role.ADMIN, self.Role.DIRECTOR}


class OrganizationGroup(TimestampedModel):
    name = models.CharField("Наименование", max_length=150)
    parent = models.ForeignKey(
        "self",
        verbose_name="Родительская группа",
        related_name="children",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    is_active = models.BooleanField("Активна", default=True)

    class Meta:
        verbose_name = "группа контрагентов"
        verbose_name_plural = "группы контрагентов"
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                fields=("parent", "name"), name="unique_organization_group_name"
            )
        ]

    def __str__(self):
        if self.parent_id:
            return f"{self.parent} / {self.name}"
        return self.name


class Organization(TimestampedModel):
    class Kind(models.TextChoices):
        LEGAL_ENTITY = "legal_entity", "Юридическое лицо"
        ENTREPRENEUR = "entrepreneur", "Индивидуальный предприниматель"
        INDIVIDUAL = "individual", "Физическое лицо"

    class VerificationStatus(models.TextChoices):
        NOT_CHECKED = "not_checked", "Не проверена"
        VERIFIED = "verified", "Проверена"
        WARNING = "warning", "Требует проверки"

    class FNSStatus(models.TextChoices):
        UNKNOWN = "unknown", "Не проверен"
        ACTIVE = "active", "Действует"
        LIQUIDATED = "liquidated", "Ликвидировано"
        LIQUIDATING = "liquidating", "В процессе ликвидации"
        REORGANIZING = "reorganizing", "В процессе реорганизации"
        BANKRUPT = "bankrupt", "Банкротство"

    class OriginalsHandling(models.TextChoices):
        EDO = "edo", "Только ЭДО"
        PAPER = "paper", "Бумажные оригиналы"
        BOTH = "both", "ЭДО и бумажные оригиналы"

    kind = models.CharField(
        "Вид контрагента",
        max_length=20,
        choices=Kind.choices,
        default=Kind.LEGAL_ENTITY,
    )
    name = models.CharField("Наименование для документов", max_length=255)
    short_name = models.CharField("Наименование в программе", max_length=150, blank=True)
    group = models.ForeignKey(
        OrganizationGroup,
        verbose_name="В группе",
        related_name="organizations",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    registration_country = models.CharField(
        "Страна регистрации", max_length=100, default="РОССИЯ"
    )
    tax_id = models.CharField("ИНН", max_length=20, blank=True, db_index=True)
    kpp = models.CharField("КПП", max_length=20, blank=True)
    ogrn = models.CharField("ОГРН / ОГРНИП", max_length=30, blank=True)
    registration_date = models.DateField("Дата регистрации", null=True, blank=True)
    okato = models.CharField("ОКАТО", max_length=20, blank=True)
    legal_address = models.CharField("Юридический адрес", max_length=255, blank=True)
    legal_address_fias_id = models.CharField("ФИАС юридического адреса", max_length=36, blank=True)
    legal_address_postal_code = models.CharField("Индекс юридического адреса", max_length=12, blank=True)
    legal_address_region_code = models.CharField("Код региона юридического адреса", max_length=3, blank=True)
    legal_address_region = models.CharField("Регион юридического адреса", max_length=150, blank=True)
    legal_address_area = models.CharField("Район юридического адреса", max_length=150, blank=True)
    legal_address_city = models.CharField("Город юридического адреса", max_length=150, blank=True)
    legal_address_settlement = models.CharField("Посёлок юридического адреса", max_length=150, blank=True)
    legal_address_street = models.CharField("Улица юридического адреса", max_length=150, blank=True)
    legal_address_house = models.CharField("Дом юридического адреса", max_length=30, blank=True)
    legal_address_block = models.CharField("Корпус юридического адреса", max_length=30, blank=True)
    legal_address_flat = models.CharField("Квартира юридического адреса", max_length=30, blank=True)
    contact_name = models.CharField("Контактное лицо", max_length=150, blank=True)
    director_name = models.CharField("Руководитель", max_length=150, blank=True)
    phone = models.CharField("Телефон", max_length=30, blank=True)
    email = models.EmailField("Email", blank=True)
    bank_name = models.CharField("Наименование банка", max_length=255, blank=True)
    bik = models.CharField("БИК", max_length=20, blank=True)
    settlement_account = models.CharField("Расчётный счёт", max_length=30, blank=True)
    correspondent_account = models.CharField(
        "Корреспондентский счёт", max_length=30, blank=True
    )
    is_own_company = models.BooleanField("Наша компания", default=False)
    profit_tax_rate = models.DecimalField(
        "Расчётная ставка налога на прибыль, %",
        max_digits=5,
        decimal_places=2,
        default=Decimal("25.00"),
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    verification_status = models.CharField(
        "Проверка реквизитов",
        max_length=20,
        choices=VerificationStatus.choices,
        default=VerificationStatus.NOT_CHECKED,
    )
    verified_at = models.DateTimeField("Проверено", null=True, blank=True)
    fns_status = models.CharField(
        "Статус ФНС",
        max_length=20,
        choices=FNSStatus.choices,
        default=FNSStatus.UNKNOWN,
    )
    fns_checked_at = models.DateTimeField("Проверено ФНС", null=True, blank=True)
    default_vat_rate = models.ForeignKey(
        "VATRate",
        verbose_name="Ставка НДС по умолчанию",
        related_name="default_for_organizations",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    payment_term_days = models.PositiveSmallIntegerField(
        "Отсрочка оплаты, дней", default=0
    )
    default_payment_form = models.CharField(
        "Форма оплаты по умолчанию",
        max_length=30,
        choices=ORDER_PAYMENT_FORM_CHOICES,
        blank=True,
    )
    credit_limit = models.DecimalField(
        "Кредитный лимит",
        max_digits=14,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(Decimal("0"))],
    )
    edo_operator = models.CharField("Оператор ЭДО", max_length=150, blank=True)
    edo_id = models.CharField(
        "Идентификатор участника ЭДО",
        max_length=255,
        blank=True,
        help_text="Идентификатор организации в Контур.Диадок/ЭДО (boxId или participantId).",
    )
    originals_handling = models.CharField(
        "Работа с оригиналами",
        max_length=10,
        choices=OriginalsHandling.choices,
        default=OriginalsHandling.BOTH,
    )
    notes = models.TextField("Комментарий", blank=True)
    is_active = models.BooleanField("Активна", default=True)

    class Meta:
        verbose_name = "организация"
        verbose_name_plural = "организации"
        ordering = ("name",)
        indexes = [models.Index(fields=("is_own_company", "is_active"))]
        constraints = [
            models.UniqueConstraint(
                fields=("tax_id",),
                condition=~models.Q(tax_id=""),
                name="unique_nonempty_organization_tax_id",
            )
        ]

    def __str__(self):
        return self.short_name or self.name

    def save(self, *args, **kwargs):
        self.tax_id = re.sub(r"\D", "", self.tax_id or "")
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("organization-update", kwargs={"pk": self.pk})

    @property
    def role_values(self):
        return list(self.roles.values_list("role", flat=True))


class OrganizationRole(TimestampedModel):
    class Role(models.TextChoices):
        CLIENT = "client", "Клиент"
        FORWARDER = "forwarder", "Экспедитор"
        CARRIER = "carrier", "Перевозчик"
        SHIPPER = "shipper", "Грузоотправитель"
        CONSIGNEE = "consignee", "Грузополучатель"

    organization = models.ForeignKey(
        Organization,
        verbose_name="Организация",
        related_name="roles",
        on_delete=models.CASCADE,
    )
    role = models.CharField("Роль", max_length=20, choices=Role.choices)
    is_active = models.BooleanField("Активна", default=True)

    class Meta:
        verbose_name = "роль организации"
        verbose_name_plural = "роли организаций"
        ordering = ("organization", "role")
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "role"), name="unique_organization_role"
            )
        ]

    def __str__(self):
        return f"{self.organization} · {self.get_role_display()}"


class OrganizationChange(TimestampedModel):
    """Audit trail for edits made to a counterparty card."""

    class Action(models.TextChoices):
        CREATE = "create", "Создание"
        UPDATE = "update", "Изменение"
        FNS_SYNC = "fns_sync", "Обновление из ФНС"

    organization = models.ForeignKey(
        Organization,
        verbose_name="Контрагент",
        related_name="change_history",
        on_delete=models.CASCADE,
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Кто изменил",
        related_name="organization_changes",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    action = models.CharField(
        "Действие", max_length=20, choices=Action.choices, default=Action.UPDATE
    )
    changes = models.JSONField("Изменения", default=dict)
    comment = models.CharField("Комментарий", max_length=255, blank=True)

    class Meta:
        verbose_name = "изменение контрагента"
        verbose_name_plural = "история изменений контрагентов"
        ordering = ("-created_at",)
        indexes = [models.Index(fields=("organization", "-created_at"))]

    def __str__(self):
        return f"{self.organization} · {self.get_action_display()} · {self.created_at:%d.%m.%Y %H:%M}"


class OrganizationBankAccount(TimestampedModel):
    organization = models.ForeignKey(
        Organization,
        verbose_name="Контрагент",
        related_name="bank_accounts",
        on_delete=models.CASCADE,
    )
    account_number = models.CharField("Расчётный счёт", max_length=30)
    bank_name = models.CharField("Наименование банка", max_length=255)
    bik = models.CharField("БИК", max_length=20, blank=True)
    correspondent_account = models.CharField(
        "Корреспондентский счёт", max_length=30, blank=True
    )
    currency = models.CharField(
        "Валюта",
        max_length=3,
        choices=[("RUB", "RUB"), ("USD", "USD"), ("EUR", "EUR")],
        default="RUB",
    )
    is_primary = models.BooleanField("Основной", default=False)
    is_active = models.BooleanField("Используется", default=True)
    notes = models.CharField("Комментарий", max_length=255, blank=True)

    class Meta:
        verbose_name = "банковский счёт контрагента"
        verbose_name_plural = "банковские счета контрагента"
        ordering = ("-is_primary", "bank_name", "account_number")
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "account_number"),
                name="unique_organization_bank_account",
            ),
            models.UniqueConstraint(
                fields=("organization",),
                condition=models.Q(is_primary=True, is_active=True),
                name="unique_primary_bank_account_per_organization",
            ),
        ]

    def __str__(self):
        return f"{self.account_number} · {self.bank_name}"


class OrganizationContact(TimestampedModel):
    organization = models.ForeignKey(
        Organization,
        verbose_name="Контрагент",
        related_name="contact_people",
        on_delete=models.CASCADE,
    )
    full_name = models.CharField("Ф. И. О.", max_length=150)
    position = models.CharField("Должность", max_length=150, blank=True)
    phone = models.CharField("Телефон", max_length=30, blank=True)
    email = models.EmailField("Email", blank=True)
    is_primary = models.BooleanField("Основное контактное лицо", default=False)
    is_active = models.BooleanField("Актуально", default=True)
    notes = models.CharField("Комментарий", max_length=255, blank=True)

    class Meta:
        verbose_name = "контактное лицо контрагента"
        verbose_name_plural = "контактные лица контрагента"
        ordering = ("-is_primary", "full_name")
        constraints = [
            models.UniqueConstraint(
                fields=("organization",),
                condition=models.Q(is_primary=True, is_active=True),
                name="unique_primary_contact_per_organization",
            )
        ]

    def __str__(self):
        return self.full_name


class VATRate(TimestampedModel):
    code = models.CharField("Код", max_length=20, unique=True)
    name = models.CharField("Наименование", max_length=100)
    rate = models.DecimalField(
        "Ставка, %", max_digits=5, decimal_places=2, default=0
    )
    is_without_vat = models.BooleanField("Без НДС", default=False)
    is_active = models.BooleanField("Используется", default=True)
    valid_from = models.DateField("Действует с", null=True, blank=True)

    class Meta:
        verbose_name = "ставка НДС"
        verbose_name_plural = "ставки НДС"
        ordering = ("is_without_vat", "rate")

    def __str__(self):
        return self.name

    def vat_from_gross(self, amount):
        amount = Decimal(amount or 0)
        if self.is_without_vat or not self.rate:
            return Decimal("0.00")
        return (
            amount * self.rate / (Decimal("100") + self.rate)
        ).quantize(Decimal("0.01"))


class PackageType(TimestampedModel):
    name = models.CharField("Наименование", max_length=100, unique=True)
    is_active = models.BooleanField("Используется", default=True)

    class Meta:
        verbose_name = "вид упаковки"
        verbose_name_plural = "виды упаковки"
        ordering = ("name",)

    def __str__(self):
        return self.name


class CargoHandlingMethod(TimestampedModel):
    name = models.CharField("Наименование", max_length=100, unique=True)
    is_active = models.BooleanField("Используется", default=True)

    class Meta:
        verbose_name = "способ погрузки / выгрузки"
        verbose_name_plural = "способы погрузки / выгрузки"
        ordering = ("name",)

    def __str__(self):
        return self.name


class CompanyProfile(TimestampedModel):
    class VATRate(models.TextChoices):
        WITHOUT_VAT = "without_vat", "Без НДС"
        ZERO = "0", "0%"
        FIVE = "5", "5%"
        SEVEN = "7", "7%"
        TEN = "10", "10%"
        TWENTY = "20", "20% (переходные операции)"
        TWENTY_TWO = "22", "22%"

    name = models.CharField("Полное наименование", max_length=255)
    short_name = models.CharField("Краткое наименование", max_length=150, blank=True)
    tax_id = models.CharField("ИНН", max_length=20)
    kpp = models.CharField("КПП", max_length=20, blank=True)
    ogrn = models.CharField("ОГРН / ОГРНИП", max_length=30, blank=True)
    legal_address = models.CharField("Юридический адрес", max_length=255)
    phone = models.CharField("Телефон", max_length=30, blank=True)
    email = models.EmailField("Email", blank=True)
    bank_name = models.CharField("Наименование банка", max_length=255, blank=True)
    bik = models.CharField("БИК", max_length=20, blank=True)
    settlement_account = models.CharField("Расчётный счёт", max_length=30, blank=True)
    correspondent_account = models.CharField(
        "Корреспондентский счёт", max_length=30, blank=True
    )
    director_name = models.CharField("Руководитель", max_length=150, blank=True)
    chief_accountant_name = models.CharField(
        "Главный бухгалтер", max_length=150, blank=True
    )
    default_vat_rate = models.CharField(
        "Ставка НДС по умолчанию",
        max_length=20,
        choices=VATRate.choices,
        default=VATRate.WITHOUT_VAT,
    )
    is_active = models.BooleanField("Активен", default=True)
    organization = models.ForeignKey(
        Organization,
        verbose_name="Единая карточка",
        related_name="legacy_expeditors",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "экспедитор"
        verbose_name_plural = "экспедиторы"
        ordering = ("name",)

    def __str__(self):
        return self.short_name or self.name

    def get_absolute_url(self):
        return reverse("expeditor-detail", kwargs={"pk": self.pk})


class Customer(TimestampedModel):
    name = models.CharField("Название", max_length=255)
    tax_id = models.CharField("ИНН", max_length=20, blank=True)
    kpp = models.CharField("КПП", max_length=20, blank=True)
    ogrn = models.CharField("ОГРН / ОГРНИП", max_length=30, blank=True)
    contact_name = models.CharField("Контактное лицо", max_length=150, blank=True)
    phone = models.CharField("Телефон", max_length=30, blank=True)
    email = models.EmailField("Email", blank=True)
    address = models.CharField("Юридический адрес", max_length=255, blank=True)
    director_name = models.CharField("Руководитель", max_length=150, blank=True)
    bank_name = models.CharField("Наименование банка", max_length=255, blank=True)
    bik = models.CharField("БИК", max_length=20, blank=True)
    settlement_account = models.CharField("Расчётный счёт", max_length=30, blank=True)
    correspondent_account = models.CharField(
        "Корреспондентский счёт", max_length=30, blank=True
    )
    notes = models.TextField("Комментарий", blank=True)
    is_active = models.BooleanField("Активен", default=True)
    organization = models.ForeignKey(
        Organization,
        verbose_name="Единая карточка",
        related_name="legacy_customers",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "клиент"
        verbose_name_plural = "клиенты"
        ordering = ("name",)

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("customer-detail", kwargs={"pk": self.pk})


class Carrier(TimestampedModel):
    name = models.CharField("Название", max_length=255)
    tax_id = models.CharField("ИНН", max_length=20, blank=True)
    kpp = models.CharField("КПП", max_length=20, blank=True)
    ogrn = models.CharField("ОГРН / ОГРНИП", max_length=30, blank=True)
    address = models.CharField("Юридический адрес", max_length=255, blank=True)
    contact_name = models.CharField("Контактное лицо", max_length=150, blank=True)
    phone = models.CharField("Телефон", max_length=30, blank=True)
    email = models.EmailField("Email", blank=True)
    director_name = models.CharField("Руководитель", max_length=150, blank=True)
    bank_name = models.CharField("Наименование банка", max_length=255, blank=True)
    bik = models.CharField("БИК", max_length=20, blank=True)
    settlement_account = models.CharField("Расчётный счёт", max_length=30, blank=True)
    correspondent_account = models.CharField(
        "Корреспондентский счёт", max_length=30, blank=True
    )
    vehicle_types = models.CharField("Типы транспорта", max_length=255, blank=True)
    rating = models.PositiveSmallIntegerField(
        "Рейтинг", default=5, choices=[(value, str(value)) for value in range(1, 6)]
    )
    notes = models.TextField("Комментарий", blank=True)
    is_active = models.BooleanField("Активен", default=True)
    organization = models.ForeignKey(
        Organization,
        verbose_name="Единая карточка",
        related_name="legacy_carriers",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "перевозчик"
        verbose_name_plural = "перевозчики"
        ordering = ("name",)

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("carrier-detail", kwargs={"pk": self.pk})


class Contract(TimestampedModel):
    class Kind(models.TextChoices):
        CLIENT_FORWARDING = (
            "client_forwarding",
            "ТЭО с клиентом",
        )
        CARRIER_TRANSPORT = (
            "carrier_transport",
            "Перевозка с перевозчиком",
        )
        SUBCONTRACTOR_FORWARDING = (
            "subcontractor_forwarding",
            "ТЭО с привлечённым экспедитором",
        )

    class Status(models.TextChoices):
        DRAFT = "draft", "Черновик"
        READY = "ready", "Готов к подписанию"
        SIGNED = "signed", "Подписан"
        TERMINATED = "terminated", "Расторгнут"
        ARCHIVED = "archived", "Архив"

    kind = models.CharField("Тип договора", max_length=40, choices=Kind.choices)
    number = models.CharField("Номер", max_length=100, blank=True)
    contract_date = models.DateField("Дата договора", default=timezone.localdate)
    city = models.CharField("Город подписания", max_length=120, default="Санкт-Петербург")
    valid_until = models.DateField("Действует до", null=True, blank=True)
    terminated_on = models.DateField("Дата расторжения", null=True, blank=True)
    status = models.CharField(
        "Статус", max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    expeditor = models.ForeignKey(
        CompanyProfile,
        verbose_name="Наша компания",
        related_name="contracts",
        on_delete=models.PROTECT,
    )
    customer = models.ForeignKey(
        Customer,
        verbose_name="Клиент",
        related_name="contracts",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    carrier = models.ForeignKey(
        Carrier,
        verbose_name="Перевозчик / привлечённый экспедитор",
        related_name="contracts",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    expeditor_representative = models.CharField(
        "Представитель нашей компании", max_length=150, blank=True
    )
    expeditor_authority_basis = models.CharField(
        "Основание полномочий", max_length=150, default="Устава"
    )
    counterparty_representative = models.CharField(
        "Представитель контрагента", max_length=150, blank=True
    )
    counterparty_authority_basis = models.CharField(
        "Основание полномочий контрагента", max_length=150, default="Устава"
    )
    payment_term_days = models.PositiveSmallIntegerField(
        "Отсрочка оплаты, дней", default=0
    )
    payment_terms = models.TextField("Условия оплаты", blank=True)
    debt_limit = models.DecimalField(
        "Лимит задолженности",
        max_digits=14,
        decimal_places=2,
        blank=True,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    vat_rate = models.ForeignKey(
        "VATRate",
        verbose_name="Ставка НДС",
        related_name="contracts",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    document_file = models.FileField(
        "PDF договора",
        upload_to="contracts/%Y/%m/",
        blank=True,
        null=True,
        validators=[FileExtensionValidator(["pdf"])],
    )
    notes = models.TextField("Внутренний комментарий", blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Создал",
        related_name="created_contracts",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "договор"
        verbose_name_plural = "договоры"
        ordering = ("-contract_date", "-created_at")
        constraints = [
            models.UniqueConstraint(
                fields=("expeditor", "number"), name="unique_contract_number_per_expeditor"
            )
        ]

    def __str__(self):
        return f"Договор № {self.number} · {self.counterparty_name}"

    @property
    def counterparty(self):
        return self.customer if self.kind == self.Kind.CLIENT_FORWARDING else self.carrier

    @property
    def counterparty_name(self):
        return self.counterparty.name if self.counterparty else "Контрагент не выбран"

    def clean(self):
        super().clean()
        errors = {}
        if self.kind == self.Kind.CLIENT_FORWARDING:
            if not self.customer_id:
                errors["customer"] = "Выберите клиента."
            if self.carrier_id:
                errors["carrier"] = "Для клиентского договора перевозчик не выбирается."
        else:
            if not self.carrier_id:
                errors["carrier"] = "Выберите перевозчика или привлечённого экспедитора."
            if self.customer_id:
                errors["customer"] = "Для этого типа договора клиент не выбирается."
        if self.valid_until and self.valid_until < self.contract_date:
            errors["valid_until"] = "Срок действия не может закончиться раньше даты договора."
        if self.terminated_on and self.terminated_on < self.contract_date:
            errors["terminated_on"] = "Дата расторжения не может быть раньше даты договора."
        if self.terminated_on and self.valid_until and self.terminated_on > self.valid_until:
            errors["terminated_on"] = "Дата расторжения не может быть позже срока действия договора."
        if self.status == self.Status.TERMINATED and not self.terminated_on:
            errors["terminated_on"] = "Для расторгнутого договора укажите дату расторжения."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self.number and self.expeditor_id:
            prefix = f"ДГ-{self.contract_date:%Y}-"
            last_number = (
                Contract.objects.filter(expeditor_id=self.expeditor_id, number__startswith=prefix)
                .order_by("number")
                .values_list("number", flat=True)
                .last()
            )
            sequence = int(last_number.rsplit("-", 1)[-1]) + 1 if last_number else 1
            self.number = f"{prefix}{sequence:04d}"
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("contract-detail", kwargs={"pk": self.pk})


class Driver(TimestampedModel):
    carrier = models.ForeignKey(
        Carrier,
        verbose_name="Перевозчик",
        related_name="drivers",
        on_delete=models.PROTECT,
    )
    last_name = models.CharField("Фамилия", max_length=100)
    first_name = models.CharField("Имя", max_length=100)
    middle_name = models.CharField("Отчество", max_length=100, blank=True)
    phone = models.CharField("Телефон", max_length=30)
    email = models.EmailField("Email", blank=True)
    birth_date = models.DateField("Дата рождения", null=True, blank=True)
    tax_id = models.CharField(
        "ИНН",
        max_length=12,
        blank=True,
        db_index=True,
        validators=[RegexValidator(r"^\d{12}$", "ИНН физлица должен содержать 12 цифр.")],
    )
    address = models.CharField("Адрес регистрации", max_length=255, blank=True)
    passport_series = models.CharField("Серия паспорта", max_length=10, blank=True)
    passport_number = models.CharField("Номер паспорта", max_length=20, blank=True)
    passport_issued_by = models.CharField(
        "Кем выдан паспорт", max_length=255, blank=True
    )
    passport_issue_date = models.DateField(
        "Дата выдачи паспорта", null=True, blank=True
    )
    license_number = models.CharField(
        "Номер водительского удостоверения", max_length=30, blank=True
    )
    license_categories = models.CharField(
        "Категории", max_length=100, blank=True, help_text="Например: B, C, CE"
    )
    license_issue_date = models.DateField(
        "Дата выдачи удостоверения", null=True, blank=True
    )
    license_expiry_date = models.DateField(
        "Удостоверение действительно до", null=True, blank=True
    )
    medical_certificate_expiry = models.DateField(
        "Медсправка действительна до", null=True, blank=True
    )
    notes = models.TextField("Комментарий", blank=True)
    is_active = models.BooleanField("Работает", default=True)
    carriers = models.ManyToManyField(
        Carrier,
        verbose_name="Компании-работодатели",
        related_name="associated_drivers",
        through="DriverEmployment",
    )

    class Meta:
        verbose_name = "водитель"
        verbose_name_plural = "водители"
        ordering = ("last_name", "first_name", "middle_name")
        constraints = [
            models.UniqueConstraint(
                fields=("tax_id",),
                condition=~models.Q(tax_id=""),
                name="unique_driver_tax_id_when_present",
                violation_error_message="Водитель с таким ИНН уже существует.",
            )
        ]

    def __str__(self):
        return f"{self.full_name} — {self.carrier.name}"

    def save(self, *args, **kwargs):
        """Keep the legacy primary carrier and the employment register aligned."""

        with transaction.atomic():
            self.tax_id = re.sub(r"\D", "", self.tax_id or "")
            super().save(*args, **kwargs)
            DriverEmployment.objects.filter(
                driver=self, is_primary=True
            ).exclude(carrier_id=self.carrier_id).update(is_primary=False)
            employment, _ = DriverEmployment.objects.get_or_create(
                driver=self,
                carrier_id=self.carrier_id,
                defaults={"is_primary": True, "is_active": True},
            )
            changes = []
            if not employment.is_primary:
                employment.is_primary = True
                changes.append("is_primary")
            if not employment.is_active:
                employment.is_active = True
                changes.append("is_active")
            if changes:
                employment.save(update_fields=[*changes, "updated_at"])
            if self.license_number and not DriverLicense.objects.filter(
                driver=self, is_current=True
            ).exists():
                DriverLicense.objects.create(
                    driver=self,
                    number=self.license_number,
                    categories=self.license_categories,
                    issue_date=self.license_issue_date,
                    expiry_date=self.license_expiry_date,
                    is_current=True,
                )

    @property
    def full_name(self):
        return " ".join(
            part for part in (self.last_name, self.first_name, self.middle_name) if part
        )

    @property
    def license_is_expired(self):
        return bool(
            self.license_expiry_date
            and self.license_expiry_date < timezone.localdate()
        )

    @property
    def current_passport(self):
        return self.passports.filter(is_current=True).first()

    @property
    def current_license(self):
        return self.licenses.filter(is_current=True).first()

    def works_for_carrier(self, carrier):
        carrier_id = getattr(carrier, "pk", carrier)
        if not carrier_id:
            return False
        return self.carrier_id == carrier_id or self.employments.filter(
            carrier_id=carrier_id, is_active=True
        ).exists()

    def works_for_organization(self, organization):
        organization_id = getattr(organization, "pk", organization)
        if not organization_id:
            return False
        if self.carrier.organization_id == organization_id:
            return True
        return self.employments.filter(
            carrier__organization_id=organization_id, is_active=True
        ).exists()

    def get_absolute_url(self):
        return reverse("driver-detail", kwargs={"pk": self.pk})


class DriverEmployment(TimestampedModel):
    driver = models.ForeignKey(
        Driver,
        verbose_name="Водитель",
        related_name="employments",
        on_delete=models.CASCADE,
    )
    carrier = models.ForeignKey(
        Carrier,
        verbose_name="Компания",
        related_name="driver_employments",
        on_delete=models.PROTECT,
    )
    is_primary = models.BooleanField("Основное место работы", default=False)
    is_active = models.BooleanField("Работает", default=True)

    class Meta:
        verbose_name = "место работы водителя"
        verbose_name_plural = "места работы водителей"
        ordering = ("-is_primary", "carrier__name")
        constraints = [
            models.UniqueConstraint(
                fields=("driver", "carrier"),
                name="unique_driver_employment",
            ),
            models.UniqueConstraint(
                fields=("driver",),
                condition=models.Q(is_primary=True),
                name="unique_primary_driver_employment",
            ),
        ]

    def __str__(self):
        return f"{self.driver.full_name} — {self.carrier.name}"


class DriverPassport(TimestampedModel):
    driver = models.ForeignKey(
        Driver,
        verbose_name="Водитель",
        related_name="passports",
        on_delete=models.CASCADE,
    )
    series = models.CharField(
        "Серия",
        max_length=4,
        validators=[RegexValidator(r"^\d{4}$", "Серия должна содержать 4 цифры.")],
    )
    number = models.CharField(
        "Номер",
        max_length=6,
        validators=[RegexValidator(r"^\d{6}$", "Номер должен содержать 6 цифр.")],
    )
    issued_by = models.CharField("Кем выдан", max_length=255, blank=True)
    issue_date = models.DateField("Дата выдачи", null=True, blank=True)
    is_current = models.BooleanField("Действующий паспорт", default=True)
    notes = models.CharField("Комментарий", max_length=255, blank=True)

    class Meta:
        verbose_name = "паспорт водителя"
        verbose_name_plural = "паспорта водителей"
        ordering = ("-is_current", "-issue_date", "-created_at")
        constraints = [
            models.UniqueConstraint(
                fields=("series", "number"),
                name="unique_driver_passport_identity",
                violation_error_message=(
                    "Водитель с такой серией и номером паспорта уже существует."
                ),
            ),
            models.UniqueConstraint(
                fields=("driver",),
                condition=models.Q(is_current=True),
                name="unique_current_driver_passport",
            ),
        ]

    @staticmethod
    def normalize_part(value):
        return re.sub(r"\D", "", value or "")

    def clean(self):
        self.series = self.normalize_part(self.series)
        self.number = self.normalize_part(self.number)
        super().clean()

    def save(self, *args, **kwargs):
        self.series = self.normalize_part(self.series)
        self.number = self.normalize_part(self.number)
        with transaction.atomic():
            if self.is_current and self.driver_id:
                DriverPassport.objects.filter(
                    driver_id=self.driver_id, is_current=True
                ).exclude(pk=self.pk).update(is_current=False)
            super().save(*args, **kwargs)
            if self.is_current:
                Driver.objects.filter(pk=self.driver_id).update(
                    passport_series=self.series,
                    passport_number=self.number,
                    passport_issued_by=self.issued_by,
                    passport_issue_date=self.issue_date,
                )

    def delete(self, *args, **kwargs):
        driver_id = self.driver_id
        was_current = self.is_current
        with transaction.atomic():
            result = super().delete(*args, **kwargs)
            if was_current:
                replacement = DriverPassport.objects.filter(
                    driver_id=driver_id
                ).first()
                if replacement:
                    replacement.is_current = True
                    replacement.save(update_fields=["is_current", "updated_at"])
                else:
                    Driver.objects.filter(pk=driver_id).update(
                        passport_series="",
                        passport_number="",
                        passport_issued_by="",
                        passport_issue_date=None,
                    )
        return result

    def __str__(self):
        return f"{self.series} {self.number}"


class DriverLicense(TimestampedModel):
    driver = models.ForeignKey(
        Driver,
        verbose_name="Водитель",
        related_name="licenses",
        on_delete=models.CASCADE,
    )
    number = models.CharField("Номер удостоверения", max_length=30)
    identity_key = models.CharField(
        "Нормализованный номер", max_length=30, unique=True, editable=False
    )
    categories = models.CharField(
        "Категории", max_length=100, help_text="Например: B, C, CE"
    )
    issue_date = models.DateField("Дата выдачи", null=True, blank=True)
    expiry_date = models.DateField("Действительно до")
    is_current = models.BooleanField("Действующее удостоверение", default=True)
    notes = models.CharField("Комментарий", max_length=255, blank=True)

    class Meta:
        verbose_name = "водительское удостоверение"
        verbose_name_plural = "водительские удостоверения"
        ordering = ("-is_current", "-expiry_date", "-created_at")
        constraints = [
            models.UniqueConstraint(
                fields=("driver",),
                condition=models.Q(is_current=True),
                name="unique_current_driver_license",
            )
        ]

    @staticmethod
    def identity_from_number(value):
        return re.sub(r"[^0-9A-ZА-Я]", "", (value or "").upper())

    def clean(self):
        self.identity_key = self.identity_from_number(self.number)
        super().clean()
        if self.issue_date and self.expiry_date and self.expiry_date < self.issue_date:
            raise ValidationError(
                {"expiry_date": "Срок действия не может закончиться раньше даты выдачи."}
            )

    def save(self, *args, **kwargs):
        self.identity_key = self.identity_from_number(self.number)
        with transaction.atomic():
            if self.is_current and self.driver_id:
                DriverLicense.objects.filter(
                    driver_id=self.driver_id, is_current=True
                ).exclude(pk=self.pk).update(is_current=False)
            super().save(*args, **kwargs)
            if self.is_current:
                Driver.objects.filter(pk=self.driver_id).update(
                    license_number=self.number,
                    license_categories=self.categories,
                    license_issue_date=self.issue_date,
                    license_expiry_date=self.expiry_date,
                )

    def delete(self, *args, **kwargs):
        driver_id = self.driver_id
        was_current = self.is_current
        with transaction.atomic():
            result = super().delete(*args, **kwargs)
            if was_current:
                replacement = DriverLicense.objects.filter(
                    driver_id=driver_id
                ).first()
                if replacement:
                    replacement.is_current = True
                    replacement.save(update_fields=["is_current", "updated_at"])
        return result

    @property
    def is_expired(self):
        return self.expiry_date < timezone.localdate()

    def __str__(self):
        return self.number


class Vehicle(TimestampedModel):
    class Kind(models.TextChoices):
        TRUCK = "truck", "Грузовой автомобиль"
        TRACTOR = "tractor", "Седельный тягач"
        VAN = "van", "Фургон"
        GAZELLE = "gazelle", "Газель"
        TRAILER = "trailer", "Прицеп"
        SEMITRAILER = "semitrailer", "Полуприцеп"
        OTHER = "other", "Другое"

    carrier = models.ForeignKey(
        Carrier,
        verbose_name="Перевозчик",
        related_name="vehicles",
        on_delete=models.PROTECT,
    )
    kind = models.CharField("Тип единицы", max_length=20, choices=Kind.choices)
    registration_number = models.CharField(
        "Государственный номер", max_length=20, unique=True
    )
    trailer_registration_number = models.CharField(
        "Номер прицепа / полуприцепа", max_length=20, blank=True
    )
    vin = models.CharField("VIN", max_length=32, blank=True)
    make = models.CharField("Марка", max_length=100)
    model = models.CharField("Модель", max_length=100, blank=True)
    year = models.PositiveSmallIntegerField(
        "Год выпуска", null=True, blank=True, validators=[MinValueValidator(1950)]
    )
    body_type = models.CharField("Тип кузова", max_length=100, blank=True)
    capacity_kg = models.DecimalField(
        "Грузоподъёмность, кг",
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(Decimal("0"))],
    )
    volume_m3 = models.DecimalField(
        "Объём кузова, м³",
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(Decimal("0"))],
    )
    pallet_capacity = models.PositiveSmallIntegerField(
        "Вместимость, паллет", default=0
    )
    insurance_expiry_date = models.DateField(
        "Страховка действительна до", null=True, blank=True
    )
    inspection_expiry_date = models.DateField(
        "Техосмотр действителен до", null=True, blank=True
    )
    notes = models.TextField("Комментарий", blank=True)
    is_active = models.BooleanField("В эксплуатации", default=True)

    class Meta:
        verbose_name = "транспортное средство"
        verbose_name_plural = "подвижной состав"
        ordering = ("registration_number",)

    def __str__(self):
        vehicle_name = " ".join(part for part in (self.make, self.model) if part)
        return f"{self.registration_number} · {vehicle_name} — {self.carrier.name}"

    @property
    def is_trailer(self):
        return self.kind in {self.Kind.TRAILER, self.Kind.SEMITRAILER}

    @property
    def is_power_unit(self):
        return self.kind in {self.Kind.TRACTOR, self.Kind.TRUCK}

    @property
    def can_tow_trailer(self):
        """Whether this unit may form a road train with a trailer."""
        return self.kind in {self.Kind.TRACTOR, self.Kind.TRUCK}

    @property
    def requires_trailer(self):
        """Saddle tractors cannot operate as a complete vehicle by themselves."""
        return self.kind == self.Kind.TRACTOR

    @property
    def insurance_is_expired(self):
        return bool(
            self.insurance_expiry_date
            and self.insurance_expiry_date < timezone.localdate()
        )

    @property
    def inspection_is_expired(self):
        return bool(
            self.inspection_expiry_date
            and self.inspection_expiry_date < timezone.localdate()
        )

    def get_absolute_url(self):
        return reverse("vehicle-detail", kwargs={"pk": self.pk})


class VehicleCombination(TimestampedModel):
    """A reusable, time-bound combination of a power unit and a trailer."""

    tractor = models.ForeignKey(
        Vehicle,
        verbose_name="Основной автомобиль",
        related_name="combinations_as_tractor",
        on_delete=models.PROTECT,
    )
    trailer = models.ForeignKey(
        Vehicle,
        verbose_name="Прицеп / полуприцеп",
        related_name="combinations_as_trailer",
        on_delete=models.PROTECT,
    )
    valid_from = models.DateField("Действует с", null=True, blank=True)
    valid_until = models.DateField("Действует по", null=True, blank=True)
    is_active = models.BooleanField("Активна", default=True)
    notes = models.TextField("Комментарий", blank=True)

    class Meta:
        verbose_name = "сцепка"
        verbose_name_plural = "сцепки"
        ordering = ("-is_active", "tractor__registration_number", "trailer__registration_number")
        constraints = [
            models.UniqueConstraint(
                fields=("tractor",),
                condition=models.Q(is_active=True),
                name="unique_active_combination_tractor",
            ),
            models.UniqueConstraint(
                fields=("trailer",),
                condition=models.Q(is_active=True),
                name="unique_active_combination_trailer",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.tractor_id and self.trailer_id and self.tractor_id == self.trailer_id:
            errors["trailer"] = "Основной автомобиль и прицеп должны быть разными единицами."
        if self.tractor_id and not self.tractor.is_power_unit:
            errors["tractor"] = "В сцепку можно добавить только тягач или грузовой автомобиль."
        if self.trailer_id and not self.trailer.is_trailer:
            errors["trailer"] = "В сцепку можно добавить только прицеп или полуприцеп."
        if (
            self.tractor_id
            and self.trailer_id
            and self.trailer.kind == Vehicle.Kind.SEMITRAILER
            and self.tractor.kind != Vehicle.Kind.TRACTOR
        ):
            errors["tractor"] = "Полуприцеп можно соединить только с седельным тягачом."
        if (
            self.tractor_id
            and self.trailer_id
            and self.tractor.carrier_id != self.trailer.carrier_id
        ):
            errors["trailer"] = "Тягач и прицеп должны принадлежать одному перевозчику."
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            errors["valid_until"] = "Дата окончания не может быть раньше даты начала."
        if self.is_active:
            if self.tractor_id and not self.tractor.is_active:
                errors["tractor"] = "Нельзя активировать сцепку с неактивным автомобилем."
            if self.trailer_id and not self.trailer.is_active:
                errors["trailer"] = "Нельзя активировать сцепку с неактивным прицепом."
            if self.tractor_id:
                active_tractor = VehicleCombination.objects.filter(
                    tractor_id=self.tractor_id, is_active=True
                ).exclude(pk=self.pk)
                if active_tractor.exists():
                    errors["tractor"] = "У этого автомобиля уже есть активная сцепка."
            if self.trailer_id:
                active_trailer = VehicleCombination.objects.filter(
                    trailer_id=self.trailer_id, is_active=True
                ).exclude(pk=self.pk)
                if active_trailer.exists():
                    errors["trailer"] = "У этого прицепа уже есть активная сцепка."
        if errors:
            raise ValidationError(errors)

    @property
    def carrier(self):
        return self.tractor.carrier

    def __str__(self):
        return f"{self.tractor.registration_number} + {self.trailer.registration_number}"

    def get_absolute_url(self):
        return reverse("vehicle-combination-update", kwargs={"pk": self.pk})


class Shipment(TimestampedModel):
    class Status(models.TextChoices):
        NEW = "new", "Новая"
        PLANNED = "planned", "Назначена"
        LOADING = "loading", "На погрузке"
        IN_TRANSIT = "in_transit", "В пути"
        DELIVERED = "delivered", "Доставлена"
        CLOSED = "closed", "Закрыта"
        CANCELLED = "cancelled", "Отменена"

    class PaymentStatus(models.TextChoices):
        AWAITING = "awaiting", "Ожидается"
        PARTIAL = "partial", "Частично"
        PAID = "paid", "Оплачено"
        OVERDUE = "overdue", "Просрочено"

    number = models.CharField("Номер заявки", max_length=30, unique=True, blank=True)
    expeditor = models.ForeignKey(
        CompanyProfile,
        verbose_name="Экспедитор",
        related_name="shipments",
        on_delete=models.PROTECT,
    )
    customer = models.ForeignKey(
        Customer, verbose_name="Клиент", related_name="shipments", on_delete=models.PROTECT
    )
    carrier = models.ForeignKey(
        Carrier, verbose_name="Перевозчик", related_name="shipments",
        on_delete=models.PROTECT, null=True, blank=True,
    )
    driver = models.ForeignKey(
        Driver,
        verbose_name="Водитель",
        related_name="shipments",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    vehicle = models.ForeignKey(
        Vehicle,
        verbose_name="Транспорт",
        related_name="shipments",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="Менеджер", related_name="shipments",
        on_delete=models.PROTECT,
    )
    status = models.CharField(
        "Статус", max_length=20, choices=Status.choices, default=Status.NEW
    )
    cargo_name = models.CharField("Груз", max_length=255)
    weight_kg = models.DecimalField(
        "Вес, кг", max_digits=12, decimal_places=2, default=0,
        validators=[MinValueValidator(Decimal("0"))],
    )
    volume_m3 = models.DecimalField(
        "Объём, м³", max_digits=10, decimal_places=2, default=0,
        validators=[MinValueValidator(Decimal("0"))],
    )
    vehicle_type = models.CharField("Тип транспорта", max_length=100, blank=True)
    pickup_city = models.CharField("Город погрузки", max_length=120)
    pickup_address = models.CharField("Адрес погрузки", max_length=255, blank=True)
    pickup_date = models.DateField("Дата погрузки")
    delivery_city = models.CharField("Город выгрузки", max_length=120)
    delivery_address = models.CharField("Адрес выгрузки", max_length=255, blank=True)
    delivery_date = models.DateField("Плановая дата выгрузки")
    customer_price = models.DecimalField(
        "Ставка клиенту", max_digits=12, decimal_places=2, default=0,
        validators=[MinValueValidator(Decimal("0"))],
    )
    carrier_price = models.DecimalField(
        "Ставка перевозчику", max_digits=12, decimal_places=2, default=0,
        validators=[MinValueValidator(Decimal("0"))],
    )
    currency = models.CharField(
        "Валюта", max_length=3,
        choices=[("RUB", "RUB"), ("USD", "USD"), ("EUR", "EUR")], default="RUB",
    )
    payment_status = models.CharField(
        "Оплата", max_length=20, choices=PaymentStatus.choices,
        default=PaymentStatus.AWAITING,
    )
    customer_payment_due_date = models.DateField(
        "Оплата от клиента до", null=True, blank=True
    )
    carrier_payment_due_date = models.DateField(
        "Оплата перевозчику до", null=True, blank=True
    )
    customer_reference = models.CharField("Номер клиента", max_length=100, blank=True)
    notes = models.TextField("Комментарий", blank=True)

    class Meta:
        verbose_name = "заявка"
        verbose_name_plural = "заявки"
        ordering = ("-pickup_date", "-created_at")

    def __str__(self):
        return f"{self.number}: {self.pickup_city} → {self.delivery_city}"

    def save(self, *args, **kwargs):
        if not self.number:
            today = timezone.localdate()
            prefix = f"EXP-{today:%y%m}-"
            last_number = (
                Shipment.objects.filter(number__startswith=prefix)
                .order_by("number")
                .values_list("number", flat=True)
                .last()
            )
            sequence = int(last_number.rsplit("-", 1)[-1]) + 1 if last_number else 1
            self.number = f"{prefix}{sequence:04d}"
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        errors = {}
        if self.driver_id and not self.carrier_id:
            errors["driver"] = "Сначала выберите перевозчика."
        elif self.driver_id and not self.driver.works_for_carrier(self.carrier_id):
            errors["driver"] = "Водитель должен принадлежать выбранному перевозчику."
        if self.vehicle_id and not self.carrier_id:
            errors["vehicle"] = "Сначала выберите перевозчика."
        elif self.vehicle_id and self.vehicle.carrier_id != self.carrier_id:
            errors["vehicle"] = "Транспорт должен принадлежать выбранному перевозчику."
        if errors:
            raise ValidationError(errors)

    @property
    def margin(self):
        return self.customer_price - self.carrier_price

    def _payment_total(self, direction):
        prefetched = getattr(self, "_prefetched_objects_cache", {}).get("payments")
        if prefetched is not None:
            return sum(
                (payment.amount for payment in prefetched if payment.direction == direction),
                Decimal("0"),
            )
        return (
            self.payments.filter(direction=direction).aggregate(total=Sum("amount"))[
                "total"
            ]
            or Decimal("0")
        )

    @property
    def received_amount(self):
        return self._payment_total(Payment.Direction.INCOME)

    @property
    def paid_to_carrier_amount(self):
        return self._payment_total(Payment.Direction.EXPENSE)

    @property
    def receivable_balance(self):
        return self.customer_price - self.received_amount

    @property
    def payable_balance(self):
        return self.carrier_price - self.paid_to_carrier_amount

    @staticmethod
    def _debt_state(balance, paid_amount, due_date):
        if balance <= 0:
            return Shipment.PaymentStatus.PAID
        if due_date and due_date < timezone.localdate():
            return Shipment.PaymentStatus.OVERDUE
        if paid_amount > 0:
            return Shipment.PaymentStatus.PARTIAL
        return Shipment.PaymentStatus.AWAITING

    @property
    def receivable_state(self):
        return self._debt_state(
            self.receivable_balance,
            self.received_amount,
            self.customer_payment_due_date,
        )

    @property
    def payable_state(self):
        return self._debt_state(
            self.payable_balance,
            self.paid_to_carrier_amount,
            self.carrier_payment_due_date,
        )

    @property
    def receivable_state_label(self):
        return self.PaymentStatus(self.receivable_state).label

    @property
    def payable_state_label(self):
        return self.PaymentStatus(self.payable_state).label

    def refresh_payment_status(self):
        state = self.receivable_state
        Shipment.objects.filter(pk=self.pk).update(payment_status=state)
        self.payment_status = state

    @property
    def route(self):
        return f"{self.pickup_city} → {self.delivery_city}"

    def get_absolute_url(self):
        return reverse("shipment-detail", kwargs={"pk": self.pk})


class TransportationNumberSequence(TimestampedModel):
    owner_company = models.ForeignKey(
        Organization,
        verbose_name="Наша компания",
        related_name="transportation_number_sequences",
        on_delete=models.CASCADE,
    )
    year = models.PositiveSmallIntegerField("Год")
    last_value = models.PositiveIntegerField("Последний номер", default=0)

    class Meta:
        verbose_name = "нумератор заявок / рейсов"
        verbose_name_plural = "нумераторы заявок / рейсов"
        constraints = [
            models.UniqueConstraint(
                fields=("owner_company", "year"),
                name="unique_transportation_sequence_per_company_year",
            )
        ]

    def __str__(self):
        return f"{self.owner_company} · {self.year}: {self.last_value}"


class Transportation(TimestampedModel):
    class PostingStatus(models.TextChoices):
        DRAFT = "draft", "Черновик"
        POSTED = "posted", "Проведён"
        VOIDED = "voided", "Аннулирован"

    class PaymentDueBasis(models.TextChoices):
        DELIVERY_DATE = "delivery_date", "Дата доставки"
        DOCUMENT_DATE = "document_date", "Дата документа"
        ORIGINALS_RECEIVED = "originals_received", "Получение оригиналов"

    class Status(models.TextChoices):
        NEW = "new", "Новая"
        CLIENT_INSTRUCTION_RECEIVED = (
            "client_instruction_received",
            "Поручение клиента получено",
        )
        EXECUTOR_SEARCH = "executor_search", "Поиск исполнителя"
        EXECUTOR_SELECTED = "executor_selected", "Назначен исполнитель"
        EXECUTOR_DOCUMENTS_VERIFIED = (
            "executor_documents_verified",
            "Документы исполнителя проверены",
        )
        VEHICLE_CONFIRMED = "vehicle_confirmed", "Машина подтверждена"
        LOADING = "loading", "На погрузке"
        IN_TRANSIT = "in_transit", "В пути"
        UNLOADING = "unloading", "На выгрузке"
        DELIVERED = "delivered", "Доставлено"
        DOCUMENTS_RECEIVED = "documents_received", "Документы получены"
        DOCUMENTS_SENT = "documents_sent", "Документы отправлены"
        DOCUMENT_FLOW_COMPLETED = "document_flow_completed", "Документооборот завершён"
        CUSTOMER_INVOICED = "customer_invoiced", "Выставлено клиенту"
        CLOSED = "closed", "Закрыто"
        ON_HOLD = "on_hold", "Приостановлено"
        CANCELLED = "cancelled", "Отменено"

    WORKFLOW_STATUSES = (
        Status.NEW,
        Status.CLIENT_INSTRUCTION_RECEIVED,
        Status.EXECUTOR_SEARCH,
        Status.EXECUTOR_SELECTED,
        Status.EXECUTOR_DOCUMENTS_VERIFIED,
        Status.VEHICLE_CONFIRMED,
        Status.LOADING,
        Status.IN_TRANSIT,
        Status.UNLOADING,
        Status.DELIVERED,
        Status.DOCUMENTS_RECEIVED,
        Status.DOCUMENTS_SENT,
        Status.DOCUMENT_FLOW_COMPLETED,
        Status.CUSTOMER_INVOICED,
        Status.CLOSED,
    )

    legacy_shipment = models.OneToOneField(
        Shipment,
        verbose_name="Исходная заявка",
        related_name="transportation",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    number = models.CharField("Номер рейса", max_length=40, blank=True, default="")
    number_year = models.PositiveSmallIntegerField(
        "Год нумерации", null=True, blank=True, editable=False
    )
    document_date = models.DateField("Дата документа", default=timezone.localdate)
    posting_status = models.CharField(
        "Состояние документа",
        max_length=20,
        choices=PostingStatus.choices,
        default=PostingStatus.DRAFT,
    )
    posted_at = models.DateTimeField("Проведён", null=True, blank=True)
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Провёл",
        related_name="posted_transportations",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    owner_company = models.ForeignKey(
        Organization,
        verbose_name="Наша компания",
        related_name="owned_transportations",
        on_delete=models.PROTECT,
    )
    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Ответственный менеджер",
        related_name="transportations",
        on_delete=models.PROTECT,
    )
    status = models.CharField(
        "Статус", max_length=40, choices=Status.choices, default=Status.NEW
    )
    client_reference = models.CharField(
        "Номер поручения клиента", max_length=100, blank=True
    )
    customer_contract = models.ForeignKey(
        Contract,
        verbose_name="Договор с клиентом",
        related_name="customer_transportations",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    customer_amount = models.DecimalField(
        "Клиент платит, всего",
        max_digits=14,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(Decimal("0"))],
    )
    customer_vat_rate = models.ForeignKey(
        VATRate,
        verbose_name="НДС клиента",
        related_name="customer_transportations",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    executor_amount = models.DecimalField(
        "Исполнителю, всего",
        max_digits=14,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(Decimal("0"))],
    )
    executor_vat_rate = models.ForeignKey(
        VATRate,
        verbose_name="НДС исполнителя",
        related_name="executor_transportations",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    currency = models.CharField(
        "Валюта",
        max_length=3,
        choices=[("RUB", "RUB"), ("USD", "USD"), ("EUR", "EUR")],
        default="RUB",
    )
    customer_payment_term_days = models.PositiveSmallIntegerField(
        "Отсрочка клиента, дней", default=0
    )
    executor_payment_term_days = models.PositiveSmallIntegerField(
        "Отсрочка исполнителю, дней", default=0
    )
    payment_due_basis = models.CharField(
        "Основание срока оплаты",
        max_length=30,
        choices=PaymentDueBasis.choices,
        default=PaymentDueBasis.DELIVERY_DATE,
    )
    customer_payment_due_date = models.DateField(
        "Оплата от клиента до", null=True, blank=True, editable=False
    )
    executor_payment_due_date = models.DateField(
        "Оплата исполнителю до", null=True, blank=True, editable=False
    )
    cargo_name = models.CharField("Груз", max_length=255)
    cargo_description = models.TextField("Описание груза", blank=True)
    weight_kg = models.DecimalField(
        "Вес, кг",
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(Decimal("0"))],
    )
    volume_m3 = models.DecimalField(
        "Объём, м³",
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(Decimal("0"))],
    )
    package_count = models.PositiveIntegerField("Количество мест", null=True, blank=True)
    pallet_count = models.PositiveIntegerField("Количество паллет", null=True, blank=True)
    package_type = models.ForeignKey(
        PackageType,
        verbose_name="Вид упаковки",
        related_name="transportations",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )

    @property
    def total_package_count(self):
        return (self.package_count or 0) + (self.pallet_count or 0) or None
    loading_method = models.ForeignKey(
        CargoHandlingMethod,
        verbose_name="Способ погрузки",
        related_name="loading_transportations",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    unloading_method = models.ForeignKey(
        CargoHandlingMethod,
        verbose_name="Способ выгрузки",
        related_name="unloading_transportations",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    temperature_regime = models.CharField(
        "Температурный режим", max_length=100, blank=True
    )
    adr_class = models.CharField(
        "Класс опасности ADR", max_length=3, blank=True
    )
    vehicle_requirements = models.CharField(
        "Требования к транспорту", max_length=255, blank=True
    )
    special_requirements = models.TextField("Особые требования", blank=True)
    planned_start_date = models.DateField("Плановая дата начала", null=True, blank=True)
    planned_end_date = models.DateField("Плановая дата окончания", null=True, blank=True)
    legacy_chain_sync = models.BooleanField(
        "Синхронизировать цепочку со старой заявкой", default=True
    )
    notes = models.TextField("Комментарий", blank=True)

    class Meta:
        verbose_name = "перевозка / рейс"
        verbose_name_plural = "перевозки / рейсы"
        ordering = ("-planned_start_date", "-created_at")
        indexes = [
            models.Index(fields=("owner_company", "status")),
            models.Index(fields=("owner_company", "posting_status", "document_date")),
            models.Index(fields=("planned_start_date", "planned_end_date")),
            models.Index(fields=("manager", "status")),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("owner_company", "number_year", "number"),
                condition=~models.Q(number=""),
                name="unique_transportation_number_per_company_year",
            )
        ]

    def __str__(self):
        return f"{self.number or 'Черновик'} · {self.route}"

    def get_absolute_url(self):
        return reverse("transportation-detail", kwargs={"pk": self.pk})

    @property
    def route(self):
        stops = list(self.stops.all())
        if not stops:
            return "Маршрут не указан"
        points = [stop.city or stop.address for stop in stops]
        return " → ".join(point for point in points if point) or "Маршрут не указан"

    @property
    def revenue(self):
        return self.customer_amount

    @property
    def cost(self):
        return self.executor_amount

    @property
    def margin(self):
        return self.revenue - self.cost

    @property
    def margin_percent(self):
        if not self.revenue:
            return Decimal("0")
        return (self.margin / self.revenue * Decimal("100")).quantize(Decimal("0.01"))

    @property
    def customer_vat_amount(self):
        if not self.customer_vat_rate_id:
            return Decimal("0.00")
        return self.customer_vat_rate.vat_from_gross(self.customer_amount)

    @property
    def customer_amount_without_vat(self):
        return self.customer_amount - self.customer_vat_amount

    @property
    def executor_vat_amount(self):
        if not self.executor_vat_rate_id:
            return Decimal("0.00")
        return self.executor_vat_rate.vat_from_gross(self.executor_amount)

    @property
    def executor_amount_without_vat(self):
        return self.executor_amount - self.executor_vat_amount

    @property
    def vat_balance(self):
        """Output VAT less deductible input VAT for this transportation."""
        return self.customer_vat_amount - self.executor_vat_amount

    @property
    def vat_payable(self):
        return max(self.vat_balance, Decimal("0.00"))

    @property
    def profit(self):
        """Direct trip profit calculated from amounts excluding VAT."""
        return self.customer_amount_without_vat - self.executor_amount_without_vat

    @property
    def profit_tax_amount(self):
        taxable_profit = max(self.profit, Decimal("0.00"))
        rate = Decimal(self.owner_company.profit_tax_rate or 0)
        return (taxable_profit * rate / Decimal("100")).quantize(Decimal("0.01"))

    @property
    def net_profit(self):
        return self.profit - self.profit_tax_amount

    @property
    def receivable_balance(self):
        return self.settlement_movements.filter(
            side=SettlementMovement.Side.RECEIVABLE
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0")

    @property
    def payable_balance(self):
        return self.settlement_movements.filter(
            side=SettlementMovement.Side.PAYABLE
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0")

    def active_execution_link(self):
        return self.execution_links.filter(is_active=True).select_related(
            "contractor_party__organization", "contract"
        ).order_by("sequence").first()

    def active_vehicle_assignment(self):
        return self.vehicle_assignments.filter(is_active=True).select_related(
            "actual_carrier", "driver", "vehicle", "trailer", "combination"
        ).first()

    def chain_issues(self):
        issues = []
        link = self.active_execution_link()
        if not link:
            return ["Не выбран исполнитель"]
        if not link.contract_id:
            expected = (
                "договор перевозки"
                if link.contractor_role == TransportationLink.ContractorRole.CARRIER
                else "договор ТЭО"
            )
            issues.append(f"Не указан {expected} с исполнителем")
        assignment = self.active_vehicle_assignment()
        if not assignment or not assignment.actual_carrier_id:
            issues.append("Не указан фактический перевозчик")
            return issues
        if (
            link.contractor_role == TransportationLink.ContractorRole.CARRIER
            and assignment.actual_carrier_id != link.contractor_party.organization_id
        ):
            issues.append("Для прямого перевозчика исполнитель и фактический перевозчик должны совпадать")
        if not assignment.driver_id:
            issues.append("Не назначен водитель")
        if not assignment.vehicle_id:
            issues.append("Не назначен тягач или автомобиль")
        elif (
            assignment.vehicle.requires_trailer
            and not assignment.trailer_id
            and not assignment.trailer_registration_number
            and not assignment.vehicle.trailer_registration_number
        ):
            issues.append("Не указан полуприцеп")
        elif assignment.trailer_id and not assignment.vehicle.can_tow_trailer:
            issues.append("Для этого типа автомобиля прицеп не предусмотрен")
        return issues

    @property
    def chain_is_confirmed(self):
        return not self.chain_issues()

    def status_transition_issues(self, target_status):
        """Return human-readable reasons why a workflow transition is invalid."""

        if target_status not in self.Status.values:
            return ["Выбран неизвестный статус рейса."]
        if not self.pk or target_status == self.status:
            return []
        if self.status == self.Status.CANCELLED:
            return ["Отменённый рейс нельзя вернуть в работу."]
        if self.status == self.Status.CLOSED:
            return ["Закрытый рейс нельзя перевести на другой этап."]
        if target_status == self.Status.CANCELLED:
            if self.posting_status == self.PostingStatus.POSTED:
                return ["Сначала отмените проведение документа."]
            return []
        if target_status == self.Status.ON_HOLD:
            return []
        if self.status == self.Status.ON_HOLD:
            return []
        try:
            current_index = self.WORKFLOW_STATUSES.index(self.status)
            target_index = self.WORKFLOW_STATUSES.index(target_status)
        except ValueError:
            return []
        if target_index != current_index + 1:
            expected = self.WORKFLOW_STATUSES[current_index + 1]
            expected_label = dict(self.Status.choices).get(expected, expected)
            target_label = dict(self.Status.choices).get(target_status, target_status)
            return [
                f"После этапа «{self.get_status_display()}» доступен только этап «{expected_label}», а не «{target_label}»."
            ]
        return []

    @property
    def next_workflow_status(self):
        try:
            index = self.WORKFLOW_STATUSES.index(self.status)
        except ValueError:
            return None
        if index + 1 >= len(self.WORKFLOW_STATUSES):
            return None
        return self.WORKFLOW_STATUSES[index + 1]


class TransportationStop(TimestampedModel):
    class Kind(models.TextChoices):
        PICKUP = "pickup", "Погрузка"
        DELIVERY = "delivery", "Выгрузка"
        INTERMEDIATE = "intermediate", "Промежуточная точка"

    transportation = models.ForeignKey(
        Transportation,
        verbose_name="Рейс",
        related_name="stops",
        on_delete=models.CASCADE,
    )
    sequence = models.PositiveSmallIntegerField("Порядок")
    kind = models.CharField("Тип точки", max_length=20, choices=Kind.choices)
    organization = models.ForeignKey(
        Organization,
        verbose_name="Организация",
        related_name="transportation_stops",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    organization_text = models.CharField(
        "Наименование организации вручную", max_length=255, blank=True
    )
    city = models.CharField("Город", max_length=120)
    address = models.CharField("Адрес", max_length=255, blank=True)
    # Structured address parts returned by DaData.  ``city``/``address`` are
    # intentionally kept as the human-readable fallback used by old records.
    address_fias_id = models.CharField("ФИАС", max_length=36, blank=True)
    address_postal_code = models.CharField("Индекс", max_length=12, blank=True)
    address_region_code = models.CharField("Код региона", max_length=3, blank=True)
    address_region = models.CharField("Регион", max_length=150, blank=True)
    address_area = models.CharField("Район", max_length=150, blank=True)
    address_city = models.CharField("Населённый пункт", max_length=150, blank=True)
    address_settlement = models.CharField("Посёлок", max_length=150, blank=True)
    address_street = models.CharField("Улица", max_length=150, blank=True)
    address_house = models.CharField("Дом", max_length=30, blank=True)
    address_block = models.CharField("Корпус", max_length=30, blank=True)
    address_flat = models.CharField("Квартира", max_length=30, blank=True)
    contact_name = models.CharField("Контактное лицо", max_length=150, blank=True)
    contact_phone = models.CharField("Телефон", max_length=30, blank=True)
    planned_from = models.DateTimeField("План с", null=True, blank=True)
    planned_to = models.DateTimeField("План до", null=True, blank=True)
    actual_arrival = models.DateTimeField("Фактическое прибытие", null=True, blank=True)
    actual_departure = models.DateTimeField("Фактическое убытие", null=True, blank=True)
    instructions = models.TextField("Инструкции", blank=True)

    class Meta:
        verbose_name = "точка маршрута"
        verbose_name_plural = "точки маршрута"
        ordering = ("sequence",)
        constraints = [
            models.UniqueConstraint(
                fields=("transportation", "sequence"),
                name="unique_transportation_stop_sequence",
            )
        ]

    def __str__(self):
        return f"{self.sequence}. {self.get_kind_display()} · {self.city}"


class TransportOrderNumberSequence(TimestampedModel):
    owner_company = models.ForeignKey(
        Organization,
        verbose_name="Наша компания",
        related_name="order_number_sequences",
        on_delete=models.CASCADE,
    )
    year = models.PositiveSmallIntegerField("Год")
    last_value = models.PositiveIntegerField("Последний номер", default=0)

    class Meta:
        verbose_name = "нумератор заказов"
        verbose_name_plural = "нумераторы заказов"
        constraints = [
            models.UniqueConstraint(
                fields=("owner_company", "year"),
                name="unique_order_sequence_per_company_year",
            )
        ]

    def __str__(self):
        return f"{self.owner_company} · {self.year}: {self.last_value}"


class TransportOrder(TimestampedModel):
    class Status(models.TextChoices):
        NEW = "new", "Новый"
        ASSIGNED = "assigned", "Назначен в рейс"
        CANCELLED = "cancelled", "Отменён"

    class PaymentForm(models.TextChoices):
        BANK_VAT_0 = "bank_vat_0", "НДС 0%"
        BANK_VAT_5 = "bank_vat_5", "НДС 5%"
        BANK_VAT_7 = "bank_vat_7", "НДС 7%"
        BANK_VAT_10 = "bank_vat_10", "НДС 10%"
        BANK_VAT_18 = "bank_vat_18", "НДС 18%"
        BANK_VAT_20 = "bank_vat_20", "НДС 20%"
        BANK_VAT_22 = "bank_vat_22", "НДС 22%"
        BANK_NOT_TAXABLE = "bank_not_taxable", "НДС не облагается"
        CASH = "cash", "Наличные"

    class ADRClass(models.TextChoices):
        NONE = "", "Не относится к опасным грузам"
        CLASS_1 = "1", "Класс 1 — Взрывчатые вещества и изделия"
        CLASS_2_1 = "2.1", "Класс 2.1 — Воспламеняющиеся газы"
        CLASS_2_2 = "2.2", "Класс 2.2 — Невоспламеняющиеся нетоксичные газы"
        CLASS_2_3 = "2.3", "Класс 2.3 — Токсичные газы"
        CLASS_3 = "3", "Класс 3 — Легковоспламеняющиеся жидкости"
        CLASS_4_1 = "4.1", "Класс 4.1 — Легковоспламеняющиеся твёрдые вещества"
        CLASS_4_2 = "4.2", "Класс 4.2 — Самовозгорающиеся вещества"
        CLASS_4_3 = "4.3", "Класс 4.3 — Вещества, выделяющие горючие газы при контакте с водой"
        CLASS_5_1 = "5.1", "Класс 5.1 — Окисляющие вещества"
        CLASS_5_2 = "5.2", "Класс 5.2 — Органические пероксиды"
        CLASS_6_1 = "6.1", "Класс 6.1 — Токсичные вещества"
        CLASS_6_2 = "6.2", "Класс 6.2 — Инфекционные вещества"
        CLASS_7 = "7", "Класс 7 — Радиоактивные материалы"
        CLASS_8 = "8", "Класс 8 — Коррозионные вещества"
        CLASS_9 = "9", "Класс 9 — Прочие опасные вещества и изделия"

    @classmethod
    def payment_form_for_vat_rate(cls, vat_rate):
        """Choose the visible payment form from a customer's default VAT rate."""
        if not vat_rate:
            return cls.PaymentForm.BANK_VAT_22
        if vat_rate.is_without_vat:
            return cls.PaymentForm.BANK_NOT_TAXABLE
        rate_key = str(vat_rate.rate).rstrip("0").rstrip(".")
        return {
            "0": cls.PaymentForm.BANK_VAT_0,
            "5": cls.PaymentForm.BANK_VAT_5,
            "7": cls.PaymentForm.BANK_VAT_7,
            "10": cls.PaymentForm.BANK_VAT_10,
            "18": cls.PaymentForm.BANK_VAT_18,
            "20": cls.PaymentForm.BANK_VAT_20,
            "22": cls.PaymentForm.BANK_VAT_22,
        }.get(rate_key, cls.PaymentForm.BANK_VAT_22)

    number = models.CharField("Номер заказа", max_length=40, unique=True, blank=True)
    number_year = models.PositiveSmallIntegerField(
        "Год нумерации", null=True, blank=True, editable=False
    )
    document_date = models.DateField("Дата заказа", default=timezone.localdate)
    owner_company = models.ForeignKey(
        Organization,
        verbose_name="Наша компания",
        related_name="transport_orders",
        on_delete=models.PROTECT,
    )
    client = models.ForeignKey(
        Organization,
        verbose_name="Клиент",
        related_name="client_transport_orders",
        on_delete=models.PROTECT,
    )
    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Ответственный менеджер",
        related_name="transport_orders",
        on_delete=models.PROTECT,
    )
    status = models.CharField(
        "Статус", max_length=20, choices=Status.choices, default=Status.NEW
    )
    rate = models.DecimalField(
        "Ставка клиента",
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
    )
    currency = models.CharField(
        "Валюта",
        max_length=3,
        choices=[("RUB", "RUB"), ("USD", "USD"), ("EUR", "EUR")],
        default="RUB",
    )
    payment_form = models.CharField(
        "Форма оплаты",
        max_length=30,
        choices=PaymentForm.choices,
        default=PaymentForm.BANK_VAT_22,
    )
    payment_term_days = models.PositiveSmallIntegerField(
        "Отсрочка, дней", default=0
    )
    cargo_name = models.CharField("Наименование груза", max_length=255)
    cargo_description = models.TextField("Характеристики груза", blank=True)
    weight_kg = models.DecimalField(
        "Вес, кг",
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(Decimal("0"))],
    )
    volume_m3 = models.DecimalField(
        "Объём, м³",
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(Decimal("0"))],
    )
    package_count = models.PositiveIntegerField(
        "Количество мест", null=True, blank=True
    )
    pallet_count = models.PositiveIntegerField(
        "Количество паллет", null=True, blank=True
    )
    package_type = models.ForeignKey(
        PackageType,
        verbose_name="Вид упаковки",
        related_name="transport_orders",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )

    @property
    def total_package_count(self):
        return (self.package_count or 0) + (self.pallet_count or 0) or None
    temperature_regime = models.CharField(
        "Температурный режим", max_length=100, blank=True, default="Отсутствует"
    )
    adr_class = models.CharField(
        "Класс опасности ADR", max_length=3, choices=ADRClass.choices, blank=True
    )
    vehicle_requirements = models.CharField(
        "Требования к транспорту", max_length=255, blank=True
    )
    special_requirements = models.TextField("Особые требования", blank=True)
    planned_start_date = models.DateField(
        "Плановая дата начала", null=True, blank=True, editable=False
    )
    planned_end_date = models.DateField(
        "Плановая дата окончания", null=True, blank=True, editable=False
    )
    transportation = models.OneToOneField(
        Transportation,
        verbose_name="Созданный рейс",
        related_name="source_order",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    assigned_at = models.DateTimeField("Назначен", null=True, blank=True)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Назначил",
        related_name="assigned_transport_orders",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    notes = models.TextField("Комментарий", blank=True)

    class Meta:
        verbose_name = "заказ"
        verbose_name_plural = "заказы"
        ordering = ("-document_date", "-created_at")
        indexes = [
            models.Index(fields=("owner_company", "status")),
            models.Index(fields=("client", "document_date")),
            models.Index(fields=("planned_start_date", "planned_end_date")),
        ]

    def __str__(self):
        return f"{self.number or 'Новый заказ'} · {self.client}"

    def save(self, *args, **kwargs):
        if self.number:
            return super().save(*args, **kwargs)
        with transaction.atomic():
            year = self.document_date.year
            sequence, _ = (
                TransportOrderNumberSequence.objects.select_for_update().get_or_create(
                    owner_company=self.owner_company,
                    year=year,
                    defaults={"last_value": 0},
                )
            )
            sequence.last_value += 1
            sequence.save(update_fields=["last_value", "updated_at"])
            self.number_year = year
            self.number = f"ЗК-{year}-{sequence.last_value:05d}"
            return super().save(*args, **kwargs)

    @property
    def route(self):
        stops = list(self.stops.all())
        if not stops:
            return "Маршрут не указан"
        points = [stop.city or stop.address for stop in stops]
        return " → ".join(point for point in points if point) or "Маршрут не указан"

    def get_absolute_url(self):
        return reverse("order-update", kwargs={"pk": self.pk})


class TransportOrderStop(TimestampedModel):
    class Kind(models.TextChoices):
        PICKUP = "pickup", "Погрузка"
        DELIVERY = "delivery", "Выгрузка"

    order = models.ForeignKey(
        TransportOrder,
        verbose_name="Заказ",
        related_name="stops",
        on_delete=models.CASCADE,
    )
    sequence = models.PositiveSmallIntegerField("Порядок")
    kind = models.CharField("Операция", max_length=20, choices=Kind.choices)
    city = models.CharField("Город", max_length=120)
    address = models.CharField("Адрес", max_length=255, blank=True)
    address_fias_id = models.CharField("ФИАС", max_length=36, blank=True)
    address_postal_code = models.CharField("Индекс", max_length=12, blank=True)
    address_region_code = models.CharField("Код региона", max_length=3, blank=True)
    address_region = models.CharField("Регион", max_length=150, blank=True)
    address_area = models.CharField("Район", max_length=150, blank=True)
    address_city = models.CharField("Населённый пункт", max_length=150, blank=True)
    address_settlement = models.CharField("Посёлок", max_length=150, blank=True)
    address_street = models.CharField("Улица", max_length=150, blank=True)
    address_house = models.CharField("Дом", max_length=30, blank=True)
    address_block = models.CharField("Корпус", max_length=30, blank=True)
    address_flat = models.CharField("Квартира", max_length=30, blank=True)
    planned_date = models.DateField("Дата", null=True, blank=True)
    planned_time_from = models.TimeField("Время с", null=True, blank=True)
    planned_time_to = models.TimeField("Время до", null=True, blank=True)
    contact_name = models.CharField("Контактное лицо", max_length=150, blank=True)
    contact_phone = models.CharField("Телефон", max_length=30, blank=True)
    instructions = models.TextField("Инструкции", blank=True)

    class Meta:
        verbose_name = "точка маршрута заказа"
        verbose_name_plural = "точки маршрута заказа"
        ordering = ("sequence",)
        constraints = [
            models.UniqueConstraint(
                fields=("order", "sequence"),
                name="unique_transport_order_stop_sequence",
            )
        ]

    def clean(self):
        super().clean()
        if (
            self.planned_time_from
            and self.planned_time_to
            and self.planned_time_to < self.planned_time_from
        ):
            raise ValidationError(
                {"planned_time_to": "Окончание интервала не может быть раньше начала."}
            )

    def __str__(self):
        return f"{self.sequence}. {self.get_kind_display()} · {self.city}"


class TransportationParty(TimestampedModel):
    class Role(models.TextChoices):
        CLIENT = "client", "Клиент"
        OWN_COMPANY = "own_company", "Наша компания / экспедитор"
        EXECUTOR = "executor", "Наш исполнитель"
        FORWARDER = "forwarder", "Привлечённый экспедитор"
        FACTUAL_CARRIER = "factual_carrier", "Фактический перевозчик"
        SHIPPER = "shipper", "Грузоотправитель"
        CONSIGNEE = "consignee", "Грузополучатель"
        PAYER = "payer", "Плательщик"

    transportation = models.ForeignKey(
        Transportation,
        verbose_name="Рейс",
        related_name="parties",
        on_delete=models.CASCADE,
    )
    organization = models.ForeignKey(
        Organization,
        verbose_name="Организация",
        related_name="transportation_participations",
        on_delete=models.PROTECT,
    )
    role = models.CharField("Роль в рейсе", max_length=30, choices=Role.choices)
    sequence = models.PositiveSmallIntegerField("Порядок", default=0)
    source = models.CharField("Источник", max_length=20, default="manual")
    is_active = models.BooleanField("Активен", default=True)
    notes = models.TextField("Комментарий", blank=True)

    class Meta:
        verbose_name = "участник рейса"
        verbose_name_plural = "участники рейса"
        ordering = ("sequence", "created_at")
        constraints = [
            models.UniqueConstraint(
                fields=("transportation", "organization", "role"),
                name="unique_transportation_organization_role",
            )
        ]

    def __str__(self):
        return f"{self.transportation.number} · {self.get_role_display()} · {self.organization}"


class TransportationLink(TimestampedModel):
    class ContractorRole(models.TextChoices):
        FORWARDER = "forwarder", "Экспедитор"
        CARRIER = "carrier", "Перевозчик"

    transportation = models.ForeignKey(
        Transportation,
        verbose_name="Рейс",
        related_name="execution_links",
        on_delete=models.CASCADE,
    )
    parent = models.ForeignKey(
        "self",
        verbose_name="Предыдущее звено",
        related_name="children",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    principal_party = models.ForeignKey(
        TransportationParty,
        verbose_name="Кто поручил",
        related_name="outgoing_links",
        on_delete=models.PROTECT,
    )
    contractor_party = models.ForeignKey(
        TransportationParty,
        verbose_name="Кому поручили",
        related_name="incoming_links",
        on_delete=models.PROTECT,
    )
    contractor_role = models.CharField(
        "Роль исполнителя", max_length=20, choices=ContractorRole.choices
    )
    sequence = models.PositiveSmallIntegerField("Порядок")
    contract = models.ForeignKey(
        Contract,
        verbose_name="Договор",
        related_name="transportation_links",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    instruction_number = models.CharField("Номер поручения / заявки", max_length=100, blank=True)
    instruction_status = models.CharField("Статус поручения / заявки", max_length=100, blank=True)
    source = models.CharField("Источник", max_length=20, default="manual")
    is_active = models.BooleanField("Активно", default=True)
    verified_at = models.DateTimeField("Документы проверены", null=True, blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Проверил",
        related_name="verified_transportation_links",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "звено цепочки исполнения"
        verbose_name_plural = "звенья цепочки исполнения"
        ordering = ("sequence",)
        constraints = [
            models.UniqueConstraint(
                fields=("transportation", "sequence"),
                name="unique_transportation_link_sequence",
            )
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.principal_party_id == self.contractor_party_id:
            errors["contractor_party"] = "Нельзя поручить рейс тому же участнику."
        if self.principal_party_id and self.principal_party.transportation_id != self.transportation_id:
            errors["principal_party"] = "Участник должен относиться к этому рейсу."
        if self.contractor_party_id and self.contractor_party.transportation_id != self.transportation_id:
            errors["contractor_party"] = "Участник должен относиться к этому рейсу."
        if self.parent_id and self.parent.transportation_id != self.transportation_id:
            errors["parent"] = "Предыдущее звено должно относиться к этому рейсу."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.principal_party.organization} → {self.contractor_party.organization}"


class VehicleAssignment(TimestampedModel):
    transportation = models.ForeignKey(
        Transportation,
        verbose_name="Рейс",
        related_name="vehicle_assignments",
        on_delete=models.CASCADE,
    )
    execution_link = models.ForeignKey(
        TransportationLink,
        verbose_name="Конечное звено",
        related_name="vehicle_assignments",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    combination = models.ForeignKey(
        "VehicleCombination",
        verbose_name="Сцепка",
        related_name="vehicle_assignments",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    actual_carrier = models.ForeignKey(
        Organization,
        verbose_name="Фактический перевозчик",
        related_name="factual_transportations",
        on_delete=models.PROTECT,
    )
    driver = models.ForeignKey(
        Driver,
        verbose_name="Водитель",
        related_name="transportation_assignments",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    vehicle = models.ForeignKey(
        Vehicle,
        verbose_name="Тягач / автомобиль",
        related_name="transportation_assignments",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    trailer = models.ForeignKey(
        Vehicle,
        verbose_name="Прицеп / полуприцеп",
        related_name="trailer_transportation_assignments",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    trailer_registration_number = models.CharField(
        "Номер прицепа / полуприцепа", max_length=20, blank=True
    )
    is_active = models.BooleanField("Текущее назначение", default=True)
    confirmed_at = models.DateTimeField("Подтверждено", null=True, blank=True)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Подтвердил",
        related_name="confirmed_vehicle_assignments",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    notes = models.TextField("Комментарий", blank=True)

    class Meta:
        verbose_name = "назначение транспорта"
        verbose_name_plural = "назначения транспорта"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("transportation",),
                condition=models.Q(is_active=True),
                name="unique_active_vehicle_assignment",
            )
        ]

    def clean(self):
        super().clean()
        errors = {}
        combination = self.combination
        if combination:
            if (
                self.actual_carrier_id
                and combination.tractor.carrier.organization_id != self.actual_carrier_id
            ):
                errors["combination"] = "Сцепка должна принадлежать фактическому перевозчику."
            if self.is_active and not combination.is_active:
                errors["combination"] = "Выберите активную сцепку."
            if self.vehicle_id and self.vehicle_id != combination.tractor_id:
                errors["vehicle"] = "Основной автомобиль не соответствует выбранной сцепке."
            if self.trailer_id and self.trailer_id != combination.trailer_id:
                errors["trailer"] = "Прицеп не соответствует выбранной сцепке."
            if not self.vehicle_id:
                errors["vehicle"] = "Укажите основной автомобиль из выбранной сцепки."
            if not self.trailer_id:
                errors["trailer"] = "Укажите прицеп из выбранной сцепки."
        if self.driver_id and not self.driver.works_for_organization(
            self.actual_carrier_id
        ):
            errors["driver"] = "Водитель должен принадлежать фактическому перевозчику."
        if self.vehicle_id and self.vehicle.carrier.organization_id != self.actual_carrier_id:
            errors["vehicle"] = "Транспорт должен принадлежать фактическому перевозчику."
        if self.trailer_id and self.trailer.carrier.organization_id != self.actual_carrier_id:
            errors["trailer"] = "Прицеп должен принадлежать фактическому перевозчику."
        if self.vehicle_id and self.vehicle.is_trailer:
            errors["vehicle"] = "В качестве основного автомобиля нельзя выбрать прицеп."
        if self.trailer_id and not self.trailer.is_trailer:
            errors["trailer"] = "В поле прицепа можно выбрать только прицеп или полуприцеп."
        if (
            self.vehicle_id
            and self.trailer_id
            and not self.vehicle.can_tow_trailer
        ):
            errors["trailer"] = "Для этого типа автомобиля прицеп не предусмотрен."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.transportation.number} · {self.actual_carrier}"


class Payment(TimestampedModel):
    class Direction(models.TextChoices):
        INCOME = "income", "Поступление от клиента"
        EXPENSE = "expense", "Оплата перевозчику"

    class Method(models.TextChoices):
        BANK = "bank", "Банковский перевод"
        CASH = "cash", "Наличные"
        CARD = "card", "Банковская карта"
        OFFSET = "offset", "Взаимозачёт"
        OTHER = "other", "Другое"

    shipment = models.ForeignKey(
        Shipment,
        verbose_name="Заявка",
        related_name="payments",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    transportation = models.ForeignKey(
        Transportation,
        verbose_name="Перевозка / рейс",
        related_name="payments",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    direction = models.CharField(
        "Операция", max_length=10, choices=Direction.choices
    )
    amount = models.DecimalField(
        "Сумма",
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    payment_date = models.DateField("Дата платежа", default=timezone.localdate)
    method = models.CharField(
        "Способ оплаты", max_length=20, choices=Method.choices, default=Method.BANK
    )
    reference = models.CharField(
        "Платёжное поручение", max_length=100, blank=True
    )
    notes = models.TextField("Комментарий", blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Добавил",
        related_name="created_payments",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "платёж"
        verbose_name_plural = "платежи"
        ordering = ("-payment_date", "-created_at")
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(shipment__isnull=False, transportation__isnull=True)
                    | models.Q(shipment__isnull=True, transportation__isnull=False)
                ),
                name="payment_has_exactly_one_document",
            )
        ]

    def __str__(self):
        document = self.transportation or self.shipment
        currency = document.currency if document else "RUB"
        return f"{self.get_direction_display()} · {self.amount} {currency}"

    def get_absolute_url(self):
        if self.transportation_id:
            return reverse(
                "transportation-payment-update",
                kwargs={
                    "transportation_pk": self.transportation_id,
                    "pk": self.pk,
                },
            )
        return reverse(
            "payment-update",
            kwargs={"shipment_pk": self.shipment_id, "pk": self.pk},
        )

    def clean(self):
        super().clean()
        if bool(self.shipment_id) == bool(self.transportation_id):
            raise ValidationError(
                "Платёж должен быть привязан ровно к одной заявке или перевозке."
            )
        if (
            self.direction == self.Direction.EXPENSE
            and self.shipment_id
            and not self.shipment.carrier_id
        ):
            raise ValidationError(
                {"direction": "Нельзя оплатить перевозчику, пока он не назначен."}
            )
        if self.direction == self.Direction.EXPENSE and self.transportation_id:
            if not self.transportation.active_execution_link():
                raise ValidationError(
                    {"direction": "Нельзя оплатить исполнителю, пока он не назначен."}
                )

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.shipment_id:
            shipment = Shipment.objects.get(pk=self.shipment_id)
            shipment.refresh_payment_status()

    def delete(self, *args, **kwargs):
        shipment_id = self.shipment_id
        result = super().delete(*args, **kwargs)
        shipment = Shipment.objects.filter(pk=shipment_id).first()
        if shipment:
            shipment.refresh_payment_status()
        return result


class BankStatementNumberSequence(TimestampedModel):
    owner_company = models.ForeignKey(
        Organization,
        verbose_name="Наша компания",
        related_name="bank_statement_number_sequences",
        on_delete=models.CASCADE,
    )
    year = models.PositiveSmallIntegerField("Год")
    last_value = models.PositiveIntegerField("Последний номер", default=0)

    class Meta:
        verbose_name = "нумератор банковских документов"
        verbose_name_plural = "нумераторы банковских документов"
        constraints = [
            models.UniqueConstraint(
                fields=("owner_company", "year"),
                name="unique_bank_statement_sequence_per_company_year",
            )
        ]

    def __str__(self):
        return f"{self.owner_company} · {self.year}: {self.last_value}"


class BankStatement(TimestampedModel):
    """Групповой банковский документ для проведения платежей по рейсам."""

    class Direction(models.TextChoices):
        INCOME = "income", "Приход от клиентов"
        EXPENSE = "expense", "Расход перевозчикам"

    class Status(models.TextChoices):
        DRAFT = "draft", "Черновик"
        POSTED = "posted", "Проведён"
        VOIDED = "voided", "Аннулирован"

    number = models.CharField(
        "Номер банковского документа", max_length=40, unique=True, blank=True
    )
    statement_date = models.DateField("Дата выписки", default=timezone.localdate)
    direction = models.CharField(
        "Вид операции", max_length=10, choices=Direction.choices, default=Direction.INCOME
    )
    status = models.CharField(
        "Статус", max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    owner_company = models.ForeignKey(
        Organization,
        verbose_name="Наша компания",
        related_name="bank_statements",
        on_delete=models.PROTECT,
    )
    bank_account = models.ForeignKey(
        OrganizationBankAccount,
        verbose_name="Банковский счёт",
        related_name="bank_statements",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    currency = models.CharField(
        "Валюта",
        max_length=3,
        choices=[("RUB", "RUB"), ("USD", "USD"), ("EUR", "EUR")],
        default="RUB",
    )
    reference = models.CharField(
        "Номер банковской выписки", max_length=100, blank=True
    )
    notes = models.TextField("Комментарий", blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Создал",
        related_name="created_bank_statements",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Провёл",
        related_name="posted_bank_statements",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    posted_at = models.DateTimeField("Дата проведения", null=True, blank=True)

    class Meta:
        verbose_name = "банковский приход / расход"
        verbose_name_plural = "банковские приходы / расходы"
        ordering = ("-statement_date", "-created_at")
        indexes = [
            models.Index(fields=("owner_company", "statement_date")),
            models.Index(fields=("status", "direction")),
        ]

    def __str__(self):
        return f"{self.number or 'Новый документ'} · {self.get_direction_display()}"

    def save(self, *args, **kwargs):
        if self.number:
            return super().save(*args, **kwargs)
        with transaction.atomic():
            year = self.statement_date.year
            sequence, _ = BankStatementNumberSequence.objects.select_for_update().get_or_create(
                owner_company=self.owner_company,
                year=year,
                defaults={"last_value": 0},
            )
            sequence.last_value += 1
            sequence.save(update_fields=["last_value", "updated_at"])
            self.number = f"ПБ-{year}-{sequence.last_value:05d}"
            return super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if self.bank_account_id and self.owner_company_id:
            if self.bank_account.organization_id != self.owner_company_id:
                raise ValidationError(
                    {"bank_account": "Банковский счёт должен принадлежать нашей компании."}
                )
            if self.bank_account.currency != self.currency:
                raise ValidationError(
                    {"currency": "Валюта выписки должна совпадать с валютой банковского счёта."}
                )

    @property
    def total_amount(self):
        return self.lines.aggregate(total=Sum("amount"))["total"] or Decimal("0")

    @property
    def line_count(self):
        return self.lines.count()

    def get_absolute_url(self):
        return reverse("bank-statement-detail", kwargs={"pk": self.pk})


class BankStatementLine(TimestampedModel):
    statement = models.ForeignKey(
        BankStatement,
        verbose_name="Банковский документ",
        related_name="lines",
        on_delete=models.CASCADE,
    )
    transportation = models.ForeignKey(
        Transportation,
        verbose_name="Рейс",
        related_name="bank_statement_lines",
        on_delete=models.PROTECT,
    )
    amount = models.DecimalField(
        "Сумма",
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    payment_reference = models.CharField(
        "Платёжное поручение",
        max_length=100,
        blank=True,
        help_text="Номер или реквизиты платёжного поручения из банковской выписки.",
    )
    payment = models.OneToOneField(
        Payment,
        verbose_name="Созданный платёж",
        related_name="bank_statement_line",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "строка банковского документа"
        verbose_name_plural = "строки банковского документа"
        constraints = [
            models.UniqueConstraint(
                fields=("statement", "transportation"),
                name="unique_bank_statement_transportation",
            )
        ]

    def __str__(self):
        return f"{self.statement} · {self.transportation} · {self.amount}"


class TransportationInstruction(TimestampedModel):
    class Kind(models.TextChoices):
        CLIENT_ORDER = "client_order", "Поручение клиента"
        CARRIER_APPLICATION = "carrier_application", "Заявка перевозчику"
        FORWARDER_INSTRUCTION = (
            "forwarder_instruction",
            "Поручение привлечённому экспедитору",
        )

    class Status(models.TextChoices):
        DRAFT = "draft", "Черновик"
        READY = "ready", "Подготовлен"
        SIGNED = "signed", "Подписан"
        CANCELLED = "cancelled", "Аннулирован"

    transportation = models.ForeignKey(
        Transportation,
        verbose_name="Заявка / рейс",
        related_name="instructions",
        on_delete=models.CASCADE,
    )
    kind = models.CharField("Вид документа", max_length=30, choices=Kind.choices)
    number = models.CharField("Номер", max_length=100)
    document_date = models.DateField("Дата", default=timezone.localdate)
    counterparty = models.ForeignKey(
        Organization,
        verbose_name="Контрагент",
        related_name="transportation_instructions",
        on_delete=models.PROTECT,
    )
    contract = models.ForeignKey(
        Contract,
        verbose_name="Договор",
        related_name="transportation_instructions",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    status = models.CharField(
        "Статус", max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    generated_on_posting = models.BooleanField("Создан при проведении", default=True)

    class Meta:
        verbose_name = "поручение / заявка по рейсу"
        verbose_name_plural = "поручения / заявки по рейсам"
        ordering = ("kind", "created_at")
        constraints = [
            models.UniqueConstraint(
                fields=("transportation", "kind"),
                name="unique_instruction_kind_per_transportation",
            )
        ]

    def __str__(self):
        return f"{self.get_kind_display()} № {self.number}"


class TripCharge(TimestampedModel):
    class Direction(models.TextChoices):
        REVENUE = "revenue", "Доход"
        COST = "cost", "Расход"

    transportation = models.ForeignKey(
        Transportation,
        verbose_name="Документ-регистратор",
        related_name="charges",
        on_delete=models.CASCADE,
    )
    direction = models.CharField("Вид движения", max_length=10, choices=Direction.choices)
    owner_company = models.ForeignKey(
        Organization,
        verbose_name="Наша компания",
        related_name="trip_charges",
        on_delete=models.PROTECT,
    )
    counterparty = models.ForeignKey(
        Organization,
        verbose_name="Контрагент",
        related_name="counterparty_trip_charges",
        on_delete=models.PROTECT,
    )
    contract = models.ForeignKey(
        Contract,
        verbose_name="Договор",
        related_name="trip_charges",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    amount = models.DecimalField("Сумма всего", max_digits=14, decimal_places=2)
    amount_without_vat = models.DecimalField(
        "Сумма без НДС", max_digits=14, decimal_places=2
    )
    vat_amount = models.DecimalField("Сумма НДС", max_digits=14, decimal_places=2)
    vat_rate = models.ForeignKey(
        VATRate,
        verbose_name="Ставка НДС",
        related_name="trip_charges",
        on_delete=models.PROTECT,
    )
    currency = models.CharField("Валюта", max_length=3, default="RUB")
    movement_date = models.DateField("Период")

    class Meta:
        verbose_name = "движение доходов / расходов"
        verbose_name_plural = "движения доходов / расходов"
        ordering = ("movement_date", "direction")
        constraints = [
            models.UniqueConstraint(
                fields=("transportation", "direction"),
                name="unique_trip_charge_direction",
            )
        ]

    def __str__(self):
        return f"{self.get_direction_display()} · {self.transportation} · {self.amount}"


class SettlementMovement(TimestampedModel):
    class Side(models.TextChoices):
        RECEIVABLE = "receivable", "Дебиторская задолженность"
        PAYABLE = "payable", "Кредиторская задолженность"

    class Kind(models.TextChoices):
        ACCRUAL = "accrual", "Начисление"
        PAYMENT = "payment", "Оплата"

    transportation = models.ForeignKey(
        Transportation,
        verbose_name="Заявка / рейс",
        related_name="settlement_movements",
        on_delete=models.CASCADE,
    )
    payment = models.OneToOneField(
        Payment,
        verbose_name="Платёж-регистратор",
        related_name="settlement_movement",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    side = models.CharField("Сторона расчётов", max_length=15, choices=Side.choices)
    kind = models.CharField("Вид движения", max_length=10, choices=Kind.choices)
    owner_company = models.ForeignKey(
        Organization,
        verbose_name="Наша компания",
        related_name="settlement_movements",
        on_delete=models.PROTECT,
    )
    counterparty = models.ForeignKey(
        Organization,
        verbose_name="Контрагент",
        related_name="counterparty_settlement_movements",
        on_delete=models.PROTECT,
    )
    contract = models.ForeignKey(
        Contract,
        verbose_name="Договор",
        related_name="settlement_movements",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    amount = models.DecimalField(
        "Движение задолженности",
        max_digits=14,
        decimal_places=2,
        help_text="Начисление положительное, оплата отрицательная.",
    )
    currency = models.CharField("Валюта", max_length=3, default="RUB")
    movement_date = models.DateField("Период")
    due_date = models.DateField("Срок оплаты", null=True, blank=True)

    class Meta:
        verbose_name = "движение взаиморасчётов"
        verbose_name_plural = "движения взаиморасчётов"
        ordering = ("movement_date", "created_at")
        constraints = [
            models.UniqueConstraint(
                fields=("transportation", "side", "kind"),
                condition=models.Q(kind="accrual"),
                name="unique_trip_settlement_accrual",
            )
        ]

    def __str__(self):
        return f"{self.get_side_display()} · {self.amount} {self.currency}"


class TransportationIncident(TimestampedModel):
    """Claim, penalty or operational incident linked to a transportation."""

    class Kind(models.TextChoices):
        CLIENT_PENALTY = "client_penalty", "Штраф клиенту"
        CARRIER_PENALTY = "carrier_penalty", "Штраф перевозчику"
        CLAIM = "claim", "Претензия"
        SHORTAGE = "shortage", "Недостача"
        DAMAGE = "damage", "Повреждение груза"
        DELAY = "delay", "Срыв сроков"
        IDLE = "idle", "Простой"
        EXTRA_COST = "extra_cost", "Дополнительный расход"

    class Status(models.TextChoices):
        OPEN = "open", "Открыта"
        IN_PROGRESS = "in_progress", "В работе"
        RESOLVED = "resolved", "Закрыта"
        CANCELLED = "cancelled", "Отменена"

    class FinancialImpact(models.TextChoices):
        NONE = "none", "Не влияет на финансы"
        INCOME = "income", "Дополнительный доход"
        EXPENSE = "expense", "Дополнительный расход"

    transportation = models.ForeignKey(
        Transportation,
        verbose_name="Рейс",
        related_name="incidents",
        on_delete=models.CASCADE,
    )
    kind = models.CharField("Вид события", max_length=30, choices=Kind.choices)
    status = models.CharField(
        "Статус", max_length=20, choices=Status.choices, default=Status.OPEN
    )
    counterparty = models.ForeignKey(
        Organization,
        verbose_name="Контрагент",
        related_name="transportation_incidents",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    occurred_on = models.DateField("Дата события", default=timezone.localdate)
    title = models.CharField("Краткое описание", max_length=255)
    description = models.TextField("Описание", blank=True)
    financial_impact = models.CharField(
        "Финансовый эффект",
        max_length=10,
        choices=FinancialImpact.choices,
        default=FinancialImpact.NONE,
    )
    amount = models.DecimalField(
        "Сумма", max_digits=14, decimal_places=2, default=0,
        validators=[MinValueValidator(Decimal("0"))],
    )
    currency = models.CharField(
        "Валюта", max_length=3,
        choices=[("RUB", "RUB"), ("USD", "USD"), ("EUR", "EUR")],
        default="RUB",
    )
    resolution = models.TextField("Решение / результат", blank=True)
    document_file = models.FileField(
        "Подтверждающий документ",
        upload_to="transportation-incidents/%Y/%m/",
        blank=True,
        null=True,
        validators=[FileExtensionValidator(["pdf", "jpg", "jpeg", "png"])],
    )
    resolved_on = models.DateField("Дата закрытия", null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Создал",
        related_name="created_transportation_incidents",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "штраф / претензия по рейсу"
        verbose_name_plural = "штрафы и претензии по рейсам"
        ordering = ("-occurred_on", "-created_at")
        indexes = [models.Index(fields=("transportation", "status"))]

    def __str__(self):
        return f"{self.get_kind_display()} · {self.title}"

    def get_absolute_url(self):
        return reverse(
            "transportation-incident-update",
            kwargs={"transportation_pk": self.transportation_id, "pk": self.pk},
        )


class TransportationStatusEvent(TimestampedModel):
    class Source(models.TextChoices):
        DOCUMENT = "document", "Карточка рейса"
        ORDER = "order", "Заказ"
        POSTING = "posting", "Проведение"
        UNPOSTING = "unposting", "Отмена проведения"
        CHAIN = "chain", "Цепочка исполнения"
        PAYMENT = "payment", "Платёж"
        INCIDENT = "incident", "Штраф / претензия"
        EPD = "epd", "ЭПД"
        MANUAL = "manual", "Вручную"

    transportation = models.ForeignKey(
        Transportation,
        verbose_name="Заявка / рейс",
        related_name="status_events",
        on_delete=models.CASCADE,
    )
    old_status = models.CharField("Предыдущий статус", max_length=40, blank=True)
    new_status = models.CharField("Новый статус", max_length=40)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Изменил",
        related_name="transportation_status_events",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    comment = models.CharField("Комментарий", max_length=255, blank=True)
    source = models.CharField(
        "Источник", max_length=30, choices=Source.choices, default=Source.MANUAL
    )
    changes = models.JSONField(
        "Изменения",
        default=dict,
        blank=True,
        help_text="Пары значений «было → стало» для аудита документа.",
    )

    class Meta:
        verbose_name = "событие статуса рейса"
        verbose_name_plural = "история статусов рейса"
        ordering = ("created_at",)

    def __str__(self):
        return f"{self.transportation} · {self.old_status} → {self.new_status}"

    @staticmethod
    def _status_label(value):
        labels = dict(Transportation.Status.choices)
        labels.update(dict(Transportation.PostingStatus.choices))
        return labels.get(value, value)


class PlannerTask(TimestampedModel):
    """Ручное поручение менеджеру в планировщике.

    События рейса (погрузка, выгрузка, сроки оплаты) вычисляются из карточки
    перевозки. Здесь храним только то, что пользователь добавил вручную, чтобы
    не создавать дубликаты маршрута и финансовых сроков.
    """

    class Kind(models.TextChoices):
        MANUAL = "manual", "Поручение"
        ASSIGNMENT = "assignment", "Назначение исполнителя"
        DOCUMENT = "document", "Документы"
        PAYMENT = "payment", "Оплата"
        CONTROL = "control", "Контроль рейса"
        OTHER = "other", "Другое"

    class Status(models.TextChoices):
        TODO = "todo", "Новая"
        IN_PROGRESS = "in_progress", "В работе"
        DONE = "done", "Выполнена"
        CANCELLED = "cancelled", "Отменена"

    class Priority(models.TextChoices):
        LOW = "low", "Низкий"
        NORMAL = "normal", "Обычный"
        HIGH = "high", "Высокий"
        URGENT = "urgent", "Срочный"

    transportation = models.ForeignKey(
        Transportation,
        verbose_name="Рейс",
        related_name="planner_tasks",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    title = models.CharField("Задача", max_length=255)
    description = models.TextField("Описание", blank=True)
    kind = models.CharField(
        "Тип", max_length=30, choices=Kind.choices, default=Kind.MANUAL
    )
    status = models.CharField(
        "Статус", max_length=20, choices=Status.choices, default=Status.TODO
    )
    priority = models.CharField(
        "Приоритет", max_length=20, choices=Priority.choices, default=Priority.NORMAL
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Ответственный",
        related_name="planner_tasks",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    due_date = models.DateField("Срок", null=True, blank=True)
    completed_at = models.DateTimeField("Выполнена", null=True, blank=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Завершил",
        related_name="completed_planner_tasks",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "задача планировщика"
        verbose_name_plural = "задачи планировщика"
        ordering = ("due_date", "-priority", "-created_at")
        indexes = [
            models.Index(fields=("status", "due_date")),
            models.Index(fields=("assignee", "status")),
            models.Index(fields=("transportation", "due_date")),
        ]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("planner-task-update", kwargs={"pk": self.pk})

    @property
    def is_overdue(self):
        return bool(
            self.due_date
            and self.due_date < timezone.localdate()
            and self.status in {self.Status.TODO, self.Status.IN_PROGRESS}
        )

    @property
    def old_status_label(self):
        return self._status_label(self.old_status) if self.old_status else ""

    @property
    def new_status_label(self):
        return self._status_label(self.new_status) if self.new_status else ""


class NotificationRead(TimestampedModel):
    """Marks a calculated navigation notification as read for one user."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Пользователь",
        related_name="crm_notification_reads",
        on_delete=models.CASCADE,
    )
    notification_key = models.CharField("Ключ уведомления", max_length=255)
    read_at = models.DateTimeField("Прочитано", default=timezone.now)

    class Meta:
        verbose_name = "прочитанное уведомление"
        verbose_name_plural = "прочитанные уведомления"
        constraints = [
            models.UniqueConstraint(
                fields=("user", "notification_key"),
                name="unique_user_notification_read",
            )
        ]

class TransportationElectronicDocument(TimestampedModel):
    """Electronic transport document prepared for an EPD operator.

    The model deliberately keeps a canonical payload and the generated XML
    separately from operator-specific exchange identifiers.  This lets us
    support Kontur and Saby without coupling the transportation register to a
    single provider's API or schema.
    """

    class Kind(models.TextChoices):
        EZZ = "ezz", "ЭЗЗ · заказ-заявка"
        EPE = "epe", "ЭПЭ · поручение экспедитору"
        EER = "eer", "ЭЭР · экспедиторская расписка"
        ETRN = "etrn", "ЭТрН · электронная транспортная накладная"

    class Provider(models.TextChoices):
        INTERNAL = "internal", "Внутренний черновик"
        KONTUR = "kontur", "Контур.Логистика"
        SABY = "saby", "Saby (СБИС)"

    class Status(models.TextChoices):
        DRAFT = "draft", "Черновик"
        READY = "ready", "Подготовлен"
        SENT = "sent", "Отправлен"
        PROCESSING = "processing", "Обрабатывается"
        ACCEPTED = "accepted", "Принят"
        ACCEPTED_WITH_WARNINGS = "accepted_with_warnings", "Принят с предупреждениями"
        REJECTED = "rejected", "Отклонён"
        ERROR = "error", "Ошибка обмена"
        CANCELLED = "cancelled", "Аннулирован"

    transportation = models.ForeignKey(
        Transportation,
        verbose_name="Рейс",
        related_name="electronic_documents",
        on_delete=models.CASCADE,
    )
    stop = models.ForeignKey(
        TransportationStop,
        verbose_name="Точка маршрута",
        related_name="electronic_documents",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="Для ЭТрН указывается точка выгрузки; остальные документы относятся ко всему рейсу.",
    )
    kind = models.CharField("Вид ЭПД", max_length=10, choices=Kind.choices)
    provider = models.CharField(
        "Оператор", max_length=20, choices=Provider.choices, default=Provider.INTERNAL
    )
    number = models.CharField("Номер документа", max_length=100, blank=True)
    status = models.CharField(
        "Статус", max_length=30, choices=Status.choices, default=Status.DRAFT
    )
    external_id = models.CharField("Идентификатор у оператора", max_length=255, blank=True)
    external_status = models.CharField("Статус у оператора", max_length=100, blank=True)
    title_statuses = models.JSONField(
        "Статусы титулов", default=dict, blank=True,
        help_text="Например: {'1': 'draft', '2': 'signed'}.",
    )
    payload = models.JSONField("Каноническое содержимое", default=dict, blank=True)
    raw_xml = models.TextField("Сформированный XML", blank=True)
    operator_xml = models.TextField(
        "XML UserDataXml оператора",
        blank=True,
        help_text="Упрощённый XML для GenerateTitleXml; итоговый титул формирует оператор ЭПД.",
    )
    generated_xml = models.TextField(
        "Итоговый XML титула",
        blank=True,
        help_text="XML, возвращённый Контур.Диадок после GenerateTitleXml.",
    )
    last_error = models.TextField("Последняя ошибка", blank=True)
    sent_at = models.DateTimeField("Отправлен", null=True, blank=True)
    processed_at = models.DateTimeField("Обработан", null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Подготовил",
        related_name="created_transportation_electronic_documents",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "электронный перевозочный документ"
        verbose_name_plural = "электронные перевозочные документы"
        ordering = ("kind", "stop__sequence", "created_at")
        indexes = [
            models.Index(fields=("transportation", "kind", "status")),
            models.Index(fields=("provider", "status")),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("transportation", "kind"),
                condition=models.Q(stop__isnull=True),
                name="unique_transportation_epd_kind_whole_trip",
            ),
            models.UniqueConstraint(
                fields=("transportation", "kind", "stop"),
                condition=models.Q(stop__isnull=False),
                name="unique_transportation_epd_kind_stop",
            ),
        ]

    def __str__(self):
        suffix = f" · {self.stop}" if self.stop_id else ""
        return f"{self.get_kind_display()} · {self.transportation}{suffix}"

    @property
    def is_terminal(self):
        return self.status in {
            self.Status.ACCEPTED,
            self.Status.ACCEPTED_WITH_WARNINGS,
            self.Status.REJECTED,
            self.Status.ERROR,
            self.Status.CANCELLED,
        }

    def get_absolute_url(self):
        return reverse(
            "transportation-epd-download",
            kwargs={"transportation_pk": self.transportation_id, "pk": self.pk},
        )


class ForwardingOrder(TimestampedModel):
    class Insurance(models.TextChoices):
        NOT_SPECIFIED = "", "Не указано"
        YES = "yes", "Да"
        NO = "no", "Нет"

    shipment = models.OneToOneField(
        Shipment,
        verbose_name="Заявка",
        related_name="forwarding_order",
        on_delete=models.CASCADE,
    )
    contract_number = models.CharField("Номер договора", max_length=100, blank=True)
    contract_date = models.DateField("Дата договора", null=True, blank=True)
    order_date = models.DateField("Дата поручения", null=True, blank=True)

    shipper_name = models.CharField("Грузоотправитель", max_length=255, blank=True)
    shipper_tax_id = models.CharField("ИНН грузоотправителя", max_length=20, blank=True)
    shipper_address = models.CharField(
        "Адрес грузоотправителя", max_length=255, blank=True
    )
    shipper_contact_name = models.CharField(
        "Контактное лицо грузоотправителя", max_length=150, blank=True
    )
    shipper_phone = models.CharField(
        "Телефон грузоотправителя", max_length=30, blank=True
    )

    consignee_name = models.CharField("Грузополучатель", max_length=255, blank=True)
    consignee_address = models.CharField(
        "Адрес грузополучателя", max_length=255, blank=True
    )
    consignee_contact_name = models.CharField(
        "Контактное лицо грузополучателя", max_length=150, blank=True
    )
    consignee_phone = models.CharField(
        "Телефон грузополучателя", max_length=30, blank=True
    )

    pickup_hours = models.CharField("Часы работы на погрузке", max_length=100, blank=True)
    packaging_type = models.CharField("Вид упаковки", max_length=100, blank=True)
    package_count = models.PositiveIntegerField(
        "Количество мест", null=True, blank=True
    )
    cargo_length_m = models.DecimalField(
        "Длина груза, м",
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0"))],
    )
    cargo_width_m = models.DecimalField(
        "Ширина груза, м",
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0"))],
    )
    cargo_height_m = models.DecimalField(
        "Высота груза, м",
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0"))],
    )
    special_conditions = models.TextField("Особые условия и требования", blank=True)
    cargo_insurance = models.CharField(
        "Страхование груза",
        max_length=3,
        choices=Insurance.choices,
        default=Insurance.NOT_SPECIFIED,
        blank=True,
    )
    payer = models.CharField("Плательщик", max_length=255, blank=True)
    payment_place = models.CharField("Место оплаты", max_length=255, blank=True)
    expediter_representative = models.CharField(
        "Представитель экспедитора", max_length=150, blank=True
    )
    client_representative = models.CharField(
        "Представитель клиента", max_length=150, blank=True
    )

    class Meta:
        verbose_name = "экспедиторское поручение"
        verbose_name_plural = "экспедиторские поручения"

    def __str__(self):
        return f"Экспедиторское поручение · {self.shipment.number}"

    def get_absolute_url(self):
        return reverse("forwarding-order", kwargs={"pk": self.shipment_id})


def shipment_document_upload_path(instance, filename):
    safe_filename = Path(filename).name
    if instance.transportation_id:
        return f"transportations/{instance.transportation_id}/documents/{safe_filename}"
    if instance.shipment_id:
        return f"shipments/{instance.shipment_id}/documents/{safe_filename}"
    return f"documents/unassigned/{safe_filename}"


class ShipmentDocument(TimestampedModel):
    class Direction(models.TextChoices):
        OUTGOING = "outgoing", "Исходящий"
        INCOMING = "incoming", "Входящий"

    class Kind(models.TextChoices):
        TRANSPORT_WAYBILL = "trn", "Транспортная накладная (ТрН)"
        INVOICE = "invoice", "Счёт"
        UPD = "upd", "УПД"
        ACT = "act", "Акт"
        VAT_INVOICE = "vat_invoice", "Счёт-фактура"
        OTHER = "other", "Другое"

    class Party(models.TextChoices):
        CUSTOMER = "customer", "Клиент"
        CARRIER = "carrier", "Перевозчик"
        INTERNAL = "internal", "Внутренний документ"
        OTHER = "other", "Другой контрагент"

    class Status(models.TextChoices):
        EXPECTED = "expected", "Ожидается"
        DRAFT = "draft", "Черновик"
        ISSUED = "issued", "Выставлен"
        RECEIVED = "received", "Получен"
        SIGNED = "signed", "Подписан"
        ORIGINAL = "original", "Оригинал получен"
        CANCELLED = "cancelled", "Аннулирован"

    shipment = models.ForeignKey(
        Shipment,
        verbose_name="Заявка",
        related_name="documents",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    transportation = models.ForeignKey(
        Transportation,
        verbose_name="Рейс",
        related_name="documents",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    direction = models.CharField(
        "Направление",
        max_length=20,
        choices=Direction.choices,
        default=Direction.OUTGOING,
    )
    counterparty = models.ForeignKey(
        Organization,
        verbose_name="Контрагент",
        related_name="shipment_documents",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    kind = models.CharField("Тип документа", max_length=20, choices=Kind.choices)
    party = models.CharField(
        "Сторона", max_length=20, choices=Party.choices, default=Party.CUSTOMER
    )
    status = models.CharField(
        "Статус", max_length=20, choices=Status.choices, default=Status.EXPECTED
    )
    number = models.CharField("Номер документа", max_length=100, blank=True)
    document_date = models.DateField("Дата документа", null=True, blank=True)
    expected_date = models.DateField("Ожидаем до", null=True, blank=True)
    amount = models.DecimalField(
        "Сумма",
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0"))],
    )
    currency = models.CharField(
        "Валюта",
        max_length=3,
        choices=[("RUB", "RUB"), ("USD", "USD"), ("EUR", "EUR")],
        default="RUB",
    )
    vat_amount = models.DecimalField(
        "НДС",
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0"))],
    )
    file = models.FileField(
        "Файл",
        upload_to=shipment_document_upload_path,
        blank=True,
        validators=[
            FileExtensionValidator(
                ["pdf", "xml", "doc", "docx", "xls", "xlsx", "jpg", "jpeg", "png", "zip"]
            )
        ],
    )
    notes = models.TextField("Комментарий", blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Добавил",
        related_name="created_shipment_documents",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "документ по заявке"
        verbose_name_plural = "документы по заявкам"
        ordering = ("-document_date", "-created_at")
        indexes = [
            models.Index(fields=("direction", "kind", "status")),
            models.Index(fields=("document_date", "expected_date")),
        ]

    def __str__(self):
        details = self.number or self.get_status_display()
        return f"{self.get_kind_display()} · {details} · {self.source_number}"

    @property
    def file_name(self):
        return Path(self.file.name).name if self.file else ""

    @property
    def counterparty_name(self):
        if self.counterparty_id:
            return str(self.counterparty)
        if self.transportation_id:
            if self.party == self.Party.CUSTOMER:
                party = self.transportation.parties.filter(
                    role=TransportationParty.Role.CLIENT, is_active=True
                ).select_related("organization").first()
                return str(party.organization) if party else "Клиент не указан"
            if self.party == self.Party.CARRIER:
                link = self.transportation.active_execution_link()
                if link:
                    return str(link.contractor_party.organization)
                return "Исполнитель не указан"
            if self.party == self.Party.INTERNAL:
                return str(self.transportation.owner_company)
        if self.party == self.Party.CUSTOMER and self.shipment_id:
            return self.shipment.customer.name
        if self.party == self.Party.CARRIER and self.shipment_id and self.shipment.carrier_id:
            return self.shipment.carrier.name
        if self.party == self.Party.INTERNAL and self.shipment_id:
            return str(self.shipment.expeditor)
        return "Не указан"

    @property
    def source_number(self):
        if self.transportation_id:
            return self.transportation.number or "Черновик"
        if self.shipment_id:
            return self.shipment.number
        return "Без основания"

    @property
    def source_route(self):
        if self.transportation_id:
            return self.transportation.route
        if self.shipment_id:
            return self.shipment.route
        return "Маршрут не указан"

    @property
    def source_customer_name(self):
        if self.transportation_id:
            party = self.transportation.parties.filter(
                role=TransportationParty.Role.CLIENT, is_active=True
            ).select_related("organization").first()
            return str(party.organization) if party else "Клиент не указан"
        if self.shipment_id:
            return self.shipment.customer.name
        return "Клиент не указан"

    @property
    def source_owner_company(self):
        if self.transportation_id:
            return self.transportation.owner_company
        if self.shipment_id:
            return self.shipment.expeditor
        return None

    @property
    def source_absolute_url(self):
        if self.transportation_id:
            return self.transportation.get_absolute_url()
        if self.shipment_id:
            return self.shipment.get_absolute_url()
        return reverse("shipment-document-list")

    @property
    def is_overdue(self):
        return bool(
            self.status == self.Status.EXPECTED
            and self.expected_date
            and self.expected_date < timezone.localdate()
        )

    def get_absolute_url(self):
        return reverse("shipment-document-update", kwargs={"pk": self.pk})


class DocumentBatchNumberSequence(TimestampedModel):
    owner_company = models.ForeignKey(
        Organization,
        verbose_name="Наша компания",
        related_name="document_batch_number_sequences",
        on_delete=models.CASCADE,
    )
    year = models.PositiveSmallIntegerField("Год")
    last_value = models.PositiveIntegerField("Последний номер", default=0)

    class Meta:
        verbose_name = "нумератор пачек документов"
        verbose_name_plural = "нумераторы пачек документов"
        constraints = [
            models.UniqueConstraint(
                fields=("owner_company", "year"),
                name="unique_document_batch_sequence_per_company_year",
            )
        ]

    def __str__(self):
        return f"{self.owner_company} · {self.year}: {self.last_value}"


class DocumentBatch(TimestampedModel):
    """Групповое присвоение входящих/исходящих документов рейсам."""

    class Direction(models.TextChoices):
        OUTGOING = "outgoing", "Исходящие клиенту"
        INCOMING = "incoming", "Входящие от исполнителей"

    class Status(models.TextChoices):
        DRAFT = "draft", "Черновик"
        POSTED = "posted", "Проведён"
        VOIDED = "voided", "Аннулирован"

    number = models.CharField("Номер документа", max_length=40, unique=True, blank=True)
    document_date = models.DateField("Дата документа", default=timezone.localdate)
    direction = models.CharField(
        "Направление", max_length=20, choices=Direction.choices, default=Direction.OUTGOING
    )
    status = models.CharField(
        "Статус", max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    owner_company = models.ForeignKey(
        Organization,
        verbose_name="Наша компания",
        related_name="document_batches",
        on_delete=models.PROTECT,
    )
    default_kind = models.CharField(
        "Тип документа по умолчанию",
        max_length=20,
        choices=ShipmentDocument.Kind.choices,
        default=ShipmentDocument.Kind.UPD,
    )
    default_status = models.CharField(
        "Статус строк по умолчанию",
        max_length=20,
        choices=ShipmentDocument.Status.choices,
        default=ShipmentDocument.Status.ISSUED,
    )
    currency = models.CharField(
        "Валюта",
        max_length=3,
        choices=[("RUB", "RUB"), ("USD", "USD"), ("EUR", "EUR")],
        default="RUB",
    )
    reference = models.CharField("Номер реестра / входящего пакета", max_length=100, blank=True)
    notes = models.TextField("Комментарий", blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Создал",
        related_name="created_document_batches",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Провёл",
        related_name="posted_document_batches",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    posted_at = models.DateTimeField("Дата проведения", null=True, blank=True)

    class Meta:
        verbose_name = "пачка документов"
        verbose_name_plural = "пачки документов"
        ordering = ("-document_date", "-created_at")
        indexes = [
            models.Index(fields=("owner_company", "document_date")),
            models.Index(fields=("status", "direction")),
        ]

    def __str__(self):
        return f"{self.number or 'Новая пачка'} · {self.get_direction_display()}"

    def save(self, *args, **kwargs):
        if self.number:
            return super().save(*args, **kwargs)
        with transaction.atomic():
            year = self.document_date.year
            sequence, _ = DocumentBatchNumberSequence.objects.select_for_update().get_or_create(
                owner_company=self.owner_company,
                year=year,
                defaults={"last_value": 0},
            )
            sequence.last_value += 1
            sequence.save(update_fields=["last_value", "updated_at"])
            prefix = "РЛ" if self.direction == self.Direction.OUTGOING else "ПД"
            self.number = f"{prefix}-{year}-{sequence.last_value:05d}"
            return super().save(*args, **kwargs)

    @property
    def total_amount(self):
        return self.lines.aggregate(total=Sum("amount"))["total"] or Decimal("0")

    @property
    def total_vat_amount(self):
        return self.lines.aggregate(total=Sum("vat_amount"))["total"] or Decimal("0")

    @property
    def line_count(self):
        return self.lines.count()

    def get_absolute_url(self):
        return reverse("document-batch-detail", kwargs={"pk": self.pk})


class DocumentBatchLine(TimestampedModel):
    batch = models.ForeignKey(
        DocumentBatch,
        verbose_name="Пачка документов",
        related_name="lines",
        on_delete=models.CASCADE,
    )
    transportation = models.ForeignKey(
        Transportation,
        verbose_name="Рейс",
        related_name="document_batch_lines",
        on_delete=models.PROTECT,
    )
    kind = models.CharField(
        "Тип документа", max_length=20, choices=ShipmentDocument.Kind.choices
    )
    counterparty = models.ForeignKey(
        Organization,
        verbose_name="Контрагент",
        related_name="document_batch_lines",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    document_number = models.CharField("Номер документа", max_length=100, blank=True)
    document_date = models.DateField("Дата документа", null=True, blank=True)
    amount = models.DecimalField(
        "Сумма",
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
        default=0,
    )
    vat_amount = models.DecimalField(
        "НДС",
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
        default=0,
    )
    shipment_document = models.OneToOneField(
        ShipmentDocument,
        verbose_name="Запись реестра",
        related_name="document_batch_line",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "строка пачки документов"
        verbose_name_plural = "строки пачки документов"
        constraints = [
            models.UniqueConstraint(
                fields=("batch", "transportation", "kind"),
                name="unique_document_batch_transportation_kind",
            )
        ]

    def __str__(self):
        return f"{self.batch} · {self.transportation} · {self.get_kind_display()}"


class ReconciliationActNumberSequence(TimestampedModel):
    owner_company = models.ForeignKey(
        Organization,
        verbose_name="Наша компания",
        related_name="reconciliation_number_sequences",
        on_delete=models.CASCADE,
    )
    year = models.PositiveSmallIntegerField("Год")
    last_value = models.PositiveIntegerField("Последний номер", default=0)

    class Meta:
        verbose_name = "нумератор актов сверки"
        verbose_name_plural = "нумераторы актов сверки"
        constraints = [
            models.UniqueConstraint(
                fields=("owner_company", "year"),
                name="unique_reconciliation_sequence_per_company_year",
            )
        ]


class ReconciliationAct(TimestampedModel):
    """Акт сверки взаиморасчётов с контрагентом за период."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Черновик"
        GENERATED = "generated", "Сформирован"
        VOIDED = "voided", "Аннулирован"

    number = models.CharField("Номер акта", max_length=40, unique=True, blank=True)
    document_date = models.DateField("Дата акта", default=timezone.localdate)
    status = models.CharField(
        "Статус", max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    owner_company = models.ForeignKey(
        Organization,
        verbose_name="Наша компания",
        related_name="reconciliation_acts",
        on_delete=models.PROTECT,
    )
    counterparty = models.ForeignKey(
        Organization,
        verbose_name="Контрагент",
        related_name="counterparty_reconciliation_acts",
        on_delete=models.PROTECT,
    )
    period_from = models.DateField("Период с")
    period_to = models.DateField("Период по")
    currency = models.CharField(
        "Валюта",
        max_length=3,
        choices=[("RUB", "RUB"), ("USD", "USD"), ("EUR", "EUR")],
        default="RUB",
    )
    opening_balance = models.DecimalField(
        "Сальдо на начало",
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    debit_turnover = models.DecimalField(
        "Дебетовый оборот",
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    credit_turnover = models.DecimalField(
        "Кредитовый оборот",
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    closing_balance = models.DecimalField(
        "Сальдо на конец",
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    notes = models.TextField("Комментарий", blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Создал",
        related_name="created_reconciliation_acts",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Сформировал",
        related_name="generated_reconciliation_acts",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    generated_at = models.DateTimeField("Дата формирования", null=True, blank=True)

    class Meta:
        verbose_name = "акт сверки"
        verbose_name_plural = "акты сверки"
        ordering = ("-document_date", "-created_at")
        indexes = [
            models.Index(fields=("owner_company", "counterparty", "period_from", "period_to")),
            models.Index(fields=("status", "document_date")),
        ]

    def __str__(self):
        return f"{self.number or 'Новый акт сверки'} · {self.counterparty}"

    def save(self, *args, **kwargs):
        if self.number:
            return super().save(*args, **kwargs)
        with transaction.atomic():
            year = self.document_date.year
            sequence, _ = ReconciliationActNumberSequence.objects.select_for_update().get_or_create(
                owner_company=self.owner_company,
                year=year,
                defaults={"last_value": 0},
            )
            sequence.last_value += 1
            sequence.save(update_fields=["last_value", "updated_at"])
            self.number = f"АС-{year}-{sequence.last_value:05d}"
            return super().save(*args, **kwargs)

    @property
    def line_count(self):
        return self.lines.count()

    def get_absolute_url(self):
        return reverse("reconciliation-act-detail", kwargs={"pk": self.pk})


class ReconciliationActLine(TimestampedModel):
    act = models.ForeignKey(
        ReconciliationAct,
        verbose_name="Акт сверки",
        related_name="lines",
        on_delete=models.CASCADE,
    )
    movement = models.ForeignKey(
        SettlementMovement,
        verbose_name="Движение взаиморасчётов",
        related_name="reconciliation_lines",
        on_delete=models.PROTECT,
    )
    transportation = models.ForeignKey(
        Transportation,
        verbose_name="Рейс",
        related_name="reconciliation_lines",
        on_delete=models.PROTECT,
    )
    movement_date = models.DateField("Дата")
    description = models.CharField("Содержание операции", max_length=255)
    debit = models.DecimalField(
        "Дебет", max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    credit = models.DecimalField(
        "Кредит", max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    balance = models.DecimalField(
        "Сальдо", max_digits=14, decimal_places=2, default=Decimal("0.00")
    )

    class Meta:
        verbose_name = "строка акта сверки"
        verbose_name_plural = "строки акта сверки"
        ordering = ("movement_date", "created_at")
        constraints = [
            models.UniqueConstraint(
                fields=("act", "movement"),
                name="unique_reconciliation_act_movement",
            )
        ]

    def __str__(self):
        return f"{self.act} · {self.description}"


class DirectConversation(TimestampedModel):
    user_low = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Первый участник",
        related_name="chat_conversations_as_low",
        on_delete=models.CASCADE,
    )
    user_high = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Второй участник",
        related_name="chat_conversations_as_high",
        on_delete=models.CASCADE,
    )

    class Meta:
        verbose_name = "личный диалог"
        verbose_name_plural = "личные диалоги"
        ordering = ("-updated_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("user_low", "user_high"),
                name="unique_direct_conversation",
            ),
            models.CheckConstraint(
                condition=~models.Q(user_low=models.F("user_high")),
                name="direct_conversation_different_users",
            ),
        ]

    def __str__(self):
        return f"{self.user_low} ↔ {self.user_high}"

    def clean(self):
        super().clean()
        if self.user_low_id and self.user_low_id == self.user_high_id:
            raise ValidationError("Нельзя создать диалог с самим собой.")

    def save(self, *args, **kwargs):
        if self.user_low_id and self.user_high_id and self.user_low_id > self.user_high_id:
            self.user_low_id, self.user_high_id = self.user_high_id, self.user_low_id
        super().save(*args, **kwargs)

    @classmethod
    def get_or_create_between(cls, first_user, second_user):
        low_id, high_id = sorted((first_user.pk, second_user.pk))
        return cls.objects.get_or_create(user_low_id=low_id, user_high_id=high_id)

    def includes(self, user):
        return user.pk in {self.user_low_id, self.user_high_id}

    def other_participant(self, user):
        return self.user_high if user.pk == self.user_low_id else self.user_low

    def get_absolute_url(self):
        return reverse("chat-conversation", kwargs={"pk": self.pk})


CHAT_ATTACHMENT_EXTENSIONS = (
    "pdf", "doc", "docx", "xls", "xlsx", "csv", "txt", "rtf", "odt",
    "ods", "ppt", "pptx", "xml", "json", "jpg", "jpeg", "png", "gif",
    "webp", "heic", "zip", "rar", "7z", "eml", "msg",
)
CHAT_ATTACHMENT_MAX_SIZE = 20 * 1024 * 1024


def validate_chat_attachment_size(upload):
    if upload.size > CHAT_ATTACHMENT_MAX_SIZE:
        raise ValidationError("Размер файла не должен превышать 20 МБ.")


def chat_attachment_upload_path(instance, filename):
    safe_name = Path(filename).name
    return f"chat/{instance.conversation_id}/{uuid4().hex}_{safe_name}"


class ChatMessage(TimestampedModel):
    conversation = models.ForeignKey(
        DirectConversation,
        verbose_name="Диалог",
        related_name="messages",
        on_delete=models.CASCADE,
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Отправитель",
        related_name="chat_messages",
        on_delete=models.CASCADE,
    )
    text = models.TextField("Сообщение", max_length=4000, blank=True)
    attachment = models.FileField(
        "Файл",
        upload_to=chat_attachment_upload_path,
        max_length=500,
        blank=True,
        validators=[
            FileExtensionValidator(allowed_extensions=CHAT_ATTACHMENT_EXTENSIONS),
            validate_chat_attachment_size,
        ],
    )
    attachment_name = models.CharField("Имя файла", max_length=255, blank=True)
    attachment_size = models.PositiveBigIntegerField("Размер файла", default=0)
    edited_at = models.DateTimeField("Изменено", null=True, blank=True)
    read_at = models.DateTimeField("Прочитано", null=True, blank=True)

    class Meta:
        verbose_name = "сообщение чата"
        verbose_name_plural = "сообщения чата"
        ordering = ("created_at", "pk")
        indexes = [
            models.Index(fields=("conversation", "created_at")),
            models.Index(fields=("read_at",)),
        ]

    def __str__(self):
        content = self.text[:60] or self.attachment_filename or "Без текста"
        return f"{self.sender}: {content}"

    @property
    def attachment_filename(self):
        if self.attachment_name:
            return self.attachment_name
        if not self.attachment:
            return ""
        stored_name = Path(self.attachment.name).name
        return stored_name.split("_", 1)[-1]

    def get_absolute_url(self):
        return reverse(
            "chat-message-update",
            kwargs={"conversation_pk": self.conversation_id, "pk": self.pk},
        )

    def get_delete_url(self):
        return reverse(
            "chat-message-delete",
            kwargs={"conversation_pk": self.conversation_id, "pk": self.pk},
        )

    def get_attachment_url(self):
        if not self.attachment:
            return ""
        return reverse(
            "chat-message-attachment",
            kwargs={"conversation_pk": self.conversation_id, "pk": self.pk},
        )

    def clean(self):
        super().clean()
        if self.conversation_id and self.sender_id and not self.conversation.includes(
            self.sender
        ):
            raise ValidationError("Отправитель не является участником диалога.")
        if not (self.text or "").strip() and not self.attachment:
            raise ValidationError("Введите сообщение или прикрепите файл.")

    def save(self, *args, **kwargs):
        if self.attachment:
            if not self.attachment_name:
                self.attachment_name = Path(self.attachment.name).name
            if not self.attachment_size:
                self.attachment_size = self.attachment.size
        super().save(*args, **kwargs)
        DirectConversation.objects.filter(pk=self.conversation_id).update(
            updated_at=timezone.now()
        )

    def delete(self, *args, **kwargs):
        attachment = self.attachment
        result = super().delete(*args, **kwargs)
        if attachment:
            attachment.delete(save=False)
        return result
