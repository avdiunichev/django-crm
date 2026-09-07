from django.contrib import admin

from .models import (
    BankStatement,
    BankStatementLine,
    BankStatementNumberSequence,
    Carrier,
    CargoHandlingMethod,
    ChatMessage,
    CompanyProfile,
    Contract,
    Customer,
    DocumentBatch,
    DocumentBatchLine,
    Driver,
    DriverEmployment,
    DriverLicense,
    DriverPassport,
    DirectConversation,
    ForwardingOrder,
    Organization,
    OrganizationBankAccount,
    OrganizationChange,
    OrganizationContact,
    OrganizationGroup,
    OrganizationRole,
    Payment,
    PlannerTask,
    PackageType,
    SettlementMovement,
    Shipment,
    ShipmentDocument,
    TransportOrder,
    TransportOrderNumberSequence,
    TransportOrderStop,
    Transportation,
    TransportationElectronicDocument,
    TransportationInstruction,
    TransportationIncident,
    TransportationLink,
    TransportationNumberSequence,
    TransportationParty,
    TransportationStop,
    TransportationStatusEvent,
    TripCharge,
    UserProfile,
    VATRate,
    VehicleAssignment,
    VehicleCombination,
    Vehicle,
)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "can_see_all_records", "updated_at")
    list_filter = ("role", "can_see_all_records")
    search_fields = ("user__username", "user__first_name", "user__last_name", "user__email")
    autocomplete_fields = ("user",)


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "tax_id", "kpp", "contact_name", "phone", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "tax_id", "contact_name", "phone")


class OrganizationRoleInline(admin.TabularInline):
    model = OrganizationRole
    extra = 0


class OrganizationBankAccountInline(admin.TabularInline):
    model = OrganizationBankAccount
    extra = 0


@admin.register(OrganizationBankAccount)
class OrganizationBankAccountAdmin(admin.ModelAdmin):
    list_display = (
        "organization", "account_number", "bank_name", "bik", "currency",
        "is_primary", "is_active",
    )
    list_filter = ("currency", "is_primary", "is_active", "organization")
    search_fields = ("organization__name", "account_number", "bank_name", "bik")
    autocomplete_fields = ("organization",)


class OrganizationContactInline(admin.TabularInline):
    model = OrganizationContact
    extra = 0


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = (
        "name", "tax_id", "is_own_company", "fns_status", "verification_status", "is_active"
    )
    list_filter = ("is_own_company", "fns_status", "verification_status", "is_active", "roles__role")
    search_fields = ("name", "short_name", "tax_id", "kpp", "contact_name")
    inlines = (
        OrganizationRoleInline,
        OrganizationBankAccountInline,
        OrganizationContactInline,
    )


@admin.register(OrganizationChange)
class OrganizationChangeAdmin(admin.ModelAdmin):
    list_display = ("organization", "action", "changed_by", "created_at")
    list_filter = ("action", "created_at")
    search_fields = ("organization__name", "organization__tax_id", "changed_by__username")
    readonly_fields = ("organization", "changed_by", "action", "changes", "comment", "created_at", "updated_at")


@admin.register(OrganizationGroup)
class OrganizationGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "parent", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "parent__name")


class TransportationStopInline(admin.TabularInline):
    model = TransportationStop
    extra = 0


class TransportOrderStopInline(admin.TabularInline):
    model = TransportOrderStop
    extra = 0


@admin.register(TransportOrder)
class TransportOrderAdmin(admin.ModelAdmin):
    list_display = (
        "number", "document_date", "owner_company", "client", "rate",
        "currency", "status", "manager",
    )
    list_filter = ("status", "owner_company", "payment_form", "document_date")
    search_fields = (
        "number", "client__name", "client__tax_id", "cargo_name",
        "stops__city", "stops__address",
    )
    autocomplete_fields = (
        "owner_company", "client", "manager", "transportation", "assigned_by"
    )
    inlines = (TransportOrderStopInline,)


admin.site.register(TransportOrderNumberSequence)


class TransportationPartyInline(admin.TabularInline):
    model = TransportationParty
    extra = 0


@admin.register(Transportation)
class TransportationAdmin(admin.ModelAdmin):
    list_display = (
        "number", "owner_company", "route", "planned_start_date", "status",
        "posting_status", "manager"
    )
    list_filter = (
        "owner_company", "status", "posting_status", "planned_start_date", "manager"
    )
    search_fields = ("number", "cargo_name", "parties__organization__name")
    autocomplete_fields = ("owner_company", "manager", "legacy_shipment")
    inlines = (TransportationStopInline, TransportationPartyInline)


@admin.register(VATRate)
class VATRateAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "rate", "is_without_vat", "is_active")
    list_filter = ("is_active", "is_without_vat")


