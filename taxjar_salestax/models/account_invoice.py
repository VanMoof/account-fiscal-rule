# Copyright 2017-2020 Vanmoof B.V.
# Copyright 2017-2020 Stefan Rijnhart <stefan@opener.amsterdam>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
import odoo.addons.decimal_precision as dp
from odoo import api, fields, models
from odoo.addons.queue_job.job import job
from odoo.exceptions import UserError
from odoo.tools.translate import _


class AccountInvoice(models.Model):
    _inherit = 'account.invoice'

    warehouse_id = fields.Many2one(
        'stock.warehouse', 'Warehouse',
        help=('Determines the TaxJar origin address. You can override it '
              'here without affecting any related stock operations.'))
    taxjar_applies = fields.Boolean(compute="_compute_taxjar_applies")
    taxjar_amount = fields.Float(
        string='TaxJar Amount', digits=dp.get_precision('Account'),
        readonly=True)
    taxjar_shipping_amount = fields.Float(
        string='Shipping Cost', digits=dp.get_precision('Account'),
        store=True, readonly=True, compute='_compute_taxjar_shipping_amount')

    def _compute_taxjar_applies(self):
        """
        Determine if the invoice's related company has a Taxjar
        configuration that is valid for this invoice.
        """
        for invoice in self:
            invoice.taxjar_applies = (
                invoice.type in ('out_invoice', 'out_refund') and bool(
                    invoice._get_taxjar_params()[0]))

    @api.depends('invoice_line_ids.price_subtotal')
    def _compute_taxjar_shipping_amount(self):
        for inv in self:
            config, partner = inv._get_taxjar_params()
            if not config:
                continue
            shipping_amount = 0.0
            for line in inv.invoice_line_ids:
                shipping_amount += line._get_taxjar_shipping_amount(config)
            sign = -1 if inv.type == 'out_refund' else 1
            inv.taxjar_shipping_amount = sign * shipping_amount

    def _get_taxjar_partner(self):
        """ Partner for TaxJar to use as destination """
        self.ensure_one()
        order = self.get_sale_order()
        if order:
            return order._get_taxjar_partner()
        return self.partner_id

    def get_sale_order(self):
        """ Return the first sale order linked to this invoice """
        self.ensure_one()
        order_lines = (
            self.mapped('invoice_line_ids.sale_line_ids') or
            self.refund_invoice_id.mapped('invoice_line_ids.sale_line_ids'))
        if order_lines:
            return order_lines[0].order_id
        if self.origin:  # support legacy orders
            a = self.origin
            if len(a.split(':')) > 1:
                so_origin = a.split(':')[1]
            else:
                so_origin = a.split(':')[0]
            return self.env['sale.order'].search(
                [('name', '=', so_origin)], limit=1)
        return self.env['sale.order']

    def _get_taxjar_origin_address(self):
        """ Partner for TaxJar to use as origin """
        self.ensure_one()
        order = self.get_sale_order()
        return (
            order.warehouse_id.partner_id or
            self.warehouse_id.partner_id or
            self.company_id.partner_id)

    def action_cancel(self):
        """ Cancel the invoice in TaxJar """
        to_cancel = self.filtered(
            lambda invoice: invoice.type in ('out_invoice', 'out_refund') and
            invoice.state in ('open', 'paid'))
        res = super().action_cancel()
        for invoice in to_cancel.filtered(
                lambda invoice: invoice.state == 'cancel'):
            config, partner = invoice._get_taxjar_params()
            if config:
                invoice.with_delay()._taxjar_cancel()
        return res

    def compute_taxes(self):
        """ Fetch TaxJar taxes when applicable """
        for invoice in self:
            invoice._call_taxjar()
        # Taxes are reset in the super method
        return super().compute_taxes()

    def action_move_create(self):
        """ Fetch TaxJar taxes when applicable """
        for invoice in self:
            if invoice.taxjar_applies:
                invoice.compute_taxes()
        return super().action_move_create()

    def button_update_taxjar_taxes(self):
        """ Recompute taxes, which fetches TaxJar taxes when applicable """
        return self.compute_taxes()

    def _cleanup_taxjar(self):
        """ Reset tax fields """
        self.ensure_one()
        self.invoice_line_ids.filtered(
            lambda l: l.taxjar_amount).write({'taxjar_amount': 0.0})
        if self.taxjar_amount:
            self.taxjar_amount = 0

    def _call_taxjar(self):
        """ Fetch the sales tax for this invoice. Don't call directly,
        because it does not populate the native tax amounts on the document.
        Call compute_taxes instead.
        """
        self.ensure_one()
        config, partner = self._get_taxjar_params()
        if not config:
            self._cleanup_taxjar()
            return

        # Only allow the preloaded taxjar tax
        tax = self.env['account.tax'].search(
            [('name', '=ilike', 'taxjar'),
             ('company_id', '=', self.company_id.id)],
            order='id desc', limit=1)
        if tax.amount:
            raise UserError(_(
                'A tax amount is configured on the TaxJar tax. '
                'As this is a placeholder for tax amounts fetched '
                'externally, this is not allowed.'))

        # Some sanity checking on the tax' configuration
        if tax.price_include:
            raise UserError(_(
                'The TaxJar tax is configured for taxes included in the '
                'product\'s sales price. This configuration is not '
                'supported.'))
        if self.invoice_line_ids.mapped('invoice_line_tax_ids') - tax:
            raise UserError(_(
                'Taxes on this invoice are fetched using TaxJar. '
                'Additional taxes are not supported. Please remove '
                'these taxes from the invoice lines.'))

        origin = self._get_taxjar_origin_address()
        lines = self.invoice_line_ids._get_taxjar_lines(config=config)
        sign = -1 if self.type == 'out_refund' else 1

        res = config.tax_for_order(
            origin, partner, lines, self.taxjar_shipping_amount)

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
            items[0][1] += (total - line_total)

        for line_id, amount in items:
            line = self.env['account.invoice.line'].browse(line_id)
            line.taxjar_amount = amount
            if tax not in line.invoice_line_tax_ids:
                line.invoice_line_tax_ids += tax

        if res.breakdown.shipping.tax_collectable:
            shipping_tax = sign * res.breakdown.shipping.tax_collectable
            shipping_lines = self.invoice_line_ids.filtered(
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
            # Ensure the TaxJar tax is present on the lines
            shipping_lines.write({'invoice_line_tax_ids': [(4, tax.id)]})

        self.taxjar_amount = sign * (res.amount_to_collect or 0.0)
        return self.taxjar_amount

    def _get_taxjar_params(self):
        """ Check if TaxJar taxes apply to this invoice.
        Returns the appropriate config and tax partner, else (False, False)
        """
        self.ensure_one()
        if self.type not in ('out_invoice', 'out_refund'):
            return False, False
        config = self.env['taxjar.config'].with_context(
            force_company=self.company_id.id)._get_config()
        if not config:
            return False, False
        partner = self._get_taxjar_partner()
        if (not partner.country_id or
                partner.country_id not in config.country_ids):
            return False, False
        return config, partner

    @job
    def _taxjar_commit(self):
        """ Create the transaction for this invoice in TaxJar from a queued job
        """
        self.ensure_one()
        config, partner = self._get_taxjar_params()
        if not config or not config.enable_tax_reporting:
            return
        if self.state not in ('open', 'paid'):
            raise UserError(
                _('Cannot commit an TaxJar invoice (%s) that is not in a '
                  'confirmed state (%s)') % (self.name, self.state))

        origin = self._get_taxjar_origin_address()
        lines = self.invoice_line_ids._get_taxjar_lines(
            config=config, commit=True)

        if self.type == 'out_refund' and self.refund_invoice_id:
            refund_reference = self.refund_invoice_id.number
        else:
            refund_reference = False
        invoice_date = self.date_invoice or fields.Date.context_today(self)
        res = config.create_order(
            self.number, invoice_date,
            self.amount_untaxed, self.taxjar_amount,
            origin, partner, lines,
            self.taxjar_shipping_amount, self.company_id, self.currency_id,
            refund_reference=refund_reference)
        return res

    @job
    def _taxjar_cancel(self):
        """ Delete the transaction for this invoice in TaxJar from a queued job
        """
        self.ensure_one()
        config, _partner = self._get_taxjar_params()
        if not config or config.enable_tax_reporting:
            return
        config.cancel_order(self.move_name, refund=self.type == 'out_refund')

    def invoice_validate(self):
        """Commit the TaxJar invoice record on invoice validation """
        to_commit = self.filtered(
            lambda inv: inv.state in ('draft', 'proforma2'))
        res = super().invoice_validate()
        for invoice in to_commit:
            if invoice.taxjar_applies:
                invoice.with_delay()._taxjar_commit()
        return res

    def _prepare_tax_line_vals(self, line, tax):
        """ Plug in the amount fetched from the TaxJar API """
        res = super()._prepare_tax_line_vals(line, tax)
        if tax['name'].lower() == 'taxjar':
            res['amount'] = line.taxjar_amount
        return res
