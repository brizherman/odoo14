# -*- coding: utf-8 -*-
# pylint: disable=import-error,missing-function-docstring,protected-access
"""Shared companies, pricelists, customers, registers, and completed sales.

Dates passed to the helpers are naive UTC. Use ``to_utc`` to build an instant
from an America/Tijuana local clock time. Qualifying totals use ``amount_total``
on paid POS orders and confirmed sales orders, so the helpers store that
amount after discounts and taxes.
"""
from datetime import datetime

import pytz

from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.pos_wholesale_control.models.wholesale_pricelist_mapping import (
    CUSTOMER_TYPE_SELECTION,
)
from odoo.tests import tagged

RETAIL_PRICELIST_NAME = 'Public Pricelist'
CLUB_PRICELIST_NAME = 'Club Mayorista'
DISTRIBUTOR_PRICELIST_NAME = 'Super Precios a Distribuidores'

# Confirmed decision: distributors use Super Precios. The other three types
# use Club Mayorista once the order qualifies. Publico general and dormant
# wholesale still need that mapping; the threshold decides when it applies.
WHOLESALE_LIST_KEY_BY_TYPE = {
    'mayorista': 'club',
    'publico_general': 'club',
    'distribuidores': 'distributor',
    'mayorista_dormido': 'club',
}

POS_DONE_STATES = ('paid', 'done', 'invoiced')
SALE_DONE_STATES = ('sale', 'done')


