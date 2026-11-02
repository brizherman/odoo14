odoo.define('product_price_lookup.PriceLookupPopup', function (require) {
    'use strict';

    const { useState, useRef } = owl.hooks;
    const AbstractAwaitablePopup = require('point_of_sale.AbstractAwaitablePopup');
    const Registries = require('point_of_sale.Registries');
    const { useBarcodeReader } = require('point_of_sale.custom_hooks');

    class PriceLookupPopup extends AbstractAwaitablePopup {
        constructor() {
            super(...arguments);
            this.state = useState({
                message: '',
                product: null,
                matches: [],
                prices: [],
            });
            this.searchRef = useRef('search');
            useBarcodeReader({
                product: this._onBarcode,
                weight: this._onBarcode,
                price: this._onBarcode,
            }, true);
        }
        mounted() {
            this._focus();
        }
        _onBarcode(parsed) {
            const code = (parsed && (parsed.base_code || parsed.code)) || '';
            if (this.searchRef.el) {
                this.searchRef.el.value = code;
            }
            this._search();
        }
        onSearchKeydown(event) {
            if (event.key !== 'Enter') {
                return;
            }
            event.preventDefault();
            this._search();
        }
        selectMatch(event) {
            const productId = parseInt(event.currentTarget.dataset.id, 10);
            this._search(productId);
        }
        async _search(productId) {
            const input = this.searchRef.el;
            const text = input ? input.value : '';
            if (!productId && !(text || '').trim()) {
                this._focus();
                return;
            }
            const companyField = this.env.pos.config && this.env.pos.config.company_id;
            const companyId = companyField ? companyField[0] : false;
            if (!companyId) {
                this._showUnconfigured();
                return;
            }
            const result = await this.rpc({
                model: 'product.price.lookup',
                method: 'lookup',
                args: [text],
                kwargs: {
                    company_id: companyId,
                    product_id: productId || false,
                },
            });
            this._applyResult(result);
        }
        _showUnconfigured() {
            this.state.message = 'Esta sucursal no tiene listas de precios configuradas.';
            this.state.product = null;
            this.state.matches = [];
            this.state.prices = [];
            this._focus();
        }
        _applyResult(result) {
            if (!result || result.state === 'empty') {
                this._focus();
                return;
            }
            this.state.message = result.message || '';
            this.state.product = result.product || null;
            this.state.matches = result.matches || [];
            this.state.prices = result.prices || [];
            const input = this.searchRef.el;
            if (input && (result.state === 'prices' || result.state === 'unconfigured')) {
                input.value = '';
            }
            this._focus();
        }
        _focus() {
            const input = this.searchRef.el;
            if (input) {
                input.focus();
            }
        }
    }

    PriceLookupPopup.template = 'PriceLookupPopup';
    PriceLookupPopup.defaultProps = {
        cancelText: 'Cerrar',
        title: 'Consulta de precios',
    };

    Registries.Component.add(PriceLookupPopup);

    return PriceLookupPopup;
});
