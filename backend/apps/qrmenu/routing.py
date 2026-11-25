from django.urls import path

from .realtime import StaffConsumer

# /<slug>/ws/staff/ on the platform host (restaurants live under a path); /ws/staff/ on a verified custom domain.
websocket_urlpatterns = [
    path("<slug:slug>/ws/staff/", StaffConsumer.as_asgi()),
    path("ws/staff/", StaffConsumer.as_asgi()),
]
