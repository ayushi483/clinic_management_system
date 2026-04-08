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
                    return self._error_response(
                        f"{field} is required",
                        f"MISSING_{field.upper()}",
                        400
                    )

            dob_raw = data.get("dob")
            age_years = data.get("age_years")

            if dob_raw:
                try:
                    dob = datetime.strptime(dob_raw, "%Y-%m-%d").date()
                except Exception:
                    return self._error_response("Invalid DOB format", "INVALID_DOB", 400)
            elif age_years:
                age_years = int(age_years)
                dob = datetime.today().date() - relativedelta(years=age_years)
            else:
                return self._error_response("Provide dob or age_years", "MISSING_DOB", 400)

            email = data.get("email", "").strip()
            mobile = data.get("mobile", "").strip()

            if email:
                existing_user = request.env['res.users'].sudo().search([
                    ('email', '=', email)
                ], limit=1)
                if existing_user:
                    return self._error_response("Email already registered", "EMAIL_EXISTS", 400)

            existing_patient = request.env['clinic.patient'].sudo().search([
                ('phone', '=', mobile)
            ], limit=1)
            if existing_patient:
                return self._error_response("Mobile number already registered", "MOBILE_EXISTS", 400)

            company = request.env["res.company"].sudo().search([], limit=1)
            if not company:
                return self._error_response("No company found", "NO_COMPANY", 500)

            portal_group = request.env.ref("base.group_portal")
            internal_group = request.env.ref("base.group_user")

            # Step 1: Create user (no group fields in create)
            user = request.env["res.users"].sudo().with_context(
                no_reset_password=True
            ).create({
                "name": data.get("name"),
                "login": email or mobile,
                "password": data.get("password"),
                "email": email,
                "company_id": company.id,
                "company_ids": [(4, company.id)],
            })

            # Step 2: Assign portal group via group_ids on res.users (Odoo 19)
            # group_ids is the correct writable field on res.users AFTER creation
            user.sudo().write({
                'group_ids': [
                    (4, portal_group.id),    # add portal
                    (3, internal_group.id),  # remove internal
                ]
            })

            # Step 3: Sync partner fields
            user.partner_id.sudo().write({
                'email': email,
                'phone': mobile,
                'name': data.get("name"),
            })

            _logger.info(
                f"Portal user created: id={user.id}, login={user.login}, "
                f"email={user.email}, partner_id={user.partner_id.id}"
            )

            # Step 4: Create patient
            existing_patient_for_partner = request.env["clinic.patient"].sudo().search([
                ('partner_id', '=', user.partner_id.id)
            ], limit=1)

            if existing_patient_for_partner:
                patient = existing_patient_for_partner
            else:
                patient = request.env["clinic.patient"].sudo().create({
                    "name": data.get("name"),
                    "phone": mobile,
                    "email": email,
                    "gender": data.get("gender"),
                    "date_of_birth": dob,
                    "partner_id": user.partner_id.id,
                })

            patient.action_confirm()

            _logger.info(f"Patient created: id={patient.id}, partner_id={patient.partner_id.id}")

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
