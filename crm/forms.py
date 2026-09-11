from datetime import datetime, time
from decimal import Decimal
import json
import re

from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.forms import BaseInlineFormSet, inlineformset_factory
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from .models import (
    Carrier,
    ChatMessage,
    BankStatement,
    BankStatementLine,
    CompanyProfile,
    Contract,
    Customer,
    Driver,
    DocumentBatch,
    DriverEmployment,
    DriverLicense,
    DriverPassport,
    ForwardingOrder,
    Organization,
    OrganizationBankAccount,
    OrganizationChange,
    OrganizationContact,
    OrganizationRole,
    Payment,
    PlannerTask,
    ReconciliationAct,
    Shipment,
    ShipmentDocument,
    TransportOrder,
    TransportOrderStop,
    TransportationIncident,
    VehicleCombination,
    Transportation,
    TransportationLink,
    TransportationParty,
    TransportationStop,
    VehicleAssignment,
    Vehicle,
    VATRate,
)


CRM_DATE_DISPLAY_FORMAT = "%d.%m.%Y"
CRM_DATE_INPUT_FORMATS = (CRM_DATE_DISPLAY_FORMAT, "%Y-%m-%d")

# Категории водительских удостоверений и пояснения из справочника категорий.
# Коды хранятся в едином латинском формате, чтобы корректно сравнивать данные
# из старых карточек, где визуально похожие буквы могли быть кириллицей.
DRIVER_LICENSE_CATEGORY_CHOICES = (
    (
        "A",
        "Мотоциклы и квадрициклы (с мотоциклетным рулем) "
        "с двигателем объемом от 125 см³",
    ),
    (
        "A1",
        "Мотоциклы и квадрициклы (с мотоциклетным рулем) "
        "с двигателем объемом до 125 см³",
    ),
    (
        "B",
        "Легковые авто с разрешенной массой до 3,5 т "
        "и количеством пассажиров до 8",
    ),
    (
        "BE",
        "Легковые авто с прицепом, масса которого не превышает 750 кг. "
        "Суммарный вес состава – более 3,5 т",
    ),
    ("B1", "Трициклы"),
    (
        "C",
        "Грузовые автомобили массой от 3,5 т, а также внедорожная техника – "
        "снегоходы квадроциклы (с 2023 года)",
    ),
    ("CE", "Грузовые автомобили с прицепом"),
    (
        "C1",
        "Средние грузовые автомобили массой от 3,5 т до 7,5 т с прицепом",
    ),
    ("C1E", "Средние грузовые автомобили с прицепом"),
    (
        "D",
        "Автобусы для перевозки пассажиров с количеством сидячих мест более 8 "
        "по городским и междугородним маршрутам",
    ),
    ("D1", "Малые автобусы с 8-16 пассажирскими местами"),
    ("DE", "Автомобили категории Д с прицепом, автобусы-«гармошки»"),
    ("D1E", "Транспорт категории D1 с прицепом, не предназначенным для пассажиров"),
    ("M", "Мопеды, легкие квадрициклы"),
    ("Tm", "Трамваи"),
    ("Tb", "Троллейбусы"),
)
_DRIVER_LICENSE_CATEGORY_DESCRIPTIONS = dict(DRIVER_LICENSE_CATEGORY_CHOICES)
_DRIVER_LICENSE_CATEGORY_ALIASES = str.maketrans(
    "АВСЕМТавсемт",
    "ABCEMTabcemt",
)


def normalize_driver_license_category(value):
    """Return an official category code for both Latin and Cyrillic input."""

    code = str(value or "").strip().translate(_DRIVER_LICENSE_CATEGORY_ALIASES)
    code = code.upper()
    if code in {"TM", "TB"}:
        return code[0] + code[1].lower()
    return code


def split_driver_license_categories(value):
    """Return category codes from both checkbox lists and legacy text values."""
    if isinstance(value, str):
        values = re.split(r"[,;/\n]+", value)
    else:
        values = []
        for item in value or []:
            if isinstance(item, str):
                values.extend(re.split(r"[,;/\n]+", item))
            else:
                values.append(item)
    normalized = []
    for item in values:
        code = normalize_driver_license_category(item)
        if code and code not in normalized:
            normalized.append(code)
    return normalized


class CRMDateInput(forms.DateInput):
    """Text date input without the browser's native calendar popup."""

    input_type = "text"

    def __init__(self, attrs=None):
        date_attrs = {
            "placeholder": "ДД.ММ.ГГГГ",
            "inputmode": "numeric",
            "autocomplete": "off",
            "maxlength": "10",
            "data-crm-date": "",
        }
        date_attrs.update(attrs or {})
        date_attrs.pop("type", None)
        super().__init__(attrs=date_attrs, format=CRM_DATE_DISPLAY_FORMAT)


class CRMTimeInput(forms.TimeInput):
    """Text time input in HH:MM format without the browser's native picker."""

    input_type = "text"

    def __init__(self, attrs=None):
        time_attrs = {
            "placeholder": "ЧЧ:ММ",
            "inputmode": "numeric",
            "autocomplete": "off",
            "maxlength": "5",
            "data-crm-time": "",
        }
        time_attrs.update(attrs or {})
        time_attrs.pop("type", None)
        super().__init__(attrs=time_attrs, format="%H:%M")


def configure_crm_date_fields(form):
    """Apply one display and input format to every date field in a form."""

    for field in form.fields.values():
        if isinstance(field, forms.DateField) and not isinstance(
            field, forms.DateTimeField
        ):
            field.input_formats = CRM_DATE_INPUT_FORMATS
            field.widget = CRMDateInput(attrs=field.widget.attrs)


def configure_crm_time_fields(form):
    """Apply one display and input format to every time field in a form."""

    for field in form.fields.values():
        if isinstance(field, forms.TimeField):
            field.input_formats = ("%H:%M",)
            field.widget = CRMTimeInput(attrs=field.widget.attrs)


def configure_dadata_address_fields(form):
    """Enable server-proxied DaData suggestions for route address fields."""

    suggestions_url = reverse("dadata-address-suggestions")
    for city_name in ("pickup_city", "delivery_city"):
        if city_name not in form.fields:
            continue
        form.fields[city_name].widget.attrs.update(
            {
                "autocomplete": "off",
                "data-dadata-city": "",
                "data-dadata-city-url": suggestions_url,
                "placeholder": "Начните вводить город или населённый пункт",
            }
        )
    for address_name, city_name in (
        ("pickup_address", "pickup_city"),
        ("delivery_address", "delivery_city"),
    ):
        if address_name not in form.fields or city_name not in form.fields:
            continue
        form.fields[address_name].widget.attrs.update(
            {
                "autocomplete": "off",
                "data-dadata-address": "",
                "data-dadata-address-url": suggestions_url,
                "data-dadata-city-source": f"id_{city_name}",
                "data-dadata-meta-target": f"id_{address_name}_meta",
                "placeholder": "Начните вводить улицу, дом или полный адрес",
            }
        )


class StyledModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        configure_crm_date_fields(self)
        configure_crm_time_fields(self)
        for field in self.fields.values():
            if isinstance(
                field.widget, (forms.CheckboxInput, forms.CheckboxSelectMultiple)
            ):
                field.widget.attrs["class"] = "checkbox uk-checkbox"
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs["class"] = "form-control uk-select"
            elif isinstance(field.widget, forms.Textarea):
                field.widget.attrs["class"] = "form-control uk-textarea"
            else:
                field.widget.attrs["class"] = "form-control uk-input"


class OrganizationRoleSelect(forms.Select):
    """Adds organization roles to options for client-side filtering."""

    role_map = None

    def create_option(
        self, name, value, label, selected, index, subindex=None, attrs=None
    ):
        option = super().create_option(
            name, value, label, selected, index, subindex=subindex, attrs=attrs
        )
        raw_value = getattr(value, "value", value)
        if raw_value not in (None, ""):
            roles = (self.role_map or {}).get(str(raw_value), ())
            option["attrs"]["data-roles"] = " ".join(roles)
        return option


class OrganizationChoiceField(forms.ModelChoiceField):
    widget = OrganizationRoleSelect

    def label_from_instance(self, organization):
        tax_id = f" · ИНН {organization.tax_id}" if organization.tax_id else ""
        return f"{organization}{tax_id}"


class UserDisplayChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, user):
        return user.get_full_name().strip() or user.username


class DriverChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, driver):
        license_number = (
            f" · В/У {driver.license_number}" if driver.license_number else ""
        )
        return f"{driver.full_name}{license_number}"


class CarrierChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, carrier):
        tax_id = f" · ИНН {carrier.tax_id}" if carrier.tax_id else ""
        return f"{carrier.name}{tax_id}"


class VehicleChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, vehicle):
        vehicle_name = " ".join(
            part for part in (vehicle.make, vehicle.model) if part
        )
        return " · ".join(
            part for part in (vehicle.registration_number, vehicle_name) if part
        )


class CustomerForm(StyledModelForm):
    class Meta:
        model = Customer
        fields = [
            "name", "tax_id", "kpp", "ogrn", "address", "director_name",
            "contact_name", "phone", "email", "bank_name", "bik",
            "settlement_account", "correspondent_account", "notes", "is_active",
        ]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}


class CarrierForm(StyledModelForm):
    class Meta:
        model = Carrier
        fields = [
            "name", "tax_id", "kpp", "ogrn", "address", "director_name",
            "contact_name", "phone", "email", "bank_name", "bik",
            "settlement_account", "correspondent_account", "vehicle_types",
            "rating", "notes", "is_active",
        ]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}


