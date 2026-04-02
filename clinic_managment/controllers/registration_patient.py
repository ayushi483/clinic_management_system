from odoo import http, fields
from odoo.http import request
import json
import logging
from datetime import datetime
from dateutil.relativedelta import relativedelta
from .base_controller import BaseAPIController

_logger = logging.getLogger(__name__)


class PatientRegistrationAPI(BaseAPIController):

    @http.route('/api/v19/patient/register', type='http', auth='public', methods=['POST'], csrf=False)
    def patient_register(self, **kwargs):
        try:

            raw_data = request.httprequest.get_data(as_text=True)

            if raw_data:
                data = json.loads(raw_data)
                if isinstance(data, str):
                    data = json.loads(data)
            elif kwargs:
                data = kwargs
            else:
                return self._error_response("Empty request body", "EMPTY_REQUEST", 400)

            if not isinstance(data, dict):
                return self._error_response("Invalid format", "INVALID_FORMAT", 400)

            required_fields = ["name", "mobile", "gender", "password"]
            for field in required_fields:
                if not data.get(field):
                    return self._error_response(f"{field} is required", f"MISSING_{field.upper()}", 400)

            dob_raw = data.get("dob")
            age_years = data.get("age_years")

            if dob_raw:
                try:
                    dob = datetime.strptime(dob_raw, "%Y-%m-%d").date()
                except:
                    return self._error_response("Invalid DOB format", "INVALID_DOB", 400)
            elif age_years:
                age_years = int(age_years)
                dob = datetime.today().date() - relativedelta(years=age_years)
            else:
                return self._error_response("Provide dob or age_years", "MISSING_DOB", 400)

            email = data.get("email", "")
            mobile = data.get("mobile")


            login = f"{mobile}_{int(datetime.now().timestamp())}"


            company = request.env["res.company"].sudo().search([], limit=1)
            if not company:
                return self._error_response("No company found", "NO_COMPANY", 500)

            user_env = request.env(user=1)

            user_vals = {
                "name": data.get("name"),
                "login": login,
                "password": data.get("password"),
                "email": email,
                "company_id": company.id,
                "company_ids": [(4, company.id)],
            }

            user = user_env["res.users"].sudo().create(user_vals)

            portal_group = request.env.ref("base.group_portal")
            request.env.cr.execute(
                "INSERT INTO res_groups_users_rel (gid, uid) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (portal_group.id, user.id)
            )

            patient_vals = {
                "name": data.get("name"),
                "phone": mobile,
                "email": email,
                "gender": data.get("gender"),
                "date_of_birth": dob,
                "partner_id": user.partner_id.id,
            }

            patient = request.env["clinic.patient"].sudo().create(patient_vals)
            patient.action_confirm()

            api_key, error = self._generate_api_key(user, prefix="Patient")
            if error:
                return error

            return self._json_response(
                self._success_response({
                    "patient_id": patient.id,
                    "name": patient.name,
                    "phone": patient.phone,
                    "email": patient.email,
                    "gender": patient.gender,
                    "age": patient.age,
                    "patient_code": patient.patient_code,
                    "user_id": user.id,
                    "api_key": api_key,
                    "message": "Registration successful"
                }),
                201
            )

        except Exception as e:
            _logger.exception("Registration Error")
            return self._error_response(str(e), "INTERNAL_SERVER_ERROR", 500)