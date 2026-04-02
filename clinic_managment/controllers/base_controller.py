from odoo import http, fields
from odoo.http import Response, request
import json
from datetime import timedelta
import logging

_logger = logging.getLogger(__name__)


class BaseAPIController(http.Controller):

    def _json_response(self, data, status=200):
        return Response(
            json.dumps(data),
            status=status,
            mimetype='application/json'
        )

    def _success_response(self, data=None):
        return {
            'success': True,
            'data': data if data else {},
            'error': None
        }

    def _error_response(self, message, code, http_status=500):
        return self._json_response({
            'success': False,
            'data': None,
            'error': {
                'code': code,
                'message': message
            }
        }, http_status)

    def _generate_api_key(self, user, prefix="API"):
        try:
            current_time = fields.Datetime.now()
            key_name = f'{prefix} - {user.name} - {current_time}'

            max_days = int(request.env['ir.config_parameter'].sudo().get_param(
                'base_setup.api_key_duration', default=1
            ))

            expiration_date = current_time + timedelta(days=max_days)

            api_key = request.env['res.users.apikeys'].with_user(user)._generate(
                scope='rpc',
                name=key_name,
                expiration_date=expiration_date,
            )

            return api_key, None

        except Exception as e:
            _logger.exception("API Key Generation Error")
            return None, self._error_response(
                f"API key generation failed: {str(e)}",
                "API_KEY_ERROR",
                500
            )
                   #Api validation common
    def _validate_api_key(self):
        try:
            auth_header = request.httprequest.headers.get("Authorization")

            if not auth_header or not auth_header.startswith("Bearer "):
                return self._error_response(
                    "Missing Authorization Header",
                    "MISSING_TOKEN",
                    401
                )

            token = auth_header.split(" ")[1].strip()

            uid = request.env['res.users.apikeys']._check_credentials(
                scope='rpc',
                key=token
            )

            if not uid:
                return self._error_response(
                    "Invalid API Key",
                    "INVALID_API_KEY",
                    401
                )

            # ✅ Get logged-in user
            user = request.env['res.users'].sudo().browse(uid)

            return user

        except Exception as e:
            _logger.exception("API Key validation failed")
            return self._error_response(
                str(e),
                "VALIDATION_ERROR",
                500
            )