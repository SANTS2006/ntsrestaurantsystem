"""Rules shared by every form that stores a map pin."""
from rest_framework import serializers


def check_pin(data, instance=None):
    """Latitude and longitude only make sense together: both, or neither."""
    lat = data.get("latitude", getattr(instance, "latitude", None))
    lng = data.get("longitude", getattr(instance, "longitude", None))
    if (lat is None) != (lng is None):
        raise serializers.ValidationError({"latitude": "Give both the latitude and the longitude, or leave both empty."})
    return data
