from odoo import http, fields
from odoo.http import request, Response
import json
import logging
from datetime import datetime
from .base_controller import BaseAPIController

_logger = logging.getLogger(__name__)


class AppointmentAPI(BaseAPIController):


    @http.route('/api/v19/appointment/book', type='http', auth='none', methods=['POST'], csrf=False)
    def book_appointment(self, **kwargs):
        try:
            user = self._validate_api_key()
            if isinstance(user, Response):
                return user
            if not hasattr(user, 'id'):
                return user

            raw_data = request.httprequest.get_data(as_text=True)
            try:
                data = json.loads(raw_data) if raw_data else kwargs
                if isinstance(data, str):
                    data = json.loads(data)
            except (ValueError, json.JSONDecodeError):
                return self._error_response("Invalid JSON format", "INVALID_JSON", 400)

            if not isinstance(data, dict):
                return self._error_response("Invalid request format", "INVALID_FORMAT", 400)

            return self._book_appointment(data, user)

        except Exception as e:
            _logger.exception("Book Appointment Error")
            return self._error_response(repr(e), "INTERNAL_SERVER_ERROR", 500)


    @http.route('/api/v19/appointments', type='http', auth='none', methods=['GET'], csrf=False)
    def get_all_appointments(self, **kwargs):
        try:
            user = self._validate_api_key()
            if isinstance(user, Response):
                return user
            if not hasattr(user, 'id'):
                return user

            appointments = request.env["clinic.appointment"].sudo().search([])
            result = [self._format_appointment(appt) for appt in appointments]

            return self._json_response(
                self._success_response({
                    "total": len(result),
                    "appointments": result
                }),
                200
            )

        except Exception as e:
            _logger.exception("Error fetching all appointments")
            return self._error_response(repr(e), "INTERNAL_SERVER_ERROR", 500)


    @http.route('/api/v19/appointments/confirmed', type='http', auth='none', methods=['GET'], csrf=False)
    def get_confirmed_appointments(self, **kwargs):
        try:
            user = self._validate_api_key()
            if isinstance(user, Response):
                return user
            if not hasattr(user, 'id'):
                return user

            appointments = request.env["clinic.appointment"].sudo().search([
                ("status", "=", "confirmed")
            ])
            result = [self._format_appointment(appt) for appt in appointments]

            return self._json_response(
                self._success_response({
                    "status_filter": "confirmed",
                    "total": len(result),
                    "appointments": result
                }),
                200
            )

        except Exception as e:
            _logger.exception("Error fetching confirmed appointments")
            return self._error_response(repr(e), "INTERNAL_SERVER_ERROR", 500)



    @http.route('/api/v19/appointments/completed', type='http', auth='none', methods=['GET'], csrf=False)
    def get_completed_appointments(self, **kwargs):
        try:
            user = self._validate_api_key()
            if isinstance(user, Response):
                return user
            if not hasattr(user, 'id'):
                return user

            appointments = request.env["clinic.appointment"].sudo().search([
                ("status", "=", "done")
            ])
            result = [self._format_appointment(appt) for appt in appointments]

            return self._json_response(
                self._success_response({
                    "status_filter": "done",
                    "total": len(result),
                    "appointments": result
                }),
                200
            )

        except Exception as e:
            _logger.exception("Error fetching completed appointments")
            return self._error_response(repr(e), "INTERNAL_SERVER_ERROR", 500)



    @http.route('/api/v19/appointments/no_show', type='http', auth='none', methods=['GET'], csrf=False)
    def get_no_show_appointments(self, **kwargs):
        try:
            user = self._validate_api_key()
            if isinstance(user, Response):
                return user
            if not hasattr(user, 'id'):
                return user

            appointments = request.env["clinic.appointment"].sudo().search([
                ("status", "=", "no_show")
            ])
            result = [self._format_appointment(appt) for appt in appointments]

            return self._json_response(
                self._success_response({
                    "status_filter": "no_show",
                    "total": len(result),
                    "appointments": result
                }),
                200
            )

        except Exception as e:
            _logger.exception("Error fetching no-show appointments")
            return self._error_response(repr(e), "INTERNAL_SERVER_ERROR", 500)



    @http.route('/api/v19/appointments/cancelled', type='http', auth='none', methods=['GET'], csrf=False)
    def get_cancelled_appointments(self, **kwargs):
        try:
            user = self._validate_api_key()
            if isinstance(user, Response):
                return user
            if not hasattr(user, 'id'):
                return user

            appointments = request.env["clinic.appointment"].sudo().search([
                ("status", "=", "cancel")
            ])
            result = [self._format_appointment(appt) for appt in appointments]

            return self._json_response(
                self._success_response({
                    "status_filter": "cancel",
                    "total": len(result),
                    "appointments": result
                }),
                200
            )

        except Exception as e:
            _logger.exception("Error fetching cancelled appointments")
            return self._error_response(repr(e), "INTERNAL_SERVER_ERROR", 500)

    @http.route('/api/v19/appointments/draft', type='http', auth='none', methods=['GET'], csrf=False)
    def get_draft_appointments(self, **kwargs):
        try:
            user = self._validate_api_key()
            if isinstance(user, Response):
                return user
            if not hasattr(user, 'id'):
                return user

            appointments = request.env["clinic.appointment"].sudo().search([
                ("status", "=", "draft")
            ])
            result = [self._format_appointment(appt) for appt in appointments]

            return self._json_response(
                self._success_response({
                    "status_filter": "draft",
                    "total": len(result),
                    "appointments": result
                }),
                200
            )

        except Exception as e:
            _logger.exception("Error fetching draft appointments")
            return self._error_response(repr(e), "INTERNAL_SERVER_ERROR", 500)

