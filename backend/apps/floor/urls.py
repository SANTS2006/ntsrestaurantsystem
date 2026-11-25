from django.urls import path

from . import views as v

urlpatterns = [
    path("public/options/", v.OptionsView.as_view()),
    path("public/availability/", v.AvailabilityView.as_view()),
    path("public/reservations/", v.BookView.as_view()),
    path("public/reservations/<str:token>/", v.GuestReservationView.as_view()),
    path("status/", v.StatusView.as_view()),
    path("reservations/", v.ReservationsView.as_view()),
    path("reservations/<int:pk>/", v.ReservationView.as_view()),
    path("reservations/<int:pk>/<str:act>/", v.ReservationActionView.as_view()),
    path("zones/", v.ZonesView.as_view()),
    path("zones/<int:pk>/", v.ZoneView.as_view()),
    path("tables/<int:pk>/layout/", v.TableLayoutView.as_view()),
]
