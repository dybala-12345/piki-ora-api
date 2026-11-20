from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    # Kept only for developer debugging - NOT the clinic's admin dashboard.
    # The administrator dashboard is built in the React app.
    path('django-admin/', admin.site.urls),
    path('', include('clinic.urls')),
]
