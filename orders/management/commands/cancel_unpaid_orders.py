"""FR-X09 — schedule with cron, e.g. every 15 minutes:

    */15 * * * * cd /path/to/program && .venv/bin/python manage.py cancel_unpaid_orders
"""

from django.core.management.base import BaseCommand

from orders.workflow import OrderWorkflow


class Command(BaseCommand):
    help = "Cancel bank-transfer orders left in Pending Payment for longer than the timeout and restore stock."

    def add_arguments(self, parser):
        parser.add_argument("--hours", type=int, default=None,
                            help="Override UNPAID_ORDER_TIMEOUT_HOURS (default 24).")

    def handle(self, *args, hours=None, **options):
        cancelled = OrderWorkflow.cancel_expired(hours=hours)
        if cancelled:
            self.stdout.write(self.style.SUCCESS(f"Cancelled {len(cancelled)} order(s): {', '.join(cancelled)}"))
        else:
            self.stdout.write("No unpaid orders past the timeout.")
