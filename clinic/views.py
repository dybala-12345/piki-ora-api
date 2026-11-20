from datetime import datetime, timedelta

from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Q
from django.http import JsonResponse
from django.utils import timezone
from rest_framework import generics, permissions, status, viewsets
from rest_framework.authtoken.models import Token
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Appointment, AppointmentSlot, Doctor, Notification
from .permissions import IsAdmin, IsAdminOrReadOnly, IsOwnerOrAdmin
from .serializers import (AppointmentSerializer, AppointmentSlotSerializer,
                          BulkSlotSerializer, DoctorSerializer, NotificationSerializer,
                          PatientAdminSerializer, RegisterSerializer, UserSerializer)


def api_root(request):
    return JsonResponse({
        'name': 'Piki Ora Medical Centre API',
        'endpoints': ['/api/register/', '/api/login/', '/api/logout/', '/api/me/',
                      '/api/doctors/', '/api/slots/', '/api/appointments/',
                      '/api/notifications/', '/api/patients/', '/api/admin/stats/'],
    })


def notify(user, message):
    """Save an in-app notification and send a confirmation email (printed to the log)."""
    Notification.objects.create(user=user, message=message)
    if user.email:
        send_mail('Piki Ora Medical Centre', message, None, [user.email], fail_silently=True)


def describe(slot):
    return f'{slot.doctor} on {slot.date:%A %d %B %Y} at {slot.start_time:%I:%M %p}'


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
class RegisterView(generics.CreateAPIView):
    """POST /api/register/ - patient creates an account and is logged in straight away."""
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        token, _ = Token.objects.get_or_create(user=user)
        return Response({'token': token.key, 'user': UserSerializer(user).data},
                        status=status.HTTP_201_CREATED)


class LoginView(APIView):
    """POST /api/login/ {username, password} -> {token, user}"""
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        username = request.data.get('username', '')
        password = request.data.get('password', '')
        if not username or not password:
            return Response({'detail': 'Username and password are required.'},
                            status=status.HTTP_400_BAD_REQUEST)
        user = authenticate(username=username, password=password)
        if user is None:
            return Response({'detail': 'Invalid username or password.'},
                            status=status.HTTP_400_BAD_REQUEST)
        token, _ = Token.objects.get_or_create(user=user)
        return Response({'token': token.key, 'user': UserSerializer(user).data})


class LogoutView(APIView):
    """POST /api/logout/ - deletes the token so it can't be used again."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        Token.objects.filter(user=request.user).delete()
        return Response({'detail': 'Logged out.'})


class MeView(APIView):
    """GET /api/me/ - who is logged in (used by React to restore a session)."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)


# ---------------------------------------------------------------------------
# Doctors
# ---------------------------------------------------------------------------
class DoctorViewSet(viewsets.ModelViewSet):
    """Everyone can view doctors; only admins can add / edit / remove them."""
    serializer_class = DoctorSerializer
    permission_classes = [IsAdminOrReadOnly]

    def get_queryset(self):
        today = timezone.localdate()
        # count free future slots in the same query (avoids one query per doctor)
        qs = Doctor.objects.annotate(free_slots=Count(
            'slots', distinct=True,
            filter=Q(slots__date__gte=today) & ~Q(slots__appointments__status=Appointment.BOOKED)))
        # patients only see active doctors; admins see all
        if not self.request.user.is_staff:
            qs = qs.filter(is_active=True)
        search = self.request.query_params.get('search')
        if search:
            qs = qs.filter(Q(first_name__icontains=search) | Q(last_name__icontains=search) |
                           Q(specialisation__icontains=search))
        return qs


