from django.db import IntegrityError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler


def custom_exception_handler(exc, context):
    """
    Return clean JSON errors instead of HTML error pages.
    IntegrityError happens if two people book the same slot at the same moment -
    the database constraint stops the second one and we return a friendly 409.
    """
    response = exception_handler(exc, context)
    if response is not None:
        return response

    if isinstance(exc, IntegrityError):
        return Response({'detail': 'That slot was just booked by someone else. '
                                   'Please choose another time.'},
                        status=status.HTTP_409_CONFLICT)
    return None
