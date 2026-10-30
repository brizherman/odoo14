odoo.define('pos_wholesale_control.WholesaleStatusPanel', function (require) {
    'use strict';

    const PosComponent = require('point_of_sale.PosComponent');
    const Registries = require('point_of_sale.Registries');
    const { onChangeOrder } = require('point_of_sale.custom_hooks');

    const CUSTOMER_TYPE_LABELS = {
        mayorista: 'Mayorista',
        publico_general: 'Público General',
        distribuidores: 'Distribuidores',
        mayorista_dormido: 'Mayorista dormido',
    };

    class WholesaleStatusPanel extends PosComponent {
        constructor() {
            super(...arguments);
            onChangeOrder(this._onPrevOrder, this._onNewOrder);
        }
        get order() {
            return this.env.pos.get_order();
        }
        get wholesale() {
            const order = this.order;
            return (order && order.wholesale) || {};
        }
        get client() {
            return this.order ? this.order.get_client() : null;
        }
        get customerName() {
            return this.client ? this.client.name : '';
        }
        get customerTypeLabel() {
            const type = this.wholesale.customerType || (this.client && this.client.customer_type);
            if (!type) {
                return '';
            }
            return this.env._t(CUSTOMER_TYPE_LABELS[type] || type);
        }
        get isLoading() {
            return !!this.wholesale.loading;
        }
        get hasOverride() {
            return !!(this.wholesale.override && this.wholesale.override.pricelist_id);
        }
        get needsIdentification() {
            return !this.client;
        }
        get showMonths() {
            return !!(this.client && this.wholesale.months && this.wholesale.months.length);
        }
        get months() {
            return this.wholesale.months || [];
        }
        get errorText() {
            return this.wholesale.validationError || this.wholesale.error || false;
        }
        get reasonText() {
            if (this.isLoading) {
                return this.env._t('Validating…');
            }
            return this.wholesale.reasonText || this.env._t('No decision yet.');
        }
        get pricelistName() {
            const order = this.order;
            if (!order || !order.pricelist) {
                return '';
            }
            return order.pricelist.display_name || order.pricelist.name || '';
        }
        get pricingLabel() {
            if (this.hasOverride) {
                return this.wholesale.override.final_decision === 'wholesale'
                    ? this.env._t('Wholesale')
                    : this.env._t('Retail / General Public');
            }
            if (this.wholesale.automaticDecision === 'wholesale' && !this.wholesale.error) {
                return this.env._t('Wholesale');
            }
            return this.env._t('Retail / General Public');
        }
        get automaticDecisionLabel() {
            return this.wholesale.automaticDecision === 'wholesale'
                ? this.env._t('Wholesale')
                : this.env._t('Retail / General Public');
        }
        get statusTitle() {
            if (this.errorText) {
                return this.env._t('Wholesale control — error');
            }
            if (this.hasOverride) {
                return this.env._t('Wholesale control — override');
            }
            if (this.wholesale.automaticDecision === 'wholesale' && !this.wholesale.error) {
                return this.env._t('Wholesale control — wholesale');
            }
            return this.env._t('Wholesale control — retail');
        }
        get statusIconClass() {
            if (this.isLoading) {
                return 'fa fa-spinner fa-spin';
            }
            if (this.errorText) {
                return 'fa fa-exclamation-triangle';
            }
            if (this.hasOverride) {
                return 'fa fa-key';
            }
            if (this.wholesale.automaticDecision === 'wholesale' && !this.wholesale.error) {
                return 'fa fa-certificate';
            }
            if (!this.client) {
                return 'fa fa-user';
            }
            return 'fa fa-tag';
        }
        get panelClass() {
            const classes = {};
            if (this.isLoading) {
                classes['wholesale-state-loading'] = true;
            } else if (this.errorText) {
                classes['wholesale-state-error'] = true;
            } else if (this.hasOverride) {
                classes['wholesale-state-override'] = true;
            } else if (this.wholesale.automaticDecision === 'wholesale' && !this.wholesale.error) {
                classes['wholesale-state-wholesale'] = true;
            } else {
                classes['wholesale-state-retail'] = true;
            }
            return classes;
        }
        get canRequestOverride() {
            if (!this.env.pos.wholesaleControlActive()) {
                return false;
            }
            if (!this.client || this.hasOverride || this.isLoading) {
                return false;
            }
            if (this.wholesale.reasonCode === 'history_unavailable' || this.wholesale.error) {
                return true;
            }
            return this.wholesale.automaticDecision !== 'wholesale';
        }
        formatAmount(amount) {
            return this.env.pos.format_currency(amount || 0);
        }
        _onNewOrder(order) {
            if (order) {
                order.on('change', this.render, this);
            }
            this.render();
        }
        _onPrevOrder(order) {
            if (order) {
                order.off('change', null, this);
            }
        }
        async onOverrideClick() {
            const order = this.order;
            if (!order || !this.canRequestOverride) {
                return;
            }
            if (!this.env.pos.config.module_pos_hr) {
                await this.showPopup('ErrorPopup', {
                    title: this.env._t('Manager override'),
                    body: this.env._t(
                        'This register does not use employee PINs, so it cannot authorize an override.'
                    ),
                });
                return;
            }
            const employees = this.env.pos.employees || [];
            if (!employees.length) {
                await this.showPopup('ErrorPopup', {
                    title: this.env._t('Manager override'),
                    body: this.env._t(
                        'No POS employees are available to authorize an override on this register.'
                    ),
                });
                return;
            }
            const { confirmed: picked, payload: manager } = await this.showPopup('SelectionPopup', {
                title: this.env._t('Select manager'),
                list: employees.map((employee) => ({
                    id: employee.id,
                    item: employee,
                    label: employee.name,
                    isSelected: false,
                })),
            });
            if (!picked || !manager) {
                return;
            }
            const { confirmed, payload } = await this.showPopup('ManagerOverridePopup', {
                title: this.env._t('Manager override'),
                automaticDecision: this.automaticDecisionLabel,
                reasonText: this.reasonText,
                confirmText: this.env._t('Authorize'),
                cancelText: this.env._t('Cancel'),
            });
            if (!confirmed || !payload) {
                return;
            }
            if (manager.pin && Sha1.hash(payload.pin) !== manager.pin) {
                await this.showPopup('ErrorPopup', {
                    title: this.env._t('Incorrect Password'),
                    body: this.env._t('The manager PIN is incorrect.'),
                });
                return;
            }
            await this._wholesaleAuthorize(manager, payload.pin, payload.reason);
        }
        async _wholesaleAuthorize(manager, pin, reason) {
            const order = this.order;
            const uiOrder = order.export_as_JSON();
            try {
                const result = await this.rpc({
                    model: 'pos.wholesale.override',
                    method: 'authorize_from_pos',
                    args: [
                        manager.id,
                        pin,
                        reason,
                        'wholesale',
                        uiOrder,
                    ],
                });
                if (!result || !result.applied_pricelist || !result.applied_pricelist.id) {
                    await this.showPopup('ErrorPopup', {
                        title: this.env._t('Manager override'),
                        body: this.env._t('The server did not return an authorized pricelist.'),
                    });
                    return;
                }
                order.wholesale.override = {
                    id: result.id,
                    pricelist_id: result.applied_pricelist.id,
                    reason: result.reason,
                    final_decision: result.final_decision || 'wholesale',
                    automatic_decision: result.automatic_decision,
                };
                order.wholesale.validationError = false;
                order.wholesale.error = false;
                if (order._wholesaleUsePricelist) {
                    order._wholesaleUsePricelist(order._wholesaleAllowedPricelist());
                } else {
                    order.trigger('change', order);
                    order.save_to_db();
                }
                this.render();
            } catch (error) {
                await this.showPopup('ErrorPopup', {
                    title: this.env._t('Manager override denied'),
                    body: this._wholesaleRpcMessage(error),
                });
            }
        }
        _wholesaleRpcMessage(error) {
            const nested = error && error.message;
            const data = (error && error.data) || (nested && nested.data);
            if (data && data.message) {
                return data.message;
            }
            if (nested && typeof nested === 'string') {
                return nested;
            }
            if (error && typeof error.message === 'string') {
                return error.message;
            }
            return this.env._t(
                'The manager override could not be authorized. Check the PIN, permissions, and connection.'
            );
        }
    }

    WholesaleStatusPanel.template = 'WholesaleStatusPanel';

    Registries.Component.add(WholesaleStatusPanel);

    return WholesaleStatusPanel;
});
