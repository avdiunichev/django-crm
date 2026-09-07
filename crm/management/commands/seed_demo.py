from datetime import timedelta
from decimal import Decimal
import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from crm.models import (
    Carrier,
    ChatMessage,
    CompanyProfile,
    Contract,
    Customer,
    Driver,
    DirectConversation,
    ForwardingOrder,
    Payment,
    Shipment,
    ShipmentDocument,
    Vehicle,
)


class Command(BaseCommand):
    help = "Создаёт демонстрационные данные для локального запуска CRM."

    def handle(self, *args, **options):
        username = os.environ.get("DEMO_USERNAME", "demo")
        password = os.environ.get("DEMO_PASSWORD", "demo12345")
        User = get_user_model()
        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                "first_name": "Анна", "last_name": "Петрова",
                "email": "demo@example.com", "is_staff": True, "is_superuser": True,
            },
        )
        if created or not user.has_usable_password():
            user.set_password(password)
            user.save()

        team_data = [
            ("logist", "Илья", "Соколов", "logist@example.com"),
            ("accountant", "Мария", "Орлова", "accountant@example.com"),
        ]
        team_users = []
        for team_username, first_name, last_name, email in team_data:
            team_user, team_created = User.objects.update_or_create(
                username=team_username,
                defaults={
                    "first_name": first_name,
                    "last_name": last_name,
                    "email": email,
                    "is_active": True,
                },
            )
            if team_created or not team_user.has_usable_password():
                team_user.set_password(password)
                team_user.save(update_fields=["password"])
            team_users.append(team_user)

        primary_expeditor, _ = CompanyProfile.objects.update_or_create(
            tax_id="7701234560",
            defaults={
                "name": 'Общество с ограниченной ответственностью "Экспедитор"',
                "short_name": 'ООО "Экспедитор"',
                "kpp": "770101001",
                "ogrn": "1267700000000",
                "legal_address": "г. Москва, ул. Логистическая, д. 1",
                "phone": "+7 495 000-00-00",
                "email": "accounting@expeditor.example",
                "bank_name": 'АО "Демо Банк"',
                "bik": "044525000",
                "settlement_account": "40702810000000000001",
                "correspondent_account": "30101810000000000000",
                "director_name": "Петрова Анна Сергеевна",
                "chief_accountant_name": "Петрова Анна Сергеевна",
                "default_vat_rate": CompanyProfile.VATRate.TWENTY_TWO,
                "is_active": True,
            },
        )
        northern_expeditor, _ = CompanyProfile.objects.update_or_create(
            tax_id="7812345671",
            defaults={
                "name": 'Общество с ограниченной ответственностью "Экспедитор Север"',
                "short_name": 'ООО "Экспедитор Север"',
                "kpp": "780101001",
                "ogrn": "1267800000001",
                "legal_address": "г. Санкт-Петербург, пр. Логистический, д. 7",
                "phone": "+7 812 000-00-00",
                "email": "accounting@north-expeditor.example",
                "bank_name": 'ПАО "Северный Банк"',
                "bik": "044030001",
                "settlement_account": "40702810000000000002",
                "correspondent_account": "30101810000000000001",
                "director_name": "Смирнов Павел Олегович",
                "chief_accountant_name": "Смирнова Ольга Игоревна",
                "default_vat_rate": CompanyProfile.VATRate.WITHOUT_VAT,
                "is_active": True,
            },
        )
        expeditors = [primary_expeditor, northern_expeditor]

        customers_data = [
            {"name": "СеверТорг", "tax_id": "7801234567", "kpp": "780101001", "ogrn": "1027800000001", "contact_name": "Илья Соколов", "director_name": "Соколов Илья Андреевич", "phone": "+7 921 555-18-20", "email": "logistics@severtorg.example", "address": "Санкт-Петербург, Пискарёвский проспект, 25", "bank_name": 'ПАО "Демо Банк"', "bik": "044030001", "settlement_account": "40702810000000001001", "correspondent_account": "30101810000000001001"},
            {"name": "Волга Продукт", "tax_id": "6312345678", "kpp": "631201001", "ogrn": "1026300000002", "contact_name": "Мария Орлова", "director_name": "Орлова Мария Викторовна", "phone": "+7 927 410-22-11", "email": "supply@volgaproduct.example", "address": "Самара, Московское шоссе, 18", "bank_name": 'ПАО "Демо Банк"', "bik": "043601001", "settlement_account": "40702810000000001002", "correspondent_account": "30101810000000001002"},
            {"name": "ПромКомплект", "tax_id": "7709876543", "kpp": "770901001", "ogrn": "1027700000003", "contact_name": "Алексей Морозов", "director_name": "Морозов Алексей Сергеевич", "phone": "+7 916 340-48-99", "email": "a.morozov@promkomplekt.example", "address": "Москва, Рязанский проспект, 10", "bank_name": 'ПАО "Демо Банк"', "bik": "044525001", "settlement_account": "40702810000000001003", "correspondent_account": "30101810000000001003"},
        ]
        customers = []
        for data in customers_data:
            customer, _ = Customer.objects.update_or_create(
                tax_id=data["tax_id"], defaults=data
            )
            customers.append(customer)

        carriers_data = [
            {"name": "ТрансЛиния", "tax_id": "7723456789", "kpp": "772301001", "ogrn": "1027700000011", "address": "Москва, ул. Дорожная, 11", "director_name": "Ковалёв Дмитрий Игоревич", "contact_name": "Дмитрий Ковалёв", "phone": "+7 903 112-45-78", "email": "dispatch@transline.example", "bank_name": 'ПАО "Демо Банк"', "bik": "044525011", "settlement_account": "40702810000000002001", "correspondent_account": "30101810000000002001", "vehicle_types": "Тент 20 т, рефрижератор", "rating": 5},
            {"name": "АвтоПуть", "tax_id": "5250123456", "kpp": "525001001", "ogrn": "1025200000012", "address": "Нижний Новгород, ул. Транспортная, 12", "director_name": "Власов Олег Петрович", "contact_name": "Олег Власов", "phone": "+7 910 700-14-60", "email": "info@autoput.example", "bank_name": 'ПАО "Демо Банк"', "bik": "042202012", "settlement_account": "40702810000000002002", "correspondent_account": "30101810000000002002", "vehicle_types": "Тент 10–20 т, бортовой", "rating": 4},
            {"name": "Регион Карго", "tax_id": "6671234567", "kpp": "667101001", "ogrn": "1026600000013", "address": "Екатеринбург, ул. Грузовая, 13", "director_name": "Зорина Елена Сергеевна", "contact_name": "Елена Зорина", "phone": "+7 912 880-33-09", "email": "fleet@regioncargo.example", "bank_name": 'ПАО "Демо Банк"', "bik": "046577013", "settlement_account": "40702810000000002003", "correspondent_account": "30101810000000002003", "vehicle_types": "Рефрижератор, изотерм", "rating": 5},
        ]
        carriers = []
        for data in carriers_data:
            carrier, _ = Carrier.objects.update_or_create(
                tax_id=data["tax_id"], defaults=data
            )
            carriers.append(carrier)

        today = timezone.localdate()
        demo_contracts = (
            (Contract.Kind.CLIENT_FORWARDING, "ДЕМО-ТЭО-001", customers[0], None),
            (Contract.Kind.CARRIER_TRANSPORT, "ДЕМО-ПЕР-001", None, carriers[0]),
            (
                Contract.Kind.SUBCONTRACTOR_FORWARDING,
                "ДЕМО-ТЭО-002",
                None,
                carriers[1],
            ),
        )
        for kind, number, customer, carrier in demo_contracts:
            counterparty = customer or carrier
            Contract.objects.update_or_create(
                expeditor=primary_expeditor,
                number=number,
                defaults={
                    "kind": kind,
                    "contract_date": today,
                    "city": "Москва",
                    "valid_until": today + timedelta(days=365),
                    "status": Contract.Status.READY,
                    "customer": customer,
                    "carrier": carrier,
                    "expeditor_representative": primary_expeditor.director_name,
                    "counterparty_representative": counterparty.director_name,
                    "created_by": user,
                },
            )

        drivers_data = [
            (carriers[0], "Кузнецов", "Сергей", "Андреевич", "+7 903 555-14-21", "77 11 123456", "B, C, CE"),
            (carriers[1], "Волков", "Николай", "Петрович", "+7 910 777-28-44", "52 09 654321", "B, C, CE"),
            (carriers[2], "Мельников", "Артём", "Игоревич", "+7 912 440-19-35", "66 14 789012", "B, C, CE"),
        ]
        drivers = []
        for carrier, last_name, first_name, middle_name, phone, license_number, categories in drivers_data:
            driver, _ = Driver.objects.update_or_create(
                license_number=license_number,
                defaults={
                    "carrier": carrier,
                    "last_name": last_name,
                    "first_name": first_name,
                    "middle_name": middle_name,
                    "phone": phone,
                    "license_categories": categories,
                    "license_issue_date": today - timedelta(days=365 * 4),
                    "license_expiry_date": today + timedelta(days=365 * 6),
                    "medical_certificate_expiry": today + timedelta(days=300),
                    "is_active": True,
                },
            )
            drivers.append(driver)

        vehicles_data = [
            (carriers[0], "А111АА77", "Volvo", "FH", "Тент", 20000, 82),
            (carriers[1], "В222ВВ52", "КамАЗ", "54901", "Тент", 20000, 90),
            (carriers[2], "Е333ЕЕ66", "MAN", "TGX", "Рефрижератор", 20000, 86),
        ]
        vehicles = []
        for carrier, number, make, model, body_type, capacity, volume in vehicles_data:
            vehicle, _ = Vehicle.objects.update_or_create(
                registration_number=number,
                defaults={
                    "carrier": carrier,
                    "kind": Vehicle.Kind.TRACTOR,
                    "make": make,
                    "model": model,
                    "year": today.year - 3,
                    "body_type": body_type,
                    "capacity_kg": Decimal(str(capacity)),
                    "volume_m3": Decimal(str(volume)),
                    "pallet_capacity": 33,
                    "insurance_expiry_date": today + timedelta(days=220),
                    "inspection_expiry_date": today + timedelta(days=160),
                    "is_active": True,
                },
            )
            vehicles.append(vehicle)

        carrier_resources = {
            carrier.pk: (drivers[index], vehicles[index])
            for index, carrier in enumerate(carriers)
        }
        shipment_data = [
            (customers[0], carriers[0], "Бытовая техника", "Санкт-Петербург", "Москва", 0, 1, Shipment.Status.IN_TRANSIT, 148000, 112000, Shipment.PaymentStatus.AWAITING),
            (customers[1], carriers[2], "Молочная продукция", "Самара", "Казань", 0, 0, Shipment.Status.LOADING, 92000, 71000, Shipment.PaymentStatus.PARTIAL),
            (customers[2], None, "Металлоконструкции", "Москва", "Екатеринбург", 1, 4, Shipment.Status.NEW, 235000, 0, Shipment.PaymentStatus.AWAITING),
            (customers[0], carriers[1], "Сантехника", "Тверь", "Псков", 2, 3, Shipment.Status.PLANNED, 87000, 65000, Shipment.PaymentStatus.AWAITING),
            (customers[2], carriers[0], "Кабельная продукция", "Подольск", "Нижний Новгород", -2, -1, Shipment.Status.DELIVERED, 116000, 88000, Shipment.PaymentStatus.PAID),
            (customers[1], carriers[2], "Замороженные продукты", "Казань", "Уфа", -5, -4, Shipment.Status.CLOSED, 99000, 74000, Shipment.PaymentStatus.PAID),
            (customers[0], carriers[1], "Мебель", "Москва", "Воронеж", -8, -7, Shipment.Status.DELIVERED, 105000, 79000, Shipment.PaymentStatus.OVERDUE),
            (customers[2], carriers[0], "Промышленное оборудование", "Тула", "Пермь", 4, 7, Shipment.Status.PLANNED, 270000, 210000, Shipment.PaymentStatus.AWAITING),
        ]
        demo_shipments = {}
        for index, data in enumerate(shipment_data, start=1):
            (customer, carrier, cargo, pickup_city, delivery_city, pickup_offset,
             delivery_offset, status, customer_price, carrier_price, payment_status) = data
            driver, vehicle = carrier_resources.get(carrier.pk, (None, None)) if carrier else (None, None)
            delivery_date = today + timedelta(days=delivery_offset)
            customer_due_date = delivery_date + timedelta(days=10)
            carrier_due_date = delivery_date + timedelta(days=5)
            if payment_status == Shipment.PaymentStatus.OVERDUE:
                customer_due_date = today - timedelta(days=2)
                carrier_due_date = today - timedelta(days=2)
            shipment, _ = Shipment.objects.update_or_create(
                number=f"DEMO-{index:04d}",
                defaults={
                    "expeditor": expeditors[(index - 1) % len(expeditors)],
                    "customer": customer, "carrier": carrier, "driver": driver,
                    "vehicle": vehicle, "manager": user,
                    "status": status, "cargo_name": cargo,
                    "weight_kg": Decimal("20000"), "volume_m3": Decimal("82"),
                    "vehicle_type": "Рефрижератор" if "продукт" in cargo.lower() else "Тент 20 т",
                    "pickup_city": pickup_city, "pickup_address": "Склад отправителя",
                    "pickup_date": today + timedelta(days=pickup_offset),
                    "delivery_city": delivery_city, "delivery_address": "Склад получателя",
                    "delivery_date": delivery_date,
                    "customer_price": customer_price, "carrier_price": carrier_price,
                    "currency": "RUB", "payment_status": payment_status,
                    "customer_payment_due_date": customer_due_date,
                    "carrier_payment_due_date": carrier_due_date if carrier else None,
                    "customer_reference": f"ЗК-{today:%m}-{index:03d}",
                },
            )
            demo_shipments[index] = shipment
            ForwardingOrder.objects.update_or_create(
                shipment=shipment,
                defaults={
                    "contract_number": "ТЭ-2026/01",
                    "contract_date": today - timedelta(days=180),
                    "order_date": today,
                    "shipper_name": customer.name,
                    "shipper_tax_id": customer.tax_id,
                    "shipper_address": customer.address,
                    "shipper_contact_name": customer.contact_name,
                    "shipper_phone": customer.phone,
                    "consignee_name": f"Склад получателя · {delivery_city}",
                    "consignee_address": f"{delivery_city}, Склад получателя",
                    "consignee_contact_name": "Ответственный на выгрузке",
                    "consignee_phone": "+7 900 000-00-00",
                    "pickup_hours": "09:00–18:00",
                    "packaging_type": "Заводская упаковка / паллеты",
                    "package_count": 20,
                    "special_conditions": "Надёжное крепление груза в кузове.",
                    "cargo_insurance": ForwardingOrder.Insurance.YES,
                    "payer": customer.name,
                    "payment_place": "Безналичный расчёт",
                    "expediter_representative": shipment.expeditor.director_name,
                    "client_representative": customer.contact_name,
                },
            )

        payments_data = [
            (2, Payment.Direction.INCOME, Decimal("46000"), "DEMO-PAY-2-IN"),
            (2, Payment.Direction.EXPENSE, Decimal("25000"), "DEMO-PAY-2-OUT"),
            (5, Payment.Direction.INCOME, Decimal("116000"), "DEMO-PAY-5-IN"),
            (5, Payment.Direction.EXPENSE, Decimal("88000"), "DEMO-PAY-5-OUT"),
            (6, Payment.Direction.INCOME, Decimal("99000"), "DEMO-PAY-6-IN"),
            (6, Payment.Direction.EXPENSE, Decimal("74000"), "DEMO-PAY-6-OUT"),
        ]
        for shipment_index, direction, amount, reference in payments_data:
            Payment.objects.update_or_create(
                shipment=demo_shipments[shipment_index],
                direction=direction,
                reference=reference,
                defaults={
                    "amount": amount,
                    "payment_date": today - timedelta(days=1),
                    "method": Payment.Method.BANK,
                    "created_by": user,
                },
            )

        documents_data = [
            (1, ShipmentDocument.Kind.TRANSPORT_WAYBILL, ShipmentDocument.Status.EXPECTED, "", None, today + timedelta(days=2)),
            (2, ShipmentDocument.Kind.INVOICE, ShipmentDocument.Status.ISSUED, "СЧ-2026-002", Decimal("92000"), None),
            (5, ShipmentDocument.Kind.UPD, ShipmentDocument.Status.SIGNED, "УПД-2026-005", Decimal("116000"), None),
            (6, ShipmentDocument.Kind.ACT, ShipmentDocument.Status.ORIGINAL, "АКТ-2026-006", Decimal("99000"), None),
            (7, ShipmentDocument.Kind.TRANSPORT_WAYBILL, ShipmentDocument.Status.EXPECTED, "", None, today - timedelta(days=3)),
        ]
        for shipment_index, kind, status, number, amount, expected_date in documents_data:
            shipment = demo_shipments[shipment_index]
            ShipmentDocument.objects.update_or_create(
                shipment=shipment,
                kind=kind,
                number=number,
                defaults={
                    "party": ShipmentDocument.Party.CUSTOMER,
                    "status": status,
                    "document_date": today if number else None,
                    "expected_date": expected_date,
                    "amount": amount,
                    "currency": shipment.currency,
                    "created_by": user,
                },
            )

        chat_examples = [
            (
                team_users[0],
                "Анна, перевозчик подтвердил машину на сегодняшнюю погрузку.",
            ),
            (
                team_users[1],
                "Проверьте, пожалуйста, оригиналы УПД по закрытым заявкам.",
            ),
        ]
        for sender, text in chat_examples:
            conversation, _ = DirectConversation.get_or_create_between(user, sender)
            ChatMessage.objects.get_or_create(
                conversation=conversation,
                sender=sender,
                text=text,
            )

        self.stdout.write(self.style.SUCCESS("Демонстрационные данные готовы."))
        self.stdout.write(f"Вход: {username} / {password}")
