from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (AdminStatsView, AppointmentSlotViewSet, AppointmentViewSet,
                    DoctorViewSet, LoginView, LogoutView, MeView, NotificationViewSet,
                    PatientViewSet, RegisterView, api_root)

router = DefaultRouter()
router.register('doctors', DoctorViewSet, basename='doctors')
router.register('slots', AppointmentSlotViewSet, basename='slots')
router.register('appointments', AppointmentViewSet, basename='appointments')
router.register('notifications', NotificationViewSet, basename='notifications')
router.register('patients', PatientViewSet, basename='patients')

urlpatterns = [
    path('', api_root),
    path('api/register/', RegisterView.as_view()),
    path('api/login/', LoginView.as_view()),
    path('api/logout/', LogoutView.as_view()),
    path('api/me/', MeView.as_view()),
    path('api/admin/stats/', AdminStatsView.as_view()),
    path('api/', include(router.urls)),
]
