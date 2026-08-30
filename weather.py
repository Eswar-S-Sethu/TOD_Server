"""
Weather fetching with a 30-minute per-location cache.

Flow:
    get_weather(location, timestamp)
        -> geocode the location name to lat/lon via Open-Meteo Geocoding API
           (result is cached in memory for the lifetime of the process)
        -> check the weather cache for this location
        -> if the incoming timestamp is within 30 min of the cached reference, reuse it
        -> otherwise fetch fresh hourly data from Open-Meteo and update the cache

All APIs used are free and require no API key.
"""

import threading
from datetime import date, datetime, timedelta

import requests

CACHE_WINDOW = timedelta(minutes=30)

# Coordinates cache: location name -> (lat, lon)
# A place does not move, so this is cached for the lifetime of the process.
_geo_cache: dict[str, tuple[float, float]] = {}
_geo_lock = threading.Lock()

# Weather cache: location name -> {"reference_dt": datetime, "data": dict}
_weather_cache: dict = {}
_weather_lock = threading.Lock()

# WMO Weather Interpretation Codes -> human-readable description
WMO_CODES: dict[int, str] = {
    0:  "Clear sky",
    1:  "Mainly clear",
    2:  "Partly cloudy",
    3:  "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Heavy freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow fall",
    73: "Moderate snow fall",
    75: "Heavy snow fall",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


def _geocode(location: str) -> tuple[float, float]:
    """
    Return (lat, lon) for a place name using the Open-Meteo Geocoding API.
    Results are cached permanently in memory.

    Raises:
        ValueError              — no results found for the name
        requests.RequestException — network or HTTP error
    """
    with _geo_lock:
        if location in _geo_cache:
            return _geo_cache[location]

    resp = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": location, "count": 1, "language": "en", "format": "json"},
        timeout=10,
    )
    resp.raise_for_status()
    results = resp.json().get("results")
    if not results:
        raise ValueError(f"Could not geocode location: '{location}'")

    lat = results[0]["latitude"]
    lon = results[0]["longitude"]

    with _geo_lock:
        _geo_cache[location] = (lat, lon)

    return lat, lon


def _fetch_open_meteo(lat: float, lon: float, capture_dt: datetime) -> dict:
    """
    Fetch hourly weather from Open-Meteo for the given coordinates and datetime.

    Uses the Forecast API for dates within the last 7 days (more reliable for
    recent data), and the Archive API for older dates.
    """
    capture_date = capture_dt.date()
    days_ago = (date.today() - capture_date).days

    url = (
        "https://api.open-meteo.com/v1/forecast"
        if days_ago <= 7
        else "https://archive-api.open-meteo.com/v1/archive"
    )

    params = {
        "latitude":   lat,
        "longitude":  lon,
        "start_date": capture_date.isoformat(),
        "end_date":   capture_date.isoformat(),
        "hourly": (
            "temperature_2m,"
            "relative_humidity_2m,"
            "precipitation,"
            "wind_speed_10m,"
            "weather_code"
        ),
        # auto resolves to the local timezone for the coordinates,
        # which aligns with the "local capture time" in the payload.
        "timezone": "auto",
    }

    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    hourly = resp.json()["hourly"]

    # Open-Meteo returns times as "YYYY-MM-DDTHH:00", e.g. "2024-01-15T09:00"
    target_time = capture_dt.strftime("%Y-%m-%dT%H:00")
    try:
        idx = hourly["time"].index(target_time)
    except ValueError:
        idx = capture_dt.hour  # fallback to raw hour index

    weather_code = int(hourly["weather_code"][idx])

    return {
        "temperature_c":         hourly["temperature_2m"][idx],
        "relative_humidity_pct": hourly["relative_humidity_2m"][idx],
        "precipitation_mm":      hourly["precipitation"][idx],
        "wind_speed_kmh":        hourly["wind_speed_10m"][idx],
        "weather_code":          weather_code,
        "condition":             WMO_CODES.get(weather_code, "Unknown"),
        "reference_hour":        hourly["time"][idx],
        "source":                "Open-Meteo",
    }


def get_weather(location: str, timestamp: str) -> dict:
    """
    Return weather data for a location name and timestamp, with a 30-minute
    cache window per location.

    The location name (e.g. "Chadstone", "Mount Waverley") is geocoded
    automatically on first use and the coordinates are cached for the process
    lifetime.

    If the incoming timestamp is within 30 minutes of the timestamp that
    triggered the last weather fetch for the same location, the cached result
    is returned and no weather API call is made.

    The returned dict always includes a boolean "cached" key.

    Raises:
        ValueError                — location could not be geocoded
        requests.RequestException — network or HTTP error
    """
    capture_dt = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
    lat, lon = _geocode(location)

    with _weather_lock:
        entry = _weather_cache.get(location)
        if entry is not None:
            if abs(capture_dt - entry["reference_dt"]) <= CACHE_WINDOW:
                return {**entry["data"], "cached": True}

        weather = _fetch_open_meteo(lat, lon, capture_dt)
        _weather_cache[location] = {"reference_dt": capture_dt, "data": weather}
        return {**weather, "cached": False}
