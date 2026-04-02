from odoo import http
from odoo.http import request
from .base_controller import BaseAPIController
import logging

_logger = logging.getLogger(__name__)


class SpecialityApi(BaseAPIController):

    @http.route('/api/v19/get_speciality_list', type='http', auth='public', methods=['GET'], csrf=False)
    def get_speciality_list(self, **kwargs):
        try:
            user = self._validate_api_key()

            if not hasattr(user, 'id'):
                return user

            speciality = request.env['res.speciality'].sudo().search([('active', '=', True)])

            speciality_list = []
            for s in speciality:
                speciality_list.append({
                    'id': s.id,
                    'name': s.name or '',
                    'description': s.description or '',
                    'active': s.active,
                })

            response_data = {
                'speciality': speciality_list,
                'total': len(speciality_list)
            }

            return self._json_response(
                self._success_response(response_data)
            )

        except Exception as e:
            _logger.exception("Error fetching Speciality list")
            return self._error_response(str(e))