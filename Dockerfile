# SKU-Fashion web image: Django + gunicorn. Static files are collected at
# build time and served by WhiteNoise; uploads go to /app/media (a volume).
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
# collectstatic only needs settings to load; these values are placeholders, not used at runtime.
RUN DJANGO_SECRET_KEY=build-only DB_NAME=x DB_USER=x DB_PASSWORD=x DJANGO_PRODUCTION=1 \
    python manage.py collectstatic --noinput

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /app/media && chown app /app/media
USER app

EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", \
     "--timeout", "60", "--access-logfile", "-"]
