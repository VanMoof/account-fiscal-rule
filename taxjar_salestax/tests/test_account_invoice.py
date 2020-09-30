# Copyright 2019-2020 Vanmoof B.V.
# Copyright 2017-2020 Stefan Rijnhart <stefan@opener.amsterdam>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
from odoo.exceptions import UserError
from .common import TaxJarCase
import json
import responses


class TestAccountInvoice(TaxJarCase):
    def setUp(self):
        super().setUp()
        self.company.partner_id.write({
            'city': 'Brooklyn',
            'country_id': self.env.ref('base.us').id,
            'state_id': self.env.ref('base.state_us_27').id,
            'street': '326 Wythe Ave',
        })
        tax_account = self.env['account.account'].search(
            [('user_type_id.internal_group', '=', 'liability'),
             ('internal_type', '=', 'other'),
             ('company_id', '=', self.company.id)], limit=1)
        self.tax.write({
            'account_id': tax_account.id,
            'refund_account_id': tax_account.id,
        })

        self.us_customer = self.env['res.partner'].create({
            'city': 'Chicago',
            'country_id': self.env.ref('base.us').id,
            'name': 'Some customer',
            'state_id': self.env.ref('base.state_us_14').id,
            'street': '1450 W Cermak Rd',
        })
        self.invoice = self.env.ref('l10n_generic_coa.demo_invoice_3').copy(
            {'partner_id': self.us_customer.id})

        # Replace the second line with a shipping line.
        self.invoice.invoice_line_ids[1].write({
            'product_id': self.shipping_product.id,
            'price_unit': 100,
            'quantity': 1,
        })
        self.invoice.invoice_line_ids[
            0].product_id.taxjar_code_id = self.taxjar_code

        self.response_invoice = {
            'tax': {
                'has_nexus': False,
                'tax_source': None,
                'shipping': 0.0,
                'taxable_amount': 0,
                'rate': 0,
                'freight_taxable': True,
                'amount_to_collect': 39,
                'order_total_amount': self.invoice.amount_untaxed_signed,
                'breakdown': {
                    'line_items': [{
                        'tax_collectable': 12.40,
                        'id': self.invoice.invoice_line_ids[0].id,
                    }],
                    'shipping': {'tax_collectable': 26.60}},
            },
        }

        self.response_refund = {
            'tax': {
                'has_nexus': False,
                'tax_source': None,
                'shipping': 0.0,
                'taxable_amount': 0,
                'rate': 0,
                'freight_taxable': True,
                'amount_to_collect': -39,
                'order_total_amount': self.invoice.amount_untaxed_signed,
                'breakdown': {
                    'line_items': [{
                        'tax_collectable': -12.40,
                        'id': self.invoice.invoice_line_ids[0].id,
                    }],
                    'shipping': {'tax_collectable': -26.60}},
            },
        }
        self.payload_invoice_tax = {
            'from_city': self.company.partner_id.city,
            'from_country': self.company.partner_id.country_id.code,
            'from_state': self.company.partner_id.state_id.code,
            'from_zip': self.company.partner_id.zip,
            'line_items': [
                {'discount': x.discount,
                 'id': x.id,
                 'product_tax_code': x.product_id.taxjar_code_id.code,
                 'quantity': x.quantity,
                 'unit_price': x.price_unit
                 }
                for x in self.invoice.invoice_line_ids if
                x.product_id.id != self.shipping_product.id
            ],
            'shipping': 100,
            'to_city': self.us_customer.city,
            'to_country': self.us_customer.country_id.code,
            'to_state': self.us_customer.state_id.code,
            'to_zip': self.us_customer.zip or None,
        }

    def callback(self, request):
        """ Compare the body of the request with the payload set on the
        test object, and reply with the set response """
        if request.body is None:
            payload = None
        else:
            if isinstance(request.body, bytes):
                body = request.body.decode('utf-8')
            else:
                body = request.body
            payload = json.loads(body)
        self.assertEqual(payload, self.expected_payload)
        return (200, {}, json.dumps(self.response))

    @responses.activate
    def test_01_invoice_tax(self):
        self.response = self.response_invoice

        # Check tax amount lookup
        self.expected_payload = self.payload_invoice_tax
        responses.add_callback(
            responses.POST, 'https://api.sandbox.taxjar.com/v2/taxes',
            callback=self.callback)

        self.invoice.compute_taxes()
        self.assertEqual(self.invoice.taxjar_amount, 39)

        # Check commit of confirmed invoice with a queued job
        max_job_id = self.env['queue.job'].search(
            [], order='id desc', limit=1).id or 0

        self.invoice.taxjar_amount = 0
        self.invoice.amount_tax = 0
        self.invoice.action_invoice_open()
        self.assertEqual(self.invoice.taxjar_amount, 39)
        self.assertEqual(self.invoice.amount_tax, 39)

        job = self.env['queue.job'].search([('id', '>', max_job_id)])
        self.assertIn('account.invoice(%s,)._taxjar_commit()' %
                      self.invoice.id, job.func_string)

        invoice_number = self.invoice.number.replace('/', '_')
        self.expected_payload = {
            'transaction_id': invoice_number,
            'transaction_date': self.invoice.date_invoice.strftime('%Y/%d/%m'),
            'amount': self.invoice.amount_untaxed,
            'sales_tax': self.invoice.amount_tax,
            'from_city': self.company.partner_id.city,
            'from_country': self.company.partner_id.country_id.code,
            'from_state': self.company.partner_id.state_id.code,
            'from_zip': self.company.partner_id.zip,
            'line_items': [{
                'description': ail.name,
                'discount': ail.discount,
                'id': ail.id,
                'product_identifier': ail.product_id.default_code,
                'product_tax_code': ail.product_id.taxjar_code_id.code,
                'quantity': ail.quantity,
                'sales_tax': ail.taxjar_amount,
                'unit_price': ail.price_unit,
            } for ail in self.invoice.invoice_line_ids
                if ail.product_id.id != self.shipping_product.id],
            'shipping': 100,
            'to_city': self.us_customer.city,
            'to_country': self.us_customer.country_id.code,
            'to_state': self.us_customer.state_id.code,
            'to_zip': self.us_customer.zip or None,
        }
        responses.add_callback(
            responses.POST,
            'https://api.sandbox.taxjar.com/v2/transactions/orders',
            callback=self.callback)

        self._run_connector_job(job)

        # Check invoice amounts and created move line
        self.assertEqual(self.invoice.amount_tax, 39)
        self.assertEqual(self.invoice.amount_total, 589)
        self.assertEqual(self.invoice.amount_untaxed, 550)

        product_line = self.invoice.invoice_line_ids[0]
        self.assertEqual(product_line.taxjar_amount, 12.40)
        self.assertEqual(product_line.price_tax, 12.40)

        shipping_line = self.invoice.invoice_line_ids[1]
        self.assertEqual(shipping_line.taxjar_amount, 26.60)
        self.assertEqual(shipping_line.price_tax, 26.60)

        tax_move_line = self.invoice.move_id.line_ids.filtered(
            lambda ml: ml.tax_line_id == self.tax)
        self.assertTrue(tax_move_line)
        self.assertEqual(tax_move_line.credit, 39)
        self.assertEqual(tax_move_line.account_id, self.tax.account_id)

        # Refund the invoice
        self.env['account.invoice.refund'].with_context({
            'active_ids': [self.invoice.id],
            'active_id': self.invoice.id,
        }).create({
            'filter_refund': 'refund',
            'description': 'reason test',
        }).invoice_refund()
        refund = self.env['account.invoice'].search(
            [('refund_invoice_id', '=', self.invoice.id)])
        self.assertTrue(refund)

        self.response = self.response_refund

        # Check refund tax amount lookup
        self.expected_payload = {
            'from_city': self.company.partner_id.city,
            'from_country': self.company.partner_id.country_id.code,
            'from_state': self.company.partner_id.state_id.code,
            'from_zip': self.company.partner_id.zip,
            'line_items': [
                {'discount': x.discount,
                 'id': x.id,
                 'product_tax_code': x.product_id.taxjar_code_id.code,
                 'quantity': x.quantity,
                 'unit_price': -1 * x.price_unit
                 }
                for x in refund.invoice_line_ids if
                x.product_id.id != self.shipping_product.id
            ],
            'shipping': -100,
            'to_city': self.us_customer.city,
            'to_country': self.us_customer.country_id.code,
            'to_state': self.us_customer.state_id.code,
            'to_zip': self.us_customer.zip or None}
        responses.add_callback(
            responses.POST, 'https://api.sandbox.taxjar.com/v2/taxes',
            callback=self.callback)

        refund.compute_taxes()
        self.assertEqual(refund.taxjar_amount, 39)
        product_line = refund.invoice_line_ids[0]
        self.assertEqual(product_line.taxjar_amount, 12.40)
        self.assertEqual(product_line.price_tax, 12.40)

        shipping_line = refund.invoice_line_ids[1]
        self.assertEqual(shipping_line.taxjar_amount, 26.60)
        self.assertEqual(shipping_line.price_tax, 26.60)

        # Check if cancellation of entries schedules a job
        self.invoice.journal_id.update_posted = True
        self.invoice.action_invoice_cancel()
        job = self.env['queue.job'].search([('id', '>', job.id)])
        self.assertIn(
            'account.invoice(%s,)._taxjar_cancel()' % self.invoice.id,
            job.func_string)

        # When run, the job should call DELETE on the invoice number
        self.expected_payload = None
        self.response = {
            'order': {
                'amount': None,
                'customer_id': None,
                'exemption_type': None,
                'from_city': None,
                'from_country': None,
                'from_state': None,
                'from_street': None,
                'from_zip': None,
                'line_items': [],
                'provider': 'api',
                'sales_tax': None,
                'shipping': None,
                'to_city': None,
                'to_country': None,
                'to_state': None,
                'to_street': None,
                'to_zip': None,
                'transaction_date': None,
                'transaction_id': invoice_number,
                'transaction_reference_id': None,
                'user_id': 34768,
            }}
        responses.add_callback(
            responses.DELETE,
            'https://api.sandbox.taxjar.com/v2/transactions/orders/%s' %
            invoice_number, callback=self.callback)
        self._run_connector_job(job)

    @responses.activate
    def test_02_additional_taxex(self):
        """ There is a check on additional taxes """
        # Check tax amount lookup
        self.response = self.response_invoice
        self.expected_payload = self.payload_invoice_tax
        responses.add_callback(
            responses.POST, 'https://api.sandbox.taxjar.com/v2/taxes',
            callback=self.callback)

        extra_tax = self.env['account.tax'].search([
            ('company_id', '=', self.company.id),
            ('type_tax_use', '=', 'sale')])
        self.invoice.invoice_line_ids[0].invoice_line_tax_ids = extra_tax
        with self.assertRaisesRegexp(UserError, 'Additional taxes'):
            with self.env.cr.savepoint():
                self.invoice.action_invoice_open()

        # Taxjar tax is OK
        self.invoice.invoice_line_ids[0].invoice_line_tax_ids = self.tax
        self.invoice.action_invoice_open()

    @responses.activate
    def test_03_invoice_currency(self):
        """ Invoices are committed in TaxJar in USD """
        self.invoice.currency_id = self.env.ref('base.EUR')

        # Enforce a rate of 2 USD to 1 EUR
        self.env['res.currency.rate'].search(
            [('currency_id', '=', self.env.ref('base.USD').id)]).unlink()
        self.env['res.currency.rate'].create({
            'currency_id': self.env.ref('base.USD').id,
            'name': '2020-01-01',
            'rate': .5,
        })

        # Check tax amount lookup
        self.response = self.response_invoice
        self.expected_payload = self.payload_invoice_tax
        responses.add_callback(
            responses.POST, 'https://api.sandbox.taxjar.com/v2/taxes',
            callback=self.callback)

        self.invoice.compute_taxes()
        self.assertEqual(self.invoice.taxjar_amount, 39)

        # Check commit of confirmed invoice with a queued job
        max_job_id = self.env['queue.job'].search(
            [], order='id desc', limit=1).id or 0

        self.invoice.taxjar_amount = 0
        self.invoice.amount_tax = 0
        self.invoice.action_invoice_open()
        self.assertEqual(self.invoice.taxjar_amount, 39)
        self.assertEqual(self.invoice.amount_tax, 39)

        job = self.env['queue.job'].search([('id', '>', max_job_id)])
        self.assertIn('account.invoice(%s,)._taxjar_commit()' %
                      self.invoice.id, job.func_string)

        invoice_number = self.invoice.number.replace('/', '_')
        # Amounts in the payload are converted according to the set rate
        self.expected_payload = {
            'transaction_id': invoice_number,
            'transaction_date': self.invoice.date_invoice.strftime('%Y/%d/%m'),
            'amount': self.invoice.amount_untaxed / 2,
            'sales_tax': self.invoice.amount_tax / 2,
            'from_city': self.company.partner_id.city,
            'from_country': self.company.partner_id.country_id.code,
            'from_state': self.company.partner_id.state_id.code,
            'from_zip': self.company.partner_id.zip,
            'line_items': [{
                'description': ail.name,
                'discount': ail.discount,
                'id': ail.id,
                'product_identifier': ail.product_id.default_code,
                'product_tax_code': ail.product_id.taxjar_code_id.code,
                'quantity': ail.quantity,
                'sales_tax': ail.taxjar_amount / 2,
                'unit_price': ail.price_unit / 2,
            } for ail in self.invoice.invoice_line_ids
                if ail.product_id.id != self.shipping_product.id],
            'shipping': 50,
            'to_city': self.us_customer.city,
            'to_country': self.us_customer.country_id.code,
            'to_state': self.us_customer.state_id.code,
            'to_zip': self.us_customer.zip or None,
        }
        responses.add_callback(
            responses.POST,
            'https://api.sandbox.taxjar.com/v2/transactions/orders',
            callback=self.callback)

        self._run_connector_job(job)

        # Check invoice amounts and created move line
        self.assertEqual(self.invoice.amount_tax, 39)
        self.assertEqual(self.invoice.amount_total, 589)
        self.assertEqual(self.invoice.amount_untaxed, 550)

        product_line = self.invoice.invoice_line_ids[0]
        self.assertEqual(product_line.taxjar_amount, 12.40)
        self.assertEqual(product_line.price_tax, 12.40)

        shipping_line = self.invoice.invoice_line_ids[1]
        self.assertEqual(shipping_line.taxjar_amount, 26.60)
        self.assertEqual(shipping_line.price_tax, 26.60)

        tax_move_line = self.invoice.move_id.line_ids.filtered(
            lambda ml: ml.tax_line_id == self.tax)
        self.assertTrue(tax_move_line)
        # Tax amount on the move line is halved too
        self.assertEqual(tax_move_line.credit, self.invoice.amount_tax / 2)
        self.assertEqual(tax_move_line.account_id, self.tax.account_id)
