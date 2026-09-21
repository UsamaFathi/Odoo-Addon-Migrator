from odoo import fields, models

class SaleOrder(models.Model):
    _inherit = 'sale.order'
    x_legacy = fields.Char()

    def removed_in_target(self):
        return super().action_confirm()
