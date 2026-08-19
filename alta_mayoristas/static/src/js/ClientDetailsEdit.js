odoo.define('alta_mayoristas.ClientDetailsEdit', function (require) {
    'use strict';

    const { _t } = require('web.core');
    const ClientDetailsEdit = require('point_of_sale.ClientDetailsEdit');
    const Registries = require('point_of_sale.Registries');

    const AltaMayoristasClientDetailsEdit = (ClientDetailsEdit) =>
        class extends ClientDetailsEdit {
            constructor() {
                super(...arguments);
                if (!this.intFields.includes('primary_company_id')) {
                    this.intFields.push('primary_company_id');
                }
            }
            isCustomerTypeSelected(value) {
                const current = Object.prototype.hasOwnProperty.call(
                    this.changes,
                    'customer_type'
                )
                    ? this.changes.customer_type
                    : this.props.partner.customer_type;
                return current === value;
            }
            onCustomerTypeChange(event) {
                const selectedValue = event.target.dataset.customerType;
                if (event.target.checked) {
                    this.changes.customer_type = selectedValue;
                } else if (this.changes.customer_type === selectedValue) {
                    this.changes.customer_type = false;
                }
                this.render();
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
            saveChanges() {
                const isNewCustomer = !this.props.partner.id;
                if (isNewCustomer && !this.changes.customer_type) {
                    return this.showPopup('ErrorPopup', {
                        title: _t('Select Mayorista or Público General'),
                    });
                }
                if (isNewCustomer && this.env.pos.pricelists.length > 1) {
                    const pricelistId = this._getPricelistValue();
                    if (!pricelistId) {
                        return this.showPopup('ErrorPopup', {
                            title: _t('Select a Pricelist'),
                        });
                    }
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
