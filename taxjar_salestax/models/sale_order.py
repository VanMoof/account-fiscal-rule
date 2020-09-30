# Copyright 2019-2020 Vanmoof B.V.
# Copyright 2017-2020 Stefan Rijnhart <stefan@opener.amsterdam>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
import logging
import odoo.addons.decimal_precision as dp
from odoo import fields, models
from odoo.exceptions import UserError
from odoo.tools.translate import _

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    taxjar_amount = fields.Float(
        'Total TaxJar Amount', digits=dp.get_precision('Account'),
        readonly=True, help=(
            'The total TaxJar order amount. This is just for reference '
            'purposes. For calculations, the line amounts are used.'))
    taxjar_applies = fields.Boolean(compute="_compute_taxjar_applies")
    taxjar_policy = fields.Selection(
        [('shipping', 'Use shipping address'),
         ('pickup', 'Pick-up from shop or warehouse')],
        readonly=True,
        states={
            'draft': [('readonly', False)],
            'sent': [('readonly', False)],
        },
        default='shipping')

    def _compute_taxjar_applies(self):
        """
        Determine if the sale order's related company has a Taxjar
        configuration that is valid for this order.
        """
        for order in self:
            order.taxjar_applies = bool(order._get_taxjar_params()[0])

    def button_update_taxjar_taxes(self):
        """
        In this module, tax is not automatically updated using stored
        computed fields, so when 'update taxes' is clicked in the UI,
        actually fetch tax amounts from TaxJar.
        """
        self._call_taxjar()

    def _get_taxjar_partner(self):
        """ Partner for TaxJar to use as destination """
        self.ensure_one()
        if self.taxjar_policy == 'pickup':
            if self.warehouse_id.partner_id:
                return self.warehouse_id.partner_id
            _logger.warn(
                'No partner set on warehouse %s. Cannot apply "pickup" '
                'TaxJar policy for sale order %s', self.warehouse_id.name,
                self.name)
        return self.partner_shipping_id

    def _get_taxjar_origin_address(self):
        """ Partner for TaxJar to use as origin """
        return self.warehouse_id.partner_id or self.company_id.partner_id

    def _get_taxjar_params(self):
        self.ensure_one()
        config = self.env['taxjar.config'].with_context(
            force_company=self.company_id.id)._get_config()
        if not config:
            return False, False
        partner = self._get_taxjar_partner()
        if partner.country_id not in config.country_ids:
            return False, False
        return config, partner

    def _cleanup_taxjar(self):
        """ Reset tax fields """
        self.ensure_one()
        self.order_line.filtered(
            lambda l: l.taxjar_amount).write({'taxjar_amount': 0.0})
        if self.taxjar_amount:
            self.taxjar_amount = 0

    def _call_taxjar(self):
        """ Recompute the TaxJar tax amount for order and shipping lines """
        self.ensure_one()
        config, partner = self._get_taxjar_params()
        if not config:
            self._cleanup_taxjar()
            return

        tax = self.env['account.tax'].search(
            [('name', '=ilike', 'taxjar'),
             ('company_id', '=', self.company_id.id)], limit=1)
        if self.order_line.mapped('tax_id') - tax:
            raise UserError(
                _('Taxes on this order are fetched using TaxJar. '
                  'Additional taxes are not supported. Please remove '
                  'these taxes from the order lines.'))

        origin = self._get_taxjar_origin_address()
        lines = self.order_line._get_taxjar_lines(config=config)

        shipping_amount = 0
        for line in self.order_line:
            shipping_amount += line._get_taxjar_shipping_amount(config)

        res = config.tax_for_order(
            origin, partner, lines, shipping_amount)

        # Collect out the rounding difference
        # and assign it to the line with the largest amount
        total = self.currency_id.round(res.amount_to_collect or 0.0)
        line_total = (
            sum(self.currency_id.round(item.tax_collectable or 0.0)
                for item in res.breakdown.line_items) +
            self.currency_id.round(
                res.breakdown.shipping.tax_collectable or 0.0))

        items = sorted(
            [[int(item.id), item.tax_collectable]
             for item in res.breakdown.line_items],
            key=lambda item: abs(item[1]), reverse=True)
        if items:
            items[0][1] += total - line_total

        for line_id, amount in items:
            self.env['sale.order.line'].browse(
                line_id).taxjar_amount = amount

        if res.breakdown.shipping.tax_collectable:
            # Distribute across all shipping lines
            shipping_tax = res.breakdown.shipping.tax_collectable
            shipping_lines = self.order_line.filtered(
                lambda l: l.product_id in config.shipping_product_ids)
            shipping_tax_per_line = self.currency_id.round(
                shipping_tax / len(shipping_lines))

            if len(shipping_lines) > 1:
                shipping_lines[:-1].write(
                    {'taxjar_amount': shipping_tax_per_line})
                shipping_tax -= (
                    len(shipping_lines) - 1) * shipping_tax_per_line
            # Prevent rounding difference by setting the remainder last
            shipping_lines[-1:].taxjar_amount = shipping_tax

        self.taxjar_amount = res.amount_to_collect or 0.0
        return self.taxjar_amount

    def action_confirm(self):
        """ Fetch tax amounts from TaxJar on confirmation """
        res = super().action_confirm()
        for order in self:
            order._call_taxjar()
        return res