#appointment_id required
    @http.route('/api/v19/appointments/detail', type='http', auth='none', methods=['GET'], csrf=False)
    def get_appointment_by_id(self, **kwargs):
        try:
            user = self._validate_api_key()
            if isinstance(user, Response):
                return user
            if not hasattr(user, 'id'):
                return user

            appointment_id = kwargs.get("appointment_id")
            if not appointment_id:
                return self._error_response(
                    "appointment_id is required. Usage: ?appointment_id=5",
                    "MISSING_APPOINTMENT_ID",
                    400
                )

            try:
                appointment_id = int(appointment_id)
            except (ValueError, TypeError):
                return self._error_response(
                    "appointment_id must be a valid integer",
                    "INVALID_APPOINTMENT_ID",
                    400
                )

            appointment = request.env["clinic.appointment"].sudo().browse(appointment_id)

            if not appointment.exists():
                return self._error_response(
                    f"Appointment with ID {appointment_id} not found",
                    "APPOINTMENT_NOT_FOUND",
                    404
                )

            return self._json_response(
                self._success_response(
                    self._format_appointment(appointment)
                ),
                200
            )

        except Exception as e:
            _logger.exception("Error fetching appointment by ID")
            return self._error_response(repr(e), "INTERNAL_SERVER_ERROR", 500)

    # BOOK - INTERNAL HELPER (with full validations)


    def _book_appointment(self, data, user):
        try:
            required_fields = ["doctor_id", "appointment_datetime", "patient_id"]
            for f in required_fields:
                if not data.get(f):
                    return self._error_response(
                        f"{f} is required",
                        f"MISSING_{f.upper()}",
                        400
                    )

            override_patient_id = data.get("patient_id")
            patient = request.env["clinic.patient"].sudo().browse(int(override_patient_id))
            if not patient.exists():
                return self._error_response(
                    f"Patient with id {override_patient_id} not found",
                    "PATIENT_NOT_FOUND",
                    404
                )

            doctor = request.env["clinic.doctor"].sudo().browse(int(data.get("doctor_id")))
            if not doctor.exists():
                return self._error_response("Doctor not found", "DOCTOR_NOT_FOUND", 404)

            if not doctor.is_available:
                return self._error_response(
                    f"Dr. {doctor.name} is currently not available",
                    "DOCTOR_NOT_AVAILABLE",
                    400
                )

            try:
                appointment_datetime = fields.Datetime.from_string(
                    data.get("appointment_datetime")
                )
            except Exception:
                return self._error_response(
                    "Invalid datetime format. Use: YYYY-MM-DD HH:MM:SS (UTC)",
                    "INVALID_DATETIME",
                    400
                )

            if appointment_datetime <= fields.Datetime.now():
                return self._error_response(
                    "Appointment must be a future date and time",
                    "PAST_DATETIME",
                    400
                )

            appointment = request.env["clinic.appointment"].sudo().with_context(
                tz=request.env.user.tz or 'UTC'
            ).create({
                "patient_id": patient.id,
                "doctor_id": doctor.id,
                "appointment_datetime": appointment_datetime,
                "notes": data.get("notes", ""),
                "status": "draft",
            })

            appointment.action_confirm()
            appointment.invalidate_recordset()

            return self._json_response(
                self._success_response({
                    "appointment_id": appointment.id,
                    "appointment_code": appointment.appointment_code,

                    # ── Patient details ──
                    "patient_name": appointment.patient_id.name or '',
                    "patient_code": appointment.patient_id.patient_code or '',
                    "patient_phone": appointment.patient_phone or '',
                    "patient_email": appointment.patient_email or '',
                    "patient_gender": appointment.patient_gender or '',

                    # ── Doctor details ──
                    "doctor_name": appointment.doctor_id.name or '',
                    "doctor_speciality": appointment.doctor_speciality.name if appointment.doctor_speciality else None,
                    "doctor_fees": appointment.doctor_fees or 0,
                    "doctor_phone": appointment.doctor_phone or '',
                    "doctor_email": appointment.doctor_email or '',

                    # ── Appointment details ──
                    "appointment_datetime": str(appointment.appointment_datetime),
                    "status": appointment.status,
                    "notes": appointment.notes or '',
                    "message": "Appointment booked and confirmed successfully"
                }),
                201
            )

        except Exception as e:
            _logger.exception("Book Appointment Internal Error")
            return self._error_response(repr(e), "INTERNAL_SERVER_ERROR", 500)

    @http.route('/api/v19/appointment/check_availability', type='http', auth='none', methods=['POST'], csrf=False)
    def check_availability(self, **kwargs):
        try:
            user = self._validate_api_key()
            if isinstance(user, Response):
                return user
            if not hasattr(user, 'id'):
                return user

            # ── Parse Request ──
            raw_data = request.httprequest.get_data(as_text=True)
            try:
                data = json.loads(raw_data) if raw_data else kwargs
                if isinstance(data, str):
                    data = json.loads(data)
            except:
                return self._error_response("Invalid JSON format", "INVALID_JSON", 400)

            doctor_id = data.get("doctor_id")
            appointment_datetime = data.get("appointment_datetime")

            if not doctor_id:
                return self._error_response("doctor_id is required", "MISSING_DOCTOR_ID", 400)

            if not appointment_datetime:
                return self._error_response("appointment_datetime is required", "MISSING_DATETIME", 400)

            # ── Validate Doctor ──
            doctor = request.env["clinic.doctor"].sudo().browse(int(doctor_id))
            if not doctor.exists():
                return self._error_response("Doctor not found", "DOCTOR_NOT_FOUND", 404)

            if not doctor.is_available:
                return self._error_response(
                    f"Dr. {doctor.name} is not available",
                    "DOCTOR_NOT_AVAILABLE",
                    400
                )

            # ── Convert Datetime ──
            try:
                appointment_dt = fields.Datetime.from_string(appointment_datetime)
            except:
                return self._error_response(
                    "Invalid datetime format. Use: YYYY-MM-DD HH:MM:SS",
                    "INVALID_DATETIME",
                    400
                )

            # ── Past Check ──
            if appointment_dt <= fields.Datetime.now():
                return self._error_response(
                    "Please select future date & time",
                    "PAST_DATETIME",
                    400
                )

            # ── Check Existing Booking ──
            existing = request.env["clinic.appointment"].sudo().search([
                ("doctor_id", "=", doctor.id),
                ("appointment_datetime", "=", appointment_dt),
                ("status", "!=", "cancel")
            ], limit=1)

            # ── Get Doctor Schedule ──
            def format_time(time_float):
                hours = int(time_float)
                minutes = int((time_float - hours) * 60)
                return f"{hours:02d}:{minutes:02d}"

            doctor_schedule = [
                {
                    "day": line.day,
                    "start_time": format_time(line.start_time),
                    "end_time": format_time(line.end_time),
                }
                for line in doctor.availability_ids
            ]

            # ── Check Day & Time Availability ──
            weekday = appointment_dt.strftime('%A').lower()
            available_slot = False

            for line in doctor.availability_ids:
                if line.day.lower() == weekday:
                    start = line.start_time
                    end = line.end_time
                    hour = appointment_dt.hour + (appointment_dt.minute / 60.0)

                    if start <= hour <= end:
                        available_slot = True
                        break


            # ❌ Already booked
            if existing:
                return self._json_response(
                    self._success_response({
                        "available": False,
                        "message": "This slot is already booked",
                        "doctor_schedule": doctor_schedule
                    }),
                    200
                )

            # ❌ Not in working hours
            if not available_slot:
                return self._json_response(
                    self._success_response({
                        "available": False,
                        "message": "Doctor not available at this time",
                        "doctor_schedule": doctor_schedule
                    }),
                    200
                )

            # ✅ Available
            return self._json_response(
                self._success_response({
                    "available": True,
                    "message": "Slot is available",
                    "doctor_schedule": doctor_schedule
                }),
                200
            )

        except Exception as e:
            _logger.exception("Check Availability Error")
            return self._error_response(repr(e), "INTERNAL_SERVER_ERROR", 500)

    @http.route('/api/v19/patient/appointments', type='http', auth='none', methods=['POST'], csrf=False)
    def get_patient_appointments(self, **kwargs):
        try:
            user = self._validate_api_key()
            if not hasattr(user, 'id'):
                return user

            raw_data = request.httprequest.get_data(as_text=True)
            try:
                data = json.loads(raw_data) if raw_data else kwargs
                if isinstance(data, str):
                    data = json.loads(data)
                if not isinstance(data, dict):
                    return self._error_response("Invalid request format", "INVALID_FORMAT", 400)
            except (ValueError, TypeError, json.JSONDecodeError):
                return self._error_response("Invalid JSON format", "INVALID_JSON", 400)

            patient_id = data.get('patient_id')
            if not patient_id:
                return self._error_response("patient_id is required", "MISSING_PATIENT_ID", 400)

            try:
                patient_id = int(patient_id)
            except (ValueError, TypeError):
                return self._error_response("patient_id must be a valid integer", "INVALID_PATIENT_ID", 400)

            patient = request.env['clinic.patient'].sudo().browse(patient_id)
            if not patient.exists():
                return self._error_response(f"Patient with ID {patient_id} not found", "PATIENT_NOT_FOUND", 404)

            appointments = request.env['clinic.appointment'].sudo().search([
                ('patient_id', '=', patient_id)
            ], order='appointment_datetime desc')

            result = []
            for appt in appointments:
                result.append({
                    'id': appt.id,
                    'name': appt.appointment_code or f'Appointment #{appt.id}',
                    # ✅ FIXED: was appt.date — correct field is appointment_datetime
                    'date': str(appt.appointment_datetime) if appt.appointment_datetime else '',
                    'status': appt.status or '',
                    'doctor': appt.doctor_id.name if appt.doctor_id else '',
                    'speciality': appt.doctor_speciality.name if appt.doctor_speciality else '',
                    'notes': appt.notes or '',
                })

            total = len(result)
            completed = len([a for a in result if a['status'] == 'done'])
            confirmed = len([a for a in result if a['status'] == 'confirmed'])
            draft = len([a for a in result if a['status'] == 'draft'])
            cancelled = len([a for a in result if a['status'] in ('cancel', 'cancelled')])
            upcoming = confirmed + draft

            return self._json_response(
                self._success_response({
                    'patient_id': patient_id,
                    'total': total,
                    'completed': completed,
                    'confirmed': confirmed,
                    'draft': draft,
                    'cancelled': cancelled,
                    'upcoming': upcoming,
                    'appointments': result,
                }),
                200
            )

        except Exception as e:
            _logger.exception("Error fetching patient appointments")
            return self._error_response(str(e), "INTERNAL_SERVER_ERROR", 500)

    def _format_appointment(self, appt):
        return {
            "appointment_id": appt.id,
            "appointment_code": appt.appointment_code or '',
            "doctor_name": appt.doctor_id.name if appt.doctor_id else None,
            "doctor_speciality": appt.doctor_speciality.name if appt.doctor_speciality else None,
            "doctor_fees": appt.doctor_fees or 0,
            "doctor_phone": appt.doctor_phone or '',
            "doctor_email": appt.doctor_email or '',
            "patient_name": appt.patient_id.name if appt.patient_id else None,
            "patient_code": appt.patient_id.patient_code if appt.patient_id else None,
            "patient_phone": appt.patient_phone or '',
            "patient_email": appt.patient_email or '',
            "patient_gender": appt.patient_gender or '',
            "appointment_datetime": str(appt.appointment_datetime) if appt.appointment_datetime else None,
            "status": appt.status or '',
            "notes": appt.notes or '',
        }