@tagged('pos_wholesale_control', 'post_install', '-at_install')
class WholesaleControlCommon(AccountTestInvoicingCommon):
    """Two MXN companies with wholesale control activated on open registers."""

    @classmethod
    def setUpClass(cls):
        # The accounting fixture creates the environment and loads the generic
        # chart. Looking up that chart before super() runs has no env yet.
        super(WholesaleControlCommon, cls).setUpClass()
        cls.mxn = cls.env.ref('base.MXN')
        if not cls.mxn.active:
            cls.mxn.sudo().write({'active': True})
        cls.company = cls.company_data['company']
        cls.company_2 = cls.company_data_2['company']
        companies = cls.company | cls.company_2
        companies.sudo().write({'currency_id': cls.mxn.id})
        cls._clear_foreign_journal_currency(companies)
        cls.group_pos_user = cls.env.ref('point_of_sale.group_pos_user')
        cls.group_pos_manager = cls.env.ref('point_of_sale.group_pos_manager')
        cls.group_wholesale_manager = cls.env.ref(
            'pos_wholesale_control.group_wholesale_manager',
        )
        cls.group_wholesale_admin = cls.env.ref(
            'pos_wholesale_control.group_wholesale_admin',
        )
        cls._create_users()
        cls.product = cls._create_product('Wholesale test product')
        cls.product_included = cls._create_product('Wholesale test product included tax')
        cls.product_excluded = cls._create_product('Wholesale test product excluded tax')
        cls.bundle = cls._build_company_bundle(
            cls.company_data, 'Wholesale Register', 'WSA', with_employees=True,
        )
        cls.bundle_2 = cls._build_company_bundle(
            cls.company_data_2, 'Wholesale Other Register', 'WSB', with_employees=False,
        )
        cls.bundles = {
            cls.company.id: cls.bundle,
            cls.company_2.id: cls.bundle_2,
        }
        cls._assign_product_accounts()
        cls._create_partners()
        cls.cashier_employee = cls.bundle['cashier_employee']
        cls.manager_employee = cls.bundle['manager_employee']
        cls.config = cls.bundle['config']
        cls.session = cls.bundle['session']
        cls.config_2 = cls.bundle_2['config']
        cls.session_2 = cls.bundle_2['session']
        cls.retail_pricelist = cls.bundle['retail']
        cls.club_pricelist = cls.bundle['club']
        cls.distributor_pricelist = cls.bundle['distributor']
        cls.tax_included = cls.bundle['tax_included']
        cls.tax_excluded = cls.bundle['tax_excluded']

    @classmethod
    def _clear_foreign_journal_currency(cls, companies):
        """A journal locked to another currency cannot be the POS sales journal."""
        journals = cls.env['account.journal'].sudo().search([
            ('company_id', 'in', companies.ids),
            ('currency_id', '!=', False),
            ('currency_id', '!=', cls.mxn.id),
        ])
        if journals:
            journals.write({'currency_id': False})

    @classmethod
    def _create_users(cls):
        users = cls.env['res.users'].sudo()
        companies = cls.company | cls.company_2
        internal = cls.env.ref('base.group_user')
        cls.cashier_user = users.create({
            'name': 'Wholesale Cashier',
            'login': 'wholesale.cashier.%s' % cls.company.id,
            'email': 'wholesale.cashier@example.com',
            'groups_id': [(6, 0, [internal.id, cls.group_pos_user.id])],
            'company_id': cls.company.id,
            'company_ids': [(6, 0, companies.ids)],
        })
        cls.manager_user = users.create({
            'name': 'Wholesale Manager',
            'login': 'wholesale.manager.%s' % cls.company.id,
            'email': 'wholesale.manager@example.com',
            'groups_id': [(6, 0, [internal.id, cls.group_pos_manager.id])],
            'company_id': cls.company.id,
            'company_ids': [(6, 0, companies.ids)],
        })

    @classmethod
    def _create_product(cls, name):
        return cls.env['product.product'].sudo().create({
            'name': name,
            'type': 'service',
            'invoice_policy': 'order',
            'list_price': 100.0,
            'available_in_pos': True,
            'sale_ok': True,
            'taxes_id': [(6, 0, [])],
        })

    @classmethod
    def _create_partners(cls):
        partners = cls.env['res.partner'].sudo()
        cls.partner_by_type = {}
        for key, label in CUSTOMER_TYPE_SELECTION:
            cls.partner_by_type[key] = partners.create({
                'name': 'Wholesale %s' % label,
                'customer_type': key,
                'company_id': False,
            })
        cls.partner_mayorista = cls.partner_by_type['mayorista']
        cls.partner_publico_general = cls.partner_by_type['publico_general']
        cls.partner_distribuidores = cls.partner_by_type['distribuidores']
        cls.partner_mayorista_dormido = cls.partner_by_type['mayorista_dormido']
        cls.partner_untyped = partners.create({
            'name': 'Wholesale Untyped',
            'company_id': False,
        })

    @classmethod
    def _build_company_bundle(cls, company_data, register_name, warehouse_code, with_employees):
        company = company_data['company']
        income = company_data['default_account_revenue']
        tax_account = company_data['default_account_tax_sale'][:1] or income
        tax_included = cls._create_sale_tax(
            company, '%s included 16' % register_name, True, tax_account,
        )
        tax_excluded = cls._create_sale_tax(
            company, '%s excluded 16' % register_name, False, tax_account,
        )
        retail = cls._create_pricelist(company, RETAIL_PRICELIST_NAME)
        club = cls._create_pricelist(company, CLUB_PRICELIST_NAME)
        distributor = cls._create_pricelist(company, DISTRIBUTOR_PRICELIST_NAME)
        lists = {
            'retail': retail,
            'club': club,
            'distributor': distributor,
        }
        employees = cls.env['hr.employee']
        cashier_employee = employees
        manager_employee = employees
        if with_employees:
            cashier_employee = cls._create_employee(
                'Wholesale Cashier', cls.cashier_user, company, '1111',
            )
            manager_employee = cls._create_employee(
                'Wholesale Manager', cls.manager_user, company, '2580',
            )
            employees = cashier_employee | manager_employee
        config = cls._create_pos_config(
            company, company_data, register_name, warehouse_code,
            retail, club, distributor, employees,
        )
        session = cls.env['pos.session'].sudo().create({
            'user_id': cls.env.uid,
            'config_id': config.id,
        })
        cls._activate_wholesale(company, retail, club, lists)
        return {
            'company': company,
            'retail': retail,
            'club': club,
            'distributor': distributor,
            'tax_included': tax_included,
            'tax_excluded': tax_excluded,
            'income_account': income,
            'config': config,
            'session': session,
            'cashier_employee': cashier_employee,
            'manager_employee': manager_employee,
        }

    @classmethod
    def _create_sale_tax(cls, company, name, price_include, account):
        tax = cls.env['account.tax'].sudo().with_company(company).create({
            'name': name,
            'amount_type': 'percent',
            'amount': 16.0,
            'price_include': price_include,
            'type_tax_use': 'sale',
            'company_id': company.id,
        })
        tax_lines = (
            tax.invoice_repartition_line_ids | tax.refund_repartition_line_ids
        ).filtered(lambda line: line.repartition_type == 'tax')
        if account:
            tax_lines.write({'account_id': account.id})
        return tax

    @classmethod
    def _create_pricelist(cls, company, name):
        return cls.env['product.pricelist'].sudo().create({
            'name': name,
            'currency_id': cls.mxn.id,
            'company_id': company.id,
        })

    @classmethod
    def _create_employee(cls, name, user, company, pin):
        return cls.env['hr.employee'].sudo().create({
            'name': name,
            'company_id': company.id,
            'user_id': user.id,
            'pin': pin,
        })

    @classmethod
    def _create_pos_config(cls, company, company_data, name, warehouse_code, retail, club,
                           distributor, employees):
        warehouse = cls._create_warehouse(company, name, warehouse_code)
        payment_method = cls.env['pos.payment.method'].sudo().create({
            'name': '%s bank' % name,
            'receivable_account_id': company_data['default_account_receivable'].id,
            'is_cash_count': False,
            'company_id': company.id,
        })
        values = {
            'name': name,
            'company_id': company.id,
            'journal_id': company_data['default_journal_sale'].id,
            'invoice_journal_id': company_data['default_journal_sale'].id,
            'picking_type_id': warehouse.pos_type_id.id,
            'use_pricelist': True,
            'available_pricelist_ids': [(6, 0, [retail.id, club.id, distributor.id])],
            'pricelist_id': retail.id,
            'payment_method_ids': [(6, 0, [payment_method.id])],
            'cash_control': False,
            'module_pos_hr': bool(employees),
        }
        if employees:
            values['employee_ids'] = [(6, 0, employees.ids)]
        return cls.env['pos.config'].sudo().with_company(company).create(values)

    @classmethod
    def _create_warehouse(cls, company, name, code):
        return cls.env['stock.warehouse'].sudo().with_company(company).create({
            'name': name,
            'code': code,
            'company_id': company.id,
        })

    @classmethod
    def _activate_wholesale(cls, company, retail, club, lists):
        mappings = []
        for customer_type, list_key in WHOLESALE_LIST_KEY_BY_TYPE.items():
            mappings.append({
                'company_id': company.id,
                'customer_type': customer_type,
                'pricelist_id': lists[list_key].id,
            })
        cls.env['pos.wholesale.pricelist.mapping'].sudo().create(mappings)
        company.sudo().write({
            'wholesale_timezone': 'America/Tijuana',
            'wholesale_previous_month_min': 800.0,
            'wholesale_current_order_min': 1500.0,
            'wholesale_retail_pricelist_id': retail.id,
            'wholesale_pricelist_id': club.id,
            'wholesale_control_active': True,
        })

    @classmethod
    def _assign_product_accounts(cls):
        products = {
            cls.product: None,
            cls.product_included: 'tax_included',
            cls.product_excluded: 'tax_excluded',
        }
        for bundle in cls.bundles.values():
            company = bundle['company']
            for product, tax_key in products.items():
                values = {
                    'property_account_income_id': bundle['income_account'].id,
                }
                if tax_key:
                    values['taxes_id'] = [(6, 0, [bundle[tax_key].id])]
                else:
                    values['taxes_id'] = [(6, 0, [])]
                product.sudo().with_company(company).write(values)

    def bundle_for(self, company=None):
        """Return the fixture dict for one company. The default is the main register."""
        company = company or self.company
        bundle = self.bundles.get(company.id)
        if not bundle:
            raise AssertionError('No wholesale fixture for company %s.' % company.id)
        return bundle

    def pos_env(self, user=None, company=None):
        """POS user allowed on both fixture companies, with the business timezone."""
        user = user or self.cashier_user
        company = company or self.company
        allowed_ids = [company.id]
        for company_id in (self.company | self.company_2).ids:
            if company_id not in allowed_ids:
                allowed_ids.append(company_id)
        # Odoo 14 Environment has no with_context. Calling it replaces the
        # context, so copy the current keys and then set the company and zone.
        context = dict(
            self.env.context,
            allowed_company_ids=allowed_ids,
            tz='America/Tijuana',
        )
        return self.env(user=user, context=context)

    def to_utc(self, year, month, day, hour=12, minute=0, company=None):
        """Naive UTC for a local clock time in the company business timezone.

        Noon is outside the Tijuana daylight-saving gap. A skipped or repeated
        local time uses the same midnight rule as the eligibility calendar.
        """
        company = company or self.company
        timezone = pytz.timezone(company.wholesale_timezone)
        local = datetime(year, month, day, hour, minute, 0)
        try:
            localized = timezone.localize(local, is_dst=None)
        except pytz.AmbiguousTimeError:
            localized = timezone.localize(local, is_dst=True)
        except pytz.NonExistentTimeError:
            localized = timezone.localize(local, is_dst=False)
        return localized.astimezone(pytz.UTC).replace(tzinfo=None)

    def set_order_date(self, order, when):
        """Store a naive UTC ``date_order`` after confirmation has overwritten it."""
        order.sudo().write({'date_order': when})
        order.invalidate_cache(['date_order'])
        order.flush(['date_order'])
        return order

    def create_pos_order(self, partner, amount_total=0.0, date_order=None, company=None,
                         product=None, qty=1.0, price_unit=None, discount=0.0, tax=None,
                         state='paid', pos_reference=None):
        """Create one POS order. ``amount_total`` is the tax-inclusive total.

        Pass ``price_unit`` when the line should be priced, discounted, and
        taxed. The stored ``amount_total`` is then the computed line total.
        ``state`` is ``draft``, ``cancel``, ``paid``, ``done``, or ``invoiced``.
        """
        if state not in ('draft', 'cancel') + POS_DONE_STATES:
            raise AssertionError('Unsupported POS state %s.' % state)
        bundle = self.bundle_for(company)
        company = bundle['company']
        product = product or self.product
        totals = self._pos_line_totals(
            company, partner, product, qty, price_unit, discount, tax, amount_total,
        )
        paid = totals['total'] if state in POS_DONE_STATES else 0.0
        order = self.env['pos.order'].sudo().create({
            'company_id': company.id,
            'session_id': bundle['session'].id,
            'partner_id': partner.id if partner else False,
            'pricelist_id': bundle['retail'].id,
            'lines': [(0, 0, {
                'product_id': product.id,
                'price_unit': totals['price_unit'],
                'discount': discount or 0.0,
                'qty': qty,
                'tax_ids': [(6, 0, totals['tax_ids'])],
                'price_subtotal': totals['untaxed'],
                'price_subtotal_incl': totals['total'],
            })],
            'amount_tax': totals['tax'],
            'amount_total': totals['total'],
            'amount_paid': paid,
            'amount_return': 0.0,
            'state': 'paid' if state in POS_DONE_STATES else 'draft',
        })
        if pos_reference:
            order.write({'pos_reference': pos_reference})
        elif not order.pos_reference:
            order.write({'pos_reference': 'Order %s-001-0001' % order.id})
        if date_order:
            self.set_order_date(order, date_order)
        if state in ('done', 'invoiced', 'cancel'):
            order.write({'state': state})
        return order

    def _pos_line_totals(self, company, partner, product, qty, price_unit, discount, tax,
                         amount_total):
        unit = amount_total if price_unit is None else price_unit
        taxes = tax if tax is not None else self.env['account.tax']
        currency = company.currency_id
        discounted = unit * (1.0 - (discount or 0.0) / 100.0)
        if taxes:
            computed = taxes.compute_all(
                discounted, currency, qty, product=product, partner=partner,
            )
            untaxed = computed['total_excluded']
            total = computed['total_included']
        else:
            untaxed = currency.round(discounted * qty)
            total = untaxed
        return {
            'price_unit': unit,
            'untaxed': untaxed,
            'total': total,
            'tax': currency.round(total - untaxed),
            'tax_ids': taxes.ids,
        }

    def create_pos_refund(self, order, amount_total=None, date_order=None):
        """Pay a POS refund named from the original order.

        Odoo dates the refund now. Pass ``date_order`` only when a test needs
        a different refund timestamp. ``amount_total`` is stored as a negative
        amount; a positive value is signed automatically.
        """
        if order.state not in POS_DONE_STATES:
            raise AssertionError('Only a completed POS order can be refunded.')
        if not order.session_id.config_id.current_session_id:
            raise AssertionError('The original register has no open session.')
        refund = self.env['pos.order'].sudo().browse(order.sudo().refund()['res_id'])
        values = {
            'state': 'paid',
            'amount_paid': refund.amount_total,
            'amount_return': 0.0,
        }
        if amount_total is not None:
            signed = amount_total if amount_total < 0 else -abs(amount_total)
            values.update({
                'amount_total': signed,
                'amount_tax': 0.0,
                'amount_paid': signed,
            })
        refund.write(values)
        if date_order:
            self.set_order_date(refund, date_order)
        return refund

    def create_sale_order(self, partner, price_unit, date_order, qty=1.0, discount=0.0,
                          tax=None, company=None, product=None, state='sale'):
        """Confirm a sales order, then put ``date_order`` back on the original month.

        Confirmation replaces the date with the current time. The helper writes
        the requested instant afterwards. ``state`` is ``draft``, ``sale``,
        ``done``, or ``cancel``.
        """
        if state not in ('draft', 'cancel') + SALE_DONE_STATES:
            raise AssertionError('Unsupported sales state %s.' % state)
        if 'sale.order' not in self.env:
            raise AssertionError('Sales is not installed, so this fixture cannot create a sale.')
        bundle = self.bundle_for(company)
        company = bundle['company']
        product = product or self.product
        taxes = tax if tax is not None else self.env['account.tax']
        order = self.env['sale.order'].sudo().with_company(company).with_context(
            tracking_disable=True,
            mail_notrack=True,
        ).create({
            'partner_id': partner.id,
            'company_id': company.id,
            'date_order': date_order,
            'order_line': [(0, 0, {
                'name': product.display_name,
                'product_id': product.id,
                'product_uom_qty': qty,
                'price_unit': price_unit,
                'discount': discount or 0.0,
                'tax_id': [(6, 0, taxes.ids)],
            })],
        })
        if state in SALE_DONE_STATES or state == 'cancel':
            order.with_context(tracking_disable=True).action_confirm()
        if state == 'done':
            order.action_done()
        if state == 'cancel':
            order.with_context(disable_cancel_warning=True).action_cancel()
        if date_order:
            self.set_order_date(order, date_order)
        return order

    def create_sale_credit_note(self, order):
        """Post a full customer credit note linked to the sales order lines.

        The sales order total stays unchanged. Eligibility subtracts the
        posted refund lines from the original sale month.
        """
        if order.state not in SALE_DONE_STATES:
            raise AssertionError('Only a confirmed sales order can be credited.')
        company = order.company_id
        invoices = order.sudo().with_company(company).with_context(
            tracking_disable=True,
        )._create_invoices()
        invoices.action_post()
        refunds = invoices._reverse_moves()
        refunds.action_post()
        return refunds
