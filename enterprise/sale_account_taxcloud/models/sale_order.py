# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools import float_compare, float_round

from .taxcloud_request import TaxCloudRequest


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    is_taxcloud_configured = fields.Boolean(related='company_id.is_taxcloud_configured', help='Used to determine whether or not to warn the user to configure TaxCloud.')
    is_taxcloud = fields.Boolean(related='fiscal_position_id.is_taxcloud', help='Technical field to determine whether to hide taxes in views or not.')

    def action_confirm(self):
        if self.fiscal_position_id.is_taxcloud:
            self.validate_taxes_on_sales_order()
        return super(SaleOrder, self).action_confirm()

    def validate_taxes_on_sales_order(self):
        company = self.company_id
        shipper = company or self.env.company
        api_id = shipper.taxcloud_api_id
        api_key = shipper.taxcloud_api_key
        request = TaxCloudRequest(api_id, api_key)

        request.set_location_origin_detail(shipper)
        request.set_location_destination_detail(self.partner_shipping_id)

        request.set_order_items_detail(self)

        response = request.get_all_taxes_values()

        if response.get('error_message'):
            raise ValidationError(
                _('Unable to retrieve taxes from TaxCloud: ') + '\n' +
                response['error_message']
            )

        tax_values = response['values']

        for index, line in enumerate(self.order_line):
            if line.price_unit >= 0.0 and line.product_uom_qty >= 0.0:
                price = line.price_unit * (1 - (line.discount or 0.0) / 100.0) * line.product_uom_qty
                if not price:
                    tax_rate = 0.0
                else:
                    tax_rate = tax_values[index] / price * 100
                if len(line.tax_id) != 1 or float_compare(line.tax_id.amount, tax_rate, precision_digits=3):
                    tax_rate = float_round(tax_rate, precision_digits=3)
                    tax = self.env['account.tax'].with_context(active_test=False).sudo().search([
                        ('amount', '=', tax_rate),
                        ('amount_type', '=', 'percent'),
                        ('type_tax_use', '=', 'sale'),
                        ('company_id', '=', company.id),
                    ], limit=1)
                    if not tax:
                        tax = self.env['account.tax'].sudo().with_context(default_company_id=company.id).create({
                            'name': 'Tax %.3f %%' % (tax_rate),
                            'amount': tax_rate,
                            'amount_type': 'percent',
                            'type_tax_use': 'sale',
                            'description': 'Sales Tax',
                            'active': False,  # these taxes should never be used manually
                        })
                    line.tax_id = tax
        return True
