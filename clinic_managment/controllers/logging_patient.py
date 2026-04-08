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
            _logger.info(f"Raw data: {raw_data}")

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

            login_input = data.get('email') or data.get('mobile')
            password = data.get('password')

            if not login_input:
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

            password = str(password)

            # ── Search user by email or login ─────────────────────────────
            user = request.env['res.users'].sudo().search([
                '|',
                ('email', '=', login_input),
                ('login', '=', login_input),
            ], limit=1)

            # ── Fallback: search by partner email ─────────────────────────
            if not user:
                partner = request.env['res.partner'].sudo().search([
                    ('email', '=', login_input)
                ], limit=1)
                if partner:
                    user = request.env['res.users'].sudo().search([
                        ('partner_id', '=', partner.id)
                    ], limit=1)

            # ── Fallback: search by partner phone (mobile login) ──────────
            if not user:
                partner = request.env['res.partner'].sudo().search([
                    ('phone', '=', login_input)
                ], limit=1)
                if partner:
                    user = request.env['res.users'].sudo().search([
                        ('partner_id', '=', partner.id)
                    ], limit=1)

            _logger.info(
                f"Login attempt: input={login_input}, "
                f"found user id={user.id if user else None}, "
                f"user login={user.login if user else None}, "
                f"user email={user.email if user else None}, "
                f"partner email={user.partner_id.email if user else None}"
            )

            if not user:
                return self._error_response(
                    "Patient not found",
                    "PATIENT_NOT_FOUND",
                    404
                )

            try:
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

            # ── Search patient by partner_id (primary) ────────────────────
            patient = request.env['clinic.patient'].sudo().search([
                ('partner_id', '=', user.partner_id.id)
            ], limit=1)

            # ── Fallback: search by phone ─────────────────────────────────
            if not patient:
                patient = request.env['clinic.patient'].sudo().search([
                    ('phone', '=', login_input)
                ], limit=1)

            # ── Fallback: search by email ─────────────────────────────────
            if not patient and user.email:
                patient = request.env['clinic.patient'].sudo().search([
                    ('email', '=', user.email)
                ], limit=1)

            _logger.info(
                f"Patient lookup: partner_id={user.partner_id.id}, "
                f"found patient id={patient.id if patient else None}"
            )

            if not patient:
                return self._error_response(
                    "Patient record not found for this account",
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