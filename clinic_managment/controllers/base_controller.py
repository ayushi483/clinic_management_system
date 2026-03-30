from odoo import http
from odoo.http import Response
import json


class BaseAPIController(http.Controller):

    def _json_response(self, data, status=200):
        """
        Return a proper JSON HTTP response

        Args:
            data: Response data (dict)
            status: HTTP status code

        Returns:
            Response: HTTP response with JSON content
        """
        return Response(
            json.dumps(data),
            status=status,
            mimetype='application/json'
        )

    def _success_response(self, data=None):
        """
        Generate standardized success response

        Args:
            data: Response data (dict, list, or any JSON-serializable object)

        Returns:
            dict: Standardized success response
        """
        return {
            'success': True,
            'data': data if data is not None else {},
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
        }, status=http_status)