from odoo import http
from odoo.http import request
from .base_controller import BaseAPIController
import logging

_logger = logging.getLogger(__name__)


class DoctorAPI(BaseAPIController):

    @http.route('/api/v19/get_doctor_list', type='http', auth='public', methods=['GET'], csrf=False)
    def get_doctor_list(self, **kwargs):
        try:
            # 🔐 ONLY validate token
            user = self._validate_api_key()

            if not hasattr(user, 'id'):
                return user

            doctors = request.env['clinic.doctor'].sudo().search([('active', '=', True)])

            doctor_list = []
            for d in doctors:
                doctor_list.append({
                    'id': d.id,
                    'name': d.name or '',
                    'phone': d.phone or '',
                    'email': d.email or '',
                    'fees': d.fees or 0,
                    'total_appointment': d.total_appointment or 0,
                    'available': d.is_available or False,
                })

            return self._json_response(
                self._success_response({
                    'doctors': doctor_list,
                    'total': len(doctor_list)
                }),
                200
            )

        except Exception as e:
            _logger.exception("Error fetching doctor list")
            return self._error_response(str(e), "INTERNAL_SERVER_ERROR", 500)

    @http.route('/api/v19/doctor/info', type='http', auth='none', methods=['POST'], csrf=False)
    def get_doctor_info(self, **kwargs):
        try:
            # Validate API Key
            user = self._validate_api_key()
            if not hasattr(user, 'id'):
                return user

            # Parse request body
            import json
            raw_data = request.httprequest.get_data(as_text=True)

            try:
                if raw_data:
                    data = json.loads(raw_data)
                    if isinstance(data, str):
                        data = json.loads(data)
                elif kwargs:
                    data = kwargs
                else:
                    return self._error_response("Request body is empty", "EMPTY_REQUEST_BODY", 400)

                if not isinstance(data, dict):
                    return self._error_response("Invalid request format", "INVALID_FORMAT", 400)

            except (ValueError, TypeError, json.JSONDecodeError) as e:
                return self._error_response("Invalid JSON format", "INVALID_JSON", 400)

            # Validate doctor_id
            doctor_id = data.get('doctor_id')
            if not doctor_id:
                return self._error_response("doctor_id is required", "MISSING_DOCTOR_ID", 400)

            try:
                doctor_id = int(doctor_id)
            except (ValueError, TypeError):
                return self._error_response("doctor_id must be a valid integer", "INVALID_DOCTOR_ID", 400)

            # Fetch doctor
            doctor = request.env['clinic.doctor'].sudo().browse(doctor_id)
            if not doctor.exists():
                return self._error_response(f"Doctor with ID {doctor_id} not found", "DOCTOR_NOT_FOUND", 404)

            return self._json_response(
                self._success_response({
                    "doctor_id": doctor.id,
                    "name": doctor.name or '',
                    "phone": doctor.phone or '',
                    "email": doctor.email or '',
                    "fees": doctor.fees or 0,
                    "speciality": doctor.speciality_id.name if doctor.speciality_id else '',
                    "total_appointment": doctor.total_appointment or 0,
                    "available": doctor.is_available or False,
                    "availability": [
                        {
                            "day": line.day or '',
                            "start_time": line.start_time or 0.0,
                            "end_time": line.end_time or 0.0,
                        }
                        for line in doctor.availability_ids
                    ],
                }),
                200
            )

        except Exception as e:
            _logger.exception("Error fetching doctor info")
            return self._error_response(str(e), "INTERNAL_SERVER_ERROR", 500)

