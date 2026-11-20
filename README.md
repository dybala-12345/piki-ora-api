# Piki Ora Medical Centre – REST API

Django REST Framework back end for the Piki Ora Medical Centre appointment system
(ISCG7420 Assignment 2). The React front end lives in a separate repository
(`piki-ora-frontend`) and talks to this API with axios.

## Tech stack

- Django 5 + Django REST Framework (serializers, viewsets, routers)
- Token authentication (`rest_framework.authtoken`)
- PostgreSQL on Neon (via `DATABASE_URL`), SQLite fallback for local development
- `django-cors-headers` so the React site can call the API
- Gunicorn + WhiteNoise on Render

## Project structure

```
clinic_api/                 project settings and root URLs
clinic/
  models.py                 Doctor, AppointmentSlot, Appointment, Notification
  serializers.py            JSON <-> model conversion and validation
  views.py                  API views and viewsets
  permissions.py            IsAdminOrReadOnly, IsAdmin, IsOwnerOrAdmin
  urls.py                   router and auth endpoints
  exceptions.py             clean JSON errors (e.g. booking race condition -> 409)
  tests.py                  automated API tests
  management/commands/seed.py   creates the admin, doctors and slots
build.sh                    Render build script
```

## Roles

| Role | How | Can do |
|------|-----|--------|
| Patient | registers through `/api/register/` | view doctors and slots, book, view, edit and cancel **own** appointments, read notifications |
| Administrator | `is_staff = True` (created by `python manage.py seed`) | everything above for all patients, plus manage doctors, slots and patient accounts, and view dashboard stats |

## API endpoints

| Method | Endpoint | Who | Purpose |
|--------|----------|-----|---------|
| POST | `/api/register/` | anyone | create patient account → token |
| POST | `/api/login/` | anyone | `{username, password}` → `{token, user}` |
| POST | `/api/logout/` | logged in | delete token |
| GET | `/api/me/` | logged in | current user |
| GET | `/api/doctors/` `?search=` | anyone | list doctors |
| POST/PUT/PATCH/DELETE | `/api/doctors/{id}/` | admin | manage doctors |
| GET | `/api/slots/?doctor=&date=&from=&to=&available=true` | anyone | doctor schedules |
| POST/PUT/PATCH/DELETE | `/api/slots/{id}/` | admin | manage slots |
| POST | `/api/slots/bulk/` | admin | generate many slots at once |
| GET | `/api/appointments/?upcoming=true&status=&doctor=&date=` | logged in | own (patient) / all (admin) |
| POST | `/api/appointments/` | logged in | book `{slot, reason}` (admin may add `patient_id`) |
| PATCH | `/api/appointments/{id}/` | owner / admin | edit reason or move to another slot |
| POST | `/api/appointments/{id}/cancel/` | owner / admin | cancel |
| DELETE | `/api/appointments/{id}/` | admin | delete |
| GET | `/api/notifications/` | logged in | booking confirmations |
| POST | `/api/notifications/mark_all_read/` | logged in | mark all read |
| CRUD | `/api/patients/` | admin | manage patient accounts |
| GET | `/api/admin/stats/` | admin | dashboard numbers |

Send the token in the header for protected requests: `Authorization: Token <token>`.

## How double booking is prevented

1. **Serializer validation**: `validate_slot()` rejects a slot that already has an active booking.
2. **Row locking**: `perform_create()` locks the slot row (`select_for_update`) inside a transaction, so two requests at the same moment can't both pass the check.
3. **Database constraint**: `UniqueConstraint(fields=['slot'], condition=Q(status='booked'))` means the database itself refuses a second active booking for one slot. A cancelled booking doesn't count, so the slot can be booked again.

## Run locally

```bash
python -m venv venv
# Windows: venv\Scripts\activate   (if blocked: Set-ExecutionPolicy Unrestricted -Scope CurrentUser)
# Mac/Linux: source venv/bin/activate
pip install -r requirements.txt
copy .env.example .env        # Mac/Linux: cp .env.example .env  - then edit the values
python manage.py migrate
python manage.py seed         # admin user, demo patient, 4 doctors, 2 weeks of slots
python manage.py runserver
python manage.py test         # run the automated tests
```

Default accounts created by `seed`:
- Administrator: the `ADMIN_USERNAME` / `ADMIN_PASSWORD` set in `.env`
- Demo patient: `patient1` / `Patient2026!`

## Deploy on Render

- **Build command:** `bash build.sh`
- **Start command:** `gunicorn clinic_api.wsgi`
- **Environment variables:** `SECRET_KEY`, `DEBUG=False`, `DATABASE_URL`, `CORS_ALLOWED_ORIGINS`
  (your React Render URL), `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `ADMIN_EMAIL`, `PYTHON_VERSION=3.12.8`

The Postman collection is in `postman/`.
