"""Import fuel price CSV into the database."""

import csv
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from routing.models import FuelStop
from routing.services.geocoding import geocode_fuel_stop


class Command(BaseCommand):
    help = "Import fuel prices from CSV and geocode truck stop locations"

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv",
            type=str,
            default=str(settings.BASE_DIR / "data" / "fuel-prices.csv"),
            help="Path to fuel prices CSV file",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Clear existing fuel stops before import",
        )

    def handle(self, *args, **options):
        csv_path = Path(options["csv"])
        if not csv_path.exists():
            self.stderr.write(self.style.ERROR(f"CSV not found: {csv_path}"))
            return

        if options["clear"]:
            count = FuelStop.objects.count()
            FuelStop.objects.all().delete()
            self.stdout.write(f"Cleared {count} existing fuel stops")

        self.stdout.write(f"Importing from {csv_path}...")

        batch: list[FuelStop] = []
        batch_size = 500
        imported = 0
        geocode_failures = 0

        with csv_path.open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                city = row["City"].strip()
                state = row["State"].strip().upper()
                address = row["Address"].strip()
                opis_id = int(row["OPIS Truckstop ID"])
                price = float(row["Retail Price"])

                try:
                    lat, lng = geocode_fuel_stop(city, state, address, opis_id)
                except ValueError:
                    geocode_failures += 1
                    continue

                batch.append(
                    FuelStop(
                        opis_id=opis_id,
                        name=row["Truckstop Name"].strip(),
                        address=address,
                        city=city,
                        state=state,
                        rack_id=int(row["Rack ID"]) if row.get("Rack ID") else None,
                        retail_price=price,
                        latitude=lat,
                        longitude=lng,
                    )
                )

                if len(batch) >= batch_size:
                    FuelStop.objects.bulk_create(batch)
                    imported += len(batch)
                    batch = []
                    self.stdout.write(f"  Imported {imported} rows...", ending="\r")

        if batch:
            FuelStop.objects.bulk_create(batch)
            imported += len(batch)

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone! Imported {imported} fuel stops "
                f"({geocode_failures} geocode failures skipped)"
            )
        )
