# Spotter Fuel Route API

Django REST API that calculates the optimal driving route between two US locations and finds the most cost-effective fuel stops along the way.

## Features

- **Route calculation** via [OSRM](https://project-osrm.org/) (free, no API key) — **1 external call per request**
- **Geocoding** via [Nominatim](https://nominatim.openstreetmap.org/) with DB caching — **0–2 calls** (cached after first use)
- **Fuel stop optimization** using dynamic programming (minimize total fuel cost)
- **Route map** returned as base64-encoded PNG with route line and fuel stop markers
- **7,500+ truck stops** pre-loaded from the provided CSV

## Assumptions

| Parameter | Value |
|-----------|-------|
| Max vehicle range | 500 miles (full tank) |
| Fuel efficiency | 10 MPG |
| Tank capacity | 50 gallons |
| Route corridor | 15 miles from route |

## Quick Start

```bash
# 1. Create virtual environment
python3 -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run migrations
python manage.py migrate

# 4. Import fuel price data (one-time setup)
python manage.py import_fuel_stops

# 5. Start the server
python manage.py runserver
```

## API Endpoints

### `POST /api/route/`

Calculate route with optimal fuel stops.

**Request:**
```json
{
  "start": "Chicago, IL",
  "end": "Denver, CO"
}
```

**Response:**
```json
{
  "start": { "location": "Chicago, IL", "latitude": 41.85, "longitude": -87.65 },
  "end": { "location": "Denver, CO", "latitude": 39.74, "longitude": -104.98 },
  "route": {
    "type": "Feature",
    "geometry": { "type": "LineString", "coordinates": [[...]] },
    "properties": { "distance_miles": 1004.77, "duration_hours": 14.5 }
  },
  "fuel_stops": [
    {
      "name": "KUM & GO #0370",
      "city": "Gretna",
      "state": "NE",
      "retail_price_usd": 2.921,
      "gallons_purchased": 48.22,
      "cost_usd": 140.83,
      "distance_from_start_miles": 502.3,
      "latitude": 41.07,
      "longitude": -96.24
    }
  ],
  "total_fuel_cost_usd": 148.08,
  "total_gallons": 50.48,
  "total_distance_miles": 1004.77,
  "duration_hours": 14.5,
  "map_image_base64": "data:image/png;base64,...",
  "assumptions": {
    "max_range_miles": 500,
    "mpg": 10,
    "tank_capacity_gallons": 50.0,
    "route_corridor_miles": 15
  }
}
```

### `GET /api/health/`

Health check with fuel stop count.

## Postman Demo

1. Create a new **POST** request to `http://127.0.0.1:8000/api/route/`
2. Set header: `Content-Type: application/json`
3. Body (raw JSON):
   ```json
   {
     "start": "New York, NY",
     "end": "Los Angeles, CA"
   }
   ```
4. Send — you'll get the route GeoJSON, fuel stops, total cost, and a base64 map image.

**View the map:** Copy the `map_image_base64` value and paste it into a browser address bar.

### Example routes to try

| Start | End | Distance | Fuel stops |
|-------|-----|----------|------------|
| Boston, MA | New York, NY | ~214 mi | 0 (within range) |
| Chicago, IL | Denver, CO | ~1,005 mi | 2–3 |
| New York, NY | Los Angeles, CA | ~2,798 mi | ~11 |

## Architecture

```
POST /api/route/
    │
    ├─► Geocode start & end (Nominatim + cache)
    ├─► Get driving route (OSRM — 1 API call)
    ├─► Find fuel stops within 15mi corridor (SQLite)
    ├─► Optimize fuel purchases (DP algorithm)
    └─► Generate route map (staticmap + OSM tiles)
```

### Fuel optimization algorithm

Stations are sorted by distance along the route. Dynamic programming finds the minimum-cost path where:
- The vehicle starts with a full 50-gallon tank
- Each leg must be ≤ 500 miles
- At each stop, buy only what's needed (or fill up if cheaper stations are unreachable)

### External API usage

| Service | Purpose | Calls per request |
|---------|---------|-------------------|
| OSRM | Driving route | 1 |
| Nominatim | Geocode start/end | 0–2 (cached) |

Fuel stop coordinates are pre-geocoded during CSV import using `geonamescache` (no external calls).

## Project Structure

```
fuel_route/          # Django project settings
routing/
  models.py          # FuelStop, GeocodeCache
  views.py           # API endpoints
  services/
    geocoding.py     # Location geocoding + cache
    route_service.py # OSRM integration
    fuel_optimizer.py# DP fuel cost optimization
    map_service.py   # Static map generation
    trip_planner.py  # Main orchestration
  management/commands/
    import_fuel_stops.py
data/
  fuel-prices.csv    # Provided assessment data
```

## Loom Video Outline (≤5 min)

1. **Demo (2 min):** Postman → `POST /api/route/` with Chicago → Denver, show response fields and paste map base64 in browser
2. **Code walkthrough (2 min):**
   - `trip_planner.py` — orchestration flow
   - `fuel_optimizer.py` — DP algorithm
   - `route_service.py` — OSRM + geodesic distance
3. **Setup (30 sec):** `migrate` + `import_fuel_stops`

## License

Assessment project for Spotter Backend Django Engineer position.
