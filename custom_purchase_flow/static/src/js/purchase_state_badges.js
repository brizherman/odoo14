odoo.define('custom_purchase_flow.purchase_state_badges', function (require) {
   "use strict";

   // web.EditableListRenderer does NOT export a class — it just calls
   // ListRenderer.include() as a side effect. Requiring it here ensures
   // it has already patched ListRenderer before we do our own patches.
   require('web.EditableListRenderer');
   var ListRenderer = require('web.ListRenderer');

   /**
    * Force a fixed 105px width on the Folio (name) column in the purchase order
    * list view. _freezeColumnWidths is defined by the EditableListRenderer include
    * on ListRenderer, so we patch it here after that include has run.
    */
   ListRenderer.include({
        _freezeColumnWidths: function () {
            this._super.apply(this, arguments);
            if (!this.$el || !this.$el.hasClass('o_purchase_order')) { return; }
            var thName = this.el && this.el.querySelector('thead th[data-name="name"]');
            if (thName) { thName.style.width = '110px'; thName.style.maxWidth = '110px'; }
            var thPartner = this.el && this.el.querySelector('thead th[data-name="partner_id"]');
            if (thPartner) { thPartner.style.width = '200px'; thPartner.style.maxWidth = '200px'; }
        },

        /**
         * Tooltip on Estado badge cell via event delegation.
         * Reads reporte_ventas_compras from row record data and shows a Bootstrap
         * tooltip on hover over the state <td> in the list view.
         *
         * The state field uses widget="badge" so the <td> gets classes:
         *   o_data_cell o_field_cell o_badge_cell
         * The field name is NOT added as a class on body <td>s (only on aggregate
         * cells in debug mode). So we scope to .o_badge_cell inside the purchase
         * order list (which has class o_purchase_order on the table).
         */
        _renderView: function () {
            var self = this;
            return this._super.apply(this, arguments).then(function () {
                self._attachReporteTooltips();
            });
        },

        _attachReporteTooltips: function () {
            var self = this;
            if (!this.$el) { return; }

            // Only activate on the purchase order list view
            if (!this.$el.hasClass('o_purchase_order')) { return; }

            this.$el.off('mouseenter.reporte mouseleave.reporte', 'td.o_badge_cell');

            this.$el.on('mouseenter.reporte', 'td.o_badge_cell', function () {
                var $cell = $(this);
                var $row = $cell.closest('tr.o_data_row');
                var recordId = $row.attr('data-id');
                if (!recordId || !self.state || !self.state.data) { return; }

                var record = _.find(self.state.data, function (r) { return r.id === recordId; });
                if (!record || !record.data) { return; }

                var reporte = record.data.reporte_ventas_compras || 'Por favor llena el Reporte Ventas VS Compras';

                try { $cell.tooltip('dispose'); } catch (e) {}
                $cell
                    .attr('title', reporte)
                    .tooltip({
                        placement: 'left',
                        trigger: 'manual',
                        html: false,
                        container: 'body',
                    })
                    .tooltip('show');
            });

            this.$el.on('mouseleave.reporte', 'td.o_badge_cell', function () {
                try { $(this).tooltip('hide'); } catch (e) {}
            });
        },
    });
});
