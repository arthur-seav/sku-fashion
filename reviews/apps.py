from django.apps import AppConfig


class ReviewsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "reviews"
    verbose_name = "Reviews"

    def ready(self):
        from core.navigation import badges

        from .services import pending_review_count

        badges.register("reviews_pending", pending_review_count)
