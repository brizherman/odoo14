odoo.define('custom_purchase_flow.purchase_state_badges', function (require) {
    "use strict";

    var ListRenderer = require('web.ListRenderer');

    /**
     * Tooltip on Estado badge via ListRenderer event delegation.
     * Reads reporte_ventas_compras from the row record data and shows
     * a Bootstrap tooltip on hover over the state badge in the list view.
     */
    ListRenderer.include({
        _renderView: function () {
            var self = this;
            return this._super.apply(this, arguments).then(function () {
                self._attachReporteTooltips();
            });
        },

        _attachReporteTooltips: function () {
            var self = this;
            if (!this.$el) { return; }

            this.$el.off('mouseenter.reporte mouseleave.reporte', 'td.o_field_cell .o_field_widget[name="state"]');

            this.$el.on('mouseenter.reporte', 'td.o_field_cell .o_field_widget[name="state"]', function () {
                var $badge = $(this);
                var $row = $badge.closest('tr.o_data_row');
                var recordId = $row.data('id');
                if (!recordId || !self.state || !self.state.data) { return; }

                var record = _.find(self.state.data, function (r) { return r.id === recordId; });
                if (!record || !record.data) { return; }

                var reporte = record.data.reporte_ventas_compras || 'Por favor llena el Reporte Ventas VS Compras';

                try { $badge.tooltip('dispose'); } catch (e) {}
                $badge
                    .attr('title', reporte)
                    .tooltip({
                        placement: 'left',
                        trigger: 'manual',
                        html: false,
                        container: 'body',
                    })
                    .tooltip('show');
            });

            this.$el.on('mouseleave.reporte', 'td.o_field_cell .o_field_widget[name="state"]', function () {
                try { $(this).tooltip('hide'); } catch (e) {}
            });
        },
    });
});
