# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
import uuid

import odoo
from odoo import models, api
from odoo.addons.iap import jsonrpc

DEFAULT_ENDPOINT = 'https://ocn.odoo.com'


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    def _get_endpoint(self):
        return self.env['ir.config_parameter'].sudo().get_param('odoo_ocn.endpoint', DEFAULT_ENDPOINT)

    @api.model
    def get_fcm_project_id(self):
        ir_params_sudo = self.env['ir.config_parameter'].sudo()
        project_id = ir_params_sudo.get_param('odoo_ocn.project_id')
        if not project_id:
            params = {
                'ocnuuid': self._get_ocn_uuid(),
                'server_version': odoo.release.version,
                'db': self.env.cr.dbname,
                'company_name': self.env.company.name,
                'url': ir_params_sudo.get_param('web.base.url')
            }
            # Register instance to ocn service. Unique with ocn.uuid
            project_id = jsonrpc(self._get_endpoint() + '/iap/ocn/enable_service', params=params)
            # Storing project id for generate token
            ir_params_sudo.set_param('odoo_ocn.project_id', project_id)
        return project_id

    @api.model
    def _get_ocn_uuid(self):
        push_uuid = self.env['ir.config_parameter'].sudo().get_param('ocn.uuid')
        if not push_uuid:
            push_uuid = str(uuid.uuid4())
            self.env['ir.config_parameter'].sudo().set_param('ocn.uuid', push_uuid)
        return push_uuid

    @api.model
    def register_device(self, device_key, device_name):
        values = {
            'ocn_uuid': self._get_ocn_uuid(),
            'user_name': self.env.user.partner_id.name,
            'user_login': self.env.user.login,
            'device_name': device_name,
            'device_key': device_key,
        }
        result = jsonrpc(self._get_endpoint() + '/iap/ocn/register_device', params=values)
        if result:
            self.env.user.partner_id.ocn_token = result
            return result
        return False
