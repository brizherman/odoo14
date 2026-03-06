odoo.define('custom_purchase_flow.purchase_state_badges', function (require) {
    "use strict";

    var fieldRegistry = require('web.field_registry_owl');
    var basicFields = require('web.basic_fields_owl');

    /**
     * Extend the OWL FieldBadge widget so that any badge for a 'state' field
     * gets a value-specific CSS class like 'po-state-draft'.
     */
    var PatchedFieldBadge = basicFields.FieldBadge.extend({
        patched: function () {
            this._super.apply(this, arguments);
            try {
                if (this.props &&
                    this.props.name === 'state' &&
                    this.props.value !== undefined &&
                    this.el) {
                    var state = this.props.value;
                    // Remove any previous per-state class
                    this.el.className = (this.el.className || '')
                        .split(' ')
                        .filter(function (c) { return c.indexOf('po-state-') !== 0; })
                        .join(' ')
                        .trim();
                    this.el.className += ' po-state-' + state;
                }
            } catch (e) {
                console.error('custom_purchase_flow.purchase_state_badges FieldBadge error', e);
            }
        },
    });

    fieldRegistry.add('badge', PatchedFieldBadge);
});

