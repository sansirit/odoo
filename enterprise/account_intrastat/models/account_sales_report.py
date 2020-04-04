# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import models, fields, api, _


class IntrastatReport(models.AbstractModel):
    _name = 'account.sales.report'
    _description = 'EC Sales List'
    _inherit = 'account.report'

    filter_date = {'mode': 'range', 'filter': 'this_month'}
    filter_journals = True
    filter_multi_company = None

    def _get_filter_journals(self):
        #only show sale/purchase journals
        return self.env['account.journal'].search([('company_id', '=', self.env.company.id), ('type', '=', 'sale')], order="company_id, name")

    def _get_columns_name(self, options):
        return [
            {'name': ''},
            {'name': _('VAT')},
            {'name': _('Country Code')},
            {'name': _('Value'), 'class': 'number'},
        ]

    @api.model
    def _prepare_query(self, options):
        query = """
            SELECT
                line.move_id AS move_id,
                line.partner_id AS partner_id,
                partner.name AS partner_name,
                partner.vat AS partner_vat,
                country.code AS country_code,
                move.currency_id AS currency_id,
                move.date AS date,
                SUM(line.balance) AS total_balance,
                SUM(line.amount_currency) AS total_amount_currency
            FROM account_move_line line
                LEFT JOIN account_move move ON line.move_id = move.id
                LEFT JOIN res_partner partner ON line.partner_id = partner.id
                LEFT JOIN res_company company ON line.company_id = company.id
                LEFT JOIN res_partner company_partner ON company_partner.id = company.partner_id
                LEFT JOIN res_country country ON partner.country_id = country.id
            WHERE move.state = 'posted'
                AND line.display_type IS NULL
                AND country.intrastat = TRUE
                AND company_partner.country_id != country.id
                AND line.company_id = %s
                AND COALESCE(move.date, move.invoice_date) BETWEEN %s AND %s
                AND move.type IN ('out_invoice', 'out_refund')
                AND partner.vat IS NOT NULL
                AND line.journal_id IN %s
            GROUP BY
                line.move_id, line.partner_id, partner.name, partner.vat, country.code, move.currency_id, move.date
        """
        # Date range
        params = [self.env.company.id, options['date']['date_from'], options['date']['date_to']]

        # Filter on selected journals
        journal_ids = self.env['account.journal'].search([('type', 'in', ('sale', 'purchase'))]).ids
        if options.get('journals'):
            journal_ids = [c['id'] for c in options['journals'] if c.get('selected')] or journal_ids
        params.append(tuple(journal_ids))

        return query, params

    @api.model
    def _create_sales_report_line(self, options, vals):
        return {
            'id': vals['partner_id'],
            'caret_options': 'res.partner',
            'model': 'res.partner',
            'name': vals['partner_name'],
            'columns': [{'name': c} for c in [
                vals['partner_vat'], vals['country_code'], self.format_value(vals['value'])]
            ],
            'level': 2,
        }

    @api.model
    def _get_lines(self, options, line_id=None):
        self.env['account.move.line'].check_access_rights('read')
        query, params = self._prepare_query(options)

        self._cr.execute(query, params)
        query_res = self._cr.dictfetchall()

        company_currency = self.env.company.currency_id
        partners_values = {}
        total_value = 0

        # Aggregate total amount for each partner.
        # Take care of the multi-currencies.
        for vals in query_res:
            if vals['currency_id'] == company_currency.id:
                total_amount = vals['total_amount_currency']
            elif vals['currency_id'] != company_currency.id:
                currency = self.env['res.currency'].browse(vals['currency_id'])
                total_amount = currency._convert(vals['total_balance'], company_currency, self.env.user.company_id, vals['date'])
            else:
                total_amount = vals['total_balance']

            if vals['partner_name'] not in partners_values:
                partners_values[vals['partner_name']] = {
                    'value': total_amount,
                    'partner_id': vals['partner_id'],
                    'partner_name': vals['partner_name'],
                    'partner_vat': vals['partner_vat'],
                    'country_code': vals['country_code'],
                }
            else:
                partners_values[vals['partner_name']]['value'] += total_amount
            total_value += total_amount

        lines = [self._create_sales_report_line(options, partners_values[partner_name]) for partner_name in sorted(partners_values)]

        # Create total line
        lines.append({
            'id': 0,
            'name': _('Total'),
            'class': 'total',
            'level': 2,
            'columns': [{'name': v} for v in [self.format_value(total_value)]],
            'colspan': 3,
        })
        return lines

    @api.model
    def _get_report_name(self):
        return _('EC Sales List')
