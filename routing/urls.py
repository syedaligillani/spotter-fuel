from django.urls import path

from routing.views import HealthCheckView, TripRouteView

urlpatterns = [
    path("route/", TripRouteView.as_view(), name="trip-route"),
    path("health/", HealthCheckView.as_view(), name="health-check"),
]
