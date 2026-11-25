from django.urls import path

from .realtime import StaffConsumer

websocket_urlpatterns = [path("ws/staff/", StaffConsumer.as_asgi())]
