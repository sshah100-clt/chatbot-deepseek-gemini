from django.urls import path
from .views import index, chat, profile_login, profile_logout, admin_dashboard

urlpatterns = [
    path("", index, name="index"),
    path("login/", profile_login, name="profile_login"),
    path("logout/", profile_logout, name="profile_logout"),
    path("admin-dashboard/", admin_dashboard, name="admin_dashboard"),
    path("chat/", chat, name="chat"),
]
