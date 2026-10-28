"""{% load reviews %} {% stars review.rating %} — five Lucide stars, the first `rating` filled."""

from django import template

register = template.Library()


@register.inclusion_tag("reviews/partials/stars.html")
def stars(rating, label=True):
    try:
        filled = max(0, min(5, round(float(rating or 0))))
    except (TypeError, ValueError):
        filled = 0
    return {"filled": range(filled), "empty": range(5 - filled), "rating": rating, "label": label}
