odoo.define('pos_product_requests.components', function (require) {
    'use strict';

    const AbstractAwaitablePopup = require('point_of_sale.AbstractAwaitablePopup');
    const NumberBuffer = require('point_of_sale.NumberBuffer');
    const PosComponent = require('point_of_sale.PosComponent');
    const ProductScreen = require('point_of_sale.ProductScreen');
    const Registries = require('point_of_sale.Registries');
    const { useBarcodeReader } = require('point_of_sale.custom_hooks');
    const { _t } = require('web.core');
    const { format, parse } = require('web.field_utils');
    const { useRef, useState } = owl.hooks;

    function useRequestControls() {
        // Keep keyboard shortcuts and barcodes from modifying the active ticket.
        NumberBuffer.use({});
        useBarcodeReader({ error() {} }, true);
    }

    function requestRpc(component, method, ...args) {
        return component.rpc({
            model: 'pos.product.request',
            method,
            args: [component.env.pos.pos_session.id, ...args],
            kwargs: { context: component.env.session.user_context },
        }, { shadow: true, timeout: 10000 });
    }

    function suppressRpcDialog(error) {
        if (error && error.event) {
            error.event.preventDefault();
        }
    }

    class RegisterProductRequestButton extends PosComponent {
        onClick() {
            return this.showPopup('ProductRequestPopup');
        }
    }
    RegisterProductRequestButton.template = 'pos_product_requests.RegisterButton';
    ProductScreen.addControlButton({
        component: RegisterProductRequestButton,
        condition: () => true,
    });

    class ProductRequestPopup extends AbstractAwaitablePopup {
        constructor() {
            super(...arguments);
            useRequestControls();
            this.productInput = useRef('productInput');
            this.state = useState({
                product: '',
                reason: '',
                errors: {},
                saving: false,
                saveError: '',
            });
            // getRandomValues also works on the POS HTTP origin.
            this.captureKey = Array.from(crypto.getRandomValues(new Uint32Array(4)),
                value => value.toString(16).padStart(8, '0')).join('');
        }

        get reasons() {
            return [
                { key: 'out_of_stock', label: _t('Out of stock') },
                { key: 'not_carried', label: _t("We don't carry it") },
                { key: 'does_not_exist', label: _t('Does not exist') },
            ];
        }

        mounted() {
            if (!this.env.isMobile) {
                this.productInput.el.focus();
            }
        }

        async confirm() {
            if (this.state.saving) return;
            const product = this.state.product.trim();
            const reason = this.state.reason;
            this.state.errors = {
                product: product ? '' : _t('Enter the requested product.'),
                reason: reason ? '' : _t('Select a reason.'),
            };
            this.state.saveError = '';
            if (!product || !reason) return;

            this.state.saving = true;
            try {
                await requestRpc(this, 'save_from_pos', product, reason, this.captureKey);
                await super.confirm();
            } catch (error) {
                suppressRpcDialog(error);
                const data = error && error.message && error.message.data;
                const expectedErrors = ['odoo.exceptions.ValidationError', 'odoo.exceptions.AccessError'];
                this.state.saveError = data && expectedErrors.includes(data.name)
                    ? data.message
                    : _t('Could not save the request. Check the connection and try again.');
            } finally {
                this.state.saving = false;
            }
        }

        cancel() {
            if (!this.state.saving) {
                super.cancel();
            }
        }
    }
    ProductRequestPopup.template = 'pos_product_requests.Popup';

    class ProductRequestHistoryButton extends PosComponent {
        get label() {
            return _t('Product Requests');
        }

        onClick() {
            return this.showTempScreen('ProductRequestHistory');
        }
    }
    ProductRequestHistoryButton.template = 'pos_product_requests.HistoryButton';

    class ProductRequestHistory extends PosComponent {
        constructor() {
            super(...arguments);
            useRequestControls();
            this.state = useState({ loading: true, error: false, rows: [] });
        }

        async mounted() {
            try {
                this.state.rows = await requestRpc(this, 'history_from_pos');
            } catch (error) {
                suppressRpcDialog(error);
                this.state.error = true;
            } finally {
                this.state.loading = false;
            }
        }

        formatDate(value) {
            return format.datetime(parse.datetime(value, {}, { isUTC: true }));
        }

        back() {
            this.props.resolve();
            this.trigger('close-temp-screen');
        }
    }
    ProductRequestHistory.template = 'pos_product_requests.History';

    Registries.Component.add(RegisterProductRequestButton);
    Registries.Component.add(ProductRequestPopup);
    Registries.Component.add(ProductRequestHistoryButton);
    Registries.Component.add(ProductRequestHistory);
});
