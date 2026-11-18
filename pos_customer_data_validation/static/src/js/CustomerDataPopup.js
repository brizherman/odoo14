odoo.define('pos_customer_data_validation.CustomerDataPopup', function (require) {
    'use strict';

    const AbstractAwaitablePopup = require('point_of_sale.AbstractAwaitablePopup');
    const Registries = require('point_of_sale.Registries');
    const { useState } = owl.hooks;
    const fieldUtils = require('web.field_utils');
    const { _t } = require('web.core');

    class CustomerDataPopup extends AbstractAwaitablePopup {
        constructor() {
            super(...arguments);
            this.state = useState({
                loading: true, saving: false, error: '', errors: {},
                values: { name: '', mobile: '', customer_type: '', property_product_pricelist: '' },
            });
            this.data = null;
            this.closed = false;
        }
        async mounted() {
            await this.load();
        }
        willUnmount() {
            this.closed = true;
        }
        async load() {
            try {
                const data = await this.rpc({
                    model: 'res.partner', method: 'pos_customer_data_read',
                    args: [this.props.partnerId, this.env.pos.config.id],
                }, { shadow: true, timeout: 10000 });
                if (this.closed) return;
                this.data = data;
                const partner = data.partner;
                this.initial = {
                    name: partner.name || '', mobile: partner.mobile || '',
                    customer_type: partner.customer_type || '',
                    property_product_pricelist: partner.property_product_pricelist
                        ? String(partner.property_product_pricelist[0]) : '',
                };
                Object.assign(this.state.values, this.initial);
            } catch (error) {
                if (error && error.event) error.event.preventDefault();
                if (!this.closed) this.state.error = this.errorMessage(error);
            } finally {
                if (!this.closed) this.state.loading = false;
            }
        }
        updatedAt(field) {
            const key = field === 'property_product_pricelist' ? 'pricelist' : field;
            const value = this.data.partner['pos_' + key + '_updated_at'];
            return value ? fieldUtils.format.datetime(
                fieldUtils.parse.datetime(value, {}, { isUTC: true }),
            ) : _t('Sin fecha registrada');
        }
        errorMessage(error) {
            const data = error && (error.data || (error.message && error.message.data));
            return (data && data.message) || _t('No se pudo comunicar con el servidor. Revisa la conexión e inténtalo de nuevo.');
        }
        change(event) {
            this.state.values[event.target.name] = event.target.value;
            if (event.target.name === 'customer_type') {
                const matches = this.data.type_pricelist_ids[event.target.value] || [];
                if (!matches.includes(Number(this.state.values.property_product_pricelist))) {
                    this.state.values.property_product_pricelist = matches.length ? String(matches[0]) : '';
                }
            }
        }
        validate() {
            const values = this.state.values;
            const errors = {};
            if (!values.name.trim()) errors.name = _t('Captura el nombre.');
            if (!values.mobile.trim()) errors.mobile = _t('Captura el WhatsApp.');
            if (!this.data.customer_types.some(type => type[0] === values.customer_type)) {
                errors.customer_type = _t('Selecciona el tipo de cliente.');
            }
            const priceId = Number(values.property_product_pricelist);
            if (!this.data.pricelists.some(price => price.id === priceId)) {
                errors.property_product_pricelist = _t('Selecciona una tarifa disponible.');
            } else if (!(this.data.type_pricelist_ids[values.customer_type] || []).includes(priceId)) {
                errors.property_product_pricelist = _t('La tarifa no corresponde al tipo de cliente.');
            }
            this.state.errors = errors;
            return !Object.keys(errors).length;
        }
        async confirm() {
            if (this.closed || this.state.loading || this.state.saving || !this.data) return;
            this.state.error = '';
            if (!this.validate()) return;
            const changes = {};
            for (const key of Object.keys(this.initial)) {
                if (this.state.values[key] !== this.initial[key]) {
                    changes[key] = key === 'property_product_pricelist'
                        ? Number(this.state.values[key]) : this.state.values[key];
                }
            }
            this.state.saving = true;
            try {
                if (!this.props.isCurrent()) {
                    this.state.error = _t('El ticket o cliente cambió. Cancela esta revisión y vuelve a validar.');
                    return;
                }
                const data = await this.rpc({
                    model: 'res.partner', method: 'pos_customer_data_save',
                    args: [this.props.partnerId, this.env.pos.config.id, changes],
                }, { shadow: true, timeout: 10000 });
                if (this.closed) return;
                if (!this.props.isCurrent()) {
                    this.state.error = _t('El ticket o cliente cambió. Cancela esta revisión y vuelve a validar.');
                    return;
                }
                this.closed = true;
                this.props.resolve({ confirmed: true, payload: data });
                this.trigger('close-popup');
            } catch (error) {
                if (error && error.event) error.event.preventDefault();
                if (!this.closed) this.state.error = this.errorMessage(error);
            } finally {
                if (!this.closed) this.state.saving = false;
            }
        }
        cancel() {
            if (this.closed || this.state.saving) return;
            this.closed = true;
            super.cancel();
        }
    }
    CustomerDataPopup.template = 'pos_customer_data_validation.CustomerDataPopup';
    Registries.Component.add(CustomerDataPopup);
    return CustomerDataPopup;
});