# ---------------------------------------------------------------------------
# Appointment slots
# ---------------------------------------------------------------------------
class AppointmentSlotViewSet(viewsets.ModelViewSet):
    """
    GET /api/slots/?doctor=1&date=2026-11-21&available=true
    Admins create / edit / delete slots. POST /api/slots/bulk/ makes many at once.
    """
    serializer_class = AppointmentSlotSerializer
    permission_classes = [IsAdminOrReadOnly]

    def get_queryset(self):
        # "booked" is worked out in the same SQL query (Exists subquery), so listing
        # 100+ slots is ONE database query instead of one query per slot
        active = Appointment.objects.filter(slot=OuterRef('pk'), status=Appointment.BOOKED)
        qs = AppointmentSlot.objects.select_related('doctor').annotate(booked=Exists(active))
        params = self.request.query_params
        if params.get('doctor'):
            qs = qs.filter(doctor_id=params['doctor'])
        if params.get('date'):
            qs = qs.filter(date=params['date'])
        if params.get('from'):
            qs = qs.filter(date__gte=params['from'])
        if params.get('to'):
            qs = qs.filter(date__lte=params['to'])
        if params.get('available') == 'true':
            now = timezone.localtime()
            qs = (qs.filter(doctor__is_active=True)
                    .exclude(appointments__status=Appointment.BOOKED)
                    .filter(Q(date__gt=now.date()) |
                            Q(date=now.date(), start_time__gt=now.time())))
        return qs

    def destroy(self, request, *args, **kwargs):
        slot = self.get_object()
        if slot.is_booked:
            return Response({'detail': 'This slot has a booking. Cancel the appointment first.'},
                            status=status.HTTP_400_BAD_REQUEST)
        return super().destroy(request, *args, **kwargs)

    @action(detail=False, methods=['post'], permission_classes=[IsAdmin])
    def bulk(self, request):
        """Generate slots for a doctor over a date range (e.g. Mon-Fri, 9am-5pm, 30 mins)."""
        s = BulkSlotSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        created, skipped = 0, 0
        day = d['start_date']
        length = timedelta(minutes=d['duration_minutes'])
        while day <= d['end_date']:
            if day.weekday() in d['weekdays']:
                start = datetime.combine(day, d['day_start'])
                last = datetime.combine(day, d['day_end'])
                while start + length <= last:
                    end = start + length
                    overlap = AppointmentSlot.objects.filter(
                        doctor=d['doctor'], date=day,
                        start_time__lt=end.time(), end_time__gt=start.time()).exists()
                    if overlap:
                        skipped += 1
                    else:
                        AppointmentSlot.objects.create(doctor=d['doctor'], date=day,
                                                       start_time=start.time(),
                                                       end_time=end.time())
                        created += 1
                    start = end
            day += timedelta(days=1)
        return Response({'created': created, 'skipped': skipped},
                        status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# Appointments
# ---------------------------------------------------------------------------
class AppointmentViewSet(viewsets.ModelViewSet):
    """
    Patients: see / book / edit / cancel THEIR OWN appointments.
    Admins:   see all bookings and edit / cancel any of them.
    GET /api/appointments/?upcoming=true  &status=booked  &doctor=1  &date=...
    """
    serializer_class = AppointmentSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrAdmin]

    def get_queryset(self):
        qs = Appointment.objects.select_related('patient', 'slot', 'slot__doctor')
        user = self.request.user
        if not user.is_staff:
            qs = qs.filter(patient=user)
        params = self.request.query_params
        if params.get('upcoming') == 'true':
            qs = qs.filter(slot__date__gte=timezone.localdate())
        if params.get('past') == 'true':
            qs = qs.filter(slot__date__lt=timezone.localdate())
        if params.get('status'):
            qs = qs.filter(status=params['status'])
        if params.get('doctor'):
            qs = qs.filter(slot__doctor_id=params['doctor'])
        if params.get('date'):
            qs = qs.filter(slot__date=params['date'])
        if params.get('patient') and user.is_staff:
            qs = qs.filter(patient_id=params['patient'])
        return qs

    def perform_create(self, serializer):
        user = self.request.user
        patient = user
        # An administrator may book on behalf of a patient by sending patient_id
        if user.is_staff and self.request.data.get('patient_id'):
            patient = User.objects.filter(pk=self.request.data['patient_id']).first()
            if patient is None:
                raise ValidationError({'patient_id': 'Patient not found.'})
        with transaction.atomic():
            # Lock the slot row so two simultaneous requests can't both book it
            slot = AppointmentSlot.objects.select_for_update().get(
                pk=serializer.validated_data['slot'].pk)
            if slot.appointments.filter(status=Appointment.BOOKED).exists():
                raise ValidationError({'slot': 'Sorry, this slot has already been booked.'})
            appointment = serializer.save(patient=patient)
        notify(patient, f'Your appointment with {describe(appointment.slot)} is confirmed. '
                        f'Booking reference #{appointment.id}.')

    def perform_update(self, serializer):
        old_slot = serializer.instance.slot
        old_status = serializer.instance.status
        with transaction.atomic():
            new_slot = serializer.validated_data.get('slot', old_slot)
            AppointmentSlot.objects.select_for_update().get(pk=new_slot.pk)
            appointment = serializer.save()
        if appointment.status == Appointment.CANCELLED and old_status != Appointment.CANCELLED:
            notify(appointment.patient,
                   f'Your appointment with {describe(appointment.slot)} has been cancelled.')
        elif appointment.slot_id != old_slot.id:
            notify(appointment.patient,
                   f'Your appointment has been moved to {describe(appointment.slot)}.')
        else:
            notify(appointment.patient,
                   f'Your appointment with {describe(appointment.slot)} has been updated.')

    def destroy(self, request, *args, **kwargs):
        # Patients cancel instead of deleting, so the clinic keeps a history
        if not request.user.is_staff:
            return Response({'detail': 'Use the cancel action instead.'},
                            status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """POST /api/appointments/{id}/cancel/"""
        appointment = self.get_object()
        if appointment.status != Appointment.BOOKED:
            return Response({'detail': 'Only booked appointments can be cancelled.'},
                            status=status.HTTP_400_BAD_REQUEST)
        appointment.status = Appointment.CANCELLED
        appointment.save()
        notify(appointment.patient,
               f'Your appointment with {describe(appointment.slot)} has been cancelled.')
        return Response(self.get_serializer(appointment).data)


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------
class NotificationViewSet(viewsets.ModelViewSet):
    """Logged-in user's own notifications. PATCH {is_read: true} to mark as read."""
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]
    http_method_names = ['get', 'patch', 'delete', 'post']

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user)

    def create(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    @action(detail=False, methods=['post'])
    def mark_all_read(self, request):
        self.get_queryset().update(is_read=True)
        return Response({'detail': 'All notifications marked as read.'})


# ---------------------------------------------------------------------------
# Administrator: patient accounts + dashboard stats
# ---------------------------------------------------------------------------
class PatientViewSet(viewsets.ModelViewSet):
    """Admin-only management of patient user accounts (non-staff users)."""
    serializer_class = PatientAdminSerializer
    permission_classes = [IsAdmin]

    def get_queryset(self):
        qs = User.objects.filter(is_staff=False).order_by('last_name', 'first_name', 'username')
        search = self.request.query_params.get('search')
        if search:
            qs = qs.filter(Q(username__icontains=search) | Q(email__icontains=search) |
                           Q(first_name__icontains=search) | Q(last_name__icontains=search))
        return qs


class AdminStatsView(APIView):
    """GET /api/admin/stats/ - numbers for the dashboard home page."""
    permission_classes = [IsAdmin]

    def get(self, request):
        today = timezone.localdate()
        booked = Appointment.objects.filter(status=Appointment.BOOKED)
        return Response({
            'doctors': Doctor.objects.filter(is_active=True).count(),
            'patients': User.objects.filter(is_staff=False).count(),
            'appointments_today': booked.filter(slot__date=today).count(),
            'upcoming_appointments': booked.filter(slot__date__gte=today).count(),
            'available_slots': AppointmentSlot.objects.filter(date__gte=today)
                                .exclude(appointments__status=Appointment.BOOKED).count(),
            'cancelled': Appointment.objects.filter(status=Appointment.CANCELLED).count(),
        })
