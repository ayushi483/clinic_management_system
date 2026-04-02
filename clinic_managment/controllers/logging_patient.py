import json
import logging
from odoo import http, fields
from odoo.http import request
from odoo.exceptions import AccessDenied
from .base_controller import BaseAPIController

_logger = logging.getLogger(__name__)


class PatientLoggingAPI(BaseAPIController):

    @http.route('/api/v19/patient/login', type='http', auth='none', methods=['POST'], csrf=False)
    def patient_login(self, **kwargs):
        try:

            raw_data = request.httprequest.get_data(as_text=True)
            _logger.info(f"Patient login request received")
            _logger.info(f"Raw data type: {type(raw_data)}, value: {raw_data}")

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

                _logger.info(f"Parsed data type: {type(data)}, value: {data}")

            except (ValueError, TypeError, json.JSONDecodeError) as e:
                _logger.error(f"JSON parsing error: {str(e)}")
                return self._error_response("Invalid JSON format", "INVALID_JSON", 400)


            login = data.get('email') or data.get('mobile')
            password = data.get('password')

            if not login:
                return self._error_response(
                    "Email or Mobile is required",
                    "MISSING_LOGIN",
                    400
                )

            if not password:
                return self._error_response(
                    "Password is required",
                    "MISSING_PASSWORD",
                    400
                )


            try:
                user = request.env['res.users'].sudo().search([
                    '|',
                    ('email', '=', login),
                    ('login', '=', login),
                ], limit=1)

                if not user:
                    return self._error_response(
                        "Invalid credentials",
                        "AUTH_FAILED",
                        401
                    )

                user.with_env(request.env(user=user.id)).sudo()._check_credentials(
                    {'password': password, 'type': 'password'},
                    {'interactive': False}
                )

            except AccessDenied:
                return self._error_response(
                    "Invalid credentials",
                    "AUTH_FAILED",
                    401
                )


            patient = request.env['clinic.patient'].sudo().search([
                ('partner_id', '=', user.partner_id.id)
            ], limit=1)

            if not patient:
                return self._error_response(
                    "Patient not found",
                    "PATIENT_NOT_FOUND",
                    404
                )

            api_key, error = self._generate_api_key(user, prefix="Patient")
            if error:
                return error

            return self._json_response(
                self._success_response({
                    "patient_id": patient.id,
                    "name": patient.name,
                    "email": patient.email,
                    "phone": patient.phone,
                    "patient_code": patient.patient_code,
                    "age": patient.age,
                    "gender": patient.gender,
                    "user_id": user.id,
                    "api_key": api_key,
                    "message": "Login successful"
                }),
                200
            )

        except Exception as e:
            _logger.exception("Patient login error")
            return self._json_response({
                "success": False,
                "data": None,
                "error": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": str(e)
                }
            }, 500)