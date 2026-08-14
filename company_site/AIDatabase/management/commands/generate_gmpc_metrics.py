import os

from django.core.management.base import BaseCommand
from django.core.cache import cache

from AIDatabase.models import GMPCExcelMaster
from AIDatabase.views import refresh_gmpc_excel_cache


class Command(BaseCommand):
    help = "Generate/refresh GMPC metrics and inspect cache."

    def add_arguments(self, parser):
        parser.add_argument(
            "--country",
            choices=["mhra", "eudra", "all"],
            default="all",
            help="Country to process",
        )

        parser.add_argument(
            "--clear-cache",
            action="store_true",
            help="Clear cache before recalculating",
        )

        parser.add_argument(
            "--show-cache",
            action="store_true",
            help="Show cached value before refresh",
        )

    def handle(self, *args, **options):

        countries = (
            ["mhra", "eudra"]
            if options["country"] == "all"
            else [options["country"]]
        )

        for country in countries:

            self.stdout.write(f"\n========== {country.upper()} ==========")

            master = GMPCExcelMaster.objects.filter(
                active_excel_name__iexact=country,
                is_active=True,
            ).first()

            if not master:
                self.stdout.write(self.style.ERROR("No active master found"))
                continue

            if not master.file:
                self.stdout.write(self.style.ERROR("No file attached"))
                continue

            if not os.path.exists(master.file.path):
                self.stdout.write(
                    self.style.ERROR(f"File not found: {master.file.path}")
                )
                continue

            cache_key = f"gmpc_dashboard_metrics_{country}"

            self.stdout.write(f"Cache Key : {cache_key}")
            self.stdout.write(f"Excel File: {master.file.path}")

            if options["show_cache"]:
                cached = cache.get(cache_key)

                if cached:
                    self.stdout.write(
                        self.style.SUCCESS("✓ Cache exists")
                    )
                else:
                    self.stdout.write(
                        self.style.WARNING("✗ Cache missing")
                    )

            if options["clear_cache"]:
                cache.delete(cache_key)
                self.stdout.write("Cache cleared.")

            previous_master = (
                GMPCExcelMaster.objects.filter(
                    active_excel_name__iexact=country,
                    is_active=False,
                )
                .order_by("-uploaded_at", "-pk")
                .first()
            )

            baseline_path = (
                previous_master.file.path
                if previous_master and previous_master.file
                else None
            )

            baseline_source_key = (
                f"{previous_master.pk}_{baseline_path}"
                if previous_master and baseline_path
                else None
            )

            master.dashboard_metrics = None
            master.save(update_fields=["dashboard_metrics"])

            self.stdout.write("Calculating metrics...")

            refresh_gmpc_excel_cache(
                country=country,
                baseline_path=baseline_path,
                baseline_source_key=baseline_source_key,
            )

            master.refresh_from_db()

            metrics = master.dashboard_metrics

            if metrics:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"✓ Metrics generated ({len(metrics.get('all_changes_list', []))} changes)"
                    )
                )
            else:
                self.stdout.write(
                    self.style.ERROR("Metrics were not generated")
                )