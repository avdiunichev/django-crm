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
        parser.add_argument(
            "--force",
            action="store_true",
            help="Перепроверить все точки, включая уже заполненные.",
        )
        parser.add_argument(
            "--transportations-only",
            action="store_true",
            help="Обработать только точки маршрутов рейсов, без заказов.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        force = options["force"]
        updated = 0
        skipped = 0
        suggestions_cache = {}

        models = (TransportationStop,) if options["transportations_only"] else (
            TransportOrderStop,
            TransportationStop,
        )
        for model in models:
            stops = model.objects.exclude(city="")
            if not force:
                stops = stops.filter(address_region="")
            for stop in stops.iterator():
                lookup_address = stop.address or stop.city
                cache_key = (lookup_address, stop.city)
                try:
                    if cache_key not in suggestions_cache:
                        suggestions_cache[cache_key] = suggest_addresses(
                            lookup_address, city=stop.city, count=1
                        )
                    suggestions = suggestions_cache[cache_key]
                except DadataError as exc:
                    self.stderr.write(self.style.ERROR(str(exc)))
                    return

                suggestion = suggestions[0] if suggestions else {}
                region = suggestion.get("region", "")
                locality = suggestion.get("city") or suggestion.get("settlement") or ""
                if not region or not locality:
                    skipped += 1
                    continue

                changed_fields = []
                city = locality[:120]
                if stop.city != city:
                    stop.city = city
                    changed_fields.append("city")
                for source, target in ADDRESS_FIELDS.items():
                    value = str(suggestion.get(source) or "")
                    field = stop._meta.get_field(target)
                    value = value[: field.max_length]
                    if getattr(stop, target) != value:
                        setattr(stop, target, value)
                        changed_fields.append(target)
                if changed_fields:
                    updated += 1
                    if not dry_run:
                        stop.save(update_fields=[*changed_fields, "updated_at"])

        action = "Будет обновлено" if dry_run else "Обновлено"
        self.stdout.write(f"{action}: {updated}; пропущено: {skipped}.")