admin.site.register(PackageType)
admin.site.register(CargoHandlingMethod)
admin.site.register(TransportationNumberSequence)
admin.site.register(TransportationInstruction)
admin.site.register(TransportationIncident)
admin.site.register(TripCharge)
admin.site.register(SettlementMovement)
admin.site.register(TransportationStatusEvent)
admin.site.register(TransportationElectronicDocument)


@admin.register(PlannerTask)
class PlannerTaskAdmin(admin.ModelAdmin):
    list_display = (
        "title", "transportation", "assignee", "due_date", "status", "priority",
    )
    list_filter = ("status", "priority", "kind", "due_date")
    search_fields = ("title", "description", "transportation__number")
    autocomplete_fields = ("transportation", "assignee", "completed_by")


@admin.register(TransportationLink)
class TransportationLinkAdmin(admin.ModelAdmin):
    list_display = (
        "transportation", "sequence", "principal_party", "contractor_party",
        "contractor_role", "contract", "is_active",
    )
    list_filter = ("contractor_role", "is_active", "source")
    search_fields = (
        "transportation__number", "principal_party__organization__name",
        "contractor_party__organization__name", "instruction_number",
    )
    autocomplete_fields = (
        "transportation", "parent", "principal_party", "contractor_party",
        "contract", "verified_by",
    )


@admin.register(TransportationParty)
class TransportationPartyAdmin(admin.ModelAdmin):
    list_display = ("transportation", "organization", "role", "sequence", "is_active")
    list_filter = ("role", "is_active", "source")
    search_fields = (
        "transportation__number", "organization__name", "organization__tax_id"
    )
    autocomplete_fields = ("transportation", "organization")


@admin.register(VehicleAssignment)
class VehicleAssignmentAdmin(admin.ModelAdmin):
    list_display = (
        "transportation", "actual_carrier", "driver", "vehicle", "is_active",
        "confirmed_at",
    )
    list_filter = ("is_active", "actual_carrier")
    autocomplete_fields = (
        "transportation", "execution_link", "actual_carrier", "driver", "vehicle",
        "trailer", "confirmed_by",
    )


@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    list_display = (
        "number", "kind", "expeditor", "counterparty_name", "contract_date",
        "valid_until", "terminated_on", "debt_limit", "status", "created_by",
    )
    list_filter = ("kind", "status", "expeditor", "contract_date")
    search_fields = (
        "number", "expeditor__name", "customer__name", "customer__tax_id",
        "carrier__name", "carrier__tax_id",
    )
    autocomplete_fields = ("expeditor", "customer", "carrier", "created_by")


@admin.register(CompanyProfile)
class CompanyProfileAdmin(admin.ModelAdmin):
    list_display = (
        "name", "tax_id", "kpp", "bank_name", "default_vat_rate", "is_active"
    )
    list_filter = ("is_active", "default_vat_rate")
    search_fields = ("name", "short_name", "tax_id", "kpp")


@admin.register(Carrier)
class CarrierAdmin(admin.ModelAdmin):
    list_display = ("name", "tax_id", "contact_name", "rating", "is_active")
    list_filter = ("rating", "is_active")
    search_fields = ("name", "tax_id", "contact_name", "phone")


@admin.register(Shipment)
class ShipmentAdmin(admin.ModelAdmin):
    list_display = (
        "number", "expeditor", "customer", "route", "pickup_date", "status",
        "manager", "payment_status",
    )
    list_filter = (
        "expeditor", "status", "payment_status", "pickup_date", "manager"
    )
    search_fields = (
        "number", "expeditor__name", "customer__name", "carrier__name",
        "pickup_city", "delivery_city", "cargo_name",
    )
    autocomplete_fields = (
        "expeditor", "customer", "carrier", "driver", "vehicle", "manager"
    )


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "payment_date", "document", "direction", "amount", "method", "reference",
        "created_by",
    )
    list_filter = ("direction", "method", "payment_date")
    search_fields = (
        "shipment__number", "shipment__customer__name", "shipment__carrier__name",
        "transportation__number", "transportation__owner_company__name",
        "reference",
    )
    autocomplete_fields = ("shipment", "transportation", "created_by")

    @admin.display(description="Документ")
    def document(self, obj):
        return obj.transportation or obj.shipment


class BankStatementLineInline(admin.TabularInline):
    model = BankStatementLine
    extra = 0
    autocomplete_fields = ("transportation", "payment")


