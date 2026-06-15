from django.urls import path

from . import views


app_name = "odds"

urlpatterns = [
    path("", views.import_odds, name="import"),
    path("tickets/", views.tickets, name="tickets"),
    path("summary/", views.summary, name="summary"),
]
