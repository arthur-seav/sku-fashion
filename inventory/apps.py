from django.apps import AppConfig


class InventoryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "inventory"
    verbose_name = "Inventory"

    def ready(self):
        from core.navigation import badges

        from .services import InventoryService

        # FR-X12: the back-office sidebar shows how many variants need restocking.
        badges.register("low_stock", lambda: InventoryService.low_stock_variants().count())
