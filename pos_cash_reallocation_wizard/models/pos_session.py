# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError

from .pos_order import (
    CASH_PAYMENT_METHOD_NAME,
    WALLET_JOURNAL_CODE,
    WALLET_PAYMENT_METHOD_NAME,
)


class PosSession(models.Model):
    _inherit = 'pos.session'

    def get_lealtad_amount(self):
        """Return total Lealtad payments for this session."""
        self.ensure_one()
        wallet_method = self.env['pos.order']._get_wallet_payment_method(
            self.company_id
        )
        if not wallet_method:
            return 0.0
        payments = self.env['pos.payment'].search([
            ('session_id', '=', self.id),
            ('payment_method_id', '=', wallet_method.id),
        ])
        return sum(payments.mapped('amount'))

    def _get_cash_payment_method(self):
        self.ensure_one()
        cash_method = self.config_id.payment_method_ids.filtered(
            lambda pm: pm.name == CASH_PAYMENT_METHOD_NAME and pm.is_cash_count
        )[:1]
        if not cash_method:
            cash_method = self.env['pos.payment.method'].search([
                ('company_id', '=', self.company_id.id),
                ('name', '=', CASH_PAYMENT_METHOD_NAME),
                ('is_cash_count', '=', True),
            ], limit=1)
        return cash_method

    def _get_cash_payment_method_receivable_account(self):
        """Efectivo receivable account for this session's POS config."""
        self.ensure_one()
        cash_method = self._get_cash_payment_method()
        if not cash_method or not cash_method.receivable_account_id:
            raise UserError(_(
                'Cannot resolve Efectivo receivable account for POS session %(session)s.',
                session=self.name,
            ))
        return cash_method.receivable_account_id

    def _get_wallet_receivable_account(self, company=None):
        """Lealtad receivable account for the given company."""
        self.ensure_one()
        company = company or self.company_id
        wallet_method = self.env['pos.order']._get_wallet_payment_method(company)
        if not wallet_method or not wallet_method.receivable_account_id:
            raise UserError(_(
                'Cannot resolve Lealtad receivable account for company %(company)s.',
                company=company.display_name,
            ))
        return wallet_method.receivable_account_id

    def _get_wallet_journal(self, company=None):
        self.ensure_one()
        company = company or self.company_id
        AccountJournal = self.env['account.journal']
        journal = AccountJournal.search([
            ('company_id', '=', company.id),
            ('code', '=', WALLET_JOURNAL_CODE),
        ], limit=1)
        if not journal:
            journal = AccountJournal.search([
                ('company_id', '=', company.id),
                ('name', '=', WALLET_PAYMENT_METHOD_NAME),
            ], limit=1)
        if not journal:
            raise UserError(_(
                'Cannot resolve Lealtad journal for company %(company)s.',
                company=company.display_name,
            ))
        return journal

    def _get_reallocation_adjustment_move_date(self):
        self.ensure_one()
        if self.move_id and self.move_id.date:
            return self.move_id.date
        if self.stop_at:
            return fields.Date.to_date(self.stop_at)
        return fields.Date.context_today(self)

    def _prepare_reallocation_adjustment_move_vals(self, total_amount, ref, company):
        """Build account.move vals: debit Lealtad receivable, credit Efectivo receivable."""
        self.ensure_one()
        company = company or self.company_id
        if total_amount <= 0:
            raise UserError(_(
                'Reallocation adjustment amount must be positive for session %(session)s.',
                session=self.name,
            ))

        cash_account = self._get_cash_payment_method_receivable_account()
        wallet_account = self._get_wallet_receivable_account(company)
        wallet_journal = self._get_wallet_journal(company)
        move_date = self._get_reallocation_adjustment_move_date()
        line_name = ref or _('%s — Cash Reallocation', self.name)

        return {
            'move_type': 'entry',
            'journal_id': wallet_journal.id,
            'date': fields.Date.to_string(move_date),
            'ref': ref,
            'company_id': company.id,
            'line_ids': [
                (0, 0, {
                    'name': line_name,
                    'account_id': wallet_account.id,
                    'debit': total_amount,
                    'credit': 0.0,
                }),
                (0, 0, {
                    'name': line_name,
                    'account_id': cash_account.id,
                    'debit': 0.0,
                    'credit': total_amount,
                }),
            ],
        }

    def _create_reallocation_adjustment_move(self, total_amount, log_name):
        """Create and post the session adjustment move; return account.move."""
        self.ensure_one()
        ref = _('%s — Cash Reallocation %s') % (self.name, log_name)
        move_vals = self._prepare_reallocation_adjustment_move_vals(
            total_amount,
            ref,
            self.company_id,
        )
        move = self.env['account.move'].create(move_vals)
        try:
            move.action_post()
        except UserError:
            raise
        except Exception as exc:
            raise UserError(_(
                'Failed to post reallocation adjustment entry for session '
                '%(session)s: %(error)s',
                session=self.name,
                error=exc,
            ))
        if move.state != 'posted':
            raise UserError(_(
                'Failed to post reallocation adjustment entry for session %(session)s.',
                session=self.name,
            ))
        return move
