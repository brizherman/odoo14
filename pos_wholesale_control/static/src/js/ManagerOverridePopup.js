odoo.define('pos_wholesale_control.ManagerOverridePopup', function (require) {
    'use strict';

    const { useState, useRef } = owl.hooks;
    const AbstractAwaitablePopup = require('point_of_sale.AbstractAwaitablePopup');
    const Registries = require('point_of_sale.Registries');

    class ManagerOverridePopup extends AbstractAwaitablePopup {
        constructor() {
            super(...arguments);
            this.state = useState({
                pin: '',
                reason: '',
            });
            this.pinRef = useRef('pin');
            this.reasonRef = useRef('reason');
        }
        mounted() {
            if (this.pinRef.el) {
                this.pinRef.el.focus();
            }
        }
        async confirm() {
            const reason = (this.state.reason || '').trim();
            if (!reason) {
                await this.showPopup('ErrorPopup', {
                    title: this.env._t('Manager override'),
                    body: this.env._t('A non-empty reason is required.'),
                });
                if (this.reasonRef.el) {
                    this.reasonRef.el.focus();
                }
                return;
            }
            if (!(this.state.pin || '').length) {
                await this.showPopup('ErrorPopup', {
                    title: this.env._t('Manager override'),
                    body: this.env._t('Enter the manager PIN.'),
                });
                if (this.pinRef.el) {
                    this.pinRef.el.focus();
                }
                return;
            }
            await super.confirm();
        }
        getPayload() {
            return {
                pin: this.state.pin || '',
                reason: (this.state.reason || '').trim(),
            };
        }
    }

    ManagerOverridePopup.template = 'ManagerOverridePopup';
    ManagerOverridePopup.defaultProps = {
        confirmText: 'Authorize',
        cancelText: 'Cancel',
        title: 'Manager override',
        automaticDecision: '',
        reasonText: '',
    };

    Registries.Component.add(ManagerOverridePopup);

    return ManagerOverridePopup;
});
