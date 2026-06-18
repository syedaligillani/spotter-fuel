"""Minimum-cost fuel stop optimization along a route."""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings


@dataclass
class FuelStation:
    """A candidate or selected fuel stop along the route."""

    id: int
    name: str
    city: str
    state: str
    address: str
    retail_price: float
    latitude: float
    longitude: float
    distance_from_start: float  # miles along route
    distance_from_route: float  # miles off route


@dataclass
class FuelPlan:
    """Optimized fuel purchase plan."""

    stops: list[FuelStation]
    gallons_purchased: list[float]
    total_cost: float
    total_gallons: float


def optimize_fuel_stops(
    candidates: list[FuelStation],
    total_distance_miles: float,
    *,
    max_range_miles: float | None = None,
    mpg: float | None = None,
) -> FuelPlan:
    """
    Find the minimum-cost fuel plan using dynamic programming.

    The vehicle starts with a full tank and must reach the destination.
    At each real fuel stop we may purchase fuel up to tank capacity.
    """
    max_range = max_range_miles or settings.MAX_RANGE_MILES
    miles_per_gallon = mpg or settings.MPG
    tank_capacity = max_range / miles_per_gallon

    if total_distance_miles <= max_range:
        return FuelPlan(stops=[], gallons_purchased=[], total_cost=0.0, total_gallons=0.0)

    # Keep cheapest station per ~5-mile segment along route
    segment_size = 5
    best_by_segment: dict[int, FuelStation] = {}
    for stop in candidates:
        if stop.distance_from_start <= 0 or stop.distance_from_start >= total_distance_miles:
            continue
        seg = int(stop.distance_from_start // segment_size)
        existing = best_by_segment.get(seg)
        if existing is None or stop.retail_price < existing.retail_price:
            best_by_segment[seg] = stop

    # Build waypoint list: (distance, price, station | None)
    waypoints: list[tuple[float, float, FuelStation | None]] = [(0.0, 0.0, None)]
    for stop in sorted(best_by_segment.values(), key=lambda s: s.distance_from_start):
        waypoints.append((stop.distance_from_start, stop.retail_price, stop))
    waypoints.append((total_distance_miles, 0.0, None))

    n = len(waypoints)
    inf = float("inf")

    # cost[i] = min spend to arrive at waypoint i; fuel[i] = gallons on arrival
    cost = [inf] * n
    fuel = [0.0] * n
    prev: list[int | None] = [None] * n
    purchase: list[float] = [0.0] * n  # gallons bought at prev stop when leaving toward i

    cost[0] = 0.0
    fuel[0] = tank_capacity

    for i in range(n):
        if cost[i] == inf:
            continue

        dist_i, price_i, _ = waypoints[i]

        for j in range(i + 1, n):
            dist_j, _, _ = waypoints[j]
            leg = dist_j - dist_i
            if leg > max_range + 1e-6:
                break

            need = leg / miles_per_gallon

            # Candidate purchase amounts at waypoint i (start already has full tank)
            buy_options = [0.0]
            if i > 0:
                min_buy = max(0.0, need - fuel[i])
                max_buy = max(0.0, tank_capacity - fuel[i])
                buy_options = []
                if min_buy <= max_buy + 1e-9:
                    buy_options.append(min_buy)
                    if max_buy > min_buy + 1e-9:
                        buy_options.append(max_buy)

            for buy in buy_options:
                fuel_after_buy = fuel[i] + buy
                if fuel_after_buy + 1e-9 < need:
                    continue

                new_cost = cost[i] + buy * price_i
                new_fuel = fuel_after_buy - need

                if new_cost < cost[j] - 1e-9 or (
                    abs(new_cost - cost[j]) < 1e-9 and new_fuel > fuel[j]
                ):
                    cost[j] = new_cost
                    fuel[j] = new_fuel
                    prev[j] = i
                    purchase[j] = buy

    if cost[n - 1] == inf:
        raise ValueError(
            "No feasible fuel plan: insufficient fuel stops within 500-mile range along the route."
        )

    # Reconstruct purchases at each visited fuel stop
    selected: list[tuple[FuelStation, float]] = []
    j = n - 1
    while prev[j] is not None:
        i = prev[j]
        buy = purchase[j]
        _, _, station = waypoints[i]
        if station is not None and buy > 1e-6:
            selected.append((station, round(buy, 2)))
        j = i
    selected.reverse()

    stops = [s for s, _ in selected]
    gallons = [g for _, g in selected]
    total_gallons = round(sum(gallons), 2)

    return FuelPlan(
        stops=stops,
        gallons_purchased=gallons,
        total_cost=round(cost[n - 1], 2),
        total_gallons=total_gallons,
    )
