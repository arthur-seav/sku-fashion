"""FR-X09 — schedule with cron, e.g. hourly:

    0 * * * * cd /path/to/program && .venv/bin/python manage.py cancel_unpaid_orders
"""

from django.core.management.base import BaseCommand

from orders.workflow import OrderWorkflow


class Command(BaseCommand):
    help = ("Cancel bank-transfer orders left in Pending Payment (no receipt uploaded) for longer than the "
            "timeout, and restore their stock.")

    def add_arguments(self, parser):
        parser.add_argument("--hours", type=int, default=None,
                            help="Override UNPAID_ORDER_TIMEOUT_HOURS (default 24).")
        parser.add_argument("--dry-run", action="store_true",
                            help="Only list the orders that would be cancelled.")

    def handle(self, *args, hours=None, dry_run=False, **options):
        orders = OrderWorkflow.cancel_expired(hours=hours, dry_run=dry_run)
        if not orders:
            self.stdout.write("No unpaid orders past the timeout.")
        elif dry_run:
            self.stdout.write(f"Would cancel {len(orders)} order(s): {', '.join(orders)}")
        else:
            self.stdout.write(self.style.SUCCESS(f"Cancelled {len(orders)} order(s): {', '.join(orders)}"))
