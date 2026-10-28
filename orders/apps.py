from django.apps import AppConfig


class OrdersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "orders"
    verbose_name = "Orders"

    def ready(self):
        from core.navigation import badges

        from .backoffice import awaiting_action_count

        badges.register("orders_awaiting", awaiting_action_count)
