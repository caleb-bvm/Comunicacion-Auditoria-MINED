from django.urls import path

from . import technical

urlpatterns = [
    path("", technical.technical_dashboard, name="technical_dashboard"),
    path("usuarios/", technical.technical_user_list, name="technical_users"),
    path("usuarios/nuevo/", technical.technical_user_create, name="technical_user_create"),
    path("usuarios/<int:pk>/", technical.technical_user_detail, name="technical_user_detail"),
    path("usuarios/<int:pk>/<str:action>/", technical.technical_user_action, name="technical_user_action"),
    path("bitacora/", technical.technical_activity_log, name="technical_activity_log"),
    path("solicitudes/", technical.technical_support_requests, name="technical_support_requests"),
    path("solicitudes/<int:pk>/", technical.technical_support_requests, name="technical_support_request_detail"),
]
