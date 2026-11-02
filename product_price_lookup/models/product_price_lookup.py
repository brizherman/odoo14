# -*- coding: utf-8 -*-
# pylint: disable=import-error,too-few-public-methods
"""Shared product search and tax-included unit price for both lookup screens."""
from odoo import _, api, models
from odoo.exceptions import AccessError
from odoo.tools.misc import formatLang

# Customer-type keys, in the order the screen always shows filled slots.
# Labels come from res.partner.customer_type. Mayorista dormido is not a slot.
PRICE_LOOKUP_SLOTS = (
    ('publico_general', 'price_lookup_publico_general_pricelist_id'),
    ('mayorista', 'price_lookup_mayorista_pricelist_id'),
    ('distribuidores', 'price_lookup_distribuidores_pricelist_id'),
)
PRICE_LOOKUP_LIST_LIMIT = 8


class ProductPriceLookup(models.AbstractModel):
    """One search method for the backend screen and the POS popup.

    There is no table. Prices are computed with the current user.
    """

    _name = 'product.price.lookup'
    _description = 'Consulta de precios'

    @api.model
    def lookup(self, search_text, company_id=False, product_id=False):
        """Return a plain dict for the lookup screen.

        ``company_id`` empty means the active company. A company the user
        cannot read is rejected. ``product_id`` skips search and prices that
        variant. An empty search without a product id does not replace the
        previous result.

        The dict keys are ``state``, ``message``, ``product``, ``matches``,
        and ``prices``. ``state`` is ``empty``, ``not_found``, ``list``,
        ``prices``, or ``unconfigured``.
        """
        company = self._price_lookup_company(company_id)
        scoped = self.with_company(company)
        # with_company() is a new recordset. The search must run on that company.
        return scoped._price_lookup_run(  # pylint: disable=protected-access
            search_text, company, product_id,
        )

    def _price_lookup_run(self, search_text, company, product_id):
        """Search or price inside the company environment chosen by lookup."""
        if product_id:
            return self._price_lookup_for_product(int(product_id), company)
        text = (search_text or '').strip()
        if not text:
            return self._price_lookup_payload(state='empty')
        return self._price_lookup_for_text(text, company)

    def _price_lookup_company(self, company_id):
        """Active company, or the requested company when the user can read it."""
        if not company_id:
            return self.env.company
        company = self.env['res.company'].browse(int(company_id)).exists()
        if not company:
            raise AccessError(_('No puede consultar esta sucursal.'))
        return company

    def _price_lookup_for_product(self, product_id, company):
        """Price one variant chosen from the short list, or report no match."""
        product = self.env['product.product'].browse(product_id).exists()
        if not self._price_lookup_product_allowed(product, company):
            return self._price_lookup_not_found()
        return self._price_lookup_prices(product, company)

    def _price_lookup_for_text(self, text, company):
        """Barcode, then internal reference, then product name.

        A leading ``*`` searches only the internal reference and keeps every
        reference that contains the rest of the text.
        """
        if text.startswith('*'):
            return self._price_lookup_reference_contains(company, text[1:])
        barcode_hits = self._price_lookup_exact(company, 'barcode', text)
        if len(barcode_hits) == 1:
            return self._price_lookup_prices(barcode_hits, company)
        if barcode_hits:
            return self._price_lookup_short_list(barcode_hits)
        reference_hits = self._price_lookup_exact(company, 'default_code', text)
        if len(reference_hits) == 1:
            return self._price_lookup_prices(reference_hits, company)
        if reference_hits:
            return self._price_lookup_short_list(reference_hits)
        name_hits = self._price_lookup_by_name(company, text)
        if not name_hits:
            return self._price_lookup_not_found()
        return self._price_lookup_short_list(name_hits)

    def _price_lookup_product_domain(self, company):
        """Active salable variants shared with every company or owned by this one."""
        return [
            ('active', '=', True),
            ('sale_ok', '=', True),
            '|',
            ('company_id', '=', False),
            ('company_id', '=', company.id),
        ]

    def _price_lookup_exact(self, company, field_name, text):
        """Case-insensitive exact match. Percent and underscore stay literal."""
        domain = self._price_lookup_product_domain(company)
        domain.append((field_name, '=ilike', self._price_lookup_literal(text)))
        # One extra row tells the short list that more than eight exist.
        return self.env['product.product'].search(
            domain, order='name, id', limit=PRICE_LOOKUP_LIST_LIMIT + 1,
        )

    def _price_lookup_reference_contains(self, company, text):
        """Every internal reference that contains the text. ``*`` alone is empty."""
        needle = (text or '').strip()
        if not needle:
            return self._price_lookup_payload(state='empty')
        domain = self._price_lookup_product_domain(company)
        domain.append(('default_code', 'ilike', self._price_lookup_literal(needle)))
        products = self.env['product.product'].search(domain, order='name, id')
        if not products:
            return self._price_lookup_not_found()
        if len(products) == 1:
            return self._price_lookup_prices(products, company)
        return self._price_lookup_payload(
            state='list',
            matches=[
                self._price_lookup_product_values(product) for product in products
            ],
        )

    def _price_lookup_by_name(self, company, text):
        """Partial case-insensitive name match, ordered by name."""
        domain = self._price_lookup_product_domain(company)
        domain.append(('name', 'ilike', self._price_lookup_literal(text)))
        return self.env['product.product'].search(
            domain, order='name, id', limit=PRICE_LOOKUP_LIST_LIMIT + 1,
        )

    def _price_lookup_literal(self, text):
        """Stop LIKE wildcards so the operator stays an exact or partial literal."""
        return (
            text.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        )

    def _price_lookup_product_allowed(self, product, company):
        """False when the variant is missing, archived, not sold, or foreign."""
        if not product:
            return False
        if not product.active or not product.sale_ok:
            return False
        if product.company_id and product.company_id != company:
            return False
        return True

    def _price_lookup_prices(self, product, company):
        """Tax-included unit price for each filled, usable slot."""
        product.ensure_one()
        blocks = []
        for customer_type, field_name in PRICE_LOOKUP_SLOTS:
            pricelist = company[field_name]
            if not self._price_lookup_pricelist_ok(pricelist, company):
                continue
            blocks.append(self._price_lookup_block(
                product, pricelist, company, customer_type,
            ))
        values = self._price_lookup_product_values(product)
        if not blocks:
            return self._price_lookup_payload(
                state='unconfigured',
                message=_('Esta sucursal no tiene listas de precios configuradas.'),
                product=values,
            )
        return self._price_lookup_payload(
            state='prices',
            product=values,
            prices=blocks,
        )

    def _price_lookup_pricelist_ok(self, pricelist, company):
        """Skip an empty, archived, foreign, or wrong-currency slot."""
        if not pricelist:
            return False
        pricelist = pricelist.with_context(active_test=False)
        if not pricelist.exists() or not pricelist.active:
            return False
        if pricelist.currency_id != company.currency_id:
            return False
        if pricelist.company_id and pricelist.company_id != company:
            return False
        return True

    def _price_lookup_block(self, product, pricelist, company, customer_type):
        """One label and the currency-rounded tax-included unit price."""
        price = pricelist.get_product_price(product, 1.0, False)
        taxes = product.taxes_id.filtered(
            lambda tax: tax.company_id == company and tax.type_tax_use == 'sale',
        )
        included = taxes.compute_all(
            price,
            currency=company.currency_id,
            quantity=1.0,
            product=product,
            partner=False,
        )['total_included']
        amount = company.currency_id.round(included)
        currency = company.currency_id
        return {
            'slot': customer_type,
            'label': self._price_lookup_label(customer_type),
            'amount': amount,
            'currency': currency.name,
            'display': formatLang(self.env, amount, currency_obj=currency),
        }

    def _price_lookup_label(self, customer_type):
        """Selection label for this customer type. Companies cannot rename it."""
        selection = self.env['res.partner'].fields_get(
            ['customer_type'],
        )['customer_type']['selection']
        return dict(selection)[customer_type]

    def _price_lookup_short_list(self, products):
        """At most eight rows. A longer match asks the user to type more."""
        message = False
        if len(products) > PRICE_LOOKUP_LIST_LIMIT:
            message = _('Escriba más del nombre para reducir la lista.')
        rows = products[:PRICE_LOOKUP_LIST_LIMIT]
        return self._price_lookup_payload(
            state='list',
            message=message,
            matches=[
                self._price_lookup_product_values(product) for product in rows
            ],
        )

    def _price_lookup_not_found(self):
        """No product, so the screen drops whatever prices it was showing."""
        return self._price_lookup_payload(
            state='not_found',
            message=_('No se encontró el producto.'),
        )

    def _price_lookup_product_values(self, product):
        """Identity row. The name is not the price list name."""
        return {
            'id': product.id,
            'name': product.name or '',
            'default_code': product.default_code or '',
            'barcode': product.barcode or '',
        }

    def _price_lookup_payload(  # pylint: disable=too-many-arguments
            self, state, message=False, product=False, matches=None, prices=None):
        """Stable dict. Empty search uses state ``empty`` and blank collections."""
        return {
            'state': state,
            'message': message or False,
            'product': product or False,
            'matches': matches or [],
            'prices': prices or [],
        }
