# Copyright 2019-2020 Vanmoof B.V.
# Copyright 2017-2020 Stefan Rijnhart <stefan@opener.amsterdam>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
from .common import TaxJarCase
import json
import responses


class TestPartnerValidation(TaxJarCase):
    def setUp(self):
        super().setUp()
        self.company.partner_id.write(
            {'city': 'Brooklyn', 'street': '326 Wythe Ave',
             'state_id': self.env.ref('base.state_us_27').id,
             'country_id': self.env.ref('base.us').id})
        self.config.address_validation = True

    @responses.activate
    def test_01_partner_validation(self):
        def callback(request):
            payload = json.loads(
                request.body.decode('utf-8')
                if isinstance(request.body, bytes) else request.body)
            for key, value in [
                    ('street', '1450 W Cermak Rd'),
                    ('city', 'Cicago'),
                    ('state', 'IL'),
                    ('country', 'US')]:
                self.assertEqual(payload[key], value)
            self.assertFalse(payload.get('zip'))
            response = {'addresses': [
                {
                    'street': '1450 W Cermak Rd',
                    'zip': '60608',
                    'city': 'Chicago',
                    'state': 'IL',
                    'country': 'US',
                }, {}]}
            return (200, {}, json.dumps(response))

        responses.add_callback(
            responses.POST,
            'https://api.sandbox.taxjar.com/v2/addresses/validate',
            callback=callback)

        customer = self.env['res.partner'].create({
            'name': 'Some customer',
            'street': '1450 W Cermak Rd',
            'city': 'Cicago',
            'state_id': self.env.ref('base.state_us_14').id,
            'country_id': self.env.ref('base.us').id,
        })
        self.assertEqual(customer.city, 'Chicago'),
        self.assertEqual(customer.zip, '60608')

        customer.write({
            'city': 'Cicago',
            'zip': False,
        })
        self.assertEqual(customer.city, 'Chicago'),
        self.assertEqual(customer.zip, '60608')
