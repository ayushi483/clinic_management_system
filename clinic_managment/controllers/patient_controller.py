from odoo import http
from odoo.http import request
from .base_controller import BaseAPIController
import logging

_logger = logging.getLogger(__name__)


class PatientAPI(BaseAPIController):

    @http.route('/api/v19/get_patient_list', type='http', auth='public', methods=['GET'], csrf=False)
    def get_patient_list(self, **kwargs):
        try:
            user = super()._validate_api_key()

            if not hasattr(user, 'id'):
                return user

            patients = request.env['clinic.patient'].sudo().search([('active', '=', True)])

            patient_list = []
            for p in patients:
                patient_list.append({
                    'id': p.id,
                    'name': p.name or '',
                    'age': p.age or 0,
                    'gender': p.gender or '',
                    'phone': p.phone or '',
                    'email': p.email or '',
                    'patient_code': p.patient_code or '',
                })

            response_data = {
                'patients': patient_list,
                'total': len(patient_list)
            }

            return self._json_response(
                self._success_response(response_data),
                200
            )

        except Exception as e:
            _logger.exception("Error fetching patient list")
            return self._error_response(str(e), "INTERNAL_SERVER_ERROR", 500)

    @http.route('/api/v19/patient/info', type='http', auth='none', methods=['POST'], csrf=False)
    def get_patient_info(self, **kwargs):
        try:
            # Step 1: Validate API Key (Bearer token)
            user = self._validate_api_key()
            if not hasattr(user, 'id'):
                return user  # returns error response if invalid

            # Step 2: Parse request body
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
                    return self._error_response(
                        "Request body is empty",
                        "EMPTY_REQUEST_BODY",
                        400
                    )

                if not isinstance(data, dict):
                    return self._error_response(
                        "Invalid request format",
                        "INVALID_FORMAT",
                        400
                    )

            except (ValueError, TypeError, json.JSONDecodeError) as e:
                _logger.error(f"JSON parsing error: {str(e)}")
                return self._error_response("Invalid JSON format", "INVALID_JSON", 400)

            # Step 3: Extract and validate patient_id
            patient_id = data.get('patient_id')

            if not patient_id:
                return self._error_response(
                    "patient_id is required",
                    "MISSING_PATIENT_ID",
                    400
                )

            try:
                patient_id = int(patient_id)
            except (ValueError, TypeError):
                return self._error_response(
                    "patient_id must be a valid integer",
                    "INVALID_PATIENT_ID",
                    400
                )

            # Step 4: Fetch patient record
            patient = request.env['clinic.patient'].sudo().browse(patient_id)

            if not patient.exists():
                return self._error_response(
                    f"Patient with ID {patient_id} not found",
                    "PATIENT_NOT_FOUND",
                    404
                )

            # Step 5: Build and return response
            patient_data = {
                "patient_id": patient.id,
                "user_id": user.id,
                "contact_id": patient.partner_id.id,
                "patient_code": patient.patient_code or '',
                "name": patient.name or '',
                "gender": patient.gender or '',
                "date_of_birth": str(patient.date_of_birth) if patient.date_of_birth else None,
                "age": patient.age or 0,
                "phone": patient.phone or '',
                "email": patient.email or '',
                "address": patient.partner_id.street or '' if patient.partner_id else '',
                "active": patient.active,
            }

            return self._json_response(
                self._success_response(patient_data),
                200
            )

        except Exception as e:
            _logger.exception("Error fetching patient info")
            return self._error_response(str(e), "INTERNAL_SERVER_ERROR", 500)
