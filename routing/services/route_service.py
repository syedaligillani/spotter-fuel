"""OSRM routing service."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import requests
from django.conf import settings
from shapely.geometry import LineString, Point

logger = logging.getLogger(__name__)

METERS_TO_MILES = 0.000621371
EARTH_RADIUS_MILES = 3958.8


@dataclass
class RouteResult:
    coordinates: list[tuple[float, float]]  # (lng, lat) GeoJSON order
    distance_miles: float
    duration_seconds: float
    line: LineString
    cumulative_miles: list[float]  # cumulative distance at each coordinate


class RouteService:
    """Fetch driving routes from the public OSRM API (single external call)."""

    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or settings.OSRM_BASE_URL).rstrip("/")

    def get_route(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> RouteResult:
        """
        Get route between two (lat, lng) points.
        Makes exactly one OSRM API call.
        """
        start_lng, start_lat = start[1], start[0]
        end_lng, end_lat = end[1], end[0]
        coords = f"{start_lng},{start_lat};{end_lng},{end_lat}"
        url = f"{self.base_url}/route/v1/driving/{coords}"
        params = {
            "overview": "full",
            "geometries": "geojson",
            "steps": "false",
        }

        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        if data.get("code") != "Ok" or not data.get("routes"):
            message = data.get("message", "Unknown routing error")
            raise ValueError(f"OSRM routing failed: {message}")

        route = data["routes"][0]
        geometry = route["geometry"]["coordinates"]
        line = LineString(geometry)
        distance_miles = route["distance"] * METERS_TO_MILES
        cumulative = _cumulative_distances_miles(geometry)

        return RouteResult(
            coordinates=geometry,
            distance_miles=distance_miles,
            duration_seconds=route["duration"],
            line=line,
            cumulative_miles=cumulative,
        )


def haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in miles between two WGS84 points."""
    rlat1, rlng1, rlat2, rlng2 = map(math.radians, [lat1, lng1, lat2, lng2])
    dlat = rlat2 - rlat1
    dlng = rlng2 - rlng1
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlng / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(a))


def _cumulative_distances_miles(coords: list[tuple[float, float]]) -> list[float]:
    """Build cumulative mile markers for each (lng, lat) point on the route."""
    cumulative = [0.0]
    for i in range(1, len(coords)):
        lng1, lat1 = coords[i - 1]
        lng2, lat2 = coords[i]
        cumulative.append(cumulative[-1] + haversine_miles(lat1, lng1, lat2, lng2))
    return cumulative


def distance_along_route(
    line: LineString,
    point: Point,
    cumulative_miles: list[float] | None = None,
    coords: list[tuple[float, float]] | None = None,
) -> float:
    """
    Return distance in miles from route start to the nearest point on the route.

    Uses geodesic interpolation when cumulative_miles and coords are provided.
    """
    if cumulative_miles and coords:
        return _distance_along_geodesic(coords, cumulative_miles, point.y, point.x)

    # Fallback: shapely project (less accurate for geographic coords)
    projected_distance_m = line.project(point)
    return projected_distance_m * METERS_TO_MILES


def _distance_along_geodesic(
    coords: list[tuple[float, float]],
    cumulative_miles: list[float],
    lat: float,
    lng: float,
) -> float:
    """Find nearest segment on route and interpolate geodesic distance along it."""
    best_dist_sq = float("inf")
    best_miles = 0.0

    for i in range(len(coords) - 1):
        lng1, lat1 = coords[i]
        lng2, lat2 = coords[i + 1]
        seg_len = cumulative_miles[i + 1] - cumulative_miles[i]
        if seg_len < 1e-9:
            continue

        t = _project_on_segment(lat, lng, lat1, lng1, lat2, lng2)
        t = max(0.0, min(1.0, t))
        proj_lat = lat1 + t * (lat2 - lat1)
        proj_lng = lng1 + t * (lng2 - lng1)
        d = haversine_miles(lat, lng, proj_lat, proj_lng)

        if d < best_dist_sq:
            best_dist_sq = d
            best_miles = cumulative_miles[i] + t * seg_len

    return best_miles


