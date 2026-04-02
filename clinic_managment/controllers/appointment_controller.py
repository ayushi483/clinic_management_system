from odoo import http, fields
from odoo.http import request, Response
import json
import logging
from datetime import datetime
from .base_controller import BaseAPIController

_logger = logging.getLogger(__name__)


class AppointmentAPI(BaseAPIController):

    @http.route('/api/v19/appointment', type='http', auth='none', methods=['POST', 'GET'], csrf=False)
    def appointment_handler(self, **kwargs):
        try:
            user = self._validate_api_key()
            if isinstance(user, Response):
                return user

            if request.httprequest.method == 'POST':
                raw_data = request.httprequest.get_data(as_text=True)
                if raw_data:
                    data = json.loads(raw_data)
                    if isinstance(data, str):
                        data = json.loads(data)
                elif kwargs:
                    data = kwargs
                else:
                    return self._error_response("Empty request body", "EMPTY_REQUEST", 400)

                if not isinstance(data, dict):
                    return self._error_response("Invalid format", "INVALID_FORMAT", 400)

                action = data.get("action")

                if not action:
                    patient = request.env["clinic.patient"].sudo().search([
                        ("partner_id", "=", user.partner_id.id)
                    ], limit=1)
                    if not patient:
                        return self._error_response("Patient profile not found", "PATIENT_NOT_FOUND", 404)
                    return self._book_appointment(data, patient)

                if action == "list":
                    patient = request.env["clinic.patient"].sudo().search([
                        ("partner_id", "=", user.partner_id.id)
                    ], limit=1)
                    if not patient:
                        return self._error_response("Patient profile not found", "PATIENT_NOT_FOUND", 404)
                    return self._list_appointments(data, patient)

                elif action == "cancel":
                    patient = request.env["clinic.patient"].sudo().search([
                        ("partner_id", "=", user.partner_id.id)
                    ], limit=1)
                    if not patient:
                        return self._error_response("Patient profile not found", "PATIENT_NOT_FOUND", 404)
                    return self._cancel_appointment(data, patient)

                elif action == "doctors":
                    return self._get_doctors(data)

                elif action == "patients":
                    return self._get_patients(data)

                else:
                    return self._error_response(
                        f"Unknown action '{action}'. Options: list | cancel | doctors | patients",
                        "INVALID_ACTION",
                        400
                    )

            elif request.httprequest.method == 'GET':
                action = kwargs.get("action", "list")
                data = kwargs

                if action == "list":
                    patient = request.env["clinic.patient"].sudo().search([
                        ("partner_id", "=", user.partner_id.id)
                    ], limit=1)
                    if not patient:
                        return self._error_response("Patient profile not found", "PATIENT_NOT_FOUND", 404)
                    return self._list_appointments(data, patient)

                elif action == "doctors":
                    return self._get_doctors(data)

                elif action == "patients":
                    return self._get_patients(data)

                else:
                    return self._error_response(
                        f"Unknown action '{action}'. Options: list | doctors | patients",
                        "INVALID_ACTION",
                        400
                    )

        except Exception as e:
            _logger.exception("Appointment Handler Error")
            return self._error_response(str(e), "INTERNAL_SERVER_ERROR", 500)

    # ─────────────────────────────────────────────
    # BOOK
    # ─────────────────────────────────────────────

    def _book_appointment(self, data, logged_in_patient):
        try:
            required_fields = ["doctor_id", "appointment_datetime"]
            for field in required_fields:
                if not data.get(field):
                    return self._error_response(f"{field} is required", f"MISSING_{field.upper()}", 400)

            # ── Patient resolution ────────────────────────
            override_patient_id = data.get("patient_id")
            if override_patient_id:
                patient = request.env["clinic.patient"].sudo().browse(int(override_patient_id))
                if not patient.exists():
                    return self._error_response(
                        f"Patient with id {override_patient_id} not found",
                        "PATIENT_NOT_FOUND",
                        404
                    )
            else:
                patient = logged_in_patient

            # ── Fetch doctor ──────────────────────────────
            doctor = request.env["clinic.doctor"].sudo().browse(int(data.get("doctor_id")))
            if not doctor.exists():
                return self._error_response("Doctor not found", "DOCTOR_NOT_FOUND", 404)

            if not doctor.is_available:
                return self._error_response(
                    f"Dr. {doctor.name} is currently not available",
                    "DOCTOR_NOT_AVAILABLE",
                    400
                )

            # ── Parse datetime as UTC directly ────────────
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

            # ── Validate future datetime ──────────────────
            if appointment_datetime <= fields.Datetime.now():
                return self._error_response(
                    "Appointment must be a future date and time",
                    "PAST_DATETIME",
                    400
                )

            # ── Create appointment ────────────────────────
            appointment = request.env["clinic.appointment"].sudo().with_context(
                tz=request.env.user.tz or 'UTC'
            ).create({
                "patient_id": patient.id,
                "doctor_id": doctor.id,
                "appointment_datetime": appointment_datetime,
                "notes": data.get("notes", ""),
                "status": "draft",
            })

            # ── Confirm & generate code ───────────────────
            appointment.action_confirm()
            appointment.invalidate_recordset()

            return self._json_response(
                self._success_response({
                    "appointment_id": appointment.id,
                    "appointment_code": appointment.appointment_code,
                    "patient_name": appointment.patient_id.name,
                    "patient_code": appointment.patient_id.patient_code,
                    "doctor_name": appointment.doctor_id.name,
                    "doctor_speciality": appointment.doctor_speciality.name if appointment.doctor_speciality else None,
                    "appointment_datetime": str(appointment.appointment_datetime),
                    "doctor_fees": appointment.doctor_fees,
                    "status": appointment.status,
                    "notes": appointment.notes,
                    "message": "Appointment booked and confirmed successfully"
                }),
                201
            )

        except Exception as e:
            _logger.exception("Book Appointment Error")
            return self._error_response(str(e), "INTERNAL_SERVER_ERROR", 500)

    # ─────────────────────────────────────────────
    # LIST
    # ─────────────────────────────────────────────

    def _list_appointments(self, data, patient):
        try:
            domain = [("patient_id", "=", patient.id)]

            status_filter = data.get("status")
            if status_filter:
                domain.append(("status", "=", status_filter))

            appointments = request.env["clinic.appointment"].sudo().search(domain)

            result = []
            for appt in appointments:
                result.append({
                    "appointment_id": appt.id,
                    "appointment_code": appt.appointment_code,
                    "doctor_name": appt.doctor_id.name if appt.doctor_id else None,
                    "doctor_speciality": appt.doctor_speciality.name if appt.doctor_speciality else None,
                    "doctor_fees": appt.doctor_fees,
                    "appointment_datetime": str(appt.appointment_datetime),
                    "status": appt.status,
                    "notes": appt.notes,
                })

            return self._json_response(
                self._success_response({
                    "total": len(result),
                    "appointments": result
                }),
                200
            )

        except Exception as e:
            _logger.exception("List Appointments Error")
            return self._error_response(str(e), "INTERNAL_SERVER_ERROR", 500)

    # ─────────────────────────────────────────────
    # CANCEL
    # ─────────────────────────────────────────────

    def _cancel_appointment(self, data, patient):
        try:
            appointment_id = data.get("appointment_id")
            if not appointment_id:
                return self._error_response("appointment_id is required", "MISSING_APPOINTMENT_ID", 400)

            appointment = request.env["clinic.appointment"].sudo().browse(int(appointment_id))

            if not appointment.exists():
                return self._error_response("Appointment not found", "APPOINTMENT_NOT_FOUND", 404)

            if appointment.patient_id.id != patient.id:
                return self._error_response(
                    "You are not authorized to cancel this appointment",
                    "UNAUTHORIZED",
                    403
                )

            if appointment.status in ['done', 'cancel']:
                return self._error_response(
                    f"Cannot cancel an appointment with status: {appointment.status}",
                    "INVALID_STATUS",
                    400
                )

            appointment.action_cancel()

            return self._json_response(
                self._success_response({
                    "appointment_id": appointment.id,
                    "appointment_code": appointment.appointment_code,
                    "status": appointment.status,
                    "message": "Appointment cancelled successfully"
                }),
                200
            )

        except Exception as e:
            _logger.exception("Cancel Appointment Error")
            return self._error_response(str(e), "INTERNAL_SERVER_ERROR", 500)

    # ─────────────────────────────────────────────
    # DOCTORS
    # ─────────────────────────────────────────────

    def _get_doctors(self, data):
        try:
            domain = [("is_available", "=", True)]

            speciality_id = data.get("speciality_id")
            if speciality_id:
                domain.append(("speciality_id", "=", int(speciality_id)))

            doctors = request.env["clinic.doctor"].sudo().search(domain)

            result = []
            for doc in doctors:
                availability = []
                for line in doc.availability_ids:
                    availability.append({
                        "day": line.day,
                        "start_time": line.start_time,
                        "end_time": line.end_time,
                    })

                result.append({
                    "doctor_id": doc.id,
                    "name": doc.name,
                    "phone": doc.phone,
                    "email": doc.email,
                    "fees": doc.fees,
                    "speciality": doc.speciality_id.name if doc.speciality_id else None,
                    "total_appointment_limit": doc.total_appointment,
                    "availability": availability,
                })

            return self._json_response(
                self._success_response({
                    "total": len(result),
                    "doctors": result
                }),
                200
            )

        except Exception as e:
            _logger.exception("Get Doctors Error")
            return self._error_response(str(e), "INTERNAL_SERVER_ERROR", 500)

    # ─────────────────────────────────────────────
    # PATIENTS
    # ─────────────────────────────────────────────

    def _get_patients(self, data):
        try:
            domain = [("active", "=", True)]

            search_name = data.get("name")
            if search_name:
                domain.append(("name", "ilike", search_name))

            patients = request.env["clinic.patient"].sudo().search(domain)

            result = []
            for p in patients:
                result.append({
                    "patient_id": p.id,
                    "name": p.name or "",
                    "age": p.age or 0,
                    "gender": p.gender or "",
                    "phone": p.phone or "",
                    "email": p.email or "",
                    "patient_code": p.patient_code or "",
                })

            return self._json_response(
                self._success_response({
                    "total": len(result),
                    "patients": result
                }),
                200
            )

        except Exception as e:
            _logger.exception("Get Patients Error")
            return self._error_response(str(e), "INTERNAL_SERVER_ERROR", 500)