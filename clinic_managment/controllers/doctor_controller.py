from odoo import http
from odoo.http import request
from .base_controller import BaseAPIController
import logging

_logger = logging.getLogger(__name__)


class DoctorAPI(BaseAPIController):

    @http.route('/api/v19/get_doctor_list', type='http', auth='public', methods=['GET'], csrf=False)
    def get_doctor_list(self, **kwargs):
        try:
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
                })
            )

        except Exception as e:
            _logger.exception("Error fetching doctor list")
            return self._error_response(str(e))