odoo.define('alta_mayoristas.partner_classifier_list', function (require) {
    'use strict';

    const core = require('web.core');
    const ListController = require('web.ListController');
    const qweb = core.qweb;
    const _t = core._t;

    ListController.include({
        renderButtons: function () {
            this._super.apply(this, arguments);
            if (!this._isPartnerClassifierView()) {
                return;
            }
            this._selectedCustomerType = false;
            const $controls = $(qweb.render('PartnerClassifierList.controls'));
            this.$buttons = this.$buttons || $();
            this.$buttons.append($controls);
            this.$buttons.find('.o_partner_classifier_type')
                .on('change', this._onClassifierTypeChange.bind(this));
            this.$buttons.find('.o_partner_classifier_update')
                .on('click', this._onClassifierUpdate.bind(this));
        },

        _isPartnerClassifierView: function () {
            return (
                this.modelName === 'res.partner' &&
                this.initialState &&
                this.initialState.context &&
                this.initialState.context.partner_classifier_view
            );
        },

        _onClassifierTypeChange: function (ev) {
            const $target = $(ev.target);
            if ($target.prop('checked')) {
                this.$buttons.find('.o_partner_classifier_type').not($target).prop('checked', false);
                this._selectedCustomerType = $target.val();
            } else {
                this._selectedCustomerType = false;
            }
        },

        _onClassifierUpdate: function () {
            const self = this;
            const selectedIds = this.getSelectedIds();
            if (!selectedIds.length) {
                this.do_warn(_t('Warning'), _t('Seleccione al menos un contacto.'));
                return;
            }
            if (!this._selectedCustomerType) {
                this.do_warn(_t('Warning'), _t('Seleccione Mayorista, Público General o Distribuidores.'));
                return;
            }
            this._rpc({
                model: 'res.partner',
                method: 'action_bulk_set_customer_type',
                args: [selectedIds, this._selectedCustomerType],
            }).then(function (result) {
                if (result && result.params) {
                    self.displayNotification({
                        title: result.params.title,
                        message: result.params.message,
                        type: result.params.type || 'success',
                        sticky: result.params.sticky || false,
                    });
                }
                self.reload();
            });
        },
    });
});
