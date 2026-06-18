"""Geocoding utilities with DB cache and local city lookup."""

from __future__ import annotations

import hashlib
import logging
import time
from functools import lru_cache

import geonamescache
import requests
from django.conf import settings

from routing.models import GeocodeCache

logger = logging.getLogger(__name__)

# US state centroids (approximate) for fallback geocoding
STATE_CENTROIDS: dict[str, tuple[float, float]] = {
    "AL": (32.806671, -86.791130),
    "AK": (61.370716, -152.404419),
    "AZ": (33.729759, -111.431221),
    "AR": (34.969704, -92.373123),
    "CA": (36.116203, -119.681564),
    "CO": (39.059811, -105.311104),
    "CT": (41.597782, -72.755371),
    "DE": (39.318523, -75.507141),
    "DC": (38.897438, -77.026817),
    "FL": (27.766279, -81.686783),
    "GA": (33.040619, -83.643074),
    "HI": (21.094318, -157.498337),
    "ID": (44.240459, -114.478828),
    "IL": (40.349457, -88.986137),
    "IN": (39.849426, -86.258278),
    "IA": (42.011539, -93.210526),
    "KS": (38.526600, -96.726486),
    "KY": (37.668140, -84.670067),
    "LA": (31.169546, -91.867805),
    "ME": (44.693947, -69.381927),
    "MD": (39.063946, -76.802101),
    "MA": (42.230171, -71.530106),
    "MI": (43.326618, -84.536095),
    "MN": (45.694454, -93.900192),
    "MS": (32.741646, -89.678696),
    "MO": (38.456085, -92.288368),
    "MT": (46.921925, -110.454353),
    "NE": (41.125370, -98.268082),
    "NV": (38.313515, -117.055374),
    "NH": (43.452492, -71.563896),
    "NJ": (40.298904, -74.521011),
    "NM": (34.840515, -106.248482),
    "NY": (42.165726, -74.948051),
    "NC": (35.630066, -79.806419),
    "ND": (47.528912, -99.784012),
    "OH": (40.388783, -82.764915),
    "OK": (35.565342, -96.928917),
    "OR": (44.572021, -122.070938),
    "PA": (40.590752, -77.209755),
    "RI": (41.680893, -71.511780),
    "SC": (33.856892, -80.945007),
    "SD": (44.299782, -99.438828),
    "TN": (35.747845, -86.692345),
    "TX": (31.054487, -97.563461),
    "UT": (40.150032, -111.862434),
    "VT": (44.045876, -72.710686),
    "VA": (37.769337, -78.169968),
    "WA": (47.400897, -121.490494),
    "WV": (38.491226, -80.954453),
    "WI": (44.268543, -89.616508),
    "WY": (42.755966, -107.302490),
}


@lru_cache(maxsize=1)
def _us_city_index() -> dict[tuple[str, str], tuple[float, float]]:
    """Build a lookup of (city_lower, state) -> (lat, lng) from geonamescache."""
    gc = geonamescache.GeonamesCache(min_city_population=1000)
    index: dict[tuple[str, str], tuple[float, float]] = {}
    for city in gc.get_cities().values():
        if city["countrycode"] != "US":
            continue
        key = (city["name"].lower().strip(), city["countrycode"])
        # Prefer larger cities when names collide
        if key not in index:
            index[key] = (city["latitude"], city["longitude"])
    # Also index by state code from admin codes
    state_index: dict[tuple[str, str], tuple[float, float]] = {}
    for city in gc.get_cities().values():
        if city["countrycode"] != "US":
            continue
        state = _state_from_admin_code(city.get("admin1code", ""))
        if not state:
            continue
        key = (city["name"].lower().strip(), state)
        pop = city.get("population", 0)
        if key not in state_index or pop > state_index.get(key, (0, 0, 0))[2]:  # type: ignore[misc]
            state_index[key] = (city["latitude"], city["longitude"], pop)  # type: ignore[assignment]
    return {k: (v[0], v[1]) for k, v in state_index.items()}


def _state_from_admin_code(admin1code: str) -> str:
    """Map geonames admin1 code (e.g. US.OK) to state abbreviation."""
    if not admin1code:
        return ""
    parts = admin1code.split(".")
    return parts[-1] if len(parts) >= 2 else admin1code


def _jitter_coords(lat: float, lng: float, seed: str) -> tuple[float, float]:
    """Add small deterministic offset so stops in the same city don't overlap."""
    digest = hashlib.md5(seed.encode()).hexdigest()
    dlat = (int(digest[:4], 16) / 65535 - 0.5) * 0.08
    dlng = (int(digest[4:8], 16) / 65535 - 0.5) * 0.08
    return lat + dlat, lng + dlng


def geocode_location(query: str, *, use_api: bool = True) -> tuple[float, float]:
    """
    Geocode a location string. Checks DB cache first, then local city index,
    then Nominatim API as last resort.
    """
    normalized = query.strip()
    cached = GeocodeCache.objects.filter(query__iexact=normalized).first()
    if cached:
        return cached.latitude, cached.longitude

    coords = _geocode_local(normalized)
    if coords is None and use_api:
        coords = _geocode_nominatim(normalized)

    if coords is None:
        raise ValueError(f"Could not geocode location: {query}")

    GeocodeCache.objects.update_or_create(
        query=normalized,
        defaults={"latitude": coords[0], "longitude": coords[1]},
    )
    return coords


def geocode_fuel_stop(city: str, state: str, address: str, opis_id: int) -> tuple[float, float]:
    """Geocode a fuel stop using local data with jitter; no external API."""
    city_clean = city.strip()
    state_clean = state.strip().upper()
    city_index = _us_city_index()

    coords = city_index.get((city_clean.lower(), state_clean))
    if coords is None:
        # Try partial match
        for (c, s), loc in city_index.items():
            if s == state_clean and (c in city_clean.lower() or city_clean.lower() in c):
                coords = loc
                break

    if coords is None:
        coords = STATE_CENTROIDS.get(state_clean)
        if coords is None:
            raise ValueError(f"No coordinates for {city}, {state}")

    return _jitter_coords(coords[0], coords[1], f"{opis_id}:{address}:{city_clean}")


def _geocode_local(query: str) -> tuple[float, float] | None:
    """Try to parse 'City, ST' or 'City, State' from query."""
    parts = [p.strip() for p in query.split(",")]
    if len(parts) < 2:
        return None

    city = parts[0]
    state_part = parts[1].upper().replace(" USA", "").replace(" US", "").strip()
    state = state_part[:2] if len(state_part) >= 2 else state_part

    city_index = _us_city_index()
    return city_index.get((city.lower(), state))


def _geocode_nominatim(query: str) -> tuple[float, float] | None:
    """Call Nominatim geocoding API (rate-limited, cached)."""
    url = f"{settings.NOMINATIM_BASE_URL}/search"
    params = {
        "q": query if "USA" in query.upper() else f"{query}, USA",
        "format": "json",
        "limit": 1,
        "countrycodes": "us",
    }
    headers = {"User-Agent": settings.NOMINATIM_USER_AGENT}

    try:
        time.sleep(1.0)  # Respect Nominatim rate limit
        response = requests.get(url, params=params, headers=headers, timeout=15)
        response.raise_for_status()
        results = response.json()
        if not results:
            return None
        return float(results[0]["lat"]), float(results[0]["lon"])
    except requests.RequestException as exc:
        logger.warning("Nominatim geocoding failed for %r: %s", query, exc)
        return None
