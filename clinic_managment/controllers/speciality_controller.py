from odoo import http
from odoo.http import request
from .base_controller import BaseAPIController
import logging
import base64

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
                image_base64 = None
                try:
                    if s.image:
                        # s.image is already base64 in Odoo, just decode to string
                        image_base64 = s.image.decode('utf-8')
                except Exception:
                    image_base64 = None

                speciality_list.append({
                    'id': s.id,
                    'name': s.name or '',
                    'description': s.description or '',
                    'active': s.active,
                    'image': image_base64,
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

