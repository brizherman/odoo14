# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.osv import expression
from odoo.tools.misc import format_date

WALLET_PAYMENT_METHOD_NAME = 'Lealtad'
WALLET_LEGACY_PAYMENT_METHOD_NAMES = ('Monedero Electrónico',)
CASH_PAYMENT_METHOD_NAME = 'Efectivo'
WALLET_JOURNAL_CODE = 'MEWLT'


class PosOrder(models.Model):
    _inherit = 'pos.order'

    has_wallet_payment = fields.Boolean(
        string='Has Lealtad Payment',
        compute='_compute_has_wallet_payment',
        store=True,
        index=True,
    )

    @api.model
    def _wallet_infrastructure_names(self):
        return [WALLET_PAYMENT_METHOD_NAME] + list(WALLET_LEGACY_PAYMENT_METHOD_NAMES)

    @api.model
    def _rename_wallet_infrastructure_for_company(self, company):
        """Rename legacy Monedero Electrónico records to Lealtad."""
        company = company if hasattr(company, 'id') else self.env['res.company'].browse(company)
        company = company.sudo()
        PosPaymentMethod = self.env['pos.payment.method'].sudo()
        AccountAccount = self.env['account.account'].sudo()
        AccountJournal = self.env['account.journal'].sudo()
        for method in PosPaymentMethod.search([
            ('company_id', '=', company.id),
            ('name', 'in', WALLET_LEGACY_PAYMENT_METHOD_NAMES),
        ]):
            method.name = WALLET_PAYMENT_METHOD_NAME
        for account in AccountAccount.search([
            ('company_id', '=', company.id),
            ('name', 'in', WALLET_LEGACY_PAYMENT_METHOD_NAMES),
        ]):
            account.name = WALLET_PAYMENT_METHOD_NAME
        for journal in AccountJournal.search([
            ('company_id', '=', company.id),
            ('name', 'in', WALLET_LEGACY_PAYMENT_METHOD_NAMES),
        ]):
            journal.name = WALLET_PAYMENT_METHOD_NAME

    @api.model
    def _migrate_all_wallet_infrastructure(self):
        for company in self.env['res.company'].search([]):
            self._rename_wallet_infrastructure_for_company(company)
            self._get_wallet_payment_method(company)

    def _register_hook(self):
        super(PosOrder, self)._register_hook()
        self._migrate_all_wallet_infrastructure()

    @api.model
    def _get_wallet_payment_method(self, company):
        """Return the per-company Lealtad payment method, if it exists."""
        company_id = company.id if hasattr(company, 'id') else company
        self._rename_wallet_infrastructure_for_company(company_id)
        PosPaymentMethod = self.env['pos.payment.method']
        method = PosPaymentMethod.search([
            ('company_id', '=', company_id),
            ('name', '=', WALLET_PAYMENT_METHOD_NAME),
        ], limit=1)
        if method:
            return method
        for legacy_name in WALLET_LEGACY_PAYMENT_METHOD_NAMES:
            legacy = PosPaymentMethod.search([
                ('company_id', '=', company_id),
                ('name', '=', legacy_name),
            ], limit=1)
            if legacy:
                legacy.name = WALLET_PAYMENT_METHOD_NAME
                return legacy
        return PosPaymentMethod

    @api.model
    def _get_wallet_account_code_prefix(self, company, AccountAccount):
        reference = company.account_default_pos_receivable_account_id
        if not reference:
            reference = AccountAccount.search([
                ('company_id', '=', company.id),
                ('internal_type', '=', 'receivable'),
            ], limit=1)
        if reference and reference.code:
            prefix = reference.code.rstrip('0123456789')
            return prefix or reference.code[:1]
        return '1'

    @api.model
    def _setup_wallet_infrastructure_for_company(self, company):
        """Create wallet GL account, journal, and payment method for one company."""
        company = company if hasattr(company, 'id') else self.env['res.company'].browse(company)
        company = company.sudo()

        existing_method = self._get_wallet_payment_method(company)
        if existing_method:
            return existing_method

        AccountAccount = self.env['account.account'].sudo()
        AccountJournal = self.env['account.journal'].sudo()
        PosPaymentMethod = self.env['pos.payment.method'].sudo()

        sample_account = AccountAccount.search([('company_id', '=', company.id)], limit=1)
        if not sample_account:
            return PosPaymentMethod

        receivable_type = self.env.ref('account.data_account_type_receivable')
        digits = len(sample_account.code)
        prefix = self._get_wallet_account_code_prefix(company, AccountAccount)

        wallet_account = AccountAccount.search([
            ('company_id', '=', company.id),
            ('name', 'in', self._wallet_infrastructure_names()),
            ('user_type_id', '=', receivable_type.id),
        ], limit=1)
        if wallet_account and wallet_account.name != WALLET_PAYMENT_METHOD_NAME:
            wallet_account.name = WALLET_PAYMENT_METHOD_NAME
        if not wallet_account:
            wallet_account = AccountAccount.create({
                'name': WALLET_PAYMENT_METHOD_NAME,
                'code': AccountAccount._search_new_account_code(company, digits, prefix),
                'user_type_id': receivable_type.id,
                'reconcile': True,
                'company_id': company.id,
            })

        wallet_journal = AccountJournal.search([
            ('company_id', '=', company.id),
            '|',
            ('code', '=', WALLET_JOURNAL_CODE),
            ('name', 'in', self._wallet_infrastructure_names()),
        ], limit=1)
        if wallet_journal and wallet_journal.name != WALLET_PAYMENT_METHOD_NAME:
            wallet_journal.name = WALLET_PAYMENT_METHOD_NAME
        if not wallet_journal:
            wallet_journal = AccountJournal.create({
                'name': WALLET_PAYMENT_METHOD_NAME,
                'code': WALLET_JOURNAL_CODE,
                'type': 'general',
                'company_id': company.id,
            })

        return PosPaymentMethod.create({
            'name': WALLET_PAYMENT_METHOD_NAME,
            'is_cash_count': False,
            'receivable_account_id': wallet_account.id,
            'company_id': company.id,
        })

    @api.depends('payment_ids', 'payment_ids.payment_method_id')
    def _compute_has_wallet_payment(self):
        for order in self:
            order.has_wallet_payment = order._has_wallet_payment(order.company_id)

    def _get_net_cash_amount(self):
        self.ensure_one()
        cash_payments = self.payment_ids.filtered(
            lambda payment: payment.payment_method_id.is_cash_count
        )
        return sum(cash_payments.mapped('amount'))

    def _has_wallet_payment(self, company=None):
        self.ensure_one()
        company = company or self.company_id
        wallet_method = self._get_wallet_payment_method(company)
        if not wallet_method:
            return False
        return bool(self.payment_ids.filtered(
            lambda payment: payment.payment_method_id == wallet_method
        ))

    def _passes_cash_reallocation_payment_rules(self):
        """Shared customer and payment-method rules for open and closed paths."""
        self.ensure_one()
        if self.partner_id:
            return False
        if self._has_wallet_payment(self.company_id):
            return False
        if self._get_net_cash_amount() <= 0:
            return False

        payment_methods = self.payment_ids.mapped('payment_method_id')
        if len(payment_methods) != 1:
            return False
        payment_method = payment_methods[0]
        if payment_method.name != CASH_PAYMENT_METHOD_NAME:
            return False
        if not payment_method.is_cash_count:
            return False
        return True

    def _is_eligible_for_reallocation(self):
        """Open-session path only: paid orders on a non-closed POS session."""
        self.ensure_one()
        if self.state != 'paid':
            return False
        if self.session_id.state == 'closed':
            return False
        return self._passes_cash_reallocation_payment_rules()

    def _is_eligible_for_closed_session_reallocation(self):
        """Closed-session path: done orders on a closed session with posted move."""
        self.ensure_one()
        if self.state != 'done':
            return False
        if self.state == 'invoiced' or self.account_move:
            return False
        if self.session_id.state != 'closed':
            return False
        session_move = self.session_id.move_id
        if not session_move or session_move.state != 'posted':
            return False
        return self._passes_cash_reallocation_payment_rules()

    def _get_closed_session_reallocation_date(self):
        """Accounting date used for fiscal period lock checks on closed sessions."""
        self.ensure_one()
        session = self.session_id
        if session.move_id and session.move_id.date:
            return session.move_id.date
        if session.stop_at:
            return fields.Date.to_date(session.stop_at)
        return fields.Date.context_today(self)

    def _is_fiscal_period_locked(self, check_date):
        self.ensure_one()
        lock_date = self.company_id._get_user_fiscal_lock_date()
        return check_date <= lock_date

    def _check_closed_session_reallocation_allowed(self):
        """Hard blocks for closed-session payment rewrite and adjustment posting."""
        self.ensure_one()
        if self.state == 'invoiced' or self.account_move:
            raise UserError(_(
                'Cannot reallocate cash on invoiced order %(order)s.',
                order=self.name,
            ))
        session_move = self.session_id.move_id
        if not session_move:
            raise UserError(_(
                'Cannot reallocate cash on order %(order)s because POS session '
                '%(session)s has no journal entry.',
                order=self.name,
                session=self.session_id.name,
            ))
        if session_move.state != 'posted':
            raise UserError(_(
                'Cannot reallocate cash on order %(order)s because POS session '
                '%(session)s journal entry is not posted.',
                order=self.name,
                session=self.session_id.name,
            ))
        check_date = self._get_closed_session_reallocation_date()
        if self._is_fiscal_period_locked(check_date):
            lock_date = self.company_id._get_user_fiscal_lock_date()
            raise UserError(_(
                'Cannot reallocate cash on order %(order)s because fiscal period '
                'is locked through %(lock_date)s.',
                order=self.name,
                lock_date=format_date(self.env, lock_date),
            ))

    @api.model
    def get_reallocation_eligibility_mode(self, order):
        """Return 'open', 'closed', or False for wizard filtering."""
        order = order if hasattr(order, '_name') else self.browse(order)
        if not order:
            return False
        order.ensure_one()
        if order._is_eligible_for_reallocation():
            return 'open'
        if order._is_eligible_for_closed_session_reallocation():
            return 'closed'
        return False

    def _check_reallocation_session_open(self):
        self.ensure_one()
        if self.session_id.state == 'closed':
            raise UserError(_(
                'Cannot modify payments on order %(order)s because POS session '
                '%(session)s is closed.',
                order=self.name,
                session=self.session_id.name,
            ))

    def _apply_cash_reallocation(self, wallet_amount, wallet_method, closed_session=False):
        """Rewrite payment lines; optionally skip open-session guard for closed path."""
        self.ensure_one()
        if closed_session:
            self._check_closed_session_reallocation_allowed()
        else:
            self._check_reallocation_session_open()
        if wallet_amount <= 0:
            return self.env['pos.payment']

        cash_payment = self.payment_ids.filtered(
            lambda payment: (
                payment.payment_method_id.is_cash_count
                and payment.amount > 0
                and not payment.is_change
            )
        )[:1]
        if not cash_payment:
            cash_payment = self.payment_ids.filtered(
                lambda payment: payment.payment_method_id.is_cash_count and payment.amount > 0
            )[:1]
        if not cash_payment:
            raise UserError(_(
                'Order %s has no cash payment line to reallocate.',
                self.name,
            ))

        original_cash = cash_payment.amount
        new_cash = original_cash - wallet_amount
        if new_cash < 0:
            raise UserError(_(
                'Wallet amount %(wallet)s exceeds cash payment %(cash)s on order '
                '%(order)s.',
                wallet=wallet_amount,
                cash=original_cash,
                order=self.name,
            ))

        cash_payment.write({'amount': new_cash})
        wallet_payment = self.env['pos.payment'].create({
            'pos_order_id': self.id,
            'amount': wallet_amount,
            'payment_method_id': wallet_method.id,
            'payment_date': fields.Datetime.now(),
        })
        self.amount_paid = sum(self.payment_ids.mapped('amount'))

        comment = _(
            'Cash reallocation by %(user)s at %(timestamp)s: '
            'cash reduced from %(original).2f to %(new).2f; '
            '%(wallet_name)s payment %(wallet).2f created.',
            user=self.env.user.name,
            timestamp=fields.Datetime.to_string(fields.Datetime.now()),
            original=original_cash,
            new=new_cash,
            wallet_name=wallet_method.name,
            wallet=wallet_amount,
        )
        self.note = '%s\n%s' % (self.note or '', comment)
        return wallet_payment

    @api.model
    def search_wallet_reallocated_orders(self, company, domain=None):
        """Return orders with a Lealtad payment line, any session state."""
        company_id = company.id if hasattr(company, 'id') else company
        wallet_method = self._get_wallet_payment_method(company_id)
        if not wallet_method:
            return self.browse()

        search_domain = [('payment_ids.payment_method_id', '=', wallet_method.id)]
        if domain:
            search_domain = expression.AND([search_domain, domain])
        return self.search(search_domain)


class PosPayment(models.Model):
    _inherit = 'pos.payment'

    @api.constrains('payment_method_id')
    def _check_payment_method_id(self):
        for payment in self:
            wallet_method = self.env['pos.order']._get_wallet_payment_method(
                payment.company_id
            )
            if wallet_method and payment.payment_method_id == wallet_method:
                continue
            if payment.payment_method_id not in payment.session_id.config_id.payment_method_ids:
                raise ValidationError(_(
                    'The payment method selected is not allowed in the config of the POS session.'
                ))