def _project_on_segment(
    lat: float, lng: float,
    lat1: float, lng1: float,
    lat2: float, lng2: float,
) -> float:
    """Project point onto segment in lat/lng space (approximate, good for short segments)."""
    dx = lng2 - lng1
    dy = lat2 - lat1
    if dx == 0 and dy == 0:
        return 0.0
    return ((lng - lng1) * dx + (lat - lat1) * dy) / (dx * dx + dy * dy)


def _downsample_coords(
    coords: list[tuple[float, float]],
    cumulative_miles: list[float],
    max_points: int = 200,
) -> tuple[list[tuple[float, float]], list[float]]:
    """Reduce route points for faster geodesic matching."""
    if len(coords) <= max_points:
        return coords, cumulative_miles

    step = max(1, len(coords) // max_points)
    sampled_coords = [coords[0]]
    sampled_cumulative = [cumulative_miles[0]]
    for i in range(step, len(coords) - 1, step):
        sampled_coords.append(coords[i])
        sampled_cumulative.append(cumulative_miles[i])
    sampled_coords.append(coords[-1])
    sampled_cumulative.append(cumulative_miles[-1])
    return sampled_coords, sampled_cumulative


def match_stops_to_route(
    stops: list[tuple[float, float, float, dict]],
    coords: list[tuple[float, float]],
    cumulative_miles: list[float],
    total_distance_miles: float,
    corridor_miles: float,
) -> list[dict]:
    """
    Batch-match stops (lat, lng, price, meta) to route.

    Returns list of dicts with distance_from_start, distance_from_route, and meta.
    """
    sampled_coords, sampled_cumulative = _downsample_coords(coords, cumulative_miles)

    # Pre-build segment data for inner loop
    segments: list[tuple[float, float, float, float, float, float]] = []
    for i in range(len(sampled_coords) - 1):
        lng1, lat1 = sampled_coords[i]
        lng2, lat2 = sampled_coords[i + 1]
        seg_len = sampled_cumulative[i + 1] - sampled_cumulative[i]
        if seg_len > 1e-9:
            segments.append((lat1, lng1, lat2, lng2, sampled_cumulative[i], seg_len))

    results = []
    for lat, lng, price, meta in stops:
        best_off = float("inf")
        best_miles = 0.0

        for lat1, lng1, lat2, lng2, base_miles, seg_len in segments:
            t = _project_on_segment(lat, lng, lat1, lng1, lat2, lng2)
            t = max(0.0, min(1.0, t))
            proj_lat = lat1 + t * (lat2 - lat1)
            proj_lng = lng1 + t * (lng2 - lng1)
            off = haversine_miles(lat, lng, proj_lat, proj_lng)
            if off < best_off:
                best_off = off
                best_miles = base_miles + t * seg_len

        if best_off <= corridor_miles and 0 < best_miles < total_distance_miles:
            results.append({
                **meta,
                "retail_price": price,
                "latitude": lat,
                "longitude": lng,
                "distance_from_start": best_miles,
                "distance_from_route": best_off,
            })

    return results


def point_to_route_distance_miles(
    line: LineString,
    lat: float,
    lng: float,
    cumulative_miles: list[float] | None = None,
    coords: list[tuple[float, float]] | None = None,
) -> float:
    """Minimum distance in miles from a point to the route."""
    if cumulative_miles and coords:
        best = float("inf")
        sampled_coords, _ = _downsample_coords(coords, cumulative_miles)
        sampled_cumulative = _cumulative_distances_miles(sampled_coords)
        for i in range(len(sampled_coords) - 1):
            lng1, lat1 = sampled_coords[i]
            lng2, lat2 = sampled_coords[i + 1]
            t = _project_on_segment(lat, lng, lat1, lng1, lat2, lng2)
            t = max(0.0, min(1.0, t))
            proj_lat = lat1 + t * (lat2 - lat1)
            proj_lng = lng1 + t * (lng2 - lng1)
            best = min(best, haversine_miles(lat, lng, proj_lat, proj_lng))
        return best

    point = Point(lng, lat)
    nearest = line.interpolate(line.project(point))
    return point.distance(nearest) * METERS_TO_MILES