@admin.register(BankStatement)
class BankStatementAdmin(admin.ModelAdmin):
    list_display = (
        "number", "statement_date", "direction", "owner_company", "currency",
        "status", "total_amount", "line_count",
    )
    list_filter = ("direction", "status", "owner_company", "currency", "statement_date")
    search_fields = ("number", "reference", "notes")
    autocomplete_fields = ("owner_company", "bank_account", "created_by", "posted_by")
    readonly_fields = ("number", "posted_at", "posted_by")
    inlines = (BankStatementLineInline,)

    @admin.display(description="Сумма")
    def total_amount(self, obj):
        return obj.total_amount

    @admin.display(description="Строк")
    def line_count(self, obj):
        return obj.line_count


admin.site.register(BankStatementNumberSequence)


@admin.register(ForwardingOrder)
class ForwardingOrderAdmin(admin.ModelAdmin):
    list_display = (
        "shipment", "contract_number", "order_date", "shipper_name",
        "consignee_name", "updated_at",
    )
    search_fields = (
        "shipment__number", "shipper_name", "consignee_name", "contract_number"
    )
    autocomplete_fields = ("shipment",)


@admin.register(ShipmentDocument)
class ShipmentDocumentAdmin(admin.ModelAdmin):
    list_display = (
        "kind", "shipment", "number", "document_date", "direction",
        "counterparty", "party", "status", "amount", "vat_amount", "currency",
        "created_by",
    )
    list_filter = (
        "direction", "kind", "party", "status", "currency", "document_date",
    )
    search_fields = (
        "number", "shipment__number", "shipment__customer__name",
        "shipment__carrier__name", "counterparty__name", "counterparty__tax_id",
    )
    autocomplete_fields = ("shipment", "counterparty", "created_by")


class DocumentBatchLineInline(admin.TabularInline):
    model = DocumentBatchLine
    extra = 0
    autocomplete_fields = ("transportation", "counterparty", "shipment_document")


@admin.register(DocumentBatch)
class DocumentBatchAdmin(admin.ModelAdmin):
    list_display = (
        "number", "document_date", "direction", "status", "owner_company",
        "default_kind", "currency", "line_count", "total_amount",
    )
    list_filter = ("direction", "status", "default_kind", "currency", "document_date")
    search_fields = ("number", "reference", "owner_company__name", "owner_company__tax_id")
    autocomplete_fields = ("owner_company", "created_by", "posted_by")
    inlines = (DocumentBatchLineInline,)


class DriverEmploymentInline(admin.TabularInline):
    model = DriverEmployment
    extra = 0


class DriverPassportInline(admin.TabularInline):
    model = DriverPassport
    extra = 0


class DriverLicenseInline(admin.TabularInline):
    model = DriverLicense
    extra = 0


@admin.register(Driver)
class DriverAdmin(admin.ModelAdmin):
    list_display = (
        "full_name", "carrier", "phone", "license_number",
        "license_categories", "license_expiry_date", "is_active",
    )
    list_filter = ("is_active", "carrier", "license_categories")
    search_fields = (
        "last_name", "first_name", "middle_name", "phone", "license_number",
        "tax_id", "carrier__name", "employments__carrier__name",
    )
    autocomplete_fields = ("carrier",)
    inlines = (DriverEmploymentInline, DriverPassportInline, DriverLicenseInline)


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = (
        "registration_number", "make", "model", "kind", "carrier",
        "capacity_kg", "is_active",
    )
    list_filter = ("kind", "is_active", "carrier", "body_type")
    search_fields = (
        "registration_number", "trailer_registration_number", "vin", "make",
        "model", "carrier__name",
    )
    autocomplete_fields = ("carrier",)


@admin.register(VehicleCombination)
class VehicleCombinationAdmin(admin.ModelAdmin):
    list_display = ("tractor", "trailer", "carrier", "is_active", "valid_from", "valid_until")
    list_filter = ("is_active", "tractor__carrier")
    search_fields = (
        "tractor__registration_number",
        "trailer__registration_number",
        "tractor__make",
        "trailer__make",
    )
    autocomplete_fields = ("tractor", "trailer")


@admin.register(DirectConversation)
class DirectConversationAdmin(admin.ModelAdmin):
    list_display = ("user_low", "user_high", "updated_at")
    search_fields = (
        "user_low__username", "user_low__first_name", "user_low__last_name",
        "user_high__username", "user_high__first_name", "user_high__last_name",
    )
    autocomplete_fields = ("user_low", "user_high")


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = (
        "sender", "conversation", "attachment_name", "created_at", "edited_at",
        "read_at",
    )
    list_filter = ("created_at", "edited_at", "read_at")
    search_fields = ("text", "sender__username")
    autocomplete_fields = ("conversation", "sender")


admin.site.site_header = "Экспедитор CRM"
admin.site.site_title = "Экспедитор CRM"
admin.site.index_title = "Управление данными"
