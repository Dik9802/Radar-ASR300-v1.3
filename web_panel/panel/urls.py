from django.urls import path
from . import views

app_name = "panel"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("api/plate-config/", views.api_plate_config, name="api_plate_config"),
    path("api/display-mode/", views.api_display_mode, name="api_display_mode"),
    path("api/display-text/", views.api_display_text, name="api_display_text"),
]
