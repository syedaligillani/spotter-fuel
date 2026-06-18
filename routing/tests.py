from django.test import SimpleTestCase

from routing.services.fuel_optimizer import FuelStation, optimize_fuel_stops


def _station(dist: float, price: float, sid: int = 1) -> FuelStation:
    return FuelStation(
        id=sid,
        name=f"Stop {sid}",
        city="Test",
        state="TX",
        address="123 Hwy",
        retail_price=price,
        latitude=30.0,
        longitude=-97.0,
        distance_from_start=dist,
        distance_from_route=1.0,
    )


class FuelOptimizerTests(SimpleTestCase):
    def test_short_trip_no_stops_needed(self):
        plan = optimize_fuel_stops([], 400)
        self.assertEqual(plan.total_cost, 0.0)
        self.assertEqual(plan.stops, [])

    def test_picks_cheaper_station(self):
        candidates = [
            _station(200, 4.0, 1),
            _station(400, 2.5, 2),
            _station(600, 3.0, 3),
        ]
        plan = optimize_fuel_stops(candidates, 700)
        self.assertGreater(len(plan.stops), 0)
        self.assertLess(plan.total_cost, 200)  # cheaper than filling at $4 stations only

    def test_infeasible_route_raises(self):
        candidates = [_station(600, 3.0, 1)]
        with self.assertRaises(ValueError):
            optimize_fuel_stops(candidates, 1200)
