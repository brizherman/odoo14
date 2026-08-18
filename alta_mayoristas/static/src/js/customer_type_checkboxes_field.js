odoo.define('alta_mayoristas.customer_type_checkboxes', function (require) {
    'use strict';

    const core = require('web.core');
    const relational_fields = require('web.relational_fields');
    const field_registry = require('web.field_registry');
    const qweb = core.qweb;

    const FieldRadio = relational_fields.FieldRadio;

    const FieldCustomerTypeCheckboxes = FieldRadio.extend({
        className: 'o_field_customer_type_checkboxes o_horizontal',
        events: _.extend({}, FieldRadio.prototype.events, {
            'change input': '_onInputChange',
        }),
        _renderEdit: function () {
            const self = this;
            const currentValue = this.value;
            this.$el.empty();
            this.$el.attr('role', 'group').attr('aria-label', this.string);
            _.each(this.values, function (value, index) {
                if (value[0] === false) {
                    return;
                }
                self.$el.append(qweb.render('FieldCustomerTypeCheckboxes.button', {
                    checked: value[0] === currentValue,
                    id: self.unique_id + '_' + value[0],
                    index: index,
                    value: value,
                }));
            });
        },
        _onInputChange: function (event) {
            const index = $(event.target).data('index');
            const value = this.values[index];
            if (event.target.checked) {
                this._setValue(value[0]);
            } else {
                this._setValue(false);
            }
        },
    });

    field_registry.add('customer_type_checkboxes', FieldCustomerTypeCheckboxes);

    return FieldCustomerTypeCheckboxes;
});
