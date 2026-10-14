import math

from app.utils.validation import ValidationError, number


def haversine(latitude, longitude, office_latitude, office_longitude):
    earth_radius = 6371000
    delta_lat = math.radians(float(office_latitude) - latitude)
    delta_lon = math.radians(float(office_longitude) - longitude)
    arc = math.sin(delta_lat / 2) ** 2 + math.cos(math.radians(latitude)) * math.cos(math.radians(float(office_latitude))) * math.sin(delta_lon / 2) ** 2
    return earth_radius * 2 * math.atan2(math.sqrt(min(1, arc)), math.sqrt(max(0, 1 - arc)))


def validate_location(data, office):
    latitude = number(data, "latitude", -90, 90)
    longitude = number(data, "longitude", -180, 180)
    accuracy = number(data, "accuracy", 0.01, 50000)
    if accuracy > float(office["max_accuracy_m"]):
        raise ValidationError(f"GPS belum akurat ({accuracy:.0f} m). Maksimal {office['max_accuracy_m']} m; pindah ke area terbuka lalu ulangi.")
    distance = haversine(latitude, longitude, office["latitude"], office["longitude"])
    if distance > float(office["radius_m"]):
        raise ValidationError(f"Anda berada di luar geofence: {distance:.0f} m dari kantor, radius {office['radius_m']} m.")
    return latitude, longitude, accuracy, distance
