from odoo import fields, models


class RealisticPackaging(models.Model):
    _inherit = 'product.packaging'

    migration_note = fields.Char()


class RealisticSaleOrder(models.Model):
    _inherit = 'sale.order'

    legacy_note = fields.Char()
    show_task_button = fields.Boolean()

    def _cart_update(self, product_id, add_qty=0, set_qty=0, **kwargs):
        return super()._cart_update(product_id, add_qty=add_qty, set_qty=set_qty, **kwargs)
