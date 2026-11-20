from datetime import datetime

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Doctor(models.Model):
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    specialisation = models.CharField(max_length=150, default='General Practitioner')
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    bio = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['last_name', 'first_name']

    def __str__(self):
        return f'Dr {self.first_name} {self.last_name}'


class AppointmentSlot(models.Model):
    """A time a doctor is available for one consultation."""
    doctor = models.ForeignKey(Doctor, on_delete=models.CASCADE, related_name='slots')
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()

    class Meta:
        ordering = ['date', 'start_time']
        constraints = [
            # a doctor cannot have the same slot twice
            models.UniqueConstraint(fields=['doctor', 'date', 'start_time'],
                                    name='unique_doctor_slot'),
        ]

    def __str__(self):
        return f'{self.doctor} - {self.date} {self.start_time:%H:%M}'

    @property
    def is_booked(self):
        return self.appointments.filter(status=Appointment.BOOKED).exists()

    @property
    def is_past(self):
        start = timezone.make_aware(datetime.combine(self.date, self.start_time))
        return start < timezone.now()


class Appointment(models.Model):
    BOOKED = 'booked'
    CANCELLED = 'cancelled'
    COMPLETED = 'completed'
    STATUS_CHOICES = [
        (BOOKED, 'Booked'),
        (CANCELLED, 'Cancelled'),
        (COMPLETED, 'Completed'),
    ]

    patient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name='appointments')
    slot = models.ForeignKey(AppointmentSlot, on_delete=models.CASCADE,
                             related_name='appointments')
    reason = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=BOOKED)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['slot__date', 'slot__start_time']
        constraints = [
            # DATABASE-LEVEL double booking protection:
            # only ONE active ("booked") appointment may exist per slot.
            # Cancelled appointments don't count, so the slot can be re-booked.
            models.UniqueConstraint(fields=['slot'], condition=Q(status='booked'),
                                    name='one_active_booking_per_slot'),
        ]

    def __str__(self):
        return f'{self.patient.username} - {self.slot}'


class Notification(models.Model):
    """In-app confirmation messages shown to the patient."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name='notifications')
    message = models.CharField(max_length=500)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user.username}: {self.message[:40]}'
