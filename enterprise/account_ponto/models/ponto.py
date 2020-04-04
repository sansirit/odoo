# -*- coding: utf-8 -*-
import requests
import json
import logging
import datetime
import time

from odoo import models, api, fields
from odoo.tools.translate import _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class ProviderAccount(models.Model):
    _inherit = ['account.online.provider']

    provider_type = fields.Selection(selection_add=[('ponto', 'Ponto')])
    ponto_token = fields.Char(readonly=True, help='Technical field that contains the ponto token')

    def _get_available_providers(self):
        ret = super(ProviderAccount, self)._get_available_providers()
        ret.append('ponto')
        return ret

    def _build_ponto_headers(self):
        authorization = "Bearer " + self.ponto_token
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": authorization
        }

    def _ponto_fetch(self, method, url, params, data):
        base_url = 'https://api.myponto.com'
        if not url.startswith(base_url):
            url = base_url + url
        try:
            if data:
                data = json.dumps(data)
            headers = self._build_ponto_headers()
            resp = requests.request(method=method, url=url, params=params, data=data, headers=headers, timeout=60)
            resp_json = resp.json()
            if resp_json.get('errors') or resp.status_code >= 400:
                message = ('%s for route %s') % (json.dumps(resp_json.get('errors')), url)
                if resp_json.get('errors', [{}])[0].get('code', '') == 'authorizationCodeInvalid':
                    message = _('Invalid access token')
                self.log_ponto_message(message)
            return resp_json
        except requests.exceptions.Timeout as e:
            _logger.exception(e)
            raise UserError(_('Timeout: the server did not reply within 60s'))
        except requests.exceptions.ConnectionError as e:
            _logger.exception(e)
            raise UserError(_('Server not reachable, please try again later'))
        except ValueError as e:
            _logger.exception(e)
            self.log_ponto_message('%s for route %s' % (resp.text, url))

    def get_login_form(self, site_id, provider, beta=False):
        if provider != 'ponto':
            return super(ProviderAccount, self).get_login_form(site_id, provider, beta)
        return {
            'type': 'ir.actions.client',
            'tag': 'ponto_online_sync_widget',
            'name': _('Link your Ponto account'),
            'target': 'new',
            'context': self._context,
        }

    def log_ponto_message(self, message):
        # We need a context check because upon first synchronization the account_online_provider record is created and just after
        # we call api to get accounts but this call can result on an error (token not correct or else) and the transaction
        # would be rollbacked causing an error if we try to post a message on the deleted record with a new cursor. Solution
        # is to not try to log message in that case.
        if not self._context.get('no_post_message'):
            subject = _("An error occurred during online synchronization")
            message = _('The following error happened during the synchronization: %s' % (message,))
            with self.pool.cursor() as cr:
                self.with_env(self.env(cr=cr)).message_post(body=message, subject=subject)
                self.with_env(self.env(cr=cr)).write({'status': 'FAILED', 'action_required': True})
        raise UserError('An error has occurred: %s' % (message,))


    def _update_ponto_accounts(self, method='add'):
        resp_json = self._ponto_fetch('GET', '/accounts', {}, {})
        res = {'added': self.env['account.online.journal']}
        # When we are trying to add a new institution, add all existing account_online_journal that are not currently linked
        # The reason is that a user can first synchronize for journal A and receive 3 bank accounts, he only link one bank account
        # and does nothing with the 2 others, then later he create a new journal and synchronize again with the same ponto token
        # because he would like to link one of the two remaining account to his journal. Since the accounts were already fetched in
        # Odoo, we have to show it to him so that he can link them.
        if method == 'add':
            res['added'] = self.account_online_journal_ids.filtered(lambda j: len(j.journal_ids) == 0)
        for account in resp_json.get('data', {}):
            # Fetch accounts
            vals = {
                'balance': account.get('attributes', {}).get('currentBalance', 0)
            }
            account_search = self.env['account.online.journal'].search([('account_online_provider_id', '=', self.id), ('online_identifier', '=', account.get('id'))], limit=1)
            if len(account_search) == 0:
                # Since we just create account, set last sync to 15 days in the past to retrieve transaction from latest 15 days
                last_sync = self.last_refresh - datetime.timedelta(days=15)
                vals.update({
                    'name': account.get('attributes', {}).get('description', _('Account')),
                    'online_identifier': account.get('id'),
                    'account_online_provider_id': self.id,
                    'account_number': account.get('attributes', {}).get('reference', {}),
                    'last_sync': last_sync,
                })
                acc = self.env['account.online.journal'].create(vals)
                res['added'] += acc
        self.write({'status': 'SUCCESS', 'action_required': False})
        res.update({'status': 'SUCCESS',
            'message': '',
            'method': method,
            'number_added': len(res['added']),
            'journal_id': self.env.context.get('journal_id', False)})
        return self.show_result(res)

    def success_callback(self, token):
        # Create account.provider and fetch account
        # Search for already existing ponto provider and if found update that one, otherwise create a new one
        provider_account = self.search([('ponto_token', '=', token)])
        if not provider_account:
            vals = {
                'name': _('Ponto'),
                'ponto_token': token,
                'provider_identifier': 'ponto',
                'status': 'SUCCESS',
                'status_code': 0,
                'message': '',
                'last_refresh': fields.Datetime.now(),
                'action_required': False,
                'provider_type': 'ponto',
            }
            provider_account = self.create(vals)
        return provider_account.with_context(no_post_message=True)._update_ponto_accounts()

    def manual_sync(self):
        if self.provider_type != 'ponto':
            return super(ProviderAccount, self).manual_sync()
        transactions = []
        for account in self.account_online_journal_ids:
            if account.journal_ids:
                tr = account.retrieve_transactions()
                transactions.append({'journal': account.journal_ids[0].name, 'count': tr})
        self.write({'status': 'SUCCESS', 'action_required': False})
        result = {'status': 'SUCCESS', 'transactions': transactions, 'method': 'refresh', 'added': self.env['account.online.journal']}
        return self.show_result(result)

    def update_credentials(self):
        if self.provider_type != 'ponto':
            return super(ProviderAccount, self).update_credentials()
        # Fetch new accounts if needed
        return self._update_ponto_accounts(method='edit')

    @api.model
    def cron_fetch_online_transactions(self):
        if self.provider_type != 'ponto':
            return super(ProviderAccount, self).cron_fetch_online_transactions()
        self.manual_sync()


