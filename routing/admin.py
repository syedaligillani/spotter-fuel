from django.contrib import admin

from routing.models import FuelStop, GeocodeCache

admin.site.register(FuelStop)
admin.site.register(GeocodeCache)
