"""Fill structured locality data for legacy order and transportation stops."""

from django.core.management.base import BaseCommand

from crm.dadata import DadataError, suggest_addresses
from crm.models import TransportOrderStop, TransportationStop


ADDRESS_FIELDS = {
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


class Command(BaseCommand):
    help = (
        "Заполняет регион и населённый пункт у старых точек маршрута по их адресу "
        "через DaData."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Показать объём обновления без сохранения изменений.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        updated = 0
        skipped = 0

        for model in (TransportOrderStop, TransportationStop):
            stops = model.objects.exclude(city="").filter(address_region="")
            for stop in stops.iterator():
                try:
                    suggestions = suggest_addresses(stop.address, city=stop.city, count=1)
                except DadataError as exc:
                    self.stderr.write(self.style.ERROR(str(exc)))
                    return

                suggestion = suggestions[0] if suggestions else {}
                region = suggestion.get("region", "")
                locality = suggestion.get("city") or suggestion.get("settlement") or ""
                if not region or not locality:
                    skipped += 1
                    continue

                stop.city = locality[:120]
                for source, target in ADDRESS_FIELDS.items():
                    value = str(suggestion.get(source) or "")
                    field = stop._meta.get_field(target)
                    setattr(stop, target, value[: field.max_length])
                updated += 1
                if not dry_run:
                    stop.save(
                        update_fields=[
                            "city",
                            *ADDRESS_FIELDS.values(),
                            "updated_at",
                        ]
                    )

        action = "Будет обновлено" if dry_run else "Обновлено"
        self.stdout.write(f"{action}: {updated}; пропущено: {skipped}.")
