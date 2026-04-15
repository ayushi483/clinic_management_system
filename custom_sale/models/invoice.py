from odoo import models, fields, _

class AccountMove(models.Model):
    _inherit = 'account.move'

    sale_reference = fields.Char(string='Sale Reference')


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    sale_line_reference = fields.Char(string='Sale Line Reference')