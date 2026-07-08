"""
13.3 — Rapid Data Seeding
Management command to bulk-import Product and RecipeIngredient
records from a CSV template file.
"""

import os

from django.core.management.base import BaseCommand, CommandError

from inventory.services import bulk_seed_products_csv


class Command(BaseCommand):
    help = "Seed Product and RecipeIngredient tables from a CSV template."

    def add_arguments(self, parser):
        parser.add_argument("csv_path", help="Path to the CSV file")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and validate CSV without writing to database",
        )

    def handle(self, *args, **options):
        csv_path = options["csv_path"]
        dry_run = options["dry_run"]

        if not os.path.exists(csv_path):
            raise CommandError(f"CSV file not found: {csv_path}")

        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            csv_text = f.read()

        report = bulk_seed_products_csv(csv_text, dry_run=dry_run)

        self.stdout.write(f"Parsed {report['total']} row(s) from {csv_path}")
        self.stdout.write(f"Created {report['vendors']} vendor(s)")
        self.stdout.write(f"Created {report['products']} product(s)")
        self.stdout.write(f"Created {report['recipes']} recipe ingredient link(s)")

        for s in report["skipped"]:
            self.stderr.write(f"  SKIPPED: {s}")
        for e in report["errors"]:
            self.stderr.write(f"  ERROR: {e}")

        self.stdout.write(self.style.SUCCESS("Seed completed."))
