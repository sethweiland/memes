"""
Weather forecast module using Open-Meteo API.

Provides a 7-day forecast with emphasis on inclement weather conditions.
"""

import os
from datetime import datetime
from typing import Any, Optional

import requests


def get_weather_forecast() -> Optional[dict[str, Any]]:
    """
    Fetch 7-day weather forecast for configured location.
    
    Returns dict with forecast data or None on failure.
    Uses Open-Meteo API (free, no key required).
    
    Location defaults to NYC (lat: 40.7282, lon: -73.9942).
    Override via WEATHER_LAT/WEATHER_LON env vars.
    """
    lat = float(os.getenv("WEATHER_LAT", "40.7282"))  # NYC/East Village default
    lon = float(os.getenv("WEATHER_LON", "-73.9942"))
    
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,rain_sum,snowfall_sum,windspeed_10m_max,weathercode",
        "temperature_unit": "fahrenheit",
        "windspeed_unit": "mph",
        "precipitation_unit": "inch",
        "timezone": "America/New_York",
        "forecast_days": 7,
    }
    
    try:
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        if "daily" not in data:
            return None
            
        return _format_forecast(data)
    except Exception:
        return None


def _format_forecast(data: dict[str, Any]) -> dict[str, Any]:
    """Format raw Open-Meteo data into display-friendly structure."""
    daily = data["daily"]
    days = []
    
    for i in range(len(daily["time"])):
        date_str = daily["time"][i]
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        
        # Weather code to condition mapping (WMO codes)
        weather_code = daily["weathercode"][i]
        condition, is_inclement = _parse_weather_code(weather_code)
        
        # Additional inclement checks
        rain = daily["rain_sum"][i] or 0
        snow = daily["snowfall_sum"][i] or 0
        wind = daily["windspeed_10m_max"][i] or 0
        
        if rain > 0.1 or snow > 0:
            is_inclement = True
        if wind > 25:  # High wind threshold
            is_inclement = True
            
        day_data = {
            "date": date_str,
            "weekday": date_obj.strftime("%a"),
            "weekday_full": date_obj.strftime("%A"),
            "temp_high": round(daily["temperature_2m_max"][i]),
            "temp_low": round(daily["temperature_2m_min"][i]),
            "condition": condition,
            "is_inclement": is_inclement,
            "rain": rain,
            "snow": snow,
            "wind": round(wind),
            "weather_code": weather_code,
        }
        days.append(day_data)
    
    return {
        "days": days,
        "location": "NYC",  # Could make this configurable too
        "updated_at": datetime.now().isoformat(),
    }


def _parse_weather_code(code: int) -> tuple[str, bool]:
    """
    Parse WMO weather code into condition label and inclement flag.
    
    Returns (condition_name, is_inclement).
    """
    # WMO weather codes: https://open-meteo.com/en/docs
    code_map = {
        0: ("Clear", False),
        1: ("Mostly Clear", False),
        2: ("Partly Cloudy", False),
        3: ("Overcast", False),
        45: ("Fog", False),
        48: ("Fog", False),
        51: ("Light Drizzle", True),
        53: ("Drizzle", True),
        55: ("Heavy Drizzle", True),
        56: ("Freezing Drizzle", True),
        57: ("Freezing Drizzle", True),
        61: ("Light Rain", True),
        63: ("Rain", True),
        65: ("Heavy Rain", True),
        66: ("Freezing Rain", True),
        67: ("Freezing Rain", True),
        71: ("Light Snow", True),
        73: ("Snow", True),
        75: ("Heavy Snow", True),
        77: ("Snow Grains", True),
        80: ("Rain Showers", True),
        81: ("Rain Showers", True),
        82: ("Heavy Showers", True),
        85: ("Snow Showers", True),
        86: ("Snow Showers", True),
        95: ("Thunderstorm", True),
        96: ("Thunderstorm", True),
        99: ("Severe Storm", True),
    }
    
    return code_map.get(code, ("Unknown", False))


def get_weather_for_home() -> Optional[dict[str, Any]]:
    """
    Get formatted weather data for home page display.
    
    Returns None if fetch fails (graceful degradation).
    """
    forecast = get_weather_forecast()
    if not forecast:
        return None
        
    return {
        "has_data": True,
        "days": forecast["days"],
        "location": forecast["location"],
        "updated_at": forecast["updated_at"],
    }
