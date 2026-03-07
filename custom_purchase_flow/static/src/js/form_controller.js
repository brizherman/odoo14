odoo.define('custom_purchase_flow.form_controller', function (require) {
    "use strict";
    /* Purchase order form: hide Edit when state is not draft. */
    var FormController = require('web.FormController');

    FormController.include({
        is_action_enabled: function (action) {
            // Allow Edit for purchase.order only when can_edit_po is true.
            // can_edit_po is true for: draft (all users), to approve (Purchase Dept only).
            if (action === 'edit' && this.modelName === 'purchase.order') {
                try {
                    var record = this.model.get(this.handle, {raw: true});
                    if (record && record.data && record.data.can_edit_po !== undefined) {
                        if (!record.data.can_edit_po) {
                            return false;
                        }
                    }
                } catch (e) {
                    // ignore
                }
            }
            return this._super.apply(this, arguments);
        },
    });
});
