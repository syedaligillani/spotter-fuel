"""Main orchestration service for route + fuel optimization."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.conf import settings
from django.db.models import Min

from routing.models import FuelStop
from routing.services.fuel_optimizer import FuelPlan, FuelStation, optimize_fuel_stops
from routing.services.geocoding import geocode_location
from routing.services.map_service import generate_route_map
from routing.services.route_service import RouteResult, RouteService, match_stops_to_route

logger = logging.getLogger(__name__)


@dataclass
class TripResult:
    start: dict
    end: dict
    route: dict
    fuel_stops: list[dict]
    total_fuel_cost_usd: float
    total_gallons: float
    total_distance_miles: float
    duration_hours: float
    map_image_base64: str
    assumptions: dict


class TripPlannerService:
    """Plan a trip with optimal fuel stops along the cheapest route."""

    def __init__(self, route_service: RouteService | None = None):
        self.route_service = route_service or RouteService()

    def plan_trip(self, start_location: str, end_location: str) -> TripResult:
        start_coords = geocode_location(start_location)
        end_coords = geocode_location(end_location)

        route = self.route_service.get_route(start_coords, end_coords)
        candidates = self._find_route_candidates(route)

        fuel_plan = optimize_fuel_stops(candidates, route.distance_miles)
        map_image = generate_route_map(
            route.coordinates,
            start_coords,
            end_coords,
            fuel_plan.stops,
        )

        return TripResult(
            start={
                "location": start_location,
                "latitude": start_coords[0],
                "longitude": start_coords[1],
            },
            end={
                "location": end_location,
                "latitude": end_coords[0],
                "longitude": end_coords[1],
            },
            route={
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": route.coordinates,
                },
                "properties": {
                    "distance_miles": round(route.distance_miles, 2),
                    "duration_hours": round(route.duration_seconds / 3600, 2),
                },
            },
            fuel_stops=self._serialize_fuel_stops(fuel_plan),
            total_fuel_cost_usd=fuel_plan.total_cost,
            total_gallons=fuel_plan.total_gallons,
            total_distance_miles=round(route.distance_miles, 2),
            duration_hours=round(route.duration_seconds / 3600, 2),
            map_image_base64=map_image.base64_data_uri,
            assumptions={
                "max_range_miles": settings.MAX_RANGE_MILES,
                "mpg": settings.MPG,
                "tank_capacity_gallons": settings.TANK_CAPACITY_GALLONS,
                "route_corridor_miles": settings.ROUTE_CORRIDOR_MILES,
            },
        )

    def _find_route_candidates(self, route: RouteResult) -> list[FuelStation]:
        """Find fuel stops near the route corridor, cheapest per OPIS location."""
        bounds = route.line.bounds
        buffer_deg = settings.ROUTE_CORRIDOR_MILES / 69.0

        rows = (
            FuelStop.objects.filter(
                latitude__isnull=False,
                longitude__isnull=False,
                latitude__gte=bounds[1] - buffer_deg,
                latitude__lte=bounds[3] + buffer_deg,
                longitude__gte=bounds[0] - buffer_deg,
                longitude__lte=bounds[2] + buffer_deg,
            )
            .values("opis_id")
            .annotate(min_price=Min("retail_price"))
        )
        price_by_opis = {r["opis_id"]: r["min_price"] for r in rows}
        if not price_by_opis:
            return []

        stops_input: list[tuple[float, float, float, dict]] = []
        seen_opis: set[int] = set()
        for stop in FuelStop.objects.filter(opis_id__in=price_by_opis).order_by("retail_price"):
            if stop.opis_id in seen_opis:
                continue
            seen_opis.add(stop.opis_id)
            stops_input.append((
                stop.latitude,
                stop.longitude,
                price_by_opis[stop.opis_id],
                {
                    "id": stop.id,
                    "name": stop.name,
                    "city": stop.city,
                    "state": stop.state,
                    "address": stop.address,
                },
            ))

        matched = match_stops_to_route(
            stops_input,
            route.coordinates,
            route.cumulative_miles,
            route.distance_miles,
            settings.ROUTE_CORRIDOR_MILES,
        )

        candidates = [
            FuelStation(
                id=m["id"],
                name=m["name"],
                city=m["city"],
                state=m["state"],
                address=m["address"],
                retail_price=m["retail_price"],
                latitude=m["latitude"],
                longitude=m["longitude"],
                distance_from_start=m["distance_from_start"],
                distance_from_route=m["distance_from_route"],
            )
            for m in matched
        ]

        logger.info("Found %d candidate fuel stops along route", len(candidates))
        return candidates

    @staticmethod
    def _serialize_fuel_stops(plan: FuelPlan) -> list[dict]:
        result = []
        for stop, gallons in zip(plan.stops, plan.gallons_purchased):
            result.append(
                {
                    "name": stop.name,
                    "address": stop.address,
                    "city": stop.city,
                    "state": stop.state,
                    "retail_price_usd": round(stop.retail_price, 3),
                    "gallons_purchased": gallons,
                    "cost_usd": round(gallons * stop.retail_price, 2),
                    "distance_from_start_miles": round(stop.distance_from_start, 1),
                    "latitude": stop.latitude,
                    "longitude": stop.longitude,
                }
            )
        return result
