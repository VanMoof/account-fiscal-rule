# Copyright 2019-2020 Vanmoof B.V.
# Copyright 2017-2020 Stefan Rijnhart <stefan@opener.amsterdam>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
import odoo.addons.decimal_precision as dp
from odoo import api, fields, models


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    taxjar_amount = fields.Float(
        'TaxJar Amount', digits=dp.get_precision('Account'),
        help='Tax amount from TaxJar')

    @api.depends('taxjar_amount')
    def _compute_amount(self):
        """ Add the taxjar amount to the line tax and the total amount """
        res = super(SaleOrderLine, self)._compute_amount()
        for line in self:
            line.price_tax += line.taxjar_amount
            line.price_total += line.taxjar_amount
        return res

    def _get_taxjar_shipping_amount(self, config):
        """ Provide the shipping amount that this line represents.
        Delegated to the line level for easier overriding """
        self.ensure_one()
        if self.product_id.id not in config.shipping_product_ids.ids:
            return 0
        return self.price_subtotal

    @api.multi
    def _get_taxjar_lines(self, config):
        """
        Prepares a representation of sale order lines to pass on to Taxjar.
        """
        res = []
        for line in self:
            if line.product_id in config.shipping_product_ids:
                continue
            line_repr = {
                'id': line.id,
                'quantity': line.product_uom_qty,
                'unit_price': line.price_unit,
                'discount': line.order_id.currency_id.round(
                    line.product_uom_qty * line.price_unit *
                    ((line.discount or 0.0) / 100.0))
            }
            tax_code = (
                line.product_id.taxjar_code_id or
                line.product_id.categ_id.taxjar_code_id).code or None
            if tax_code:
                line_repr['product_tax_code'] = tax_code
            res.append(line_repr)
        return res
