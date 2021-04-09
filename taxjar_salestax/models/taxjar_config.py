# Copyright 2019-2020 Vanmoof B.V.
# Copyright 2017-2020 Stefan Rijnhart <stefan@opener.amsterdam>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
import logging
import taxjar
from taxjar.exceptions import TaxJarResponseError

from odoo import api, fields, models
from odoo.exceptions import ValidationError, UserError
from odoo.tools.translate import _

from odoo.addons.taxjar_salestax.exceptions import TaxJarAddressNotFound

_logger = logging.getLogger(__name__)


class TaxjarConfig(models.Model):
    _name = 'taxjar.config'
    _description = 'TaxJar Integration'
    _rec_name = 'company_id'

    @api.model
    def _get_default_country_ids(self):
        return self.env['res.country'].search([('code', 'in', ['US', 'CA'])])

    @api.model
    def _get_default_company(self):
        return self.env.user.company_id

    api_key = fields.Char(required=True)
    sandbox = fields.Boolean(
        default=False,
        help=('Use the sandbox environment provided by TaxJar, instead of '
              'the live environment. Use for testing purposes.'))
    request_timeout = fields.Integer(
        help=('TaxJar API request time out in seconds'), default=30)
    logging = fields.Boolean(
        'Enable Logging',
        help='Post technical TaxJar API messages to the Odoo log.')
    address_validation = fields.Boolean(
        help='Attempt automatic address validation when creating partners',
        default=True)
    enable_tax_calculation = fields.Boolean(
        'Enable Tax Calculation',
        help='Uncheck to disable TaxJar tax calculation and reporting',
        default=True)
    enable_tax_reporting = fields.Boolean(
        'Enable Tax Reporting',
        help=('When not checked, orders are not committed in TaxJar and do '
              'not show up in the TaxJar reporting.'))
    country_ids = fields.Many2many(
        comodel_name='res.country',
        relation='taxjar_config_country_rel',
        column1='taxjar_config_id', column2='country_id',
        string='Countries', default=_get_default_country_ids,
        help=('TaxJar will be applied to orders and invoices with an origin '
              'address in one of these countries'))
    company_id = fields.Many2one(
        'res.company', 'Company', required=True,
        default=_get_default_company,
        help='Company for which tax computation is delegated to TaxJar')
    shipping_product_ids = fields.Many2many(
        comodel_name='product.product',
        relation='taxjar_config_shipping_product_rel',
        column1='taxjar_config_id', column2='product_id',
        string='Shipping Products',
        help=('Amounts from lines with these products will be mentioned '
               'separately as shipping costs in the call to TaxJar'))

    @api.model
    def _get_config(self, company=None):
        """ Returns an active TaxJar configuration for this company """
        if company is None:
            company_id = (self.env.context.get('company_id') or
                          self.env.context.get('force_company'))
            if company_id:
                company = self.env['res.company'].browse(company_id)
            else:
                company = self.env.user.company_id
        return self.sudo().search(
            ['|', ('company_id', '=', company.id), ('company_id', '=', False),
             ('enable_tax_calculation', '=', True)],
            order='company_id asc', limit=1)

    @api.multi
    def _get_url(self):
        self.ensure_one()
        if self.sandbox:
            return 'https://api.sandbox.taxjar.com'
        return 'https://api.taxjar.com'

    @api.multi
    def _get_options(self):
        self.ensure_one()
        options = {}
        if self.request_timeout:
            options['timeout'] = self.request_timeout
        return options

    @api.multi
    def _get_client(self):
        self.ensure_one()
        if not taxjar:
            raise UserError(_(
                'The taxjar Python library is not available.'))
        return taxjar.Client(
            api_key=self.api_key,
            api_url=self._get_url(),
            options=self._get_options())

    @api.multi
    def _wrap_for_error(self, method, *args):
        """ If an error occurs, log profusely but raise a concise UserError """
        self.ensure_one()
        client = self._get_client()
        try:
            res = getattr(client, method)(*args)
        except TaxJarResponseError as e:
            # A failed address validation raises a 404 but has to be
            # distinguished from e.g. Route not found
            if (method == 'validate_address' and '404' in str(e) and
                getattr(e, 'full_response', {}).get(
                    'detail') == 'Resource can not be found'):
                raise TaxJarAddressNotFound()
            msg = 'Error on taxjar.%s(): %s. Reason: %s' % (
                method, e, e.full_response.get('detail'))
            _logger.exception('%s -- %s' % (msg, args))
            raise UserError(msg)
        return res

    @staticmethod
    def _convert_transaction_id(transaction_id):
        """ REST API no like slashes in invoice numbers
        DELETE /v2/transactions/orders/SAJ/2019/0002
        So we replace slashes with underscores """
        if not isinstance(transaction_id, str):
            return transaction_id
        return transaction_id.replace('/', '_')

    @api.multi
    def tax_for_order(
            self, ship_from_address, shipping_address, line_items, shipping):
        self.ensure_one()
        if not line_items:
            return 0.0
        values = {
            'shipping': shipping,
            'line_items': line_items,
        }
        values.update(ship_from_address._taxjar('from'))
        values.update(shipping_address._taxjar('to'))
        if self.logging:
            _logger.debug('tax_for_order: %s', values)
        res = self._wrap_for_error('tax_for_order', values)
        if self.logging:
            _logger.debug('Response: %s', res)
        return res

    @api.model
    def apply_currency_rate(self, company, currency, amount, date):
        """ Convert to the TaxJar native currency, which is always USD. """
        if currency == self.env.ref('base.USD'):
            return self.env.ref('base.USD').round(amount)
        return currency._convert(
            amount, self.env.ref('base.USD'),
            company, date or fields.Date.context_today(self))

    @api.multi
    def create_order(
            self, transaction_id, transaction_date, amount_untaxed, tax_amount,
            ship_from_address, shipping_address, items, shipping,
            company, currency, refund_reference=False):
        """
        :param refund_reference: the original transaction for which this is a
        refund. If this reference is not False, the order is considered to be
        a refund.

        At this point, currency conversion is applied because we need to
        register the order in TaxJar in USD. """
        self.ensure_one()
        if not items:
            raise ValidationError(
                'An order without any lines cannot be created in TaxJar')

        for item in items:
            for key in ['unit_price', 'discount', 'sales_tax']:
                item[key] = self.apply_currency_rate(
                    company, currency, item[key], transaction_date)

        values = {
            'transaction_id': self._convert_transaction_id(transaction_id),
            'transaction_date': transaction_date.strftime('%Y/%d/%m'),
            'amount': self.apply_currency_rate(
                company, currency, amount_untaxed, transaction_date),
            'sales_tax': self.apply_currency_rate(
                company, currency, tax_amount, transaction_date),
            'shipping': self.apply_currency_rate(
                company, currency, shipping, transaction_date),
            'line_items': items,
        }
        values.update(ship_from_address._taxjar('from'))
        values.update(shipping_address._taxjar('to'))
        if self.logging:
            _logger.debug('create_order: %s', values)
        if refund_reference:
            values['transaction_reference_id'] = refund_reference
            method = 'create_refund'
        else:
            method = 'create_order'
        res = self._wrap_for_error(method, values)
        if self.logging:
            _logger.debug('Response: %s', res)
        return res

    @api.multi
    def cancel_order(self, transaction_id, refund=False):
        self.ensure_one()
        method = 'delete_refund' if refund else 'delete_order'
        transaction_id = self._convert_transaction_id(transaction_id)
        _logger.info('%s(%s)', method, transaction_id)
        res = self._wrap_for_error(method, transaction_id)
        if self.logging:
            _logger.debug('Response: %s', res)
        return res

    @api.multi
    def _onthefly(self, values):
        """ Tiny thin layer between Odoo and the taxjar API, useful to fetch
        tax amounts for unmaterialized orders without persistent records. """
        self.ensure_one()
        if not values['line_items']:
            return 0.0
        if 'shipping' not in values:
            values['shipping'] = 0.0
        if self.logging:
            _logger.debug('tax_for_order: %s', values)
        res = self._wrap_for_error('tax_for_order', values)
        if self.logging:
            _logger.debug('Response: %s', res)
        return res

    @api.onchange('enable_tax_calculation')
    def onchange_enable_tax_calculation(self):
        if not self.enable_tax_calculation and self.enable_tax_reporting:
            self.enable_tax_reporting = False

    @api.onchange('enable_tax_reporting')
    def onchange_enable_tax_reporting(self):
        if not self.enable_tax_calculation and self.enable_tax_reporting:
            self.enable_tax_calculation = True

    @api.onchange('sandbox')
    def onchange_sandbox(self):
        """ Mention incompatibility of sandbox and address validation """
        if self.sandbox and self.address_validation:
            self.address_validation = False
            return {'warning': {
                'title': _('Note'),
                'message': _('The TaxJar Sandbox does not support address '
                             'validation so I\'m disabling it now for you.')}}

    @api.multi
    def test(self):
        self.ensure_one()
        client = self._get_client()
        try:
            client.categories()  # simplest call
        except TaxJarResponseError as e:
            raise UserError(
                'Connection Error: {}. Hint: Either Api key is wrong '
                'or your plan does not allow access to the sandbox '
                'environment'.format(e.message))
        raise UserError(
            'Connection successful.')

    @api.multi
    def import_categories(self):
        self.ensure_one()
        client = self._get_client()
        for category in client.categories():
            existing = self.env['taxjar.product.code'].search(
                [('code', '=', category.product_tax_code)])
            if existing:
                existing.write({
                    'name': category.name,
                    'description': category.description,
                })
                continue
            self.env['taxjar.product.code'].create({
                'code': category.product_tax_code,
                'name': category.name,
                'description': category.description,
            })
        return True
