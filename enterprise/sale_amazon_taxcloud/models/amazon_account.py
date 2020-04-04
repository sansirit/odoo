# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import models


class AmazonAccount(models.Model):
    _inherit = 'amazon.account'

    def _recompute_subtotal(self, subtotal, tax_amount, taxes, currency, fiscal_pos=None):
        """ Bypass the recomputation of the subtotal to let TaxCloud fetch the right taxes. """
        if fiscal_pos and fiscal_pos.is_taxcloud:
            return subtotal
        else:
            return super(AmazonAccount, self)._recompute_subtotal(
                subtotal, tax_amount, taxes, currency)
