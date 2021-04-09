# Copyright 2019-2020 Vanmoof B.V.
# Copyright 2017-2020 Stefan Rijnhart <stefan@opener.amsterdam>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
from odoo.exceptions import UserError
from .common import TaxJarCase
import json
import responses


class TestSaleOrder(TaxJarCase):
    def setUp(self):
        super().setUp()
        # Set-up the company in the US
        self.company.partner_id = self.env['res.partner'].create({
            'name': 'main_partner',
            'street': '1450 W Cermak Rd',
            'city': 'Chicago',
            'state_id': self.env.ref('base.state_us_14').id,
            'country_id': self.env.ref('base.us').id,
        })

        self.invoice_partner = self.env.ref('base.res_partner_address_10')
        self.shipping_partner = self.env.ref('base.res_partner_address_17')
        # Pick an order from a US customer
        self.order = self.env.ref('sale.sale_order_3').copy({
            'partner_invoice_id': self.invoice_partner.id,
            'partner_shipping_id': self.shipping_partner.id,
            'taxjar_policy': 'shipping',
        })

        # Set a taxjar product code on one of the lines
        self.order.order_line[0].product_id.write({
            'taxjar_code_id': self.taxjar_code.id,
        })

        # Add two discounted shipping line
        self.order.order_line[-1].copy(default={
            'discount': 30,
            'order_id': self.order.id,
            'price_unit': 60,
            'product_id': self.shipping_product.id,
        })
        self.order.order_line[-1].copy(default={
            'discount': 30,
            'order_id': self.order.id,
            'price_unit': 40,
            'product_id': self.shipping_product.id,
        })

    def callback(self, request):
        payload = json.loads(
            request.body.decode('utf-8')
            if isinstance(request.body, bytes) else request.body)
        expected_payload = {
            'from_city': self.order.warehouse_id.partner_id.city,
            'from_country':
                self.order.warehouse_id.partner_id.country_id.code,
            'from_state': self.order.warehouse_id.partner_id.state_id.code,
            'from_zip': self.order.warehouse_id.partner_id.zip,
            'line_items': [
                {'discount': sol.discount,
                 'id': sol.id,
                 'product_tax_code': sol.product_id.taxjar_code_id.code,
                 'quantity': sol.product_uom_qty,
                 'unit_price': sol.price_unit}
                for sol in self.order.order_line if
                sol.product_id.id != self.shipping_product.id],
            'shipping': 70.0,
            'to_city': self.order.partner_shipping_id.city,
            'to_country': self.order.partner_shipping_id.country_id.code,
            'to_state': self.order.partner_shipping_id.state_id.code,
            'to_zip': self.order.partner_shipping_id.zip or None}

        # Purge missing taxjar product codes
        for line in expected_payload['line_items']:
            if not line['product_tax_code']:
                line.pop('product_tax_code')

        self.assertEqual(payload, expected_payload)
        response = {'tax': {
            'has_nexus': False, 'tax_source': None,
            'shipping': 0.0,
            'taxable_amount': 0,
            'rate': 0, 'freight_taxable': True,
            'amount_to_collect': 40.09,
            'order_total_amount': 320.0,
            'breakdown': {
                'line_items': [
                    {'tax_collectable':
                     round(0.1 * sol.price_unit, 2),
                     'id': sol.id}
                    for sol in self.order.order_line
                    if sol.product_id.id != self.shipping_product.id],
                'shipping': {'tax_collectable': 30.0}},
        }}
        return (200, {}, json.dumps(response))

    @responses.activate
    def test_01_sale_order(self):
        responses.add_callback(
            responses.POST, 'https://api.sandbox.taxjar.com/v2/taxes',
            callback=self.callback)

        self.order.taxjar_policy = 'pickup'
        self.assertEqual(
            self.order._get_taxjar_partner(),
            self.order.warehouse_id.partner_id)

        self.order.taxjar_policy = 'shipping'
        self.assertEqual(
            self.order._get_taxjar_partner(), self.order.partner_shipping_id)

        self.order.button_update_taxjar_taxes()
        self.assertAlmostEqual(self.order.taxjar_amount, 40.09)

        # Taxes are (re)computed on order confirmation
        self.order.taxjar_amount = 0
        self.order.amount_tax = 0
        self.order.action_confirm()
        self.assertAlmostEqual(self.order.taxjar_amount, 40.09)
        self.assertAlmostEqual(self.order.amount_tax, 40.09)

        self.assertEqual(self.order.order_line[0].taxjar_amount, 3.08)
        # The rounding difference was included in the line with the highest
        # tax amount
        self.assertEqual(self.order.order_line[1].taxjar_amount, 7.01)
        # The shipping tax is distributed evenly across the shipping lines
        self.assertEqual(self.order.order_line[2].taxjar_amount, 15)
        self.assertEqual(self.order.order_line[3].taxjar_amount, 15)

    @responses.activate
    def test_02_additional_taxes(self):
        """ There is a check for additional taxes """
        responses.add_callback(
            responses.POST, 'https://api.sandbox.taxjar.com/v2/taxes',
            callback=self.callback)

        extra_tax = self.env['account.tax'].search([
            ('company_id', '=', self.company.id),
            ('type_tax_use', '=', 'sale')])
        self.order.order_line[0].tax_id = extra_tax
        with self.assertRaisesRegexp(UserError, 'Additional taxes'):
            with self.env.cr.savepoint():
                self.order.button_update_taxjar_taxes()

        # Taxjar tax is OK
        self.order.order_line[0].tax_id = self.env.ref(
            'taxjar_salestax.account_tax_taxjar')
        self.order.button_update_taxjar_taxes()
