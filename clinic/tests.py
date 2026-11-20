from datetime import time, timedelta

from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.test import APITestCase

from .models import Appointment, AppointmentSlot, Doctor, Notification


class ClinicAPITests(APITestCase):
    """Run with: python manage.py test"""

    def setUp(self):
        self.client.default_format = 'json'  # send JSON like the React app does
        self.admin = User.objects.create_user('admin', password='AdminPass123!', is_staff=True)
        self.alice = User.objects.create_user('alice', password='AlicePass123!')
        self.bob = User.objects.create_user('bob', password='BobPass123!')
        self.doctor = Doctor.objects.create(first_name='Aroha', last_name='Ngata')
        tomorrow = timezone.localdate() + timedelta(days=1)
        self.slot = AppointmentSlot.objects.create(doctor=self.doctor, date=tomorrow,
                                                   start_time=time(9), end_time=time(9, 30))

    def login(self, username, password):
        res = self.client.post('/api/login/', {'username': username, 'password': password})
        self.assertEqual(res.status_code, 200)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + res.data['token'])
        return res

    def test_register_returns_token(self):
        res = self.client.post('/api/register/', {
            'username': 'newpatient', 'password': 'Str0ngPass!99', 'email': 'n@example.com',
            'first_name': 'New', 'last_name': 'Patient'})
        self.assertEqual(res.status_code, 201)
        self.assertIn('token', res.data)
        self.assertFalse(res.data['user']['is_admin'])

    def test_anyone_can_view_doctors_and_slots(self):
        self.assertEqual(self.client.get('/api/doctors/').status_code, 200)
        res = self.client.get(f'/api/slots/?doctor={self.doctor.id}&available=true')
        self.assertEqual(len(res.data), 1)

    def test_booking_requires_login(self):
        res = self.client.post('/api/appointments/', {'slot': self.slot.id})
        self.assertEqual(res.status_code, 401)

    def test_book_creates_notification(self):
        self.login('alice', 'AlicePass123!')
        res = self.client.post('/api/appointments/', {'slot': self.slot.id, 'reason': 'Checkup'})
        self.assertEqual(res.status_code, 201)
        self.assertEqual(Notification.objects.filter(user=self.alice).count(), 1)

    def test_double_booking_is_prevented(self):
        self.login('alice', 'AlicePass123!')
        self.client.post('/api/appointments/', {'slot': self.slot.id})
        self.login('bob', 'BobPass123!')
        res = self.client.post('/api/appointments/', {'slot': self.slot.id})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(Appointment.objects.filter(slot=self.slot).count(), 1)

    def test_slot_can_be_rebooked_after_cancel(self):
        self.login('alice', 'AlicePass123!')
        appt = self.client.post('/api/appointments/', {'slot': self.slot.id}).data
        self.client.post(f"/api/appointments/{appt['id']}/cancel/")
        self.login('bob', 'BobPass123!')
        res = self.client.post('/api/appointments/', {'slot': self.slot.id})
        self.assertEqual(res.status_code, 201)

    def test_patient_cannot_see_others_appointments(self):
        Appointment.objects.create(patient=self.alice, slot=self.slot)
        self.login('bob', 'BobPass123!')
        self.assertEqual(len(self.client.get('/api/appointments/').data), 0)

    def test_patient_cannot_manage_doctors_or_patients(self):
        self.login('alice', 'AlicePass123!')
        self.assertEqual(self.client.post('/api/doctors/', {'first_name': 'X',
                                                            'last_name': 'Y'}).status_code, 403)
        self.assertEqual(self.client.get('/api/patients/').status_code, 403)

    def test_admin_can_manage_everything(self):
        self.login('admin', 'AdminPass123!')
        self.assertEqual(self.client.post('/api/doctors/', {'first_name': 'New',
                                                            'last_name': 'Doc'}).status_code, 201)
        res = self.client.post('/api/slots/bulk/', {
            'doctor': self.doctor.id, 'start_date': str(self.slot.date),
            'end_date': str(self.slot.date), 'day_start': '13:00', 'day_end': '15:00',
            'duration_minutes': 30, 'weekdays': [0, 1, 2, 3, 4, 5, 6]}, format='json')
        self.assertEqual(res.data['created'], 4)
        self.assertEqual(self.client.get('/api/patients/').status_code, 200)
        self.assertEqual(self.client.get('/api/admin/stats/').status_code, 200)

    def test_reschedule_appointment(self):
        other = AppointmentSlot.objects.create(doctor=self.doctor, date=self.slot.date,
                                               start_time=time(10), end_time=time(10, 30))
        self.login('alice', 'AlicePass123!')
        appt = self.client.post('/api/appointments/', {'slot': self.slot.id}).data
        res = self.client.patch(f"/api/appointments/{appt['id']}/", {'slot': other.id})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['slot'], other.id)
