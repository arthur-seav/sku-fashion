from django.conf import settings
from django.core.exceptions import ValidationError
from django.template.defaultfilters import filesizeformat


def validate_image_size(file):
    """NFR-03: uploaded images are limited to five megabytes."""
    limit = settings.MAX_UPLOAD_IMAGE_BYTES
    if file and file.size > limit:
        raise ValidationError(f"Image is too large ({filesizeformat(file.size)}). "
                              f"The limit is {filesizeformat(limit)}.")
