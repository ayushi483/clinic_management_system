from odoo import models, fields, api
from odoo.exceptions import ValidationError


class Delivery(models.Model):
    _inherit = 'stock.picking'
    sale_ref = fields.Char(string="Sale Reference" , related= "sale_id.delivery_ref")
    # stock_move = fields.Char(string="Sale Reference")


class DeliveryLine(models.Model):
    _inherit = 'stock.move'
    sale_line_reference = fields.Char(string="Sale Line Reference")
    # stock_move = fields.Char(string="Sale Line Reference")
