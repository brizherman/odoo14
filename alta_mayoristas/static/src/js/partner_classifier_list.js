odoo.define('alta_mayoristas.partner_classifier_list', function (require) {
    'use strict';

    const core = require('web.core');
    const ListController = require('web.ListController');
    const qweb = core.qweb;
    const _t = core._t;

    const PRICELIST_NAME_PUBLICO = 'Lista de precios a Publico en General';
    const CUSTOMER_TYPE_PRICELIST_NAME = {
        mayorista: 'Lista de precios de Mayorista',
        publico_general: PRICELIST_NAME_PUBLICO,
        distribuidores: 'Super Precios a Distribuidores',
        mayorista_dormido: PRICELIST_NAME_PUBLICO,
    };

    function stripAccents(text) {
        return text.normalize('NFD').replace(/[\u0300-\u036f]/g, '');
    }

    function normalizePricelistName(name) {
        let normalized = stripAccents((name || '').trim());
        if (normalized.slice(-6) === ' (MXN)') {
            normalized = normalized.slice(0, -6).trim();
        }
        return normalized.toLowerCase();
    }

    function withoutTrailingBranchCode(normalized) {
        const parts = normalized.split(/\s+/);
        if (parts.length < 2) {
            return normalized;
        }
        const suffix = parts[parts.length - 1];
        if (/^[a-z]{2,4}$/.test(suffix)) {
            return parts.slice(0, -1).join(' ');
        }
        return normalized;
    }

    function pricelistNameMatches(actualName, requiredName) {
        const actual = normalizePricelistName(actualName);
        const required = normalizePricelistName(requiredName);
        if (actual === required) {
            return true;
        }
        if (withoutTrailingBranchCode(actual) === required) {
            return true;
        }
        if (required.split(/\s+/).indexOf('publico') !== -1) {
            return actual.split(/\s+/).indexOf('publico') !== -1;
        }
        return false;
    }

    ListController.include({
        renderButtons: function () {
            this._super.apply(this, arguments);
            if (!this._isPartnerClassifierView()) {
                return;
            }
            this._selectedCustomerType = false;
            this._classifierPricelists = [];
            const $controls = $(qweb.render('PartnerClassifierList.controls'));
            this.$buttons = this.$buttons || $();
            this.$buttons.append($controls);
            this.$buttons.find('.o_partner_classifier_type')
                .on('change', this._onClassifierTypeChange.bind(this));
            this.$buttons.find('.o_partner_classifier_update')
                .on('click', this._onClassifierUpdate.bind(this));
            this._loadClassifierPricelists();
        },

        _isPartnerClassifierView: function () {
            return (
                this.modelName === 'res.partner' &&
                this.initialState &&
                this.initialState.context &&
                this.initialState.context.partner_classifier_view
            );
        },

        _normalizePricelistName: normalizePricelistName,

        _loadClassifierPricelists: function () {
            const self = this;
            return this._rpc({
                model: 'product.pricelist',
                method: 'search_read',
                domain: [],
                fields: ['id', 'name', 'company_id'],
                orderBy: [{name: 'name', asc: true}],
            }).then(function (pricelists) {
                self._classifierPricelists = pricelists || [];
                const $select = self.$buttons.find('.o_partner_classifier_pricelist');
                self._classifierPricelists.forEach(function (pricelist) {
                    $select.append($('<option/>', {
                        value: pricelist.id,
                        text: pricelist.name,
                    }));
                });
                if (self._selectedCustomerType) {
                    self._selectMatchingPricelist(self._selectedCustomerType);
                }
            });
        },

        _findMatchingPricelist: function (customerType) {
            const required = CUSTOMER_TYPE_PRICELIST_NAME[customerType];
            if (!required) {
                return undefined;
            }
            const companyId = (
                this.initialState.context.allowed_company_ids || []
            )[0];
            const matches = _.filter(this._classifierPricelists, function (pricelist) {
                return pricelistNameMatches(pricelist.name, required);
            });
            const companyMatch = _.find(matches, function (pricelist) {
                return pricelist.company_id && pricelist.company_id[0] === companyId;
            });
            return companyMatch || matches[0];
        },

        _selectMatchingPricelist: function (customerType) {
            const match = this._findMatchingPricelist(customerType);
            const $select = this.$buttons.find('.o_partner_classifier_pricelist');
            $select.val(match ? String(match.id) : '');
        },

        _onClassifierTypeChange: function (ev) {
            const $target = $(ev.target);
            if ($target.prop('checked')) {
                this.$buttons.find('.o_partner_classifier_type').not($target).prop('checked', false);
                this._selectedCustomerType = $target.val();
                this._selectMatchingPricelist(this._selectedCustomerType);
            } else {
                this._selectedCustomerType = false;
            }
        },

        _selectedPricelistId: function () {
            const raw = this.$buttons.find('.o_partner_classifier_pricelist').val();
            return raw ? parseInt(raw, 10) : false;
        },

        _pricelistMatchesCustomerType: function (pricelistId, customerType) {
            const required = CUSTOMER_TYPE_PRICELIST_NAME[customerType];
            if (!required || !pricelistId) {
                return false;
            }
            const selected = _.find(this._classifierPricelists, function (pricelist) {
                return pricelist.id === pricelistId;
            });
            return Boolean(selected && pricelistNameMatches(selected.name, required));
        },

        _getSelectedPartnerCustomerTypes: function () {
            const selectedIds = this.getSelectedIds();
            const types = [];
            const list = this.model.get(this.handle);
            const localIds = list && list.data ? list.data : [];
            const self = this;
            _.each(localIds, function (localId) {
                const record = typeof localId === 'string' ? self.model.get(localId) : localId;
                if (!record) {
                    return;
                }
                const resId = record.res_id || record.id;
                if (selectedIds.indexOf(resId) === -1) {
                    return;
                }
                const customerType = record.data && record.data.customer_type;
                if (customerType) {
                    types.push(customerType);
                }
            });
            return types;
        },

        _pricelistMatchesSelectedPartners: function (pricelistId) {
            const customerTypes = this._getSelectedPartnerCustomerTypes();
            const self = this;
            return _.every(customerTypes, function (customerType) {
                return self._pricelistMatchesCustomerType(pricelistId, customerType);
            });
        },

        _selectedPartnersMissingCustomerType: function () {
            const selectedCount = this.getSelectedIds().length;
            return this._getSelectedPartnerCustomerTypes().length < selectedCount;
        },

        _onClassifierUpdate: function () {
            const self = this;
            const selectedIds = this.getSelectedIds();
            if (!selectedIds.length) {
                this.do_warn(_t('Warning'), _t('Seleccione al menos un contacto.'));
                return;
            }
            const pricelistId = this._selectedPricelistId();
            if (!this._selectedCustomerType && !pricelistId) {
                this.do_warn(
                    _t('Warning'),
                    _t('Seleccione un tipo de cliente o una lista de precios.')
                );
                return;
            }
            if (this._selectedCustomerType) {
                if (!pricelistId) {
                    this.do_warn(
                        _t('Warning'),
                        _t('Seleccione la lista de precios que corresponde al tipo de cliente.')
                    );
                    return;
                }
                if (!this._pricelistMatchesCustomerType(pricelistId, this._selectedCustomerType)) {
                    this.do_warn(
                        _t('Warning'),
                        _t('La lista de precios no corresponde al tipo de cliente.')
                    );
                    return;
                }
            } else if (this._selectedPartnersMissingCustomerType()) {
                this.do_warn(
                    _t('Warning'),
                    _t('El contacto no tiene tipo de cliente.')
                );
                return;
            } else if (!this._pricelistMatchesSelectedPartners(pricelistId)) {
                this.do_warn(
                    _t('Warning'),
                    _t('La lista de precios no corresponde al tipo de cliente.')
                );
                return;
            }
            this._rpc({
                model: 'res.partner',
                method: 'action_bulk_set_customer_type',
                args: [selectedIds, this._selectedCustomerType, pricelistId],
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
