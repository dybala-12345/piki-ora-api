"""
python manage.py seed

Creates the default administrator (from ADMIN_USERNAME / ADMIN_PASSWORD / ADMIN_EMAIL
environment variables), a demo patient, some doctors and two weeks of appointment
slots. Safe to run many times - it never creates duplicates. Render runs this on
every deploy (see build.sh) because the free plan has no shell access.
"""
import os
from datetime import datetime, time, timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

from clinic.models import AppointmentSlot, Doctor

DOCTORS = [
    ('Aroha', 'Ngata', 'General Practitioner',
     'Experienced GP with a special interest in whānau health.'),
    ('James', 'Chen', 'General Practitioner',
     'Focuses on chronic illness management and preventive care.'),
    ('Priya', 'Sharma', 'Paediatrics',
     'Cares for babies, children and teenagers.'),
    ('Sione', 'Tupou', "Women's Health",
     'Provides cervical screening, contraception and antenatal care.'),
]


class Command(BaseCommand):
    help = 'Create the default admin, a demo patient, doctors and appointment slots.'

    def handle(self, *args, **options):
        self.create_admin()
        self.create_demo_patient()
        self.create_doctors()
        self.create_slots()
        self.stdout.write(self.style.SUCCESS('Seeding finished.'))

    def create_admin(self):
        username = os.environ.get('ADMIN_USERNAME', 'admin')
        password = os.environ.get('ADMIN_PASSWORD', 'PikiOraAdmin2026!')
        email = os.environ.get('ADMIN_EMAIL', 'admin@pikiora.co.nz')
        user, created = User.objects.get_or_create(
            username=username,
            defaults={'email': email, 'first_name': 'Clinic', 'last_name': 'Administrator'})
        user.is_staff = True
        user.is_superuser = True
        if created:
            user.set_password(password)
        user.save()
        self.stdout.write(f"Admin user '{username}' {'created' if created else 'already exists'}.")

    def create_demo_patient(self):
        user, created = User.objects.get_or_create(
            username='patient1',
            defaults={'email': 'patient1@example.com', 'first_name': 'Mere',
                      'last_name': 'Wilson'})
        if created:
            user.set_password('Patient2026!')
            user.save()
            self.stdout.write("Demo patient 'patient1' created.")

    def create_doctors(self):
        for first, last, spec, bio in DOCTORS:
            Doctor.objects.get_or_create(
                first_name=first, last_name=last,
                defaults={'specialisation': spec, 'bio': bio,
                          'email': f'{first.lower()}.{last.lower()}@pikiora.co.nz',
                          'phone': '09 555 0100'})

    def create_slots(self):
        """Weekdays for the next 14 days, 9am-12pm and 1pm-5pm, 30 minute slots."""
        today = timezone.localdate()
        sessions = [(time(9, 0), time(12, 0)), (time(13, 0), time(17, 0))]
        total = 0
        for doctor in Doctor.objects.filter(is_active=True):
            if doctor.slots.filter(date__gte=today).exists():
                continue  # this doctor already has future slots
            new_slots = []
            for offset in range(1, 15):
                day = today + timedelta(days=offset)
                if day.weekday() >= 5:  # skip weekends
                    continue
                for start, end in sessions:
                    current = datetime.combine(day, start)
                    while current.time() < end:
                        nxt = current + timedelta(minutes=30)
                        new_slots.append(AppointmentSlot(doctor=doctor, date=day,
                                                         start_time=current.time(),
                                                         end_time=nxt.time()))
                        current = nxt
            AppointmentSlot.objects.bulk_create(new_slots)
            total += len(new_slots)
        self.stdout.write(f'{total} appointment slots created.')
