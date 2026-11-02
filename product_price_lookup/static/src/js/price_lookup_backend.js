odoo.define('product_price_lookup.backend', function (require) {
    'use strict';

    const AbstractAction = require('web.AbstractAction');
    const core = require('web.core');

    const PriceLookupBackend = AbstractAction.extend({
        template: 'ProductPriceLookupBackend',
        hasControlPanel: false,
        events: {
            'keydown .o_price_lookup_search': '_onSearchKeydown',
            'click .o_price_lookup_match': '_onMatchClick',
        },

        start: function () {
            const self = this;
            return this._super.apply(this, arguments).then(function () {
                self._focusSearch();
            });
        },

        _onSearchKeydown: function (event) {
            if (event.key !== 'Enter') {
                return;
            }
            event.preventDefault();
            this._runLookup(false);
        },

        _onMatchClick: function (event) {
            const productId = parseInt(event.currentTarget.getAttribute('data-id'), 10);
            this._runLookup(productId);
        },

        _runLookup: function (productId) {
            const self = this;
            const text = this.$('.o_price_lookup_search').val() || '';
            if (!productId && !text.trim()) {
                this._focusSearch();
                return Promise.resolve();
            }
            // Company comes from the web client context, so a company switch
            // applies on the next search without keeping the previous company.
            return this._rpc({
                model: 'product.price.lookup',
                method: 'lookup',
                args: [text],
                kwargs: {
                    product_id: productId || false,
                },
            }).then(function (result) {
                self._applyResult(result);
            });
        },

        _applyResult: function (result) {
            if (!result || result.state === 'empty') {
                this._focusSearch();
                return;
            }
            this.$('.o_price_lookup_result').html(core.qweb.render(
                'ProductPriceLookupResult',
                {
                    message: result.message || '',
                    product: result.product || false,
                    matches: result.matches || [],
                    prices: result.prices || [],
                },
            ));
            if (result.state === 'prices' || result.state === 'unconfigured') {
                this.$('.o_price_lookup_search').val('');
            }
            this._focusSearch();
        },

        _focusSearch: function () {
            const input = this.$('.o_price_lookup_search');
            if (input.length) {
                input.focus();
            }
        },
    });

    core.action_registry.add('product_price_lookup', PriceLookupBackend);

    return PriceLookupBackend;
});
