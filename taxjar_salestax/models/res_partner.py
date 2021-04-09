# Copyright 2019-2020 Vanmoof B.V.
# Copyright 2017-2020 Stefan Rijnhart <stefan@opener.amsterdam>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
from odoo import api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.taxjar_salestax.exceptions import TaxJarAddressNotFound


class ResPartner(models.Model):
    _inherit = 'res.partner'

    taxjar_validation_error = fields.Boolean(
        default=False,
        help='The address could not be validated by TaxJar')

    @api.model
    def _taxjar(self, prefix='to'):
        "Convert to a dictionary of values usable in the TaxJar API"
        self.ensure_one()
        if prefix not in ('to', 'from'):
            raise ValidationError(
                'Unknown suffix "%s" when extracting address data from '
                'partner %s' % prefix, self.name)
        return {
            '%s_country' % prefix: self.country_id.code or None,
            '%s_zip' % prefix: self.zip or None,
            '%s_city' % prefix: self.city or None,
            '%s_state' % prefix: self.state_id.code or None,
        }

    def partner_to_dict_taxjar(self):
        """Return a dict from partner to be used as address in TaxJar"""
        self.ensure_one()
        vals = {}
        if self.country_id:
            vals['country'] = self.country_id.code
        if self.state_id:
            vals['state'] = self.state_id.code
        if self.zip:
            vals['zip'] = self.zip
        if self.city:
            vals['city'] = self.city
        if self.street:
            vals['street'] = self.street
        if self.street2:
            if vals.get('street'):
                vals['street'] = u'{} {}'.format(vals['street'], self.street2)
            else:
                vals['street'] = self.street2
        return vals

    def taxjar_validate_address(self):
        config = self.env['taxjar.config']._get_config()
        if not config or not config.address_validation:
            return
        for partner in self:
            if partner.country_id not in config.country_ids:
                continue
            taxjar_vals = partner.partner_to_dict_taxjar()
            try:
                res = config._wrap_for_error(
                    'validate_address', taxjar_vals).data
            except TaxJarAddressNotFound:
                self.write({'taxjar_validation_error': True})
                continue
            if res:
                vals = {}
                if partner.taxjar_validation_error:
                    vals['taxjar_validation_error'] = False
                address = res[0]
                if address['zip'] != partner.zip:
                    vals['zip'] = address['zip']
                if address['city'] != partner.city:
                    vals['city'] = address['city']
                if address['street'] != partner.street:
                    vals['street'] = address['street']
                # Taxjar does not support multiline street
                if partner.street2:
                    vals['street2'] = False
                if address['state']:
                    state = self.env['res.country.state'].search(
                        [('code', '=', address['state']),
                         ('country_id.code', '=', address['country'])],
                        limit=1)
                    if state and state != partner.state_id:
                        vals['state_id'] = state.id
                if vals:
                    super().write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        """ Apply automatic address validation if applicable """
        partners = super().create(vals_list)
        partners.taxjar_validate_address()
        return partners

    def write(self, vals):
        """ Apply automatic address validation if applicable """
        res = super().write(vals)
        if any(field in vals for field in (
                'street', 'street2', 'zip', 'city', 'country_id', 'state_id')):
            self.taxjar_validate_address()
        return res
