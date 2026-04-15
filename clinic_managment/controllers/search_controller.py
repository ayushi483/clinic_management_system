import base64
from odoo import http, fields
from odoo.http import request, Response
from .base_controller import BaseAPIController
import logging
import json
from datetime import datetime

_logger = logging.getLogger(__name__)


class AppointmentAPI(BaseAPIController):

    @http.route('/api/v19/appointments/search', type='http', auth='none', methods=['GET'], csrf=False)
    def search_appointments(self, **kwargs):
        """
        Search appointments with multiple filters
        Query parameters:
            - appointment_id (optional): Filter by specific appointment ID
            - doctor_id (optional): Filter by doctor ID
            - speciality_id (optional): Filter by doctor's speciality ID
            - patient_id (optional): Filter by patient ID
            - status (optional): Filter by status (draft, confirmed, done, cancel, no_show)
            - from_date (optional): Filter appointments from this date (YYYY-MM-DD)
            - to_date (optional): Filter appointments until this date (YYYY-MM-DD)
            - limit (optional): Limit number of results (default: 100)
            - offset (optional): Pagination offset (default: 0)
        """
        try:
            # ── Step 1: Validate API Key ──
            user = self._validate_api_key()
            if isinstance(user, Response):
                return user
            if not hasattr(user, 'id'):
                return user

            # ── Step 2: Build Search Domain ──
            domain = []

            # Filter by appointment_id (exact match)
            appointment_id = kwargs.get('appointment_id')
            if appointment_id:
                try:
                    appointment_id = int(appointment_id)
                    domain.append(('id', '=', appointment_id))
                except (ValueError, TypeError):
                    return self._error_response(
                        "appointment_id must be a valid integer",
                        "INVALID_APPOINTMENT_ID",
                        400
                    )

            # Filter by doctor_id
            doctor_id = kwargs.get('doctor_id')
            if doctor_id:
                try:
                    doctor_id = int(doctor_id)
                    domain.append(('doctor_id', '=', doctor_id))
                except (ValueError, TypeError):
                    return self._error_response(
                        "doctor_id must be a valid integer",
                        "INVALID_DOCTOR_ID",
                        400
                    )

            # Filter by speciality_id (through doctor's speciality)
            speciality_id = kwargs.get('speciality_id')
            if speciality_id:
                try:
                    speciality_id = int(speciality_id)
                    domain.append(('doctor_speciality', '=', speciality_id))
                except (ValueError, TypeError):
                    return self._error_response(
                        "speciality_id must be a valid integer",
                        "INVALID_SPECIALITY_ID",
                        400
                    )

            # Filter by patient_id
            patient_id = kwargs.get('patient_id')
            if patient_id:
                try:
                    patient_id = int(patient_id)
                    domain.append(('patient_id', '=', patient_id))
                except (ValueError, TypeError):
                    return self._error_response(
                        "patient_id must be a valid integer",
                        "INVALID_PATIENT_ID",
                        400
                    )

            # Filter by status
            status = kwargs.get('status')
            if status:
                valid_statuses = ['draft', 'confirmed', 'done', 'cancel', 'no_show']
                if status not in valid_statuses:
                    return self._error_response(
                        f"Invalid status. Must be one of: {', '.join(valid_statuses)}",
                        "INVALID_STATUS",
                        400
                    )
                domain.append(('status', '=', status))

            # Filter by date range
            from_date = kwargs.get('from_date')
            if from_date:
                try:
                    from_datetime = fields.Datetime.from_string(f"{from_date} 00:00:00")
                    domain.append(('appointment_datetime', '>=', from_datetime))
                except Exception:
                    return self._error_response(
                        "Invalid from_date format. Use YYYY-MM-DD",
                        "INVALID_FROM_DATE",
                        400
                    )

            to_date = kwargs.get('to_date')
            if to_date:
                try:
                    to_datetime = fields.Datetime.from_string(f"{to_date} 23:59:59")
                    domain.append(('appointment_datetime', '<=', to_datetime))
                except Exception:
                    return self._error_response(
                        "Invalid to_date format. Use YYYY-MM-DD",
                        "INVALID_TO_DATE",
                        400
                    )

            # ── Step 3: Pagination Parameters ──
            try:
                limit = int(kwargs.get('limit', 100))
                offset = int(kwargs.get('offset', 0))
                if limit > 500:
                    limit = 500
            except (ValueError, TypeError):
                limit = 100
                offset = 0

            # ── Step 4: Search Appointments ──
            appointments = request.env["clinic.appointment"].sudo().search(
                domain,
                order='appointment_datetime desc',
                limit=limit,
                offset=offset
            )

            total_count = request.env["clinic.appointment"].sudo().search_count(domain)

            # ── Step 5: Format Results ──
            result = []
            for appt in appointments:
                doctor_speciality = None
                doctor_speciality_id = None
                if appt.doctor_speciality:
                    doctor_speciality = appt.doctor_speciality.name
                    doctor_speciality_id = appt.doctor_speciality.id
                elif appt.doctor_id and appt.doctor_id.speciality_id:
                    doctor_speciality = appt.doctor_id.speciality_id.name
                    doctor_speciality_id = appt.doctor_id.speciality_id.id

                result.append({
                    "appointment_id": appt.id,
                    "appointment_code": appt.appointment_code or '',
                    "appointment_datetime": str(appt.appointment_datetime) if appt.appointment_datetime else None,
                    "status": appt.status or '',
                    "notes": appt.notes or '',
                    "created_date": str(appt.create_date) if appt.create_date else None,
                    "doctor_id": appt.doctor_id.id if appt.doctor_id else None,
                    "doctor_name": appt.doctor_id.name if appt.doctor_id else '',
                    "doctor_phone": appt.doctor_phone or '',
                    "doctor_email": appt.doctor_email or '',
                    "doctor_fees": appt.doctor_fees or 0,
                    "doctor_speciality": doctor_speciality,
                    "doctor_speciality_id": doctor_speciality_id,
                    "patient_id": appt.patient_id.id if appt.patient_id else None,
                    "patient_name": appt.patient_id.name if appt.patient_id else '',
                    "patient_code": appt.patient_id.patient_code if appt.patient_id else '',
                    "patient_phone": appt.patient_phone or '',
                    "patient_email": appt.patient_email or '',
                    "patient_gender": appt.patient_gender or '',
                })

            return self._json_response(
                self._success_response({
                    "total": total_count,
                    "limit": limit,
                    "offset": offset,
                    "filters_applied": {
                        "appointment_id": appointment_id if appointment_id else None,
                        "doctor_id": doctor_id if doctor_id else None,
                        "speciality_id": speciality_id if speciality_id else None,
                        "patient_id": patient_id if patient_id else None,
                        "status": status if status else None,
                        "from_date": from_date if from_date else None,
                        "to_date": to_date if to_date else None,
                    },
                    "appointments": result
                }),
                200
            )

        except Exception as e:
            _logger.exception("Error searching appointments")
            return self._error_response(str(e), "INTERNAL_SERVER_ERROR", 500)

    @http.route('/api/v19/doctors/search', type='http', auth='none', methods=['GET'], csrf=False)
    def search_doctors(self, **kwargs):
        """
        Search doctors by name or specialty from clinic.doctor model
        Query parameters:
            - name (optional): Search by doctor name (partial match)
            - speciality_id (optional): Filter by speciality ID
            - limit (optional): Limit number of results (default: 50)
            - offset (optional): Pagination offset (default: 0)
        """
        try:
            # Validate API Key
            user = self._validate_api_key()
            if isinstance(user, Response):
                return user
            if not hasattr(user, 'id'):
                return user

            # Get search parameters
            name = kwargs.get('name', '').strip()
            speciality_id = kwargs.get('speciality_id')

            if not name and not speciality_id:
                return self._error_response(
                    "Please provide either 'name' or 'speciality_id' parameter",
                    "MISSING_PARAMETER",
                    400
                )

            # Build search domain for clinic.doctor model
            domain = [('active', '=', True)]  # Only active doctors

            # Search by name
            if name:
                domain.append(('name', 'ilike', name))

            # Search by speciality_id
            if speciality_id:
                try:
                    speciality_id = int(speciality_id)
                    domain.append(('speciality_id', '=', speciality_id))
                except (ValueError, TypeError):
                    return self._error_response(
                        "speciality_id must be a valid integer",
                        "INVALID_SPECIALITY_ID",
                        400
                    )

            # Pagination
            try:
                limit = int(kwargs.get('limit', 50))
                offset = int(kwargs.get('offset', 0))
                if limit > 200:
                    limit = 200
            except (ValueError, TypeError):
                limit = 50
                offset = 0

            _logger.info(f"Searching doctors with domain: {domain}, limit: {limit}, offset: {offset}")

            # Search using clinic.doctor model
            doctors = request.env['clinic.doctor'].sudo().search(
                domain,
                limit=limit,
                offset=offset
            )

            total_count = request.env['clinic.doctor'].sudo().search_count(domain)

            # Format results
            result = []
            for doctor in doctors:
                # Get image as base64 if exists
                image_base64 = None
                if doctor.image_1024:
                    try:
                        image_base64 = base64.b64encode(doctor.image_1024).decode('utf-8')
                    except Exception as e:
                        _logger.warning(f"Could not encode image for doctor {doctor.id}: {e}")

                result.append({
                    "id": doctor.id,
                    "name": doctor.name,
                    "speciality_id": doctor.speciality_id.id if doctor.speciality_id else None,
                    "speciality_name": doctor.speciality_id.name if doctor.speciality_id else None,
                    "phone": doctor.phone or '',
                    "email": doctor.email or '',
                    "fees": doctor.fees or 0,
                    "image": image_base64,
                    "is_available": doctor.is_available or False,
                    "total_appointment": doctor.total_appointment or 0,
                })

            return self._json_response(
                self._success_response({
                    "total": total_count,
                    "limit": limit,
                    "offset": offset,
                    "doctors": result
                }),
                200
            )

        except Exception as e:
            _logger.exception(f"Error searching doctors: {str(e)}")
            return self._error_response(str(e), "INTERNAL_SERVER_ERROR", 500)

    @http.route('/api/v19/doctors/<int:doctor_id>', type='http', auth='none', methods=['GET'], csrf=False)
    def get_doctor_details(self, doctor_id, **kwargs):
        """
        Get detailed information about a specific doctor
        URL: /api/v19/doctors/1
        """
        try:
            # Validate API Key
            user = self._validate_api_key()
            if isinstance(user, Response):
                return user
            if not hasattr(user, 'id'):
                return user

            # Find the doctor
            doctor = request.env['clinic.doctor'].sudo().browse(doctor_id)

            if not doctor.exists():
                return self._error_response(
                    "Doctor not found",
                    "DOCTOR_NOT_FOUND",
                    404
                )

            # Get availability lines
            availability = []
            for line in doctor.availability_ids:
                availability.append({
                    "id": line.id,
                    "day": line.day,
                    "start_time": line.start_time,
                    "end_time": line.end_time,
                })

            # Get image
            image_base64 = None
            if doctor.image_1024:
                try:
                    image_base64 = base64.b64encode(doctor.image_1024).decode('utf-8')
                except Exception as e:
                    _logger.warning(f"Could not encode image for doctor {doctor.id}: {e}")

            result = {
                "id": doctor.id,
                "name": doctor.name,
                "phone": doctor.phone or '',
                "email": doctor.email or '',
                "fees": doctor.fees or 0,
                "is_available": doctor.is_available or False,
                "total_appointment": doctor.total_appointment or 0,
                "active": doctor.active or False,
                "speciality_id": doctor.speciality_id.id if doctor.speciality_id else None,
                "speciality_name": doctor.speciality_id.name if doctor.speciality_id else None,
                "image": image_base64,
                "availability": availability,
            }

            return self._json_response(
                self._success_response(result),
                200
            )

        except Exception as e:
            _logger.exception(f"Error getting doctor details: {str(e)}")
            return self._error_response(str(e), "INTERNAL_SERVER_ERROR", 500)

    @http.route('/api/v19/doctors/speciality/<int:speciality_id>', type='http', auth='none', methods=['GET'],
                csrf=False)
    def get_doctors_by_speciality(self, speciality_id, **kwargs):
        """
        Get all doctors for a specific speciality
        URL: /api/v19/doctors/speciality/1
        """
        try:
            # Validate API Key
            user = self._validate_api_key()
            if isinstance(user, Response):
                return user
            if not hasattr(user, 'id'):
                return user

            # Pagination
            try:
                limit = int(kwargs.get('limit', 50))
                offset = int(kwargs.get('offset', 0))
            except (ValueError, TypeError):
                limit = 50
                offset = 0

            # Search doctors by speciality
            domain = [
                ('speciality_id', '=', speciality_id),
                ('active', '=', True)
            ]

            doctors = request.env['clinic.doctor'].sudo().search(
                domain,
                limit=limit,
                offset=offset
            )

            total_count = request.env['clinic.doctor'].sudo().search_count(domain)

            # Format results
            result = []
            for doctor in doctors:
                image_base64 = None
                if doctor.image_1024:
                    try:
                        image_base64 = base64.b64encode(doctor.image_1024).decode('utf-8')
                    except:
                        pass

                result.append({
                    "id": doctor.id,
                    "name": doctor.name,
                    "phone": doctor.phone or '',
                    "email": doctor.email or '',
                    "fees": doctor.fees or 0,
                    "is_available": doctor.is_available or False,
                    "image": image_base64,
                })

            return self._json_response(
                self._success_response({
                    "total": total_count,
                    "doctors": result
                }),
                200
            )

        except Exception as e:
            _logger.exception(f"Error getting doctors by speciality: {str(e)}")
            return self._error_response(str(e), "INTERNAL_SERVER_ERROR", 500)

    @http.route('/api/v19/appointments/search_by_code', type='http', auth='none', methods=['GET'], csrf=False)
    def search_by_appointment_code(self, **kwargs):
        """
        Search appointment by code (partial match)
        Query parameters:
            - code: Appointment code string e.g. APT/2025/0042
        """
        try:
            user = self._validate_api_key()
            if isinstance(user, Response):
                return user
            if not hasattr(user, 'id'):
                return user

            code = kwargs.get('code', '').strip()
            if not code:
                return self._error_response(
                    "Please provide 'code' parameter",
                    "MISSING_PARAMETER",
                    400
                )

            patient_id = kwargs.get('patient_id')

            domain = [('appointment_code', 'ilike', code)]

            # Optionally restrict to the patient's own appointments
            if patient_id:
                try:
                    domain.append(('patient_id', '=', int(patient_id)))
                except (ValueError, TypeError):
                    pass

            appointments = request.env['clinic.appointment'].sudo().search(
                domain,
                order='appointment_datetime desc',
                limit=20
            )

            result = []
            for appt in appointments:
                doctor_speciality = None
                if appt.doctor_speciality:
                    doctor_speciality = appt.doctor_speciality.name
                elif appt.doctor_id and appt.doctor_id.speciality_id:
                    doctor_speciality = appt.doctor_id.speciality_id.name

                result.append({
                    "appointment_id": appt.id,
                    "appointment_code": appt.appointment_code or '',
                    "appointment_datetime": str(appt.appointment_datetime) if appt.appointment_datetime else None,
                    "status": appt.status or '',
                    "notes": appt.notes or '',
                    "doctor_name": appt.doctor_id.name if appt.doctor_id else '',
                    "doctor_speciality": doctor_speciality,
                    "patient_name": appt.patient_id.name if appt.patient_id else '',
                    "patient_id": appt.patient_id.id if appt.patient_id else None,
                })

            return self._json_response(
                self._success_response({
                    "total": len(result),
                    "appointments": result
                }),
                200
            )

        except Exception as e:
            _logger.exception("Error searching by appointment code")
            return self._error_response(str(e), "INTERNAL_SERVER_ERROR", 500)