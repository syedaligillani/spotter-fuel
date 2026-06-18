"""Static map generation for route visualization."""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass

from staticmap import CircleMarker, Line, StaticMap

from routing.services.fuel_optimizer import FuelStation


@dataclass
class MapImage:
    png_bytes: bytes
    base64_data_uri: str


def generate_route_map(
    route_coords: list[tuple[float, float]],
    start: tuple[float, float],
    end: tuple[float, float],
    fuel_stops: list[FuelStation],
    *,
    width: int = 800,
    height: int = 600,
) -> MapImage:
    """
    Generate a PNG map showing the route and fuel stops.

    route_coords are (lng, lat) GeoJSON order.
    start/end are (lat, lng).
    """
    # Downsample route for faster tile rendering
    if len(route_coords) > 300:
        step = max(1, len(route_coords) // 300)
        route_coords = route_coords[::step] + [route_coords[-1]]

    m = StaticMap(width, height, url_template="https://tile.openstreetmap.org/{z}/{x}/{y}.png")

    if len(route_coords) >= 2:
        line = Line(
            [(lng, lat) for lng, lat in route_coords],
            "#0066FF",
            4,
        )
        m.add_line(line)

    start_marker = CircleMarker((start[1], start[0]), "#00AA00", 12)
    end_marker = CircleMarker((end[1], end[0]), "#CC0000", 12)
    m.add_marker(start_marker)
    m.add_marker(end_marker)

    for stop in fuel_stops:
        marker = CircleMarker(
            (stop.longitude, stop.latitude),
            "#FF9900",
            10,
        )
        m.add_marker(marker)

    image = m.render(zoom=None, center=None)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    png_bytes = buffer.getvalue()
    b64 = base64.b64encode(png_bytes).decode("ascii")

    return MapImage(
        png_bytes=png_bytes,
        base64_data_uri=f"data:image/png;base64,{b64}",
    )
