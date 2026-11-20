from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone
from rest_framework import serializers

from .models import Appointment, AppointmentSlot, Doctor, Notification


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
class UserSerializer(serializers.ModelSerializer):
    """Basic user info returned after login and from /api/me/."""
    is_admin = serializers.BooleanField(source='is_staff', read_only=True)

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'is_admin']


class RegisterSerializer(serializers.ModelSerializer):
    """Patient self-registration."""
    password = serializers.CharField(write_only=True, validators=[validate_password])

    class Meta:
        model = User
        fields = ['id', 'username', 'password', 'email', 'first_name', 'last_name']
        extra_kwargs = {
            'email': {'required': True},
            'first_name': {'required': True},
            'last_name': {'required': True},
        }

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError('An account with this email already exists.')
        return value

    def create(self, validated_data):
        # create_user hashes the password; patients are never staff
        return User.objects.create_user(**validated_data)


class PatientAdminSerializer(serializers.ModelSerializer):
    """Used by administrators to manage patient accounts."""
    password = serializers.CharField(write_only=True, required=False,
                                     validators=[validate_password])
    appointment_count = serializers.IntegerField(source='appointments.count', read_only=True)

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'is_active',
                  'date_joined', 'appointment_count', 'password']
        read_only_fields = ['date_joined']

    def create(self, validated_data):
        password = validated_data.pop('password', None)
        if not password:
            raise serializers.ValidationError({'password': 'A password is required.'})
        return User.objects.create_user(password=password, **validated_data)

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        instance = super().update(instance, validated_data)
        if password:
            instance.set_password(password)
            instance.save()
        return instance


# ---------------------------------------------------------------------------
# Doctors and slots
# ---------------------------------------------------------------------------
class DoctorSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    upcoming_available_slots = serializers.SerializerMethodField()

    class Meta:
        model = Doctor
        fields = ['id', 'first_name', 'last_name', 'full_name', 'specialisation', 'email',
                  'phone', 'bio', 'is_active', 'upcoming_available_slots']

    def get_full_name(self, obj):
        return str(obj)

    def get_upcoming_available_slots(self, obj):
        if hasattr(obj, 'free_slots'):        # pre-calculated by the viewset query
            return obj.free_slots
        today = timezone.localdate()
        return obj.slots.filter(date__gte=today).exclude(
            appointments__status=Appointment.BOOKED).count()


class AppointmentSlotSerializer(serializers.ModelSerializer):
    doctor_name = serializers.CharField(source='doctor.__str__', read_only=True)
    is_booked = serializers.SerializerMethodField()
    is_past = serializers.BooleanField(read_only=True)

    class Meta:
        model = AppointmentSlot
        fields = ['id', 'doctor', 'doctor_name', 'date', 'start_time', 'end_time',
                  'is_booked', 'is_past']

    def get_is_booked(self, obj):
        # use the value calculated in the list query if it's there
        return obj.booked if hasattr(obj, 'booked') else obj.is_booked

    def validate(self, attrs):
        start = attrs.get('start_time', getattr(self.instance, 'start_time', None))
        end = attrs.get('end_time', getattr(self.instance, 'end_time', None))
        if start and end and end <= start:
            raise serializers.ValidationError({'end_time': 'End time must be after start time.'})

        doctor = attrs.get('doctor', getattr(self.instance, 'doctor', None))
        date = attrs.get('date', getattr(self.instance, 'date', None))
        clash = AppointmentSlot.objects.filter(doctor=doctor, date=date,
                                               start_time__lt=end, end_time__gt=start)
        if self.instance:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError('This slot overlaps another slot for this doctor.')
        return attrs


class BulkSlotSerializer(serializers.Serializer):
    """Admin helper: create many slots for a doctor in one request."""
    doctor = serializers.PrimaryKeyRelatedField(queryset=Doctor.objects.all())
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    day_start = serializers.TimeField()
    day_end = serializers.TimeField()
    duration_minutes = serializers.IntegerField(min_value=5, max_value=240)
    weekdays = serializers.ListField(child=serializers.IntegerField(min_value=0, max_value=6),
                                     help_text='0=Monday ... 6=Sunday')

    def validate(self, attrs):
        if attrs['end_date'] < attrs['start_date']:
            raise serializers.ValidationError('End date must be on or after start date.')
        if (attrs['end_date'] - attrs['start_date']).days > 90:
            raise serializers.ValidationError('You can generate at most 90 days at once.')
        if attrs['day_end'] <= attrs['day_start']:
            raise serializers.ValidationError('Day end must be after day start.')
        return attrs


# ---------------------------------------------------------------------------
# Appointments
# ---------------------------------------------------------------------------
class AppointmentSerializer(serializers.ModelSerializer):
    patient_name = serializers.SerializerMethodField()
    patient_username = serializers.CharField(source='patient.username', read_only=True)
    doctor_id = serializers.IntegerField(source='slot.doctor.id', read_only=True)
    doctor_name = serializers.CharField(source='slot.doctor.__str__', read_only=True)
    date = serializers.DateField(source='slot.date', read_only=True)
    start_time = serializers.TimeField(source='slot.start_time', read_only=True)
    end_time = serializers.TimeField(source='slot.end_time', read_only=True)

    class Meta:
        model = Appointment
        fields = ['id', 'patient', 'patient_name', 'patient_username', 'slot', 'doctor_id',
                  'doctor_name', 'date', 'start_time', 'end_time', 'reason', 'status',
                  'created_at', 'updated_at']
        # patient is set from the logged-in user (or by admin), never trusted from patients
        read_only_fields = ['patient', 'created_at', 'updated_at']

    def get_patient_name(self, obj):
        return obj.patient.get_full_name() or obj.patient.username

    def validate_slot(self, slot):
        if slot.is_past:
            raise serializers.ValidationError('You cannot book a slot in the past.')
        if not slot.doctor.is_active:
            raise serializers.ValidationError('This doctor is not currently taking bookings.')
        # The slot is taken if another ACTIVE appointment uses it
        taken = slot.appointments.filter(status=Appointment.BOOKED)
        if self.instance:
            taken = taken.exclude(pk=self.instance.pk)
        if taken.exists():
            raise serializers.ValidationError('Sorry, this slot has already been booked.')
        return slot

    def validate_status(self, value):
        request = self.context.get('request')
        # Patients may only cancel; admins may set any status
        if request and not request.user.is_staff and value not in (Appointment.BOOKED,
                                                                    Appointment.CANCELLED):
            raise serializers.ValidationError('You can only cancel your appointment.')
        return value

    def validate(self, attrs):
        # Re-activating a cancelled appointment must not steal a slot someone else booked
        if self.instance and attrs.get('status') == Appointment.BOOKED \
                and self.instance.status != Appointment.BOOKED and 'slot' not in attrs:
            self.validate_slot(self.instance.slot)
        return attrs


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ['id', 'message', 'is_read', 'created_at']
        read_only_fields = ['message', 'created_at']
