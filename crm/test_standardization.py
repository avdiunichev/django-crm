from decimal import Decimal

from django.test import TestCase

from .dadata import _normalize_party
from .forms import OrganizationForm, ContractForm, TransportOrderForm, VehicleForm
from .models import Organization, TransportOrder, VATRate, Vehicle


class StandardizationTests(TestCase):
    def test_entrepreneur_fio_and_basis(self):
        party = _normalize_party({"data": {
            "type": "INDIVIDUAL", "ogrn": "321780000000001",
            "fio": {"surname": "Иванов", "name": "Иван", "patronymic": "Иванович"},
        }})
        self.assertEqual(party["director_name"], "Иванов Иван Иванович")
        self.assertIn("ОГРНИП 321780000000001", party["acting_basis"])
        self.assertEqual(party["legal_address"], "")

    def test_no_invented_basis_for_missing_ogrnip(self):
        self.assertEqual(_normalize_party({"data": {"type": "INDIVIDUAL"}})["acting_basis"], "")

    def test_legal_entity_management_is_preserved(self):
        party = _normalize_party({"data": {"type": "LEGAL", "management": {"name": "Петров", "post": "Директор"}}})
        self.assertEqual(party["director_name"], "Петров")
        self.assertEqual(party["director_post"], "Директор")

    def test_payment_events_are_identical_for_new_documents(self):
        expected = dict(Organization.PaymentTrigger.choices)
        for form, field in [(OrganizationForm(), "payment_trigger"), (ContractForm(), "payment_trigger"), (TransportOrderForm(), "payment_due_basis")]:
            self.assertEqual({k: v for k, v in form.fields[field].choices if k}, expected)

    def test_saved_legacy_event_remains_available(self):
        order = TransportOrder(pk=999, payment_due_basis="document_date")
        form = TransportOrderForm(instance=order)
        self.assertIn("document_date", dict(form.fields["payment_due_basis"].choices))

    def test_vat_choices_preserve_saved_archive_only(self):
        old, _ = VATRate.objects.get_or_create(code="test_old", defaults={"name": "20", "rate": 20})
        current, _ = VATRate.objects.get_or_create(code="test_current", defaults={"name": "22", "rate": 22})
        form = OrganizationForm()
        self.assertNotIn(old, form.fields["default_vat_rate"].queryset)
        self.assertIn(current, form.fields["default_vat_rate"].queryset)
        saved = Organization(pk=999, default_vat_rate=old)
        self.assertIn(old, OrganizationForm(instance=saved).fields["default_vat_rate"].queryset)

    def test_manipulator_capacity_is_saved(self):
        form = VehicleForm(data={"kind": "manipulator", "make": "КАМАЗ", "registration_number": "А001АА198", "capacity_kg": "10000", "boom_capacity_kg": "3500", "volume_m3": "0", "pallet_capacity": "0"})
        self.assertTrue(form.is_valid(), form.errors)
        vehicle = form.save()
        vehicle.refresh_from_db()
        self.assertEqual(vehicle.boom_capacity_kg, Decimal("3500"))
        self.assertTrue(vehicle.is_power_unit)

    def test_negative_boom_capacity_is_rejected(self):
        form = VehicleForm(data={"kind": "manipulator", "make": "КАМАЗ", "registration_number": "А002АА198", "boom_capacity_kg": "-1"})
        self.assertFalse(form.is_valid())
        self.assertIn("boom_capacity_kg", form.errors)
