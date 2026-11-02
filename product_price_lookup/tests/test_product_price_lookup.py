# -*- coding: utf-8 -*-
# pylint: disable=import-error,missing-function-docstring,protected-access,too-many-arguments
"""Search, tax-included price, company scope, and settings access."""
from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import SavepointCase
from odoo.tools.float_utils import float_compare


@tagged('product_price_lookup', 'post_install', '-at_install')
class TestProductPriceLookup(SavepointCase):
    """Lookup prices for one company without reading a live catalog."""

    @classmethod
    def setUpClass(cls):  # pylint: disable=invalid-name
        super().setUpClass()
        cls.currency = cls.env.ref('base.MXN')
        cls.company = cls.env['res.company'].create({
            'name': 'Price Lookup Branch',
            'currency_id': cls.currency.id,
        })
        cls.other_company = cls.env['res.company'].create({
            'name': 'Price Lookup Other Branch',
            'currency_id': cls.currency.id,
        })
        cls.tax = cls.env['account.tax'].create({
            'name': 'Price Lookup IVA 8',
            'amount': 8.0,
            'amount_type': 'percent',
            'type_tax_use': 'sale',
            'price_include': False,
            'company_id': cls.company.id,
        })
        cls.product = cls._variant(
            'Caja Blanca Pastel',
            default_code='CB7P',
            barcode='7501234000001',
            tax=cls.tax,
        )
        cls.pricelist = cls._fixed_pricelist(
            'Catalogo interno', cls.product, 398.24, cls.company, cls.currency,
        )
        cls.company.price_lookup_publico_general_pricelist_id = cls.pricelist
        cls.internal = cls.env['res.users'].with_context(
            no_reset_password=True,
        ).create({
            'name': 'Price Lookup Internal',
            'login': 'price_lookup_internal',
            'email': 'price_lookup_internal@example.com',
            'groups_id': [(6, 0, [cls.env.ref('base.group_user').id])],
            'company_id': cls.company.id,
            'company_ids': [(6, 0, [cls.company.id])],
        })

    @classmethod
    def _variant(cls, name, company=None, barcode=None, default_code=None,
                 sale_ok=True, tax=None):
        company = cls.company if company is None else company
        values = {
            'name': name,
            'sale_ok': sale_ok,
            'company_id': company.id if company else False,
            'taxes_id': [(6, 0, [tax.id])] if tax else [(5, 0, 0)],
        }
        if barcode:
            values['barcode'] = barcode
        if default_code:
            values['default_code'] = default_code
        products = cls.env['product.product']
        if company:
            products = products.with_company(company)
        return products.create(values)

    @classmethod
    def _fixed_pricelist(cls, name, product, price, company, currency):
        item = {
            'compute_price': 'fixed',
            'fixed_price': price,
        }
        if product:
            item.update({
                'applied_on': '0_product_variant',
                'product_id': product.id,
            })
        else:
            item['applied_on'] = '3_global'
        return cls.env['product.pricelist'].with_company(company).create({
            'name': name,
            'company_id': company.id if company else False,
            'currency_id': currency.id,
            'item_ids': [(0, 0, item)],
        })

    def _lookup(self, text, company=None, product_id=False, user=None,
                pass_company=True):
        company = self.company if company is None else company
        model = self.env['product.price.lookup']
        if company:
            model = model.with_company(company)
        if user:
            model = model.with_user(user)
        return model.lookup(
            text,
            company_id=company.id if pass_company and company else False,
            product_id=product_id,
        )

    def _set_slots(self, publico=False, mayorista=False, distribuidores=False):
        self.company.write({
            'price_lookup_publico_general_pricelist_id': publico.id if publico else False,
            'price_lookup_mayorista_pricelist_id': mayorista.id if mayorista else False,
            'price_lookup_distribuidores_pricelist_id': (
                distribuidores.id if distribuidores else False
            ),
        })

    def _same_amount(self, left, right):
        return float_compare(
            left, right, precision_rounding=self.currency.rounding,
        ) == 0

    def test_tax_included_unit_price_is_430_10(self):
        result = self._lookup(self.product.barcode)
        self.assertEqual(result['state'], 'prices')
        self.assertEqual(len(result['prices']), 1)
        block = result['prices'][0]
        self.assertEqual(block['label'], 'Público General')
        self.assertNotEqual(block['label'], self.pricelist.name)
        self.assertEqual(block['currency'], 'MXN')
        self.assertTrue(self._same_amount(block['amount'], 430.10))

    def test_unique_barcode_and_reference_return_prices(self):
        reference = self._variant('Reference Only', default_code='REFONLY')
        self.company.price_lookup_publico_general_pricelist_id = (
            self._fixed_pricelist(
                'Reference list', reference, 10.0, self.company, self.currency,
            )
        )
        barcode_result = self._lookup('7501234000001')
        self.assertEqual(barcode_result['state'], 'prices')
        self.assertEqual(barcode_result['product']['id'], self.product.id)
        self.assertFalse(barcode_result['matches'])
        coded = self._variant('Mixed Case', barcode='AbC999')
        self.company.price_lookup_publico_general_pricelist_id = (
            self._fixed_pricelist(
                'Case list', coded, 10.0, self.company, self.currency,
            )
        )
        case_result = self._lookup('abc999')
        self.assertEqual(case_result['state'], 'prices')
        self.assertEqual(case_result['product']['id'], coded.id)
        reference_result = self._lookup('refonly')
        self.assertEqual(reference_result['state'], 'prices')
        self.assertEqual(reference_result['product']['id'], reference.id)

    def test_barcode_wins_over_another_products_reference(self):
        other = self._variant('Other Reference', default_code='7501234000001')
        result = self._lookup('7501234000001')
        self.assertEqual(result['state'], 'prices')
        self.assertEqual(result['product']['id'], self.product.id)
        self.assertNotEqual(result['product']['id'], other.id)

    def test_duplicate_barcode_or_reference_returns_a_list(self):
        self._variant('Dup Upper', barcode='DupCode')
        self._variant('Dup Lower', barcode='dupcode')
        barcode_result = self._lookup('dupcode')
        self.assertEqual(barcode_result['state'], 'list')
        self.assertEqual(len(barcode_result['matches']), 2)
        self.assertFalse(barcode_result['prices'])
        self._variant('Ref A', default_code='REFDUP')
        self._variant('Ref B', default_code='REFDUP')
        reference_result = self._lookup('refdup')
        self.assertEqual(reference_result['state'], 'list')
        self.assertEqual(len(reference_result['matches']), 2)
        self.assertFalse(reference_result['prices'])

    def test_one_name_hit_still_requires_a_pick(self):
        named = self._variant('Solo Vela Especial')
        result = self._lookup('solo vela especial')
        self.assertEqual(result['state'], 'list')
        self.assertEqual(len(result['matches']), 1)
        self.assertEqual(result['matches'][0]['id'], named.id)
        self.assertFalse(result['prices'])

    def test_nine_name_hits_return_eight_and_a_message(self):
        for index in range(1, 10):
            self._variant(f'Narrow Candle {index:02d}')
        result = self._lookup('Narrow Candle')
        self.assertEqual(result['state'], 'list')
        self.assertEqual(len(result['matches']), 8)
        names = [row['name'] for row in result['matches']]
        self.assertIn('Narrow Candle 01', names)
        self.assertNotIn('Narrow Candle 09', names)
        self.assertEqual(
            result['message'],
            'Escriba más del nombre para reducir la lista.',
        )
        self.assertFalse(result['prices'])

    def test_star_searches_internal_reference_and_keeps_every_hit(self):
        for index in range(1, 10):
            self._variant(f'Star Candle {index:02d}', default_code=f'HELIO-{index:02d}')
        self._variant('Helio By Name', default_code='OTHER')
        listed = self._lookup('*helio')
        self.assertEqual(listed['state'], 'list')
        self.assertEqual(len(listed['matches']), 9)
        self.assertFalse(listed['message'])
        codes = [row['default_code'] for row in listed['matches']]
        self.assertIn('HELIO-09', codes)
        self.assertNotIn('OTHER', codes)
        self.assertFalse(listed['prices'])
        alone = self._lookup('*')
        self.assertEqual(alone['state'], 'empty')
        one = self._lookup('*other')
        self.assertEqual(one['state'], 'prices')
        self.assertEqual(one['product']['default_code'], 'OTHER')

    def test_miss_and_empty_and_excluded_products(self):
        missing = self._lookup('NO-SUCH-PRODUCT')
        self.assertEqual(missing['state'], 'not_found')
        self.assertEqual(missing['message'], 'No se encontró el producto.')
        self.assertFalse(missing['product'])
        self.assertFalse(missing['prices'])
        empty = self._lookup('   ')
        self.assertEqual(empty['state'], 'empty')
        self.assertFalse(empty['product'])
        self.assertFalse(empty['matches'])
        self.assertFalse(empty['prices'])
        archived = self._variant('Archived Item', barcode='ARCH1')
        archived.active = False
        self.assertEqual(self._lookup('ARCH1')['state'], 'not_found')
        not_sold = self._variant('Not Sold', barcode='NOSALE', sale_ok=False)
        self.assertEqual(self._lookup(not_sold.barcode)['state'], 'not_found')
        foreign = self._variant(
            'Foreign Item',
            company=self.other_company,
            barcode='OTHERCO',
        )
        self.assertEqual(self._lookup(foreign.barcode)['state'], 'not_found')
        shared = self._variant(
            'Shared Item', company=False, barcode='SHARED1',
        )
        self.company.price_lookup_publico_general_pricelist_id = (
            self._fixed_pricelist(
                'Shared list', shared, 10.0, self.company, self.currency,
            )
        )
        shared_result = self._lookup('shared1')
        self.assertEqual(shared_result['state'], 'prices')
        self.assertEqual(shared_result['product']['id'], shared.id)

    def test_slot_order_empty_slot_and_same_list_twice(self):
        plain = self._variant('Plain Slots')
        publico = self._fixed_pricelist(
            'Slot public', plain, 10.0, self.company, self.currency,
        )
        mayorista = self._fixed_pricelist(
            'Slot wholesale', plain, 20.0, self.company, self.currency,
        )
        distribuidores = self._fixed_pricelist(
            'Slot distributor', plain, 30.0, self.company, self.currency,
        )
        self._set_slots(publico, mayorista, distribuidores)
        result = self._lookup(plain.barcode or plain.default_code or plain.name)
        # Name search returns a list. Price the picked variant.
        priced = self._lookup('', product_id=plain.id)
        labels = [block['label'] for block in priced['prices']]
        self.assertEqual(
            labels, ['Público General', 'Mayorista', 'Distribuidores'],
        )
        self.assertTrue(self._same_amount(priced['prices'][0]['amount'], 10.0))
        self.assertTrue(self._same_amount(priced['prices'][1]['amount'], 20.0))
        self.assertTrue(self._same_amount(priced['prices'][2]['amount'], 30.0))
        self._set_slots(publico, False, distribuidores)
        skipped = self._lookup('', product_id=plain.id)
        self.assertEqual(
            [block['label'] for block in skipped['prices']],
            ['Público General', 'Distribuidores'],
        )
        self._set_slots(publico, publico, False)
        repeated = self._lookup('', product_id=plain.id)
        self.assertEqual(
            [block['label'] for block in repeated['prices']],
            ['Público General', 'Mayorista'],
        )
        self.assertTrue(self._same_amount(repeated['prices'][0]['amount'], 10.0))
        self.assertTrue(self._same_amount(repeated['prices'][1]['amount'], 10.0))
        self._set_slots()
        empty_slots = self._lookup('', product_id=plain.id)
        self.assertEqual(empty_slots['state'], 'unconfigured')
        self.assertEqual(
            empty_slots['message'],
            'Esta sucursal no tiene listas de precios configuradas.',
        )
        self.assertFalse(empty_slots['prices'])
        self.assertFalse(result['prices'])

    def test_foreign_currency_or_company_pricelist_is_ignored(self):
        usd = self._fixed_pricelist(
            'Dollar list', self.product, 1.0, self.company, self.env.ref('base.USD'),
        )
        self._set_slots(usd, False, False)
        result = self._lookup(self.product.barcode)
        self.assertEqual(result['state'], 'unconfigured')
        self.assertFalse(result['prices'])
        foreign_list = self._fixed_pricelist(
            'Other branch list', False, 5.0, self.other_company, self.currency,
        )
        self._set_slots(foreign_list, False, False)
        ignored = self._lookup(self.product.barcode)
        self.assertEqual(ignored['state'], 'unconfigured')
        self.assertFalse(ignored['prices'])

    def test_other_company_code_and_company_argument_are_blocked(self):
        foreign = self._variant(
            'Hidden Item', company=self.other_company, default_code='SECRET-CODE',
        )
        hidden = self._lookup(
            foreign.default_code, user=self.internal, pass_company=False,
        )
        self.assertEqual(hidden['state'], 'not_found')
        with self.assertRaises(AccessError):
            self._lookup(
                foreign.default_code,
                company=self.other_company,
                user=self.internal,
            )

    def test_internal_user_can_lookup_but_cannot_write_slots(self):
        result = self._lookup(self.product.barcode, user=self.internal)
        self.assertEqual(result['state'], 'prices')
        self.assertTrue(self._same_amount(result['prices'][0]['amount'], 430.10))
        with self.assertRaises(AccessError):
            self.company.with_user(self.internal).write({
                'price_lookup_publico_general_pricelist_id': self.pricelist.id,
            })
        admin = self.env.ref('base.user_admin')
        self.company.with_user(admin).write({
            'price_lookup_mayorista_pricelist_id': self.pricelist.id,
        })
        self.assertEqual(
            self.company.price_lookup_mayorista_pricelist_id,
            self.pricelist,
        )

    def test_picked_product_skips_search(self):
        priced = self._lookup('not the name', product_id=self.product.id)
        self.assertEqual(priced['state'], 'prices')
        self.assertEqual(priced['product']['id'], self.product.id)
        foreign = self._variant(
            'Picked Foreign', company=self.other_company, barcode='PICKFOREIGN',
        )
        rejected = self._lookup('', product_id=foreign.id)
        self.assertEqual(rejected['state'], 'not_found')
        self.assertFalse(rejected['prices'])

    def test_omitted_company_uses_the_active_company(self):
        result = self._lookup(self.product.barcode, pass_company=False)
        self.assertEqual(result['state'], 'prices')
        self.assertEqual(result['product']['id'], self.product.id)
