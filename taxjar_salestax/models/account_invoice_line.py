# Copyright 2017-2020 Stefan Rijnhart <stefan@opener.amsterdam>
# Copyright 2017-2020 Vanmoof B.V.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
import odoo.addons.decimal_precision as dp
from odoo import api, fields, models


class AccountInvoiceLine(models.Model):
    _inherit = 'account.invoice.line'

    taxjar_amount = fields.Float(
        'TaxJar Amount', digits=dp.get_precision('Account'))

    @api.one  # noqa
    @api.depends('taxjar_amount')
    def _compute_price(self):
        """ Add the TaxJar Tax amount as a replacement of a regular tax'
        calculated amount.
        """
        res = super(AccountInvoiceLine, self)._compute_price()
        if self.taxjar_amount:
            self.price_total += self.taxjar_amount
        return res

    @api.multi
    def _get_taxjar_lines(self, config, commit=False):
        """
        Prepares a representation of invoice lines to pass on to Taxjar.

        :param commit: when True, tax amount, product sku and
        description are present in each line.
        """
        items = []
        for line in self:
            if line.product_id in config.shipping_product_ids:
                continue
            sign = -1 if line.invoice_id.type == 'out_refund' else 1
            item = {
                'id': line.id,
                'quantity': line.quantity,
                'unit_price': sign * line.price_unit,
                'discount': line.invoice_id.currency_id.round(
                    sign * line.quantity * line.price_unit *
                    (line.discount or 0.0) / 100.0)
            }
            tax_code = (
                line.product_id.taxjar_code_id or
                line.product_id.categ_id.taxjar_code_id).code or None
            if tax_code:
                item['product_tax_code'] = tax_code
            if commit:
                item.update({
                    'product_identifier': line.product_id.default_code or None,
                    'description': line.name,
                    'sales_tax': sign * line.taxjar_amount,
                })
            items.append(item)
        return items

    @api.multi
    def _get_taxjar_shipping_amount(self, config):
        """ Provide the shipping amount that this line represents.
        Delegated to the line level for easier overriding """
        self.ensure_one()
        if self.product_id.id not in config.shipping_product_ids.ids:
            return 0
        amount = self.price_unit * self.quantity
        if self.discount:
            amount = (1 - (self.discount / 100)) * amount
        return self.invoice_id.currency_id.round(amount)
