odoo.define('alta_mayoristas.ClientDetailsEdit', function (require) {
    'use strict';

    const { _t } = require('web.core');
    const ClientDetailsEdit = require('point_of_sale.ClientDetailsEdit');
    const Registries = require('point_of_sale.Registries');

    const PRICELIST_NAME_PUBLICO = 'Lista de precios a Publico en General';
    const CUSTOMER_TYPE_PRICELIST_NAME = {
        mayorista: 'Lista de precios de Mayorista',
        publico_general: PRICELIST_NAME_PUBLICO,
        distribuidores: 'Super Precios a Distribuidores',
        mayorista_dormido: PRICELIST_NAME_PUBLICO,
    };
    const POS_CUSTOMER_TYPES = ['mayorista', 'publico_general', 'distribuidores'];

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

    const AltaMayoristasClientDetailsEdit = (ClientDetailsEdit) =>
        class extends ClientDetailsEdit {
            constructor() {
                super(...arguments);
                if (!this.intFields.includes('primary_company_id')) {
                    this.intFields.push('primary_company_id');
                }
            }
            isCustomerTypeSelected(value) {
                return this._getCustomerType() === value;
            }
            onCustomerTypeChange(event) {
                const selectedValue = event.target.dataset.customerType;
                if (event.target.checked) {
                    this.changes.customer_type = selectedValue;
                    const match = this._findMatchingPricelist(selectedValue);
                    if (match) {
                        this.changes.property_product_pricelist = match.id;
                    }
                } else if (this._getCustomerType() === selectedValue) {
                    this.changes.customer_type = false;
                }
                this.render();
            }
            _getCustomerType() {
                if (Object.prototype.hasOwnProperty.call(this.changes, 'customer_type')) {
                    return this.changes.customer_type;
                }
                return this.props.partner.customer_type;
            }
            _getPricelistValue() {
                if (Object.prototype.hasOwnProperty.call(
                    this.changes,
                    'property_product_pricelist'
                )) {
                    return this.changes.property_product_pricelist;
                }
                if (this.props.partner.property_product_pricelist) {
                    return this.props.partner.property_product_pricelist[0];
                }
                return false;
            }
            _findMatchingPricelist(customerType) {
                const required = CUSTOMER_TYPE_PRICELIST_NAME[customerType];
                if (!required) {
                    return undefined;
                }
                const pricelists = this.env.pos.pricelists || [];
                const matches = _.filter(pricelists, function (pricelist) {
                    return pricelistNameMatches(pricelist.name, required);
                });
                if (!matches.length) {
                    return undefined;
                }
                const selectedId = parseInt(this._getPricelistValue(), 10);
                const selectedMatch = _.find(matches, function (pricelist) {
                    return pricelist.id === selectedId;
                });
                return selectedMatch || matches[0];
            }
            isPricelistSelected(pricelistId) {
                return parseInt(this._getPricelistValue(), 10) === pricelistId;
            }
            _selectedPricelistMatchesType(customerType) {
                const required = CUSTOMER_TYPE_PRICELIST_NAME[customerType];
                if (!required) {
                    return false;
                }
                const pricelistId = parseInt(this._getPricelistValue(), 10) || false;
                const selected = _.find(this.env.pos.pricelists || [], function (pricelist) {
                    return pricelist.id === pricelistId;
                });
                return Boolean(selected && pricelistNameMatches(selected.name, required));
            }
            _validateTypePricelistPair() {
                const customerType = this._getCustomerType();
                if (!customerType) {
                    return true;
                }
                if (
                    POS_CUSTOMER_TYPES.indexOf(customerType) === -1 &&
                    customerType !== 'mayorista_dormido'
                ) {
                    return true;
                }
                if (!this._findMatchingPricelist(customerType)) {
                    this.showPopup('ErrorPopup', {
                        title: _t('No se encontró la lista de precios requerida.'),
                    });
                    return false;
                }
                if (!this._selectedPricelistMatchesType(customerType)) {
                    this.showPopup('ErrorPopup', {
                        title: _t('La lista de precios no corresponde al tipo de cliente.'),
                    });
                    return false;
                }
                return true;
            }
            saveChanges() {
                const isNewCustomer = !this.props.partner.id;
                if (isNewCustomer && !this._getCustomerType()) {
                    return this.showPopup('ErrorPopup', {
                        title: _t('Select Mayorista, Público General or Distribuidores'),
                    });
                }
                const mobile = (
                    this.changes.mobile !== undefined
                        ? this.changes.mobile
                        : this.props.partner.mobile || ''
                ).toString().trim();
                if (!mobile) {
                    return this.showPopup('ErrorPopup', {
                        title: _t('Movil (Whatsapp) es obligatorio.'),
                    });
                }
                if (!this._validateTypePricelistPair()) {
                    return;
                }
                if (isNewCustomer && this.env.pos.company) {
                    this.changes.primary_company_id = this.env.pos.company.id;
                }
                return super.saveChanges();
            }
        };

    Registries.Component.extend(ClientDetailsEdit, AltaMayoristasClientDetailsEdit);

    return ClientDetailsEdit;
});
