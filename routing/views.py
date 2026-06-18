import logging

from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from routing.serializers import TripRequestSerializer
from routing.services.trip_planner import TripPlannerService

logger = logging.getLogger(__name__)


class TripRouteView(APIView):
    """
    Calculate optimal driving route with cost-effective fuel stops.

    POST /api/route/
    {
        "start": "New York, NY",
        "end": "Los Angeles, CA"
    }
    """

    def post(self, request: Request) -> Response:
        serializer = TripRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        start = serializer.validated_data["start"]
        end = serializer.validated_data["end"]

        try:
            planner = TripPlannerService()
            result = planner.plan_trip(start, end)
        except ValueError as exc:
            logger.warning("Trip planning failed: %s", exc)
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            logger.exception("Unexpected error during trip planning")
            return Response(
                {"error": f"Failed to plan trip: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(
            {
                "start": result.start,
                "end": result.end,
                "route": result.route,
                "fuel_stops": result.fuel_stops,
                "total_fuel_cost_usd": result.total_fuel_cost_usd,
                "total_gallons": result.total_gallons,
                "total_distance_miles": result.total_distance_miles,
                "duration_hours": result.duration_hours,
                "map_image_base64": result.map_image_base64,
                "assumptions": result.assumptions,
            }
        )


class HealthCheckView(APIView):
    """GET /api/health/ — simple health check."""

    def get(self, request: Request) -> Response:
        from routing.models import FuelStop

        return Response(
            {
                "status": "ok",
                "fuel_stops_loaded": FuelStop.objects.filter(latitude__isnull=False).count(),
            }
        )