class OrganizationForm(StyledModelForm):
    legal_address_meta = forms.CharField(required=False, widget=forms.HiddenInput())
    roles = forms.MultipleChoiceField(
        label="Роли",
        choices=OrganizationRole.Role.choices,
        widget=forms.CheckboxSelectMultiple(
            attrs={"class": "checkbox uk-checkbox"}
        ),
        help_text="Одна организация может одновременно иметь несколько ролей.",
    )

    class Meta:
        model = Organization
        fields = [
            "kind", "name", "short_name", "group", "registration_country",
            "tax_id", "kpp", "ogrn", "registration_date", "okato",
            "legal_address", "director_name", "contact_name", "phone", "email",
            "bank_name", "bik", "settlement_account", "correspondent_account",
            "is_own_company", "profit_tax_rate", "verification_status", "fns_status",
            "default_vat_rate", "default_payment_form", "payment_term_days", "credit_limit", "edo_operator", "edo_id",
            "originals_handling", "notes", "is_active",
        ]
        widgets = {
            "registration_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
            "contact_name": forms.HiddenInput(),
            "phone": forms.HiddenInput(),
            "email": forms.HiddenInput(),
            "bank_name": forms.HiddenInput(),
            "bik": forms.HiddenInput(),
            "settlement_account": forms.HiddenInput(),
            "correspondent_account": forms.HiddenInput(),
            "verification_status": forms.HiddenInput(),
            "fns_status": forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.duplicate_organization = None
        self._audit_is_create = not bool(self.instance.pk)
        self.fields["kind"].required = False
        self.fields["registration_country"].required = False
        self.fields["profit_tax_rate"].required = False
        self.fields["default_vat_rate"].queryset = VATRate.objects.filter(is_active=True)
        self.fields["default_vat_rate"].required = False
        self.fields["default_payment_form"].required = False
        self.fields["fns_status"].required = False
        self.fields["payment_term_days"].required = False
        self.fields["credit_limit"].required = False
        self.fields["edo_operator"].required = False
        self.fields["edo_id"].required = False
        self.fields["originals_handling"].required = False
        self._audit_before = {}
        for field_name in self.Meta.fields:
            if field_name in self.fields:
                value = getattr(self.instance, field_name, None)
                if hasattr(value, "isoformat"):
                    value = value.isoformat()
                elif value is not None:
                    value = str(value)
                self._audit_before[field_name] = value
        if self.instance.pk:
            self._audit_before["roles"] = sorted(
                self.instance.roles.filter(is_active=True).values_list("role", flat=True)
            )
        if self.instance.pk and not self.is_bound:
            self.initial["roles"] = list(
                self.instance.roles.filter(is_active=True).values_list(
                    "role", flat=True
                )
            )
            address_values = {
                key: getattr(self.instance, key, "")
                for key in (
                    "legal_address_fias_id", "legal_address_postal_code",
                    "legal_address_region_code", "legal_address_region",
                    "legal_address_area", "legal_address_city",
                    "legal_address_settlement", "legal_address_street",
                    "legal_address_house", "legal_address_block", "legal_address_flat",
                )
            }
            if any(address_values.values()):
                self.initial["legal_address_meta"] = json.dumps(
                    address_values, ensure_ascii=False
                )

    def clean_kind(self):
        return self.cleaned_data.get("kind") or Organization.Kind.LEGAL_ENTITY

    def clean_registration_country(self):
        return self.cleaned_data.get("registration_country") or "РОССИЯ"

    def clean_fns_status(self):
        value = self.cleaned_data.get("fns_status")
        return value or (
            self.instance.fns_status
            if self.instance.pk and self.instance.fns_status
            else Organization.FNSStatus.UNKNOWN
        )

    def clean_originals_handling(self):
        value = self.cleaned_data.get("originals_handling")
        return value or (
            self.instance.originals_handling
            if self.instance.pk and self.instance.originals_handling
            else Organization.OriginalsHandling.BOTH
        )

    def clean_tax_id(self):
        tax_id = re.sub(r"\D", "", self.cleaned_data.get("tax_id", ""))
        if tax_id and len(tax_id) not in {10, 12}:
            raise forms.ValidationError(
                "Укажите ИНН из 10 цифр для организации или 12 для ИП."
            )
        if tax_id:
            self.duplicate_organization = (
                Organization.objects.exclude(pk=self.instance.pk)
                .filter(tax_id=tax_id)
                .first()
            )
        if self.duplicate_organization:
            raise forms.ValidationError(
                "Контрагент с таким ИНН уже существует. Откройте его карточку."
            )
        return tax_id

    def clean_profit_tax_rate(self):
        value = self.cleaned_data.get("profit_tax_rate")
        if value is not None:
            return value
        if self.instance.pk and self.instance.profit_tax_rate is not None:
            return self.instance.profit_tax_rate
        return Decimal("25.00")

    def save(self, commit=True):
        if self.is_bound:
            raw_meta = self.cleaned_data.get("legal_address_meta") or ""
            try:
                address_meta = json.loads(raw_meta) if raw_meta else {}
            except (TypeError, ValueError):
                address_meta = {}
            if not isinstance(address_meta, dict):
                address_meta = {}
            aliases = {
                "legal_address_fias_id": ("legal_address_fias_id", "fias_id"),
                "legal_address_postal_code": ("legal_address_postal_code", "postal_code"),
                "legal_address_region_code": ("legal_address_region_code", "region_code"),
                "legal_address_region": ("legal_address_region", "region"),
                "legal_address_area": ("legal_address_area", "area"),
                "legal_address_city": ("legal_address_city", "city"),
                "legal_address_settlement": ("legal_address_settlement", "settlement"),
                "legal_address_street": ("legal_address_street", "street"),
                "legal_address_house": ("legal_address_house", "house"),
                "legal_address_block": ("legal_address_block", "block"),
                "legal_address_flat": ("legal_address_flat", "flat"),
            }
            max_lengths = {
                "legal_address_fias_id": 36, "legal_address_postal_code": 12,
                "legal_address_region_code": 3, "legal_address_region": 150,
                "legal_address_area": 150, "legal_address_city": 150,
                "legal_address_settlement": 150, "legal_address_street": 150,
                "legal_address_house": 30, "legal_address_block": 30,
                "legal_address_flat": 30,
            }
            for target, keys in aliases.items():
                value = next((address_meta.get(key) for key in keys if address_meta.get(key)), "")
                setattr(self.instance, target, str(value or "")[: max_lengths[target]])
        organization = super().save(commit=commit)
        if commit:
            if (
                organization.verification_status
                != Organization.VerificationStatus.NOT_CHECKED
                and (
                    not organization.verified_at
                    or "verification_status" in self.changed_data
                )
            ):
                from django.utils import timezone

                organization.verified_at = timezone.now()
                organization.save(update_fields=["verified_at", "updated_at"])
            if organization.fns_status != Organization.FNSStatus.UNKNOWN:
                from django.utils import timezone

                organization.fns_checked_at = timezone.now()
                organization.save(update_fields=["fns_checked_at", "updated_at"])
            selected_roles = set(self.cleaned_data["roles"])
            organization.roles.exclude(role__in=selected_roles).update(is_active=False)
            for role in selected_roles:
                OrganizationRole.objects.update_or_create(
                    organization=organization,
                    role=role,
                    defaults={"is_active": True},
                )
            from .sync import sync_organization_to_legacy

            sync_organization_to_legacy(organization)
            # Создание технической записи в старом справочнике перевозчиков
            # может активировать роль «Перевозчик» через сигнал. Источником
            # истины остаются чекбоксы единой карточки контрагента.
            organization.roles.exclude(role__in=selected_roles).update(is_active=False)
            audit_after = {}
            for field_name in self.Meta.fields:
                if field_name in self.fields:
                    value = getattr(organization, field_name, None)
                    if hasattr(value, "isoformat"):
                        value = value.isoformat()
                    elif value is not None:
                        value = str(value)
                    audit_after[field_name] = value
            audit_after["roles"] = sorted(selected_roles)
            self.audit_changes = {
                key: {"old": self._audit_before.get(key), "new": value}
                for key, value in audit_after.items()
                if self._audit_before.get(key) != value
            }
            self.audit_action = (
                OrganizationChange.Action.CREATE
                if self._audit_is_create
                else OrganizationChange.Action.UPDATE
            )
        else:
            self.audit_changes = {}
            self.audit_action = OrganizationChange.Action.UPDATE
        return organization


class QuickOrganizationForm(StyledModelForm):
    roles = forms.MultipleChoiceField(
        label="Роли контрагента",
        choices=OrganizationRole.Role.choices,
        widget=forms.CheckboxSelectMultiple(),
    )

    class Meta:
        model = Organization
        fields = [
            "kind", "name", "short_name", "tax_id", "kpp", "ogrn",
            "legal_address", "director_name", "phone", "email", "notes",
            "is_active",
        ]
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, required_role=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.required_role = (
            required_role
            if required_role in OrganizationRole.Role.values
            else OrganizationRole.Role.CLIENT
        )
        if not self.is_bound:
            self.initial["roles"] = [self.required_role]
            self.initial["is_active"] = True

    def clean_tax_id(self):
        tax_id = re.sub(r"\D", "", self.cleaned_data.get("tax_id", ""))
        if tax_id and len(tax_id) not in {10, 12}:
            raise forms.ValidationError(
                "Укажите ИНН из 10 цифр для организации или 12 для ИП."
            )
        if tax_id and Organization.objects.filter(tax_id=tax_id).exists():
            raise forms.ValidationError(
                "Контрагент с таким ИНН уже существует. Выберите его в заявке."
            )
        return tax_id

    def clean_roles(self):
        roles = set(self.cleaned_data.get("roles", ()))
        roles.add(self.required_role)
        return list(roles)

    def save(self, commit=True):
        organization = super().save(commit=commit)
        if commit:
            for role in self.cleaned_data["roles"]:
                OrganizationRole.objects.update_or_create(
                    organization=organization,
                    role=role,
                    defaults={"is_active": True},
                )
            from .sync import sync_organization_to_legacy

            sync_organization_to_legacy(organization)
        return organization


class PrimaryRegisterFormSet(BaseInlineFormSet):
    primary_field = "is_primary"

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        primary_count = 0
        for form in self.forms:
            if not hasattr(form, "cleaned_data") or form.cleaned_data.get("DELETE"):
                continue
            if form.cleaned_data.get(self.primary_field):
                primary_count += 1
        if primary_count > 1:
            raise forms.ValidationError("Основной записью может быть только одна строка.")


class OrganizationBankAccountForm(StyledModelForm):
    class Meta:
        model = OrganizationBankAccount
        fields = [
            "account_number", "bank_name", "bik", "correspondent_account",
            "currency", "is_primary", "is_active", "notes",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["bik"].widget.attrs.update(
            {
                "data-dadata-bank": "",
                "data-dadata-bank-url": reverse("dadata-bank-by-bik"),
                "data-bank-name-field": self.add_prefix("bank_name"),
                "data-correspondent-account-field": self.add_prefix(
                    "correspondent_account"
                ),
                "autocomplete": "off",
                "placeholder": "9 цифр",
            }
        )


class OrganizationContactForm(StyledModelForm):
    class Meta:
        model = OrganizationContact
        fields = [
            "full_name", "position", "phone", "email", "is_primary",
            "is_active", "notes",
        ]


OrganizationBankAccountFormSet = inlineformset_factory(
    Organization,
    OrganizationBankAccount,
    form=OrganizationBankAccountForm,
    formset=PrimaryRegisterFormSet,
    extra=1,
    can_delete=True,
)

OrganizationContactFormSet = inlineformset_factory(
    Organization,
    OrganizationContact,
    form=OrganizationContactForm,
    formset=PrimaryRegisterFormSet,
    extra=1,
    can_delete=True,
)


class TransportationChainForm(forms.Form):
    executor = forms.ModelChoiceField(
        label="Наш исполнитель",
        queryset=Organization.objects.none(),
    )
    executor_role = forms.ChoiceField(
        label="Роль исполнителя",
        choices=TransportationLink.ContractorRole.choices,
    )
    contract = forms.ModelChoiceField(
        label="Наш договор с исполнителем",
        queryset=Contract.objects.none(),
        required=False,
    )
    instruction_number = forms.CharField(
        label="Номер поручения / заявки", max_length=100, required=False
    )
    instruction_status = forms.CharField(
        label="Статус поручения / заявки", max_length=100, required=False
    )
    actual_carrier = forms.ModelChoiceField(
        label="Фактический перевозчик",
        queryset=Organization.objects.none(),
    )
    driver = forms.ModelChoiceField(
        label="Водитель", queryset=Driver.objects.none(), required=False
    )
    vehicle = forms.ModelChoiceField(
        label="Тягач / автомобиль", queryset=Vehicle.objects.none(), required=False
    )
    combination = forms.ModelChoiceField(
        label="Сцепка (тягач + прицеп)",
        queryset=VehicleCombination.objects.none(),
        required=False,
    )
    trailer = forms.ModelChoiceField(
        label="Прицеп / полуприцеп", queryset=Vehicle.objects.none(), required=False
    )
    trailer_registration_number = forms.CharField(
        label="Номер прицепа / полуприцепа", max_length=20, required=False
    )

    def __init__(self, *args, transportation, **kwargs):
        super().__init__(*args, **kwargs)
        self.transportation = transportation
        executor_roles = [
            OrganizationRole.Role.FORWARDER,
            OrganizationRole.Role.CARRIER,
        ]
        self.fields["executor"].queryset = Organization.objects.filter(
            is_active=True, roles__role__in=executor_roles, roles__is_active=True
        ).distinct()
        self.fields["actual_carrier"].queryset = Organization.objects.filter(
            is_active=True,
            roles__role=OrganizationRole.Role.CARRIER,
            roles__is_active=True,
        ).distinct()
        self.fields["contract"].queryset = Contract.objects.exclude(
            kind=Contract.Kind.CLIENT_FORWARDING
        ).exclude(status__in=[Contract.Status.TERMINATED, Contract.Status.ARCHIVED])

        actual_id = self.data.get("actual_carrier") if self.is_bound else None
        assignment = transportation.active_vehicle_assignment()
        link = transportation.active_execution_link()
        if not actual_id and assignment:
            actual_id = assignment.actual_carrier_id
        if actual_id and str(actual_id).isdigit():
            self.fields["driver"].queryset = Driver.objects.filter(
                Q(carrier__organization_id=actual_id)
                | Q(
                    employments__carrier__organization_id=actual_id,
                    employments__is_active=True,
                ),
                is_active=True,
            ).distinct()
            carrier_filter = {"carrier__organization_id": actual_id}
            self.fields["vehicle"].queryset = Vehicle.objects.filter(
                is_active=True, **carrier_filter
            ).exclude(kind__in=[Vehicle.Kind.TRAILER, Vehicle.Kind.SEMITRAILER])
            self.fields["trailer"].queryset = Vehicle.objects.filter(
                is_active=True,
                kind__in=[Vehicle.Kind.TRAILER, Vehicle.Kind.SEMITRAILER],
                **carrier_filter,
            )
            combination_filter = Q(
                is_active=True,
                tractor__carrier__organization_id=actual_id,
            )
            if assignment and assignment.combination_id:
                combination_filter |= Q(pk=assignment.combination_id)
            self.fields["combination"].queryset = VehicleCombination.objects.filter(
                combination_filter
            ).select_related("tractor", "trailer")

        # Keep the persisted values in ``initial`` even for a bound form.  A
        # bound field still renders the submitted value, while Django can now
        # correctly calculate ``changed_data`` for the audit trail.
        if link:
            self.initial.update(
                {
                    "executor": link.contractor_party.organization_id,
                    "executor_role": link.contractor_role,
                    "contract": self.initial.get("contract") or link.contract_id,
                    "instruction_number": link.instruction_number,
                    "instruction_status": link.instruction_status,
                }
            )
        if assignment:
            self.initial.update(
                {
                    "actual_carrier": assignment.actual_carrier_id,
                    "driver": assignment.driver_id,
                    "vehicle": assignment.vehicle_id,
                    "combination": assignment.combination_id,
                    "trailer": assignment.trailer_id,
                    "trailer_registration_number": assignment.trailer_registration_number,
                }
            )
        for field in self.fields.values():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs["class"] = "form-control uk-select"
            else:
                field.widget.attrs["class"] = "form-control uk-input"

    def clean(self):
        cleaned = super().clean()
        executor = cleaned.get("executor")
        role = cleaned.get("executor_role")
        contract = cleaned.get("contract")
        actual_carrier = cleaned.get("actual_carrier")
        if (
            executor
            and actual_carrier
            and role == TransportationLink.ContractorRole.CARRIER
            and executor != actual_carrier
        ):
            self.add_error(
                "actual_carrier",
                "Если исполнитель — перевозчик, фактический перевозчик должен совпадать с ним.",
            )
        if contract and executor:
            expected_kind = (
                Contract.Kind.CARRIER_TRANSPORT
                if role == TransportationLink.ContractorRole.CARRIER
                else Contract.Kind.SUBCONTRACTOR_FORWARDING
            )
            if contract.kind != expected_kind:
                self.add_error(
                    "contract",
                    "Вид договора не соответствует выбранной роли исполнителя.",
                )
            if (
                not contract.carrier_id
                or contract.carrier.organization_id != executor.pk
            ):
                self.add_error(
                    "contract",
                    "Договор должен быть заключён с выбранным исполнителем.",
                )
            if contract.expeditor.organization_id != self.transportation.owner_company_id:
                self.add_error(
                    "contract",
                    "Договор должен принадлежать выбранной нашей компании рейса.",
                )
        driver = cleaned.get("driver")
        combination = cleaned.get("combination")
        if combination:
            if actual_carrier and combination.tractor.carrier.organization_id != actual_carrier.pk:
                self.add_error(
                    "combination",
                    "Сцепка должна принадлежать фактическому перевозчику.",
                )
            if cleaned.get("vehicle") and cleaned["vehicle"] != combination.tractor:
                self.add_error("vehicle", "Основной автомобиль не соответствует выбранной сцепке.")
            if cleaned.get("trailer") and cleaned["trailer"] != combination.trailer:
                self.add_error("trailer", "Прицеп не соответствует выбранной сцепке.")
            # Сцепка является источником истины для обеих единиц состава.
            cleaned["vehicle"] = combination.tractor
            cleaned["trailer"] = combination.trailer
            cleaned["trailer_registration_number"] = combination.trailer.registration_number
        if driver and actual_carrier and not driver.works_for_organization(
            actual_carrier
        ):
            self.add_error(
                "driver", "Водитель должен работать у фактического перевозчика."
            )
        for field_name in ("vehicle", "trailer"):
            resource = cleaned.get(field_name)
            if resource and actual_carrier and resource.carrier.organization_id != actual_carrier.pk:
                self.add_error(
                    field_name,
                    "Ресурс должен принадлежать фактическому перевозчику.",
                )
        return cleaned

    def save(self, user):
        from .sync import set_transportation_chain

        return set_transportation_chain(
            transportation=self.transportation,
            user=user,
            **self.cleaned_data,
        )


class TransportOrderForm(StyledModelForm):
    owner_company = OrganizationChoiceField(
        label="Наша компания",
        queryset=Organization.objects.none(),
    )
    client = OrganizationChoiceField(
        label="Клиент",
        queryset=Organization.objects.none(),
    )
    manager = UserDisplayChoiceField(
        label="Ответственный менеджер",
        queryset=get_user_model().objects.none(),
    )
    adr_class = forms.ChoiceField(
        label="Класс опасности ADR",
        choices=TransportOrder.ADRClass.choices,
        required=False,
    )

    class Meta:
        model = TransportOrder
        fields = [
            "owner_company", "client", "manager", "document_date",
            "rate", "currency", "payment_form", "payment_term_days",
            "cargo_name", "cargo_description", "weight_kg", "volume_m3",
            "package_count", "pallet_count", "package_type",
            "temperature_regime", "adr_class", "vehicle_requirements",
            "special_requirements", "notes",
        ]
        widgets = {
            "cargo_description": forms.Textarea(attrs={"rows": 3}),
            "special_requirements": forms.Textarea(attrs={"rows": 3}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["owner_company"].queryset = Organization.objects.filter(
            is_own_company=True, is_active=True
        )
        manager_filter = Q(is_active=True)
        if self.instance.pk:
            manager_filter |= Q(pk=self.instance.manager_id)
        self.fields["manager"].queryset = get_user_model().objects.filter(
            manager_filter
        ).order_by("first_name", "last_name", "username")
        client_filter = Q(
            is_active=True,
            roles__role=OrganizationRole.Role.CLIENT,
            roles__is_active=True,
        )
        if self.instance.pk:
            # Текущий клиент должен оставаться доступным даже если его роль
            # впоследствии отключили. Строим один DISTINCT-запрос: объединять
            # DISTINCT и обычный QuerySet оператором `|` Django не позволяет.
            client_filter |= Q(pk=self.instance.client_id)
        self.fields["client"].queryset = Organization.objects.filter(
            client_filter
        ).distinct()
        self.fields["cargo_name"].widget.attrs.update(
            {
                "autocomplete": "off",
                "placeholder": "Начните вводить наименование груза",
                "data-cargo-autocomplete": "",
            }
        )
        self.fields["package_count"].label = "Количество мест"
        self.fields["package_count"].help_text = ""
        self.fields["pallet_count"].required = False
        self.fields["pallet_count"].widget = forms.HiddenInput()
        if not self.is_bound and self.instance.pk:
            self.initial["package_count"] = self.instance.total_package_count
            self.initial["pallet_count"] = ""
        self.fields["client"].widget.attrs.update(
            {
                "data-smart-select": "organization",
                "data-create-url": reverse("quick-organization-create"),
                "data-required-role": OrganizationRole.Role.CLIENT,
                "data-search-placeholder": "Введите название или ИНН клиента",
                "data-create-label": "Создать клиента",
            }
        )
        if self.instance.pk:
            self.fields["owner_company"].queryset = Organization.objects.filter(
                Q(is_own_company=True, is_active=True)
                | Q(pk=self.instance.owner_company_id)
            )
        elif self.fields["owner_company"].queryset.count() == 1:
            self.fields["owner_company"].initial = self.fields[
                "owner_company"
            ].queryset.first()
        if not self.instance.pk and user and user.is_authenticated:
            self.fields["manager"].initial = user
        self.fields["rate"].widget.attrs.update(
            {"inputmode": "decimal", "placeholder": "0,00", "data-money-input": ""}
        )
        self.fields["rate"].widget = forms.TextInput(
            attrs={
                "class": "form-control uk-input",
                "inputmode": "decimal",
                "placeholder": "0,00",
                "data-money-input": "",
            }
        )
        self.fields["payment_term_days"].widget.attrs.update(
            {"min": "0", "placeholder": "0"}
        )
        if not self.is_bound:
            client_id = self.initial.get("client") or self.instance.client_id
            if client_id:
                client_org = Organization.objects.select_related(
                    "default_vat_rate"
                ).filter(pk=client_id).first()
                if client_org:
                    self.initial.setdefault("payment_term_days", client_org.payment_term_days)
                    self.initial.setdefault(
                        "payment_form",
                        client_org.default_payment_form
                        or TransportOrder.payment_form_for_vat_rate(client_org.default_vat_rate),
                    )
        if not self.instance.pk and not self.is_bound:
            self.initial.setdefault("temperature_regime", "Отсутствует")

    def clean(self):
        cleaned = super().clean()
        owner = cleaned.get("owner_company")
        client = cleaned.get("client")
        if owner and client and owner == client:
            self.add_error("client", "Наша компания не может быть клиентом заказа.")
        if cleaned.get("rate") is not None and cleaned["rate"] <= 0:
            self.add_error("rate", "Ставка клиента должна быть больше нуля.")
        package_count = cleaned.get("package_count") or 0
        pallet_count = cleaned.get("pallet_count") or 0
        total_package_count = package_count + pallet_count
        cleaned["package_count"] = total_package_count or None
        cleaned["pallet_count"] = None
        return cleaned


class TransportOrderStopForm(StyledModelForm):
    # JSON is kept in a hidden field so a DaData selection can carry all
    # structured address parts without cluttering the order form.
    address_meta = forms.CharField(required=False, widget=forms.HiddenInput())

    class Meta:
        model = TransportOrderStop
        fields = [
            "sequence", "kind", "city", "address", "planned_date",
            "planned_time_from", "planned_time_to", "contact_name",
            "contact_phone", "instructions",
        ]
        widgets = {
            "sequence": forms.HiddenInput(),
            "planned_time_from": CRMTimeInput(),
            "planned_time_to": CRMTimeInput(),
            "instructions": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["planned_time_from"].input_formats = ("%H:%M",)
        self.fields["planned_time_to"].input_formats = ("%H:%M",)
        self.fields["address"].widget.attrs.update(
            {
                "autocomplete": "off",
                "data-dadata-address": "",
                "data-dadata-address-url": reverse("dadata-address-suggestions"),
                "data-dadata-city-source": f"id_{self.add_prefix('city')}",
                "data-dadata-meta-target": f"id_{self.add_prefix('address_meta')}",
                "placeholder": "Начните вводить улицу, дом или полный адрес",
            }
        )
        self.fields["city"].widget.attrs.update(
            {
                "autocomplete": "off",
                "data-dadata-city": "",
                "data-dadata-city-url": reverse("dadata-address-suggestions"),
                "placeholder": "Начните вводить город или населённый пункт",
            }
        )
        self.fields["contact_phone"].widget.attrs.update(
            {"inputmode": "tel", "placeholder": "+7 900 000-00-00"}
        )
        if self.instance.pk and not self.is_bound:
            values = {
                key: getattr(self.instance, key, "")
                for key in (
                    "address_fias_id", "address_postal_code", "address_region_code",
                    "address_region", "address_area", "address_city",
                    "address_settlement", "address_street", "address_house",
                    "address_block", "address_flat",
                )
            }
            if any(values.values()):
                self.initial["address_meta"] = json.dumps(values, ensure_ascii=False)

    def save(self, commit=True):
        instance = super().save(commit=False)
        raw = self.cleaned_data.get("address_meta") or ""
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            parsed = {}
        if not isinstance(parsed, dict):
            parsed = {}
        mapping = {
            "fias_id": "address_fias_id",
            "postal_code": "address_postal_code",
            "region_code": "address_region_code",
            "region": "address_region",
            "area": "address_area",
            "city": "address_city",
            "settlement": "address_settlement",
            "street": "address_street",
            "house": "address_house",
            "block": "address_block",
            "flat": "address_flat",
        }
        max_lengths = {
            "address_fias_id": 36, "address_postal_code": 12,
            "address_region_code": 3, "address_region": 150,
            "address_area": 150, "address_city": 150,
            "address_settlement": 150, "address_street": 150,
            "address_house": 30, "address_block": 30, "address_flat": 30,
        }
        for source, target in mapping.items():
            value = parsed.get(source) or parsed.get(target) or ""
            setattr(
                instance,
                target,
                str(value)[: max_lengths[target]],
            )
        if commit:
            instance.save()
        return instance


class BaseTransportOrderStopFormSet(BaseInlineFormSet):
    def active_forms(self):
        return [
            form
            for form in self.forms
            if hasattr(form, "cleaned_data")
            and not form.cleaned_data.get("DELETE")
            and form.cleaned_data.get("city")
        ]

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        rows = self.active_forms()
        if len(rows) < 2:
            raise forms.ValidationError(
                "Маршрут должен содержать минимум погрузку и выгрузку."
            )
        if rows[0].cleaned_data.get("kind") != TransportOrderStop.Kind.PICKUP:
            rows[0].add_error("kind", "Первая точка должна быть погрузкой.")
        if rows[-1].cleaned_data.get("kind") != TransportOrderStop.Kind.DELIVERY:
            rows[-1].add_error("kind", "Последняя точка должна быть выгрузкой.")
        previous_date = None
        for index, form in enumerate(rows, start=1):
            form.cleaned_data["sequence"] = index
            form.instance.sequence = index
            current_date = form.cleaned_data.get("planned_date")
            if previous_date and current_date and current_date < previous_date:
                form.add_error(
                    "planned_date",
                    "Дата точки не может быть раньше предыдущей точки маршрута.",
                )
            if current_date:
                previous_date = current_date

    def route_bounds(self):
        rows = self.active_forms()
        dated = [row.cleaned_data.get("planned_date") for row in rows]
        dated = [value for value in dated if value]
        return (
            dated[0] if dated else None,
            dated[-1] if dated else None,
        )


TransportOrderStopFormSet = inlineformset_factory(
    TransportOrder,
    TransportOrderStop,
    form=TransportOrderStopForm,
    formset=BaseTransportOrderStopFormSet,
    extra=0,
    can_delete=True,
)


class TransportationStopForm(StyledModelForm):
    address_meta = forms.CharField(required=False, widget=forms.HiddenInput())
    planned_date = forms.DateField(
        label="Дата",
        required=False,
        input_formats=CRM_DATE_INPUT_FORMATS,
        widget=CRMDateInput(),
    )
    planned_time_from = forms.TimeField(
        label="Время с",
        required=False,
        input_formats=("%H:%M",),
        widget=CRMTimeInput(),
    )
    planned_time_to = forms.TimeField(
        label="Время до",
        required=False,
        input_formats=("%H:%M",),
        widget=CRMTimeInput(),
    )

    class Meta:
        model = TransportationStop
        fields = [
            "sequence", "kind", "organization", "organization_text", "city",
            "address", "planned_date", "planned_time_from", "planned_time_to",
            "contact_name", "contact_phone", "instructions",
        ]
        widgets = {
            "sequence": forms.HiddenInput(),
            "instructions": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["organization"].queryset = Organization.objects.filter(
            is_active=True
        ).distinct()
        self.fields["organization"].required = False
        self.fields["organization"].widget.attrs.update(
            {
                "data-smart-select": "organization",
                "data-create-url": reverse("quick-organization-create"),
                "data-search-placeholder": "Название или ИНН контрагента",
                "data-create-label": "Создать контрагента",
            }
        )
        self.fields["planned_date"].widget = CRMDateInput()
        self.fields["planned_date"].input_formats = CRM_DATE_INPUT_FORMATS
        self.fields["planned_time_from"].input_formats = ("%H:%M",)
        self.fields["planned_time_to"].input_formats = ("%H:%M",)
        self.fields["city"].widget.attrs.update(
            {
                "autocomplete": "off",
                "data-dadata-city": "",
                "data-dadata-city-url": reverse("dadata-address-suggestions"),
                "placeholder": "Начните вводить город или населённый пункт",
            }
        )
        self.fields["address"].widget.attrs.update(
            {
                "autocomplete": "off",
                "data-dadata-address": "",
                "data-dadata-address-url": reverse("dadata-address-suggestions"),
                "data-dadata-city-source": f"id_{self.add_prefix('city')}",
                "data-dadata-meta-target": f"id_{self.add_prefix('address_meta')}",
                "placeholder": "Начните вводить улицу, дом или полный адрес",
            }
        )
        self.fields["contact_phone"].widget.attrs.update(
            {"inputmode": "tel", "placeholder": "+7 900 000-00-00"}
        )
        if self.instance.pk and not self.is_bound:
            planned_from = (
                timezone.localtime(self.instance.planned_from)
                if self.instance.planned_from and timezone.is_aware(self.instance.planned_from)
                else self.instance.planned_from
            )
            planned_to = (
                timezone.localtime(self.instance.planned_to)
                if self.instance.planned_to and timezone.is_aware(self.instance.planned_to)
                else self.instance.planned_to
            )
            self.initial["planned_date"] = (
                planned_from.date()
                if planned_from
                else None
            )
            self.initial["planned_time_from"] = (
                planned_from.time().replace(second=0, microsecond=0)
                if planned_from
                else None
            )
            self.initial["planned_time_to"] = (
                planned_to.time().replace(second=0, microsecond=0)
                if planned_to
                else None
            )
            values = {
                key: getattr(self.instance, key, "")
                for key in (
                    "address_fias_id", "address_postal_code", "address_region_code",
                    "address_region", "address_area", "address_city",
                    "address_settlement", "address_street", "address_house",
                    "address_block", "address_flat",
                )
            }
            if any(values.values()):
                self.initial["address_meta"] = json.dumps(values, ensure_ascii=False)

    @staticmethod
    def _planned_datetime(date_value, time_value):
        if not date_value:
            return None
        combined = datetime.combine(date_value, time_value or time(hour=9))
        return timezone.make_aware(combined, timezone.get_current_timezone())

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.planned_from = self._planned_datetime(
            self.cleaned_data.get("planned_date"),
            self.cleaned_data.get("planned_time_from"),
        )
        instance.planned_to = self._planned_datetime(
            self.cleaned_data.get("planned_date"),
            self.cleaned_data.get("planned_time_to"),
        )
        raw = self.cleaned_data.get("address_meta") or ""
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            parsed = {}
        if not isinstance(parsed, dict):
            parsed = {}
        mapping = {
            "fias_id": "address_fias_id",
            "postal_code": "address_postal_code",
            "region_code": "address_region_code",
            "region": "address_region",
            "area": "address_area",
            "city": "address_city",
            "settlement": "address_settlement",
            "street": "address_street",
            "house": "address_house",
            "block": "address_block",
            "flat": "address_flat",
        }
        max_lengths = {
            "address_fias_id": 36, "address_postal_code": 12,
            "address_region_code": 3, "address_region": 150,
            "address_area": 150, "address_city": 150,
            "address_settlement": 150, "address_street": 150,
            "address_house": 30, "address_block": 30, "address_flat": 30,
        }
        for source, target in mapping.items():
            value = parsed.get(source) or parsed.get(target) or ""
            setattr(instance, target, str(value)[: max_lengths[target]])
        if commit:
            instance.save()
        return instance


class BaseTransportationStopFormSet(BaseInlineFormSet):
    def active_forms(self):
        return [
            form
            for form in self.forms
            if hasattr(form, "cleaned_data")
            and not form.cleaned_data.get("DELETE")
            and form.cleaned_data.get("city")
        ]

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        rows = self.active_forms()
        if len(rows) < 2:
            raise forms.ValidationError(
                "Маршрут должен содержать минимум погрузку и выгрузку."
            )
        if rows[0].cleaned_data.get("kind") != TransportationStop.Kind.PICKUP:
            rows[0].add_error("kind", "Первая точка должна быть погрузкой.")
        if rows[-1].cleaned_data.get("kind") != TransportationStop.Kind.DELIVERY:
            rows[-1].add_error("kind", "Последняя точка должна быть выгрузкой.")
        previous_date = None
        for index, form in enumerate(rows, start=1):
            form.cleaned_data["sequence"] = index
            form.instance.sequence = index
            current_date = form.cleaned_data.get("planned_date")
            if previous_date and current_date and current_date < previous_date:
                form.add_error(
                    "planned_date",
                    "Дата точки не может быть раньше предыдущей точки маршрута.",
                )
            if current_date:
                previous_date = current_date

    def route_bounds(self):
        rows = self.active_forms()
        dated = [row.cleaned_data.get("planned_date") for row in rows]
        dated = [value for value in dated if value]
        return (
            dated[0] if dated else None,
            dated[-1] if dated else None,
        )


TransportationStopFormSet = inlineformset_factory(
    Transportation,
    TransportationStop,
    form=TransportationStopForm,
    formset=BaseTransportationStopFormSet,
    extra=0,
    can_delete=True,
)


class TransportationDocumentForm(StyledModelForm):
    pickup_address_meta = forms.CharField(required=False, widget=forms.HiddenInput())
    delivery_address_meta = forms.CharField(required=False, widget=forms.HiddenInput())
    client = OrganizationChoiceField(
        label="Клиент",
        queryset=Organization.objects.none(),
    )
    executor = OrganizationChoiceField(
        label="Исполнитель",
        queryset=Organization.objects.none(),
        required=False,
    )
    executor_role = forms.ChoiceField(
        label="Роль исполнителя",
        choices=TransportationLink.ContractorRole.choices,
        initial=TransportationLink.ContractorRole.CARRIER,
    )
    executor_contract = forms.ModelChoiceField(
        label="Договор с исполнителем",
        queryset=Contract.objects.none(),
        required=False,
    )
    executor_instruction_number = forms.CharField(
        label="Номер заявки / поручения исполнителю",
        max_length=100,
        required=False,
    )
    actual_carrier = OrganizationChoiceField(
        label="Фактический перевозчик",
        queryset=Organization.objects.none(),
        required=False,
    )
    driver = DriverChoiceField(
        label="Водитель", queryset=Driver.objects.none(), required=False
    )
    vehicle = VehicleChoiceField(
        label="Тягач / автомобиль", queryset=Vehicle.objects.none(), required=False
    )
    combination = forms.ModelChoiceField(
        label="Сцепка (тягач + прицеп)",
        queryset=VehicleCombination.objects.none(),
        required=False,
    )
    trailer = VehicleChoiceField(
        label="Прицеп / полуприцеп", queryset=Vehicle.objects.none(), required=False
    )
    trailer_registration_number = forms.CharField(
        label="Номер прицепа / полуприцепа", max_length=20, required=False
    )
    pickup_organization = OrganizationChoiceField(
        label="Грузоотправитель",
        queryset=Organization.objects.none(),
        required=False,
    )
    pickup_organization_text = forms.CharField(
        label="Грузоотправитель текстом",
        max_length=255,
        required=False,
        help_text="Если контрагента нет в справочнике, можно просто вписать название.",
    )
    pickup_city = forms.CharField(label="Город погрузки", max_length=120, required=False)
    pickup_address = forms.CharField(
        label="Адрес погрузки", max_length=255, required=False
    )
    pickup_date = forms.DateField(
        label="Дата погрузки", required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    delivery_organization = OrganizationChoiceField(
        label="Грузополучатель",
        queryset=Organization.objects.none(),
        required=False,
    )
    delivery_organization_text = forms.CharField(
        label="Грузополучатель текстом",
        max_length=255,
        required=False,
        help_text="Если контрагента нет в справочнике, можно просто вписать название.",
    )
    delivery_city = forms.CharField(label="Город выгрузки", max_length=120, required=False)
    delivery_address = forms.CharField(
        label="Адрес выгрузки", max_length=255, required=False
    )
    delivery_date = forms.DateField(
        label="Дата выгрузки", required=False, widget=forms.DateInput(attrs={"type": "date"})
    )

    class Meta:
        model = Transportation
        fields = [
            "owner_company", "manager", "document_date", "status",
            "client_reference", "customer_contract", "customer_amount",
            "customer_vat_rate", "executor_amount", "executor_vat_rate",
            "currency", "customer_payment_term_days",
            "executor_payment_term_days", "payment_due_basis", "cargo_name",
            "cargo_description", "weight_kg", "volume_m3", "package_count",
            "pallet_count", "package_type", "loading_method",
            "unloading_method", "temperature_regime", "adr_class", "vehicle_requirements",
            "special_requirements", "notes",
        ]
        widgets = {
            "document_date": forms.DateInput(
                format="%Y-%m-%d", attrs={"type": "date"}
            ),
            "cargo_description": forms.Textarea(attrs={"rows": 3}),
            "special_requirements": forms.Textarea(attrs={"rows": 3}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        configure_dadata_address_fields(self)
        self.user = user
        self.fields["owner_company"].queryset = Organization.objects.filter(
            is_own_company=True, is_active=True
        )
        self.fields["client"].queryset = Organization.objects.filter(
            is_active=True,
            roles__role=OrganizationRole.Role.CLIENT,
            roles__is_active=True,
        ).distinct()
        executor_roles = [
            OrganizationRole.Role.CARRIER,
            OrganizationRole.Role.FORWARDER,
        ]
        self.fields["executor"].queryset = Organization.objects.filter(
            is_active=True,
            roles__role__in=executor_roles,
            roles__is_active=True,
        ).distinct()
        self.fields["actual_carrier"].queryset = Organization.objects.filter(
            is_active=True,
            roles__role=OrganizationRole.Role.CARRIER,
            roles__is_active=True,
        ).distinct()
        self.fields["pickup_organization"].queryset = Organization.objects.filter(
            is_active=True,
            roles__role=OrganizationRole.Role.SHIPPER,
            roles__is_active=True,
        ).distinct()
        self.fields["delivery_organization"].queryset = Organization.objects.filter(
            is_active=True,
            roles__role=OrganizationRole.Role.CONSIGNEE,
            roles__is_active=True,
        ).distinct()
        active_contracts = Contract.objects.exclude(
            status__in=[Contract.Status.TERMINATED, Contract.Status.ARCHIVED]
        )
        self.fields["customer_contract"].queryset = active_contracts.filter(
            kind=Contract.Kind.CLIENT_FORWARDING
        )
        self.fields["executor_contract"].queryset = active_contracts.exclude(
            kind=Contract.Kind.CLIENT_FORWARDING
        )
        self.fields["customer_vat_rate"].queryset = self.fields[
            "customer_vat_rate"
        ].queryset.filter(is_active=True)
        self.fields["executor_vat_rate"].queryset = self.fields[
            "executor_vat_rate"
        ].queryset.filter(is_active=True)
        self.fields["customer_amount"].widget.attrs.update(
            {"min": "0.01", "step": "0.01", "placeholder": "0,00"}
        )
        self.fields["executor_amount"].widget.attrs.update(
            {"min": "0", "step": "0.01", "placeholder": "0,00"}
        )
        self.fields["cargo_name"].widget.attrs.update(
            {
                "list": "cargo-name-suggestions",
                "autocomplete": "off",
                "placeholder": "Начните вводить наименование груза",
            }
        )
        self.fields["package_count"].label = "Количество мест / паллет"
        self.fields["package_count"].help_text = (
            "Единое количество грузовых мест. Старые значения мест и паллет объединяются."
        )
        self.fields["pallet_count"].required = False
        self.fields["pallet_count"].widget = forms.HiddenInput()
        if not self.is_bound and self.instance.pk:
            self.initial["package_count"] = self.instance.total_package_count
            self.initial["pallet_count"] = ""

        if self.instance.pk and self.instance.owner_company_id:
            self.fields["owner_company"].queryset |= Organization.objects.filter(
                pk=self.instance.owner_company_id
            )
        elif self.fields["owner_company"].queryset.count() == 1:
            self.fields["owner_company"].initial = self.fields[
                "owner_company"
            ].queryset.first()
        if not self.instance.pk and user and user.is_authenticated:
            self.fields["manager"].initial = user

        client_party = None
        link = None
        assignment = None
        pickup = None
        delivery = None
        if self.instance.pk:
            client_party = self.instance.parties.filter(
                role=TransportationParty.Role.CLIENT, is_active=True
            ).first()
            link = self.instance.active_execution_link()
            assignment = self.instance.active_vehicle_assignment()
            pickup = self.instance.stops.filter(
                kind=TransportationStop.Kind.PICKUP
            ).order_by("sequence").first()
            delivery = self.instance.stops.filter(
                kind=TransportationStop.Kind.DELIVERY
            ).order_by("-sequence").first()

        actual_id = self.data.get("actual_carrier") if self.is_bound else None
        if not actual_id and assignment:
            actual_id = assignment.actual_carrier_id
        if actual_id and str(actual_id).isdigit():
            self.fields["driver"].queryset = Driver.objects.filter(
                Q(carrier__organization_id=actual_id)
                | Q(
                    employments__carrier__organization_id=actual_id,
                    employments__is_active=True,
                ),
                is_active=True,
            ).distinct()
            carrier_filter = {"carrier__organization_id": actual_id}
            self.fields["vehicle"].queryset = Vehicle.objects.filter(
                is_active=True, **carrier_filter
            ).exclude(kind__in=[Vehicle.Kind.TRAILER, Vehicle.Kind.SEMITRAILER])
            self.fields["trailer"].queryset = Vehicle.objects.filter(
                is_active=True,
                kind__in=[Vehicle.Kind.TRAILER, Vehicle.Kind.SEMITRAILER],
                **carrier_filter,
            )
            combination_filter = Q(
                is_active=True,
                tractor__carrier__organization_id=actual_id,
            )
            if assignment and assignment.combination_id:
                combination_filter |= Q(pk=assignment.combination_id)
            self.fields["combination"].queryset = VehicleCombination.objects.filter(
                combination_filter
            ).select_related("tractor", "trailer")

        organization_role_map = {}
        organization_ids = set()
        for field_name in (
            "client",
            "executor",
            "actual_carrier",
            "pickup_organization",
            "delivery_organization",
        ):
            organization_ids.update(
                self.fields[field_name].queryset.values_list("pk", flat=True)
            )
        for organization_id, role_value in OrganizationRole.objects.filter(
            organization_id__in=organization_ids,
            is_active=True,
        ).values_list("organization_id", "role"):
            organization_role_map.setdefault(str(organization_id), []).append(
                role_value
            )
        for field_name in (
            "client",
            "executor",
            "actual_carrier",
            "pickup_organization",
            "delivery_organization",
        ):
            self.fields[field_name].widget.role_map = organization_role_map

        if not self.is_bound and client_party:
            client_org = client_party.organization
            if client_org.default_vat_rate_id:
                self.initial.setdefault("customer_vat_rate", client_org.default_vat_rate_id)
            if client_org.payment_term_days:
                self.initial.setdefault("customer_payment_term_days", client_org.payment_term_days)
            owner_id = self.instance.owner_company_id or self.initial.get("owner_company")
            contracts = Contract.objects.filter(
                customer__organization=client_org,
                kind=Contract.Kind.CLIENT_FORWARDING,
                status__in=[Contract.Status.READY, Contract.Status.SIGNED],
            )
            if owner_id:
                contracts = contracts.filter(expeditor__organization_id=owner_id)
            contract = contracts.order_by("-status", "-contract_date").first()
            if contract:
                self.initial.setdefault("customer_contract", contract.pk)
                if contract.vat_rate_id:
                    self.initial.setdefault("customer_vat_rate", contract.vat_rate_id)
                if contract.payment_term_days:
                    self.initial.setdefault("customer_payment_term_days", contract.payment_term_days)

        organization_create_url = reverse("quick-organization-create")
        driver_create_url = reverse("quick-driver-create")
        vehicle_create_url = reverse("quick-vehicle-create")
        smart_selects = {
            "client": {
                "data-smart-select": "organization",
                "data-create-url": organization_create_url,
                "data-required-role": OrganizationRole.Role.CLIENT,
                "data-search-placeholder": "Введите название или ИНН клиента",
                "data-create-label": "Создать клиента",
            },
            "executor": {
                "data-smart-select": "organization",
                "data-create-url": organization_create_url,
                "data-role-source": "id_executor_role",
                "data-search-placeholder": "Введите название или ИНН исполнителя",
                "data-create-label": "Создать исполнителя",
            },
            "actual_carrier": {
                "data-smart-select": "organization",
                "data-create-url": organization_create_url,
                "data-required-role": OrganizationRole.Role.CARRIER,
                "data-search-placeholder": "Введите название или ИНН перевозчика",
                "data-create-label": "Создать перевозчика",
            },
            "pickup_organization": {
                "data-smart-select": "organization",
                "data-create-url": organization_create_url,
                "data-required-role": OrganizationRole.Role.SHIPPER,
                "data-search-placeholder": "Название или ИНН грузоотправителя",
                "data-create-label": "Создать грузоотправителя",
            },
            "delivery_organization": {
                "data-smart-select": "organization",
                "data-create-url": organization_create_url,
                "data-required-role": OrganizationRole.Role.CONSIGNEE,
                "data-search-placeholder": "Название или ИНН грузополучателя",
                "data-create-label": "Создать грузополучателя",
            },
            "driver": {
                "data-smart-select": "driver",
                "data-create-url": driver_create_url,
                "data-parent-source": "id_actual_carrier",
                "data-search-placeholder": "ФИО или номер удостоверения",
                "data-create-label": "Создать водителя",
            },
            "vehicle": {
                "data-smart-select": "vehicle",
                "data-create-url": vehicle_create_url,
                "data-parent-source": "id_actual_carrier",
                "data-resource-kind": "vehicle",
                "data-search-placeholder": "Госномер, марка или модель",
                "data-create-label": "Создать транспорт",
            },
            "combination": {
                "data-smart-select": "vehicle-combination",
                "data-parent-source": "id_actual_carrier",
                "data-search-placeholder": "Госномер тягача или прицепа",
            },
            "trailer": {
                "data-smart-select": "vehicle",
                "data-create-url": vehicle_create_url,
                "data-parent-source": "id_actual_carrier",
                "data-resource-kind": "trailer",
                "data-search-placeholder": "Госномер прицепа",
                "data-create-label": "Создать прицеп",
            },
        }
        for field_name, attrs in smart_selects.items():
            self.fields[field_name].widget.attrs.update(attrs)

        self.initial.update(
            {
                "client": client_party.organization_id if client_party else None,
                "executor": (
                    link.contractor_party.organization_id if link else None
                ),
                "executor_role": (
                    link.contractor_role
                    if link else TransportationLink.ContractorRole.CARRIER
                ),
                "executor_contract": link.contract_id if link else None,
                "executor_instruction_number": (
                    link.instruction_number if link else ""
                ),
                "actual_carrier": (
                    assignment.actual_carrier_id if assignment else None
                ),
                "driver": assignment.driver_id if assignment else None,
                "vehicle": assignment.vehicle_id if assignment else None,
                "combination": assignment.combination_id if assignment else None,
                "trailer": assignment.trailer_id if assignment else None,
                "trailer_registration_number": (
                    assignment.trailer_registration_number if assignment else ""
                ),
                "pickup_city": pickup.city if pickup else "",
                "pickup_organization": pickup.organization_id if pickup else None,
                "pickup_organization_text": pickup.organization_text if pickup else "",
                "pickup_address": pickup.address if pickup else "",
                "pickup_address_meta": self._stop_address_meta(pickup),
                "pickup_date": (
                    pickup.planned_from.date()
                    if pickup and pickup.planned_from
                    else self.instance.planned_start_date
                ),
                "delivery_city": delivery.city if delivery else "",
                "delivery_organization": delivery.organization_id if delivery else None,
                "delivery_organization_text": delivery.organization_text if delivery else "",
                "delivery_address": delivery.address if delivery else "",
                "delivery_address_meta": self._stop_address_meta(delivery),
                "delivery_date": (
                    delivery.planned_from.date()
                    if delivery and delivery.planned_from
                    else self.instance.planned_end_date
                ),
            }
        )

    @staticmethod
    def _stop_address_meta(stop):
        if not stop:
            return ""
        values = {
            key: getattr(stop, key, "")
            for key in (
                "address_fias_id", "address_postal_code", "address_region_code",
                "address_region", "address_area", "address_city",
                "address_settlement", "address_street", "address_house",
                "address_block", "address_flat",
            )
        }
        return json.dumps(values, ensure_ascii=False) if any(values.values()) else ""

    def clean(self):
        cleaned = super().clean()
        owner = cleaned.get("owner_company")
        client = cleaned.get("client")
        executor = cleaned.get("executor")
        role = cleaned.get("executor_role")
        actual_carrier = cleaned.get("actual_carrier")
        customer_contract = cleaned.get("customer_contract")
        executor_contract = cleaned.get("executor_contract")
        pickup_date = cleaned.get("pickup_date")
        delivery_date = cleaned.get("delivery_date")
        target_status = cleaned.get("status")
        driver = cleaned.get("driver")
        vehicle = cleaned.get("vehicle")

        if self.instance.pk and target_status:
            for message in self.instance.status_transition_issues(target_status):
                self.add_error("status", message)

        if target_status in Transportation.Status.values:
            workflow = Transportation.WORKFLOW_STATUSES
            target_index = (
                workflow.index(target_status)
                if target_status in workflow
                else -1
            )
            documents_index = workflow.index(
                Transportation.Status.EXECUTOR_DOCUMENTS_VERIFIED
            )
            vehicle_index = workflow.index(Transportation.Status.VEHICLE_CONFIRMED)
            loading_index = workflow.index(Transportation.Status.LOADING)
            if target_index >= documents_index:
                if not executor:
                    self.add_error("executor", "Для этого этапа выберите исполнителя.")
                if not executor_contract:
                    self.add_error(
                        "executor_contract",
                        "Для этого этапа нужен действующий договор с исполнителем.",
                    )
            if target_index >= vehicle_index:
                if not actual_carrier:
                    self.add_error(
                        "actual_carrier", "Для подтверждения машины укажите фактического перевозчика."
                    )
                if not driver:
                    self.add_error("driver", "Для подтверждения машины назначьте водителя.")
                if not vehicle:
                    self.add_error(
                        "vehicle", "Для подтверждения машины выберите тягач или автомобиль."
                    )
            if target_index >= loading_index and (
                not self.instance.pk
                or self.instance.posting_status != Transportation.PostingStatus.POSTED
            ):
                self.add_error(
                    "status",
                    "Сначала проведите рейс, затем переводите его на операционные этапы.",
                )
        if owner and client and owner == client:
            self.add_error("client", "Наша компания не может быть клиентом этого рейса.")
        if owner and executor and owner == executor:
            self.add_error("executor", "Наша компания не может быть своим исполнителем.")
        if pickup_date and delivery_date and delivery_date < pickup_date:
            self.add_error(
                "delivery_date", "Дата выгрузки не может быть раньше даты погрузки."
            )
        if executor and actual_carrier and role == TransportationLink.ContractorRole.CARRIER:
            if executor != actual_carrier:
                self.add_error(
                    "actual_carrier",
                    "Для прямого перевозчика исполнитель и фактический перевозчик должны совпадать.",
                )
        if any(
            cleaned.get(name)
            for name in ("driver", "vehicle", "combination", "trailer")
        ) and not actual_carrier:
            self.add_error(
                "actual_carrier", "Сначала выберите фактического перевозчика."
            )
        combination = cleaned.get("combination")
        if combination:
            if actual_carrier and combination.tractor.carrier.organization_id != actual_carrier.pk:
                self.add_error(
                    "combination",
                    "Сцепка должна принадлежать фактическому перевозчику.",
                )
            if cleaned.get("vehicle") and cleaned["vehicle"] != combination.tractor:
                self.add_error("vehicle", "Основной автомобиль не соответствует выбранной сцепке.")
            if cleaned.get("trailer") and cleaned["trailer"] != combination.trailer:
                self.add_error("trailer", "Прицеп не соответствует выбранной сцепке.")
            cleaned["vehicle"] = combination.tractor
            cleaned["trailer"] = combination.trailer
            cleaned["trailer_registration_number"] = combination.trailer.registration_number
        driver = cleaned.get("driver")
        if driver and actual_carrier and not driver.works_for_organization(
            actual_carrier
        ):
            self.add_error(
                "driver", "Водитель должен работать у фактического перевозчика."
            )
        for field_name in ("vehicle", "trailer"):
            resource = cleaned.get(field_name)
            if resource and actual_carrier and resource.carrier.organization_id != actual_carrier.pk:
                self.add_error(
                    field_name,
                    "Ресурс должен принадлежать фактическому перевозчику.",
                )
        if customer_contract and client:
            if (
                customer_contract.customer_id
                and customer_contract.customer.organization_id != client.pk
            ):
                self.add_error(
                    "customer_contract", "Договор должен быть заключён с выбранным клиентом."
                )
            if (
                owner
                and customer_contract.expeditor.organization_id != owner.pk
            ):
                self.add_error(
                    "customer_contract", "Договор относится к другой нашей компании."
                )
        if executor_contract and executor:
            expected_kind = (
                Contract.Kind.CARRIER_TRANSPORT
                if role == TransportationLink.ContractorRole.CARRIER
                else Contract.Kind.SUBCONTRACTOR_FORWARDING
            )
            if executor_contract.kind != expected_kind:
                self.add_error(
                    "executor_contract", "Вид договора не соответствует роли исполнителя."
                )
            if (
                not executor_contract.carrier_id
                or executor_contract.carrier.organization_id != executor.pk
            ):
                self.add_error(
                    "executor_contract", "Договор должен быть заключён с исполнителем."
                )
            if owner and executor_contract.expeditor.organization_id != owner.pk:
                self.add_error(
                    "executor_contract", "Договор относится к другой нашей компании."
                )
        package_count = cleaned.get("package_count") or 0
        pallet_count = cleaned.get("pallet_count") or 0
        total_package_count = package_count + pallet_count
        cleaned["package_count"] = total_package_count or None
        cleaned["pallet_count"] = None
        return cleaned

    @staticmethod
    def _planned_datetime(value):
        if not value:
            return None
        combined = datetime.combine(value, time(hour=9))
        return timezone.make_aware(combined, timezone.get_current_timezone())

    def save(self, commit=True):
        if not getattr(self, "use_route_formset", False):
            self.instance.planned_start_date = self.cleaned_data.get("pickup_date")
            self.instance.planned_end_date = self.cleaned_data.get("delivery_date")
        self.instance.package_count = self.cleaned_data.get("package_count")
        self.instance.pallet_count = None
        return super().save(commit=commit)

    def save_related(self, user):
        transportation = self.instance
        client = self.cleaned_data["client"]
        executor = self.cleaned_data.get("executor")
        executor_role = self.cleaned_data.get("executor_role")
        actual_carrier = self.cleaned_data.get("actual_carrier")

        own_party, _ = TransportationParty.objects.update_or_create(
            transportation=transportation,
            organization=transportation.owner_company,
            role=TransportationParty.Role.OWN_COMPANY,
            defaults={"sequence": 2, "source": "document", "is_active": True},
        )
        TransportationParty.objects.filter(
            transportation=transportation,
            role=TransportationParty.Role.CLIENT,
        ).exclude(organization=client).update(is_active=False)
        TransportationParty.objects.update_or_create(
            transportation=transportation,
            organization=client,
            role=TransportationParty.Role.CLIENT,
            defaults={"sequence": 1, "source": "document", "is_active": True},
        )

        def address_values(prefix):
            raw = self.cleaned_data.get(f"{prefix}_address_meta") or ""
            try:
                parsed = json.loads(raw) if isinstance(raw, str) else raw
            except (TypeError, ValueError):
                parsed = {}
            if not isinstance(parsed, dict):
                parsed = {}
            allowed = {
                "address_fias_id", "address_postal_code", "address_region_code",
                "address_region", "address_area", "address_city",
                "address_settlement", "address_street", "address_house",
                "address_block", "address_flat",
            }
            max_lengths = {
                "address_fias_id": 36, "address_postal_code": 12,
                "address_region_code": 3, "address_region": 150,
                "address_area": 150, "address_city": 150,
                "address_settlement": 150, "address_street": 150,
                "address_house": 30, "address_block": 30, "address_flat": 30,
            }
            aliases = {
                "address_fias_id": ("address_fias_id", "fias_id"),
                "address_postal_code": ("address_postal_code", "postal_code"),
                "address_region_code": ("address_region_code", "region_code"),
                "address_region": ("address_region", "region"),
                "address_area": ("address_area", "area"),
                "address_city": ("address_city", "city"),
                "address_settlement": ("address_settlement", "settlement"),
                "address_street": ("address_street", "street"),
                "address_house": ("address_house", "house"),
                "address_block": ("address_block", "block"),
                "address_flat": ("address_flat", "flat"),
            }
            return {
                key: str(
                    next((parsed.get(alias) for alias in aliases[key] if parsed.get(alias)), "")
                    or ""
                )[: max_lengths[key]]
                for key in allowed
            }

        if not getattr(self, "use_route_formset", False):
            pickup = transportation.stops.filter(
                kind=TransportationStop.Kind.PICKUP
            ).order_by("sequence").first()
            pickup_values = {
                "kind": TransportationStop.Kind.PICKUP,
                "organization": self.cleaned_data.get("pickup_organization"),
                "organization_text": self.cleaned_data.get("pickup_organization_text", ""),
                "city": self.cleaned_data["pickup_city"],
                "address": self.cleaned_data.get("pickup_address", ""),
                "planned_from": self._planned_datetime(self.cleaned_data["pickup_date"]),
            }
            pickup_values.update(address_values("pickup"))
            if pickup:
                for field_name, value in pickup_values.items():
                    setattr(pickup, field_name, value)
                pickup.save(update_fields=[*pickup_values, "updated_at"])
            else:
                TransportationStop.objects.create(
                    transportation=transportation,
                    sequence=1,
                    **pickup_values,
                )

            delivery = transportation.stops.filter(
                kind=TransportationStop.Kind.DELIVERY
            ).order_by("-sequence").first()
            delivery_values = {
                "kind": TransportationStop.Kind.DELIVERY,
                "organization": self.cleaned_data.get("delivery_organization"),
                "organization_text": self.cleaned_data.get("delivery_organization_text", ""),
                "city": self.cleaned_data["delivery_city"],
                "address": self.cleaned_data.get("delivery_address", ""),
                "planned_from": self._planned_datetime(self.cleaned_data["delivery_date"]),
            }
            delivery_values.update(address_values("delivery"))
            if delivery:
                for field_name, value in delivery_values.items():
                    setattr(delivery, field_name, value)
                delivery.save(update_fields=[*delivery_values, "updated_at"])
            else:
                last_sequence = (
                    transportation.stops.order_by("-sequence").values_list(
                        "sequence", flat=True
                    ).first()
                    or 1
                )
                TransportationStop.objects.create(
                    transportation=transportation,
                    sequence=last_sequence + 1,
                    **delivery_values,
                )

        for assignment in transportation.vehicle_assignments.filter(is_active=True):
            assignment.is_active = False
            assignment.execution_link = None
            assignment.save(update_fields=["is_active", "execution_link", "updated_at"])
        for old_link in transportation.execution_links.order_by("-sequence"):
            old_link.delete()
        transportation.parties.filter(
            role__in=[
                TransportationParty.Role.EXECUTOR,
                TransportationParty.Role.FORWARDER,
                TransportationParty.Role.FACTUAL_CARRIER,
            ]
        ).update(is_active=False)

        link = None
        if executor:
            executor_party, _ = TransportationParty.objects.update_or_create(
                transportation=transportation,
                organization=executor,
                role=TransportationParty.Role.EXECUTOR,
                defaults={"sequence": 3, "source": "document", "is_active": True},
            )
            link = TransportationLink.objects.create(
                transportation=transportation,
                principal_party=own_party,
                contractor_party=executor_party,
                contractor_role=executor_role,
                sequence=1,
                contract=self.cleaned_data.get("executor_contract"),
                instruction_number=self.cleaned_data.get(
                    "executor_instruction_number", ""
                ),
                source="document",
            )

        final_link = link
        if actual_carrier:
            factual_party, _ = TransportationParty.objects.update_or_create(
                transportation=transportation,
                organization=actual_carrier,
                role=TransportationParty.Role.FACTUAL_CARRIER,
                defaults={"sequence": 5, "source": "document", "is_active": True},
            )
            if (
                link
                and executor_role == TransportationLink.ContractorRole.FORWARDER
            ):
                final_link = TransportationLink.objects.create(
                    transportation=transportation,
                    parent=link,
                    principal_party=link.contractor_party,
                    contractor_party=factual_party,
                    contractor_role=TransportationLink.ContractorRole.CARRIER,
                    sequence=2,
                    source="document",
                )
            driver = self.cleaned_data.get("driver")
            vehicle = self.cleaned_data.get("vehicle")
            new_assignment = VehicleAssignment(
                transportation=transportation,
                execution_link=final_link,
                actual_carrier=actual_carrier,
                driver=driver,
                vehicle=vehicle,
                combination=self.cleaned_data.get("combination"),
                trailer=self.cleaned_data.get("trailer"),
                trailer_registration_number=self.cleaned_data.get(
                    "trailer_registration_number", ""
                ),
                confirmed_by=user if driver and vehicle else None,
                confirmed_at=timezone.now() if driver and vehicle else None,
            )
            new_assignment.full_clean()
            new_assignment.save()
        transportation.legacy_chain_sync = False
        transportation.save(update_fields=["legacy_chain_sync", "updated_at"])
        return transportation


class ContractForm(StyledModelForm):
    class Meta:
        model = Contract
        fields = [
            "kind", "expeditor", "customer", "carrier", "number",
            "contract_date", "city", "valid_until", "terminated_on", "status",
            "expeditor_representative", "expeditor_authority_basis",
            "counterparty_representative", "counterparty_authority_basis",
            "payment_term_days", "payment_terms", "debt_limit", "vat_rate",
            "document_file", "notes",
        ]
        widgets = {
            "contract_date": forms.DateInput(
                format="%Y-%m-%d", attrs={"type": "date"}
            ),
            "valid_until": forms.DateInput(
                format="%Y-%m-%d", attrs={"type": "date"}
            ),
            "terminated_on": forms.DateInput(
                format="%Y-%m-%d", attrs={"type": "date"}
            ),
            "payment_terms": forms.Textarea(attrs={"rows": 3}),
            "notes": forms.Textarea(attrs={"rows": 3}),
            "document_file": forms.ClearableFileInput(
                attrs={"accept": "application/pdf,.pdf"}
            ),
        }
        help_texts = {
            "number": "Оставьте пустым, чтобы CRM присвоила номер автоматически.",
            "carrier": (
                "Для договора ТЭО с привлечённым экспедитором выберите его "
                "карточку из справочника перевозчиков."
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["expeditor"].queryset = CompanyProfile.objects.filter(
            is_active=True
        )
        self.fields["customer"].queryset = Customer.objects.filter(is_active=True)
        self.fields["carrier"].queryset = Carrier.objects.filter(is_active=True)
        self.fields["vat_rate"].queryset = VATRate.objects.filter(is_active=True)
        self.fields["vat_rate"].required = False
        self.fields["payment_term_days"].required = False
        self.fields["payment_terms"].required = False
        self.fields["debt_limit"].required = False
        if self.instance.expeditor_id:
            self.fields["expeditor"].queryset |= CompanyProfile.objects.filter(
                pk=self.instance.expeditor_id
            )
        elif self.fields["expeditor"].queryset.count() == 1:
            profile = self.fields["expeditor"].queryset.first()
            self.fields["expeditor"].initial = profile
            self.fields["expeditor_representative"].initial = profile.director_name
        if self.instance.customer_id:
            self.fields["customer"].queryset |= Customer.objects.filter(
                pk=self.instance.customer_id
            )
        if self.instance.carrier_id:
            self.fields["carrier"].queryset |= Carrier.objects.filter(
                pk=self.instance.carrier_id
            )

    def clean(self):
        cleaned = super().clean()
        expeditor = cleaned.get("expeditor")
        counterparty = (
            cleaned.get("customer")
            if cleaned.get("kind") == Contract.Kind.CLIENT_FORWARDING
            else cleaned.get("carrier")
        )
        if expeditor and not cleaned.get("expeditor_representative"):
            cleaned["expeditor_representative"] = expeditor.director_name
            self.instance.expeditor_representative = expeditor.director_name
        if counterparty and not cleaned.get("counterparty_representative"):
            cleaned["counterparty_representative"] = counterparty.director_name
            self.instance.counterparty_representative = counterparty.director_name
        if cleaned.get("debt_limit") is None:
            cleaned["debt_limit"] = Decimal("0.00")
            self.instance.debt_limit = Decimal("0.00")
        return cleaned


class TransportationIncidentForm(StyledModelForm):
    class Meta:
        model = TransportationIncident
        fields = [
            "kind", "status", "counterparty", "occurred_on", "title",
            "description", "financial_impact", "amount", "currency",
            "resolution", "document_file", "resolved_on",
        ]
        widgets = {
            "occurred_on": forms.DateInput(attrs={"type": "date"}),
            "resolved_on": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 3}),
            "resolution": forms.Textarea(attrs={"rows": 3}),
            "document_file": forms.ClearableFileInput(
                attrs={"accept": "application/pdf,image/*"}
            ),
        }

    def __init__(self, *args, transportation=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.transportation = transportation or getattr(self.instance, "transportation", None)
        self.fields["counterparty"].queryset = Organization.objects.filter(
            is_active=True
        ).order_by("name")
        if self.transportation and not self.is_bound:
            self.initial.setdefault("currency", self.transportation.currency)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("status") == TransportationIncident.Status.RESOLVED:
            if not cleaned.get("resolved_on"):
                cleaned["resolved_on"] = timezone.localdate()
        if cleaned.get("financial_impact") == TransportationIncident.FinancialImpact.NONE:
            cleaned["amount"] = Decimal("0")
        return cleaned


class PlannerTaskForm(StyledModelForm):
    class Meta:
        model = PlannerTask
        fields = [
            "title", "description", "kind", "status", "priority",
            "transportation", "assignee", "due_date",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["transportation"].queryset = (
            Transportation.objects.exclude(status=Transportation.Status.CANCELLED)
            .select_related("owner_company")
            .prefetch_related("stops")
        )
        self.fields["assignee"].queryset = get_user_model().objects.filter(
            is_active=True
        ).order_by("last_name", "first_name", "username")
        if not self.is_bound and not self.instance.pk and user and user.is_authenticated:
            self.initial.setdefault("assignee", user.pk)
        self.fields["title"].widget.attrs.setdefault(
            "placeholder", "Например: запросить подписанный УПД"
        )


class DriverForm(StyledModelForm):
    carrier = CarrierChoiceField(
        label="Основная компания",
        queryset=Carrier.objects.none(),
    )
    tax_id = forms.CharField(
        label="ИНН",
        max_length=20,
        required=False,
        help_text="ИНН физического лица — 12 цифр.",
    )
    class Meta:
        model = Driver
        fields = [
            "carrier", "last_name", "first_name", "middle_name", "phone",
            "birth_date", "tax_id", "license_number",
            "license_categories", "license_issue_date",
            "license_expiry_date", "notes", "is_active",
        ]
        widgets = {
            "birth_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "license_issue_date": forms.DateInput(
                format="%Y-%m-%d", attrs={"type": "date"}
            ),
            "license_expiry_date": forms.DateInput(
                format="%Y-%m-%d", attrs={"type": "date"}
            ),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, register_mode=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.register_mode = register_mode
        self.fields["carrier"].label = "Основная компания"
        self.fields["carrier"].help_text = (
            "Компания, которая будет подставляться для водителя по умолчанию."
        )
        active_carriers = Carrier.objects.filter(is_active=True)
        if self.instance.carrier_id:
            active_carriers |= Carrier.objects.filter(pk=self.instance.carrier_id)
        self.fields["carrier"].queryset = active_carriers.distinct()
        if register_mode:
            for field_name in (
                "carrier", "license_number", "license_categories",
                "license_issue_date", "license_expiry_date",
            ):
                self.fields[field_name].required = False
                self.fields[field_name].widget = forms.HiddenInput()
        fio_url = reverse("dadata-fio-suggestions")
        for field_name, part in (
            ("last_name", "SURNAME"),
            ("first_name", "NAME"),
            ("middle_name", "PATRONYMIC"),
        ):
            self.fields[field_name].widget.attrs.update(
                {
                    "autocomplete": "off",
                    "data-dadata-driver": "fio",
                    "data-dadata-url": fio_url,
                    "data-dadata-part": part,
                }
            )
        self.fields["phone"].widget.attrs.update(
            {"autocomplete": "tel", "inputmode": "tel", "placeholder": "+7 900 000-00-00"}
        )
        self.fields["tax_id"].widget.attrs.update(
            {"inputmode": "numeric", "placeholder": "12 цифр", "maxlength": "12"}
        )
        self.fields["license_number"].widget.attrs.update(
            {"placeholder": "00 00 000000"}
        )

    def clean(self):
        cleaned = super().clean()
        issued = cleaned.get("license_issue_date") if not self.register_mode else None
        expires = cleaned.get("license_expiry_date") if not self.register_mode else None
        if issued and expires and expires < issued:
            self.add_error(
                "license_expiry_date",
                "Срок действия не может закончиться раньше даты выдачи.",
            )
        return cleaned

    def clean_tax_id(self):
        tax_id = re.sub(r"\D", "", self.cleaned_data.get("tax_id", ""))
        if tax_id and len(tax_id) != 12:
            raise forms.ValidationError("ИНН физлица должен содержать 12 цифр.")
        duplicate = Driver.objects.filter(tax_id=tax_id).exclude(
            pk=self.instance.pk
        ).first() if tax_id else None
        if duplicate:
            raise forms.ValidationError(
                f"Водитель с таким ИНН уже существует: {duplicate.full_name}."
            )
        return tax_id

class IgnoreRegisterFlagConstraintMixin:
    register_flag_field = ""

    def _post_clean(self):
        desired = self.cleaned_data.get(self.register_flag_field)
        if self.register_flag_field in self.cleaned_data:
            self.cleaned_data[self.register_flag_field] = False
        super()._post_clean()
        if self.register_flag_field:
            self.cleaned_data[self.register_flag_field] = desired
            setattr(self.instance, self.register_flag_field, desired)


class DriverPassportForm(IgnoreRegisterFlagConstraintMixin, StyledModelForm):
    register_flag_field = "is_current"
    class Meta:
        model = DriverPassport
        fields = [
            "series", "number", "issued_by", "issue_date", "is_current", "notes"
        ]
        widgets = {
            "issue_date": forms.DateInput(
                format="%Y-%m-%d", attrs={"type": "date"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.initial["is_current"] = False
            self.fields["is_current"].initial = False
        self.fields["series"].widget.attrs.update(
            {"inputmode": "numeric", "placeholder": "0000", "maxlength": "4"}
        )
        self.fields["number"].widget.attrs.update(
            {"inputmode": "numeric", "placeholder": "000000", "maxlength": "6"}
        )
        self.fields["issued_by"].widget.attrs.update(
            {
                "autocomplete": "off",
                "data-dadata-driver": "fms",
                "data-dadata-url": reverse("dadata-fms-unit-suggestions"),
                "placeholder": "Введите код или название подразделения",
            }
        )

    def clean_series(self):
        value = DriverPassport.normalize_part(self.cleaned_data.get("series"))
        if len(value) != 4:
            raise forms.ValidationError("Серия должна содержать 4 цифры.")
        return value

    def clean_number(self):
        value = DriverPassport.normalize_part(self.cleaned_data.get("number"))
        if len(value) != 6:
            raise forms.ValidationError("Номер должен содержать 6 цифр.")
        return value

    def clean(self):
        cleaned = super().clean()
        series = cleaned.get("series")
        number = cleaned.get("number")
        if series and number:
            duplicate = DriverPassport.objects.filter(
                series=series, number=number
            ).exclude(pk=self.instance.pk).select_related("driver").first()
            if duplicate:
                self.add_error(
                    "number",
                    (
                        "Паспорт с этой серией и номером уже закреплён за "
                        f"водителем {duplicate.driver.full_name}."
                    ),
                )
        return cleaned


class BaseDriverPassportFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        current_count = 0
        identities = set()
        has_passports = False
        for form in self.forms:
            if not hasattr(form, "cleaned_data") or form.cleaned_data.get("DELETE"):
                continue
            series = form.cleaned_data.get("series")
            number = form.cleaned_data.get("number")
            if not series and not number:
                continue
            has_passports = True
            identity = (series, number)
            if identity in identities:
                form.add_error("number", "Такой паспорт уже указан в этой карточке.")
            identities.add(identity)
            if form.cleaned_data.get("is_current"):
                current_count += 1
        if has_passports and current_count != 1:
            raise forms.ValidationError(
                "Укажите ровно один действующий паспорт водителя."
            )


DriverPassportFormSet = inlineformset_factory(
    Driver,
    DriverPassport,
    form=DriverPassportForm,
    formset=BaseDriverPassportFormSet,
    extra=1,
    can_delete=True,
)


class DriverLicenseCategoryWidget(forms.CheckboxSelectMultiple):
    """Compact category checkboxes with a description on hover."""

    descriptions = _DRIVER_LICENSE_CATEGORY_DESCRIPTIONS

    def create_option(
        self, name, value, label, selected, index, subindex=None, attrs=None
    ):
        option = super().create_option(
            name, value, label, selected, index, subindex=subindex, attrs=attrs
        )
        code = normalize_driver_license_category(value)
        description = self.descriptions.get(code)
        if description:
            option["attrs"]["class"] = "uk-checkbox"
            option["attrs"]["title"] = description
            option["attrs"]["data-category"] = code
            option["label"] = format_html(
                '<span class="driver-license-category-name" title="{}">{}</span>',
                description,
                code,
            )
        return option


class DriverLicenseCategoryField(forms.MultipleChoiceField):
    """Store selected checkbox values as the legacy comma-separated string."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault(
            "choices",
            tuple(
                (code, code) for code, _ in DRIVER_LICENSE_CATEGORY_CHOICES
            ),
        )
        kwargs.setdefault("widget", DriverLicenseCategoryWidget)
        super().__init__(*args, **kwargs)

    def prepare_value(self, value):
        return split_driver_license_categories(value)

    def to_python(self, value):
        return split_driver_license_categories(value)

    def clean(self, value):
        values = super().clean(value)
        return ", ".join(values)


class DriverLicenseForm(IgnoreRegisterFlagConstraintMixin, StyledModelForm):
    register_flag_field = "is_current"
    categories = DriverLicenseCategoryField(
        label="Категории",
        help_text="Наведите курсор на код категории, чтобы увидеть описание.",
    )

    class Meta:
        model = DriverLicense
        fields = [
            "number", "categories", "issue_date", "expiry_date",
            "is_current", "notes",
        ]
        widgets = {
            "issue_date": forms.DateInput(
                format="%Y-%m-%d", attrs={"type": "date"}
            ),
            "expiry_date": forms.DateInput(
                format="%Y-%m-%d", attrs={"type": "date"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name in ("number", "categories", "issue_date", "expiry_date"):
            self.fields[field_name].required = False
        if not self.instance.pk:
            self.initial["is_current"] = False
            self.fields["is_current"].initial = False
        self.fields["number"].widget.attrs.update(
            {"placeholder": "00 00 000000", "autocomplete": "off"}
        )
        self.fields["categories"].widget.attrs["class"] = (
            "driver-license-category-picker"
        )

    def clean_number(self):
        number = " ".join((self.cleaned_data.get("number") or "").split())
        identity = DriverLicense.identity_from_number(number)
        if not identity:
            return ""
        duplicate = DriverLicense.objects.filter(identity_key=identity).exclude(
            pk=self.instance.pk
        ).select_related("driver").first()
        if duplicate:
            raise forms.ValidationError(
                "Удостоверение с таким номером уже закреплено за водителем "
                f"{duplicate.driver.full_name}."
            )
        return number

    def clean(self):
        cleaned = super().clean()
        has_license_data = any(
            cleaned.get(field_name)
            for field_name in ("number", "categories", "issue_date", "expiry_date")
        )
        if has_license_data:
            if not cleaned.get("number"):
                self.add_error("number", "Укажите номер водительского удостоверения.")
            if not cleaned.get("categories"):
                self.add_error("categories", "Укажите категории.")
            if not cleaned.get("expiry_date"):
                self.add_error("expiry_date", "Укажите срок действия.")
        issued = cleaned.get("issue_date")
        expires = cleaned.get("expiry_date")
        if issued and expires and expires < issued:
            self.add_error(
                "expiry_date",
                "Срок действия не может закончиться раньше даты выдачи.",
            )
        return cleaned


class BaseDriverLicenseFormSet(BaseInlineFormSet):
    def active_forms(self):
        return [
            form for form in self.forms
            if hasattr(form, "cleaned_data")
            and not form.cleaned_data.get("DELETE")
            and form.cleaned_data.get("number")
        ]

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        forms_with_data = self.active_forms()
        if not forms_with_data:
            return
        identities = set()
        current_count = 0
        for form in forms_with_data:
            identity = DriverLicense.identity_from_number(
                form.cleaned_data.get("number")
            )
            if identity in identities:
                form.add_error(
                    "number", "Такое удостоверение уже указано в этой карточке."
                )
            identities.add(identity)
            if form.cleaned_data.get("is_current"):
                current_count += 1
        if current_count != 1:
            raise forms.ValidationError(
                "Укажите ровно одно действующее водительское удостоверение."
            )

    def current_data(self):
        return next(
            (
                form.cleaned_data
                for form in self.active_forms()
                if form.cleaned_data.get("is_current")
            ),
            None,
        )

    def save_register(self, driver):
        rows = [form.cleaned_data for form in self.active_forms()]
        keys = {
            DriverLicense.identity_from_number(row["number"]) for row in rows
        }
        DriverLicense.objects.filter(driver=driver).exclude(
            identity_key__in=keys
        ).delete()
        DriverLicense.objects.filter(driver=driver).update(is_current=False)
        for row in rows:
            identity = DriverLicense.identity_from_number(row["number"])
            DriverLicense.objects.update_or_create(
                driver=driver,
                identity_key=identity,
                defaults={
                    "number": row["number"],
                    "categories": row["categories"],
                    "issue_date": row.get("issue_date"),
                    "expiry_date": row["expiry_date"],
                    "is_current": row.get("is_current", False),
                    "notes": row.get("notes", ""),
                },
            )


DriverLicenseFormSet = inlineformset_factory(
    Driver,
    DriverLicense,
    form=DriverLicenseForm,
    formset=BaseDriverLicenseFormSet,
    extra=1,
    can_delete=True,
)


class DriverEmploymentForm(IgnoreRegisterFlagConstraintMixin, StyledModelForm):
    register_flag_field = "is_primary"
    carrier = CarrierChoiceField(
        label="Перевозчик",
        queryset=Carrier.objects.none(),
    )

    class Meta:
        model = DriverEmployment
        fields = ["carrier", "is_primary"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        carriers = Carrier.objects.filter(is_active=True)
        if self.instance.carrier_id:
            carriers |= Carrier.objects.filter(pk=self.instance.carrier_id)
        self.fields["carrier"].queryset = carriers.distinct()
        self.fields["carrier"].label = "Перевозчик"
        self.fields["carrier"].widget.attrs.update(
            {"data-search-placeholder": "Введите название или ИНН перевозчика"}
        )
        if not self.instance.pk:
            self.initial["is_primary"] = False
            self.fields["is_primary"].initial = False


class BaseDriverEmploymentFormSet(BaseInlineFormSet):
    def active_forms(self):
        return [
            form for form in self.forms
            if hasattr(form, "cleaned_data")
            and not form.cleaned_data.get("DELETE")
            and form.cleaned_data.get("carrier")
        ]

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        forms_with_data = self.active_forms()
        if not forms_with_data:
            raise forms.ValidationError("Добавьте хотя бы одного перевозчика.")
        carrier_ids = set()
        primary_count = 0
        for form in forms_with_data:
            carrier = form.cleaned_data["carrier"]
            if carrier.pk in carrier_ids:
                form.add_error(
                    "carrier", "Этот перевозчик уже указан в карточке водителя."
                )
            carrier_ids.add(carrier.pk)
            if form.cleaned_data.get("is_primary"):
                primary_count += 1
        if primary_count != 1:
            raise forms.ValidationError(
                "Укажите ровно одного основного перевозчика."
            )

    def primary_carrier(self):
        return next(
            form.cleaned_data["carrier"]
            for form in self.active_forms()
            if form.cleaned_data.get("is_primary")
        )

    def save_register(self, driver):
        rows = [form.cleaned_data for form in self.active_forms()]
        carrier_ids = {row["carrier"].pk for row in rows}
        DriverEmployment.objects.filter(driver=driver).exclude(
            carrier_id__in=carrier_ids
        ).delete()
        DriverEmployment.objects.filter(driver=driver).update(is_primary=False)
        for row in rows:
            DriverEmployment.objects.update_or_create(
                driver=driver,
                carrier=row["carrier"],
                defaults={
                    "is_primary": row.get("is_primary", False),
                    "is_active": True,
                },
            )


DriverEmploymentFormSet = inlineformset_factory(
    Driver,
    DriverEmployment,
    form=DriverEmploymentForm,
    formset=BaseDriverEmploymentFormSet,
    extra=1,
    can_delete=True,
)


class VehicleForm(StyledModelForm):
    class Meta:
        model = Vehicle
        fields = [
            "carrier", "kind", "registration_number",
            "vin", "make", "model", "year", "body_type", "capacity_kg",
            "volume_m3", "pallet_capacity", "insurance_expiry_date",
            "inspection_expiry_date", "notes", "is_active",
        ]
        widgets = {
            "insurance_expiry_date": forms.DateInput(
                format="%Y-%m-%d", attrs={"type": "date"}
            ),
            "inspection_expiry_date": forms.DateInput(
                format="%Y-%m-%d", attrs={"type": "date"}
            ),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }


class VehicleCombinationForm(StyledModelForm):
    tractor = forms.ModelChoiceField(
        label="Основной автомобиль",
        queryset=Vehicle.objects.none(),
        help_text="Седельный тягач или грузовой автомобиль.",
    )
    trailer = forms.ModelChoiceField(
        label="Прицеп / полуприцеп",
        queryset=Vehicle.objects.none(),
    )

    class Meta:
        model = VehicleCombination
        fields = ["tractor", "trailer", "valid_from", "valid_until", "is_active", "notes"]
        widgets = {
            "valid_from": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "valid_until": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        power_units = Vehicle.objects.filter(
            is_active=True,
            kind__in=[Vehicle.Kind.TRACTOR, Vehicle.Kind.TRUCK],
        ).select_related("carrier")
        trailers = Vehicle.objects.filter(
            is_active=True,
            kind__in=[Vehicle.Kind.TRAILER, Vehicle.Kind.SEMITRAILER],
        ).select_related("carrier")
        if self.instance.pk:
            power_units = Vehicle.objects.filter(
                Q(pk=self.instance.tractor_id)
                | Q(is_active=True, kind__in=[Vehicle.Kind.TRACTOR, Vehicle.Kind.TRUCK])
            ).select_related("carrier")
            trailers = Vehicle.objects.filter(
                Q(pk=self.instance.trailer_id)
                | Q(is_active=True, kind__in=[Vehicle.Kind.TRAILER, Vehicle.Kind.SEMITRAILER])
            ).select_related("carrier")
        self.fields["tractor"].queryset = power_units
        self.fields["trailer"].queryset = trailers


class ShipmentForm(StyledModelForm):
    class Meta:
        model = Shipment
        fields = [
            "expeditor", "customer", "customer_reference", "manager", "status",
            "carrier", "driver", "vehicle",
            "cargo_name", "weight_kg", "volume_m3", "vehicle_type", "pickup_city",
            "pickup_address", "pickup_date", "delivery_city", "delivery_address",
            "delivery_date", "customer_price", "carrier_price", "currency",
            "customer_payment_due_date", "carrier_payment_due_date", "notes",
        ]
        widgets = {
            "pickup_date": forms.DateInput(
                format="%Y-%m-%d", attrs={"type": "date"}
            ),
            "delivery_date": forms.DateInput(
                format="%Y-%m-%d", attrs={"type": "date"}
            ),
            "customer_payment_due_date": forms.DateInput(
                format="%Y-%m-%d", attrs={"type": "date"}
            ),
            "carrier_payment_due_date": forms.DateInput(
                format="%Y-%m-%d", attrs={"type": "date"}
            ),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        configure_dadata_address_fields(self)
        self.fields["expeditor"].queryset = CompanyProfile.objects.filter(
            is_active=True
        )
        if self.instance.expeditor_id:
            self.fields["expeditor"].queryset |= CompanyProfile.objects.filter(
                pk=self.instance.expeditor_id
            )
        elif self.fields["expeditor"].queryset.count() == 1:
            self.fields["expeditor"].initial = self.fields[
                "expeditor"
            ].queryset.first()
        carrier_id = self.data.get("carrier") if self.is_bound else self.instance.carrier_id
        if carrier_id and str(carrier_id).isdigit():
            self.fields["driver"].queryset = Driver.objects.filter(
                Q(carrier_id=carrier_id)
                | Q(employments__carrier_id=carrier_id, employments__is_active=True),
                is_active=True,
            ).distinct()
            self.fields["vehicle"].queryset = Vehicle.objects.filter(
                carrier_id=carrier_id, is_active=True
            )
        else:
            self.fields["driver"].queryset = Driver.objects.filter(is_active=True)
            self.fields["vehicle"].queryset = Vehicle.objects.filter(is_active=True)
        if self.instance.driver_id:
            self.fields["driver"].queryset |= Driver.objects.filter(
                pk=self.instance.driver_id
            )
        if self.instance.vehicle_id:
            self.fields["vehicle"].queryset |= Vehicle.objects.filter(
                pk=self.instance.vehicle_id
            )
        if not self.instance.pk and user and user.is_authenticated:
            self.fields["manager"].initial = user

    def clean(self):
        cleaned = super().clean()
        pickup_date = cleaned.get("pickup_date")
        delivery_date = cleaned.get("delivery_date")
        if pickup_date and delivery_date and delivery_date < pickup_date:
            self.add_error(
                "delivery_date", "Дата выгрузки не может быть раньше даты погрузки."
            )
        return cleaned


class PaymentForm(StyledModelForm):
    class Meta:
        model = Payment
        fields = [
            "direction", "amount", "payment_date", "method", "reference", "notes"
        ]
        widgets = {
            "payment_date": forms.DateInput(
                format="%Y-%m-%d", attrs={"type": "date"}
            ),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, shipment=None, transportation=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["reference"].label = "Платёжное поручение"
        self.shipment = shipment
        self.transportation = transportation
        if shipment:
            self.instance.shipment = shipment
            self.instance.transportation = None
        elif transportation:
            self.instance.transportation = transportation
            self.instance.shipment = None


class BankStatementForm(StyledModelForm):
    class Meta:
        model = BankStatement
        fields = [
            "direction",
            "statement_date",
            "owner_company",
            "bank_account",
            "currency",
            "reference",
            "notes",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        owner_queryset = Organization.objects.filter(is_own_company=True, is_active=True)
        if self.instance.pk:
            owner_queryset = Organization.objects.filter(
                Q(is_own_company=True, is_active=True)
                | Q(pk=self.instance.owner_company_id)
            )
        self.fields["owner_company"].queryset = owner_queryset
        owner_id = self.data.get("owner_company") if self.is_bound else self.initial.get("owner_company")
        if not owner_id and self.instance.owner_company_id:
            owner_id = self.instance.owner_company_id
        owner_id = getattr(owner_id, "pk", owner_id)
        account_queryset = OrganizationBankAccount.objects.filter(
            is_active=True, organization__is_own_company=True, organization__is_active=True
        ).select_related("organization")
        if str(owner_id or "").isdigit():
            account_queryset = account_queryset.filter(organization_id=owner_id)
        self.fields["bank_account"].queryset = account_queryset
        self.fields["bank_account"].required = False
        if not self.instance.pk and owner_queryset.count() == 1:
            self.fields["owner_company"].initial = owner_queryset.first()
        if not self.instance.pk and user and user.is_authenticated:
            self.fields["statement_date"].initial = timezone.localdate()

    def clean(self):
        cleaned = super().clean()
        owner = cleaned.get("owner_company")
        account = cleaned.get("bank_account")
        currency = cleaned.get("currency")
        if owner and account and account.organization_id != owner.pk:
            self.add_error("bank_account", "Счёт должен принадлежать выбранной нашей компании.")
        if account and currency and account.currency != currency:
            self.add_error("currency", "Валюта должна совпадать с валютой банковского счёта.")
        return cleaned


class BankStatementLineForm(StyledModelForm):
    class Meta:
        model = BankStatementLine
        fields = ["amount", "payment_reference"]
        widgets = {
            "amount": forms.NumberInput(attrs={"min": "0.01", "step": "0.01"}),
        }

    def __init__(self, *args, statement=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.statement = statement or getattr(self.instance, "statement", None)
        self.fields["payment_reference"].label = "Платёжное поручение"


class ForwardingOrderForm(StyledModelForm):
    class Meta:
        model = ForwardingOrder
        fields = [
            "contract_number",
            "contract_date",
            "order_date",
            "shipper_name",
            "shipper_tax_id",
            "shipper_address",
            "shipper_contact_name",
            "shipper_phone",
            "consignee_name",
            "consignee_address",
            "consignee_contact_name",
            "consignee_phone",
            "pickup_hours",
            "packaging_type",
            "package_count",
            "cargo_length_m",
            "cargo_width_m",
            "cargo_height_m",
            "special_conditions",
            "cargo_insurance",
            "payer",
            "payment_place",
            "expediter_representative",
            "client_representative",
        ]
        widgets = {
            "contract_date": forms.DateInput(
                format="%Y-%m-%d", attrs={"type": "date"}
            ),
            "order_date": forms.DateInput(
                format="%Y-%m-%d", attrs={"type": "date"}
            ),
            "special_conditions": forms.Textarea(attrs={"rows": 4}),
        }


class ShipmentDocumentForm(StyledModelForm):
    class Meta:
        model = ShipmentDocument
        fields = [
            "shipment",
            "transportation",
            "direction",
            "counterparty",
            "kind",
            "party",
            "status",
            "number",
            "document_date",
            "expected_date",
            "amount",
            "vat_amount",
            "currency",
            "file",
            "notes",
        ]
        widgets = {
            "document_date": CRMDateInput(),
            "expected_date": CRMDateInput(),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, shipment=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.shipment = shipment
        self.fields["shipment"].queryset = Shipment.objects.select_related(
            "customer", "carrier", "expeditor"
        ).order_by("-pickup_date", "-created_at")
        self.fields["shipment"].label_from_instance = (
            lambda obj: f"{obj.number} · {obj.route} · {obj.customer.name}"
        )
        self.fields["transportation"].queryset = Transportation.objects.select_related(
            "owner_company"
        ).prefetch_related("stops").order_by("-planned_start_date", "-created_at")
        self.fields["transportation"].label_from_instance = (
            lambda obj: f"{obj.number or 'Черновик'} · {obj.route}"
        )
        self.fields["transportation"].required = False
        self.fields["counterparty"].queryset = Organization.objects.filter(
            is_active=True
        ).order_by("name")
        self.fields["direction"].required = False
        self.fields["counterparty"].required = False
        if shipment is not None:
            self.fields["shipment"].initial = shipment
            self.fields["shipment"].required = False
            self.fields["shipment"].widget = forms.HiddenInput()

    def clean_shipment(self):
        return self.shipment or self.cleaned_data.get("shipment")

    def clean(self):
        cleaned_data = super().clean()
        shipment = cleaned_data.get("shipment")
        transportation = cleaned_data.get("transportation")
        if bool(shipment) == bool(transportation):
            raise forms.ValidationError(
                "Документ должен быть привязан либо к заявке, либо к рейсу."
            )
        return cleaned_data

    def clean_direction(self):
        return self.cleaned_data.get("direction") or ShipmentDocument.Direction.OUTGOING

    def clean_file(self):
        uploaded_file = self.cleaned_data.get("file")
        if uploaded_file and uploaded_file.size > 20 * 1024 * 1024:
            raise forms.ValidationError("Размер файла не должен превышать 20 МБ.")
        return uploaded_file


class DocumentBatchForm(StyledModelForm):
    class Meta:
        model = DocumentBatch
        fields = [
            "direction",
            "document_date",
            "owner_company",
            "default_kind",
            "default_status",
            "currency",
            "reference",
            "notes",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        owner_queryset = Organization.objects.filter(is_own_company=True, is_active=True)
        if self.instance.pk:
            owner_queryset = Organization.objects.filter(
                Q(is_own_company=True, is_active=True)
                | Q(pk=self.instance.owner_company_id)
            )
        self.fields["owner_company"].queryset = owner_queryset
        if not self.instance.pk and owner_queryset.count() == 1:
            self.fields["owner_company"].initial = owner_queryset.first()
        if not self.instance.pk:
            self.fields["document_date"].initial = timezone.localdate()


class ReconciliationActForm(StyledModelForm):
    class Meta:
        model = ReconciliationAct
        fields = [
            "document_date",
            "owner_company",
            "counterparty",
            "period_from",
            "period_to",
            "currency",
            "notes",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        owner_queryset = Organization.objects.filter(is_own_company=True, is_active=True)
        if self.instance.pk:
            owner_queryset = Organization.objects.filter(
                Q(is_own_company=True, is_active=True)
                | Q(pk=self.instance.owner_company_id)
            )
        self.fields["owner_company"].queryset = owner_queryset
        self.fields["counterparty"].queryset = Organization.objects.filter(
            is_active=True
        ).order_by("name")
        self.fields["counterparty"].widget.attrs.update(
            {
                "data-smart-select": "organization",
                "data-create-url": reverse("quick-organization-create"),
                "data-search-placeholder": "Название или ИНН контрагента",
                "data-create-label": "Создать контрагента",
            }
        )
        if not self.instance.pk:
            today = timezone.localdate()
            self.fields["document_date"].initial = today
            self.fields["period_from"].initial = today.replace(day=1)
            self.fields["period_to"].initial = today
            if owner_queryset.count() == 1:
                self.fields["owner_company"].initial = owner_queryset.first()

    def clean(self):
        cleaned = super().clean()
        owner = cleaned.get("owner_company")
        counterparty = cleaned.get("counterparty")
        period_from = cleaned.get("period_from")
        period_to = cleaned.get("period_to")
        if owner and counterparty and owner == counterparty:
            self.add_error("counterparty", "Контрагент не должен совпадать с нашей компанией.")
        if period_from and period_to and period_to < period_from:
            self.add_error("period_to", "Дата окончания периода не может быть раньше даты начала.")
        return cleaned


class CompanyProfileForm(StyledModelForm):
    profit_tax_rate = forms.DecimalField(
        label="Расчётная ставка налога на прибыль, %",
        min_value=Decimal("0"),
        max_value=Decimal("100"),
        decimal_places=2,
        required=False,
        initial=Decimal("25.00"),
        help_text="Используется для расчёта чистой прибыли по рейсам.",
    )

    class Meta:
        model = CompanyProfile
        fields = [
            "name",
            "short_name",
            "tax_id",
            "kpp",
            "ogrn",
            "legal_address",
            "phone",
            "email",
            "bank_name",
            "bik",
            "settlement_account",
            "correspondent_account",
            "director_name",
            "chief_accountant_name",
            "default_vat_rate",
            "profit_tax_rate",
            "is_active",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and self.instance.organization_id:
            self.fields["profit_tax_rate"].initial = (
                self.instance.organization.profit_tax_rate
            )

    def clean_profit_tax_rate(self):
        return self.cleaned_data.get("profit_tax_rate") or Decimal("25.00")

    def save(self, commit=True):
        profile = super().save(commit=commit)
        if commit and profile.organization_id:
            Organization.objects.filter(pk=profile.organization_id).update(
                profit_tax_rate=self.cleaned_data["profit_tax_rate"]
            )
            profile.organization.profit_tax_rate = self.cleaned_data[
                "profit_tax_rate"
            ]
        return profile


class AccountingDocumentForm(forms.Form):
    DOCUMENT_KIND_CHOICES = (
        (ShipmentDocument.Kind.INVOICE, "Счёт на оплату"),
        (ShipmentDocument.Kind.ACT, "Акт оказанных услуг"),
        (ShipmentDocument.Kind.UPD, "Универсальный передаточный документ (УПД)"),
        (ShipmentDocument.Kind.VAT_INVOICE, "Счёт-фактура"),
    )

    kind = forms.ChoiceField(label="Тип документа", choices=DOCUMENT_KIND_CHOICES)
    number = forms.CharField(label="Номер документа", max_length=100)
    document_date = forms.DateField(
        label="Дата документа", widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"})
    )
    contract_number = forms.CharField(label="Номер договора", max_length=100, required=False)
    contract_date = forms.DateField(
        label="Дата договора",
        required=False,
        widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
    )
    service_name = forms.CharField(
        label="Наименование услуги", max_length=500, widget=forms.Textarea(attrs={"rows": 3})
    )
    quantity = forms.DecimalField(
        label="Количество", min_value=Decimal("0.01"), max_digits=10, decimal_places=2
    )
    unit = forms.CharField(label="Единица измерения", max_length=20)
    amount = forms.DecimalField(
        label="Сумма с НДС", min_value=Decimal("0.01"), max_digits=12, decimal_places=2
    )
    currency = forms.ChoiceField(
        label="Валюта", choices=(("RUB", "RUB"), ("USD", "USD"), ("EUR", "EUR"))
    )
    vat_rate = forms.ChoiceField(label="Ставка НДС", choices=CompanyProfile.VATRate.choices)
    upd_status = forms.ChoiceField(
        label="Функция УПД",
        choices=(
            ("1", "1 — счёт-фактура и первичный документ"),
            ("2", "2 — только первичный документ"),
        ),
        initial="1",
        help_text="Используется только при формировании УПД.",
    )
    buyer_name = forms.CharField(label="Покупатель", max_length=255)
    buyer_tax_id = forms.CharField(label="ИНН покупателя", max_length=20, required=False)
    buyer_kpp = forms.CharField(label="КПП покупателя", max_length=20, required=False)
    buyer_address = forms.CharField(label="Адрес покупателя", max_length=255, required=False)
    notes = forms.CharField(
        label="Дополнительные сведения", required=False, widget=forms.Textarea(attrs={"rows": 3})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        configure_crm_date_fields(self)
        for field in self.fields.values():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs["class"] = "form-control uk-select"
            elif isinstance(field.widget, forms.Textarea):
                field.widget.attrs["class"] = "form-control uk-textarea"
            else:
                field.widget.attrs["class"] = "form-control uk-input"


class ChatMessageForm(forms.ModelForm):
    class Meta:
        model = ChatMessage
        fields = ("text", "attachment")
        widgets = {
            "text": forms.Textarea(
                attrs={
                    "class": "uk-textarea",
                    "rows": 2,
                    "maxlength": 4000,
                    "placeholder": "Напишите сообщение…",
                    "aria-label": "Сообщение",
                }
            ),
            "attachment": forms.FileInput(
                attrs={
                    "class": "chat-file-input",
                    "accept": ".pdf,.doc,.docx,.xls,.xlsx,.csv,.txt,.rtf,.odt,.ods,.ppt,.pptx,.xml,.json,.jpg,.jpeg,.png,.gif,.webp,.heic,.zip,.rar,.7z,.eml,.msg",
                    "aria-label": "Прикрепить файл",
                }
            ),
        }

    def clean(self):
        cleaned = super().clean()
        cleaned["text"] = (cleaned.get("text") or "").strip()
        if not cleaned["text"] and not cleaned.get("attachment"):
            self.add_error("text", "Введите сообщение или прикрепите файл.")
        return cleaned


class ChatMessageEditForm(forms.ModelForm):
    class Meta:
        model = ChatMessage
        fields = ("text",)
        widgets = {
            "text": forms.Textarea(
                attrs={
                    "class": "uk-textarea",
                    "rows": 5,
                    "maxlength": 4000,
                    "placeholder": "Текст сообщения…",
                    "aria-label": "Сообщение",
                }
            )
        }

    def clean_text(self):
        text = (self.cleaned_data.get("text") or "").strip()
        if not text and not self.instance.attachment:
            raise forms.ValidationError("Сообщение без файла не может быть пустым.")
        return text
