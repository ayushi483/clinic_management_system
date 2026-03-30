from odoo import http
from odoo.http import request
from .base_controller import BaseAPIController
import logging

_logger = logging.getLogger(__name__)


class PatientAPI(BaseAPIController):

    @http.route('/api/v19/get_patient_list', type='http', auth='public', methods=['GET'], csrf=False)
    def get_patient_list(self, **kwargs):
        try:
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
                self._success_response({response_data})
            )

        except Exception as e:
            _logger.exception("Error fetching patient list")
            return self._error_response(str(e))

