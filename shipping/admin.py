from django.contrib import admin

from .models import Shipment, ShippingMethod, ShippingRate

admin.site.register([ShippingMethod, ShippingRate, Shipment])