class OnlineAccount(models.Model):
    _inherit = 'account.online.journal'

    ponto_last_synchronization_identifier = fields.Char(readonly=True, help='id of ponto synchronization')

    def _ponto_synchronize(self, subtype):
        # To fetch the latest transactions and balance of accounts we have to call a special
        # url on ponto to tell him to refresh the data, this ressource is called "synchronization"
        # We have to call it for both "account" and "transactions" as ponto does not have the option
        # to have both in one. Once the "synchronization" are finished, their status will changed to "success"
        # and we know we can now continue and fetch the latest transactions and account balance.
        # however if we try to refresh both one after another or at the same time, an error is received
        # An error is also received if we call their synchronization route too quickly. Therefore we
        # only call this route if it has not been called in the last 5 minutes.
        last_sync_age = fields.Datetime.now() - self.account_online_provider_id.last_refresh
        # We can refresh if last refresh was greater than 5min in the past
        if last_sync_age <= datetime.timedelta(minutes=5):
            _logger.info('Skip refresh of ponto transaction as last refresh was less than 5min ago')
            return
        data = {
            'data': {
                'type': 'synchronization',
                'attributes': {
                    'resourceType': 'account',
                    'resourceId': self.online_identifier,
                    'subtype': subtype
                }
            }
        }
        # Synchronization ressource for account
        resp_json = self.account_online_provider_id._ponto_fetch('POST', '/synchronizations', {}, data)
        # Get id of synchronization ressources
        sync_id = resp_json.get('data', {}).get('id')
        sync_ressource = resp_json.get('data', {}).get('attributes', {})
        # Fetch synchronization ressources until it has been updated
        count = 0
        while True:
            if count == 180:
                raise UserError(_('Fetching transactions took too much time.'))
            if sync_ressource.get('status') not in ('success', 'error'):
                resp_json = self.account_online_provider_id._ponto_fetch('GET', '/synchronizations/' + sync_id, {}, {})
            sync_ressource = resp_json.get('data', {}).get('attributes', {})
            if sync_ressource.get('status') in ('success', 'error'):
                # If we are in error, log the error and stop
                if sync_ressource.get('status') == 'error':
                    self.account_online_provider_id.log_ponto_message(json.dumps(sync_ressource.get('errors')))
                break
            count += 1
            time.sleep(2)
        self.account_online_provider_id.last_refresh = fields.Datetime.now()
        return

    def retrieve_transactions(self):
        if (self.account_online_provider_id.provider_type != 'ponto'):
            return super(OnlineAccount, self).retrieve_transactions()
        # actualize the data in ponto
        # For some reason, ponto has 2 different routes to update the account balance and transactions
        # however if we try to refresh both one after another or at the same time, an error is received
        # An error is also received if we call their synchronization route too quickly. Therefore we
        # only refresh the transactions of the account and don't update the account which means that the
        # balance of the account won't be up-to-date. However this is not a big problem as the record that
        # store the balance is hidden for most user.
        self._ponto_synchronize('accountTransactions')
        transactions = []
        # Update account balance
        url = '/accounts/%s' % (self.online_identifier,)
        resp_json = self.account_online_provider_id._ponto_fetch('GET', url, {}, {})
        end_amount = resp_json.get('data', {}).get('attributes', {}).get('currentBalance', 0)
        self.balance = end_amount
        # Fetch transactions.
        # Transactions are paginated so we need to loop to ensure we have every transactions, we keep
        # in memory the id of the last transaction fetched in order to start over from there.
        url = url + '/transactions'
        paging_forward = True
        if self.ponto_last_synchronization_identifier:
            paging_forward = False
            url = url + '?before=' + self.ponto_last_synchronization_identifier
        last_sync = fields.Date.to_date((self.last_sync or fields.Datetime.now() - datetime.timedelta(days=15)))
        latest_transaction_identifier = False
        while url:
            resp_json = self.account_online_provider_id._ponto_fetch('GET', url, {}, {})
            # 'prev' page contains newer transactions, 'next' page contains older ones.
            # we read from last known transaction to newer ones when we know such a transaction
            # else we read from the newest transaction back to our date limit
            url = resp_json.get('links', {}).get('next' if paging_forward else 'prev', False)
            data_lines = resp_json.get('data', [])
            if data_lines:
                # latest transaction will be in the last page in backward direction, or in the first one in forward direction
                if ((not paging_forward and not url) or (paging_forward and not latest_transaction_identifier)):
                    # a chunk sent by Ponto always has its most recent transaction first
                    latest_transaction_identifier = data_lines[0].get('id')
            for transaction in data_lines:
                tr_date = fields.Date.from_string(transaction.get('attributes', {}).get('valueDate'))
                if paging_forward and tr_date < last_sync:
                    # Stop fetching transactions because we are paging forward
                    # and the following transactions are older than specified last_sync date.
                    url = False
                    break
                trans = {
                    'online_identifier': transaction.get('id'),
                    'date': fields.Date.from_string(transaction.get('attributes', {}).get('valueDate')),
                    'name': transaction.get('attributes', {}).get('remittanceInformation') or '/',
                    'amount': transaction.get('attributes', {}).get('amount'),
                    'account_number': transaction.get('attributes', {}).get('counterpartReference'),
                    'end_amount': end_amount
                }
                if transaction.get('attributes', {}).get('counterpartName'):
                    trans['online_partner_vendor_name'] = transaction['attributes']['counterpartName']
                    trans['partner_id'] = self._find_partner([('online_partner_vendor_name', '=', transaction['attributes']['counterpartName'])])
                transactions.append(trans)
        if latest_transaction_identifier:
            self.ponto_last_synchronization_identifier = latest_transaction_identifier
        # Create the bank statement with the transactions
        return self.env['account.bank.statement'].online_sync_bank_statement(transactions, self.journal_ids[0])


class OnlineAccountWizard(models.TransientModel):
    _inherit = 'account.online.wizard'

    def _get_journal_values(self, account, create=False):
        vals = super(OnlineAccountWizard, self)._get_journal_values(account=account, create=create)
        if account.online_account_id.account_online_provider_id.provider_type == 'ponto':
            vals['post_at'] = 'bank_rec'
            vals['name'] = account.account_number
            # create bank account in Odoo if not already exists
            company = account.journal_id and account.journal_id.company_id or self.env.company
            res_bank_id = self.env['res.partner.bank'].search([('acc_number', '=', account.account_number), ('company_id', '=', company.id)])
            if not len(res_bank_id):
                res_bank_id = self.env['res.partner.bank'].create({
                    'acc_number': account.account_number,
                    'company_id': company.id,
                    'currency_id': company.currency_id.id,
                    'partner_id': company.partner_id.id,
                })
            vals['bank_account_id'] = res_bank_id.id
        return vals
