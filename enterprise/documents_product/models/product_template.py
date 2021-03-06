# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import models


class ProductTemplate(models.Model):
    _name = 'product.template'
    _inherit = ['product.template', 'documents.mixin']

    def _get_document_tags(self):
        return self.company_id.product_tags

    def _get_document_folder(self):
        return self.company_id.product_folder

    def _check_create_documents(self):
        return self.company_id.documents_product_settings and super()._check_create_documents()
