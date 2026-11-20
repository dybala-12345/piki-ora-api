# The Django admin is NOT used as the clinic's administrator dashboard
# (that is built in React). Models are registered only for developer debugging.
from django.contrib import admin

from .models import Appointment, AppointmentSlot, Doctor, Notification

admin.site.register([Doctor, AppointmentSlot, Appointment, Notification])
