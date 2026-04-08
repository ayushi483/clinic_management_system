from odoo import http
from odoo.http import request
from .base_controller import BaseAPIController
import logging

_logger = logging.getLogger(__name__)


class DoctorAPI(BaseAPIController):

    @http.route('/api/v19/get_doctor_list', type='http', auth='public', methods=['GET'], csrf=False)
    def get_doctor_list(self, **kwargs):
        try:
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
                    'image_1024': d.image_1024.decode('utf-8') if d.image_1024 else None,
                    'speciality': d.speciality_id.name if d.speciality_id else '',  # ✅ added
                    'speciality_id': d.speciality_id.id if d.speciality_id else None,  # ✅ added
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
            user = self._validate_api_key()
            if not hasattr(user, 'id'):
                return user

            import json
            raw_data = request.httprequest.get_data(as_text=True)

            try:
                data = json.loads(raw_data) if raw_data else kwargs
                if isinstance(data, str):
                    data = json.loads(data)
                if not isinstance(data, dict):
                    return self._error_response("Invalid request format", "INVALID_FORMAT", 400)
            except Exception:
                return self._error_response("Invalid JSON format", "INVALID_JSON", 400)

            doctor_id = data.get('doctor_id')
            if not doctor_id:
                return self._error_response("doctor_id is required", "MISSING_DOCTOR_ID", 400)

            try:
                doctor_id = int(doctor_id)
            except:
                return self._error_response("doctor_id must be integer", "INVALID_DOCTOR_ID", 400)

            doctor = request.env['clinic.doctor'].sudo().browse(doctor_id)
            if not doctor.exists():
                return self._error_response("Doctor not found", "DOCTOR_NOT_FOUND", 404)

            return self._json_response(
                self._success_response({
                    "doctor_id": doctor.id,
                    "name": doctor.name or '',
                    "phone": doctor.phone or '',
                    "email": doctor.email or '',
                    "fees": doctor.fees or 0,
                    "image": doctor.image_1024.decode('utf-8') if doctor.image_1024 else None,
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

    @http.route('/api/v19/get_doctors_by_speciality', type='http', auth='public', methods=['GET'], csrf=False)
    def get_doctors_by_speciality(self, **kwargs):
        try:
            user = self._validate_api_key()
            if not hasattr(user, 'id'):
                return user

            speciality_id = kwargs.get('speciality_id')
            if not speciality_id:
                return self._error_response("speciality_id is required", "MISSING_SPECIALITY_ID", 400)

            try:
                speciality_id = int(speciality_id)
            except:
                return self._error_response("Invalid speciality_id", "INVALID_SPECIALITY_ID", 400)

            speciality = request.env['res.speciality'].sudo().browse(speciality_id)
            if not speciality.exists():
                return self._error_response("Speciality not found", "SPECIALITY_NOT_FOUND", 404)

            doctors = request.env['clinic.doctor'].sudo().search([
                ('speciality_id', '=', speciality_id),
                ('active', '=', True)
            ])

            doctor_list = []
            for d in doctors:
                doctor_list.append({
                    'id': d.id,
                    'name': d.name or '',
                    'phone': d.phone or '',
                    'email': d.email or '',
                    'fees': d.fees or 0,
                    'image': d.image_1024.decode('utf-8') if d.image_1024 else None,
                    'speciality': d.speciality_id.name if d.speciality_id else '',
                    'total_appointment': d.total_appointment or 0,
                    'available': d.is_available or False,
                })

            return self._json_response(
                self._success_response({
                    'speciality_id': speciality_id,
                    'speciality_name': speciality.name,
                    'doctors': doctor_list,
                    'total': len(doctor_list)
                }),
                200
            )

        except Exception as e:
            _logger.exception("Error fetching doctors by speciality")
            return self._error_response(str(e), "INTERNAL_SERVER_ERROR", 500)