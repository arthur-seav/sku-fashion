from django.conf import settings


def store(request):
    """Store-wide values available in every template."""
    return {
        "STORE_NAME": settings.STORE_NAME,
        "STORE_CURRENCY": settings.STORE_CURRENCY,
    }
