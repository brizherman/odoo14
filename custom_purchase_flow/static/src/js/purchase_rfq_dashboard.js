odoo.define('custom_purchase_flow.purchase_rfq_dashboard', function (require) {
    "use strict";

    var PurchaseDashboard = require('purchase.dashboard');

    var PurchaseListDashboardRenderer = PurchaseDashboard.PurchaseListDashboardRenderer;
    var PurchaseListDashboardController = PurchaseDashboard.PurchaseListDashboardController;

    // Extend the purchase list dashboard renderer to react to our custom squares
    PurchaseListDashboardRenderer.include({
        events: _.extend({}, PurchaseListDashboardRenderer.prototype.events, {
            'click .o_rfq_dashboard_square': '_onRfqDashboardSquareClicked',
        }),

        _onRfqDashboardSquareClicked: function (ev) {
            ev.preventDefault();
            ev.stopPropagation();
            var $square = $(ev.currentTarget);
            var state = $square.data('state');
            if (!state) {
                return;
            }
            this.trigger_up('rfq_dashboard_filter_state', { state: state });
        },
    });

    // Extend the purchase list dashboard controller to apply/remove the filter
    PurchaseListDashboardController.include({
        custom_events: _.extend({}, PurchaseListDashboardController.prototype.custom_events, {
            rfq_dashboard_filter_state: '_onRfqDashboardFilterState',
        }),

        init: function () {
            this._super.apply(this, arguments);
            this._rfqActiveState = null;
        },

        _onRfqDashboardFilterState: function (ev) {
            ev.stopPropagation();

            if (this.modelName !== 'purchase.order') {
                return;
            }

            var state = ev.data.state;
            var dataPoint = this.model.get(this.handle);
            var domain = dataPoint && dataPoint.domain ? dataPoint.domain.slice() : [];

            // Strip any existing simple state '=' filters
            domain = _.filter(domain, function (cond) {
                return !(cond && cond.length === 3 && cond[0] === 'state' && cond[1] === '=');
            });

            if (this._rfqActiveState === state) {
                this._rfqActiveState = null;
            } else {
                this._rfqActiveState = state;
                domain.push(['state', '=', state]);
            }

            var self = this;
            this.reload({ domain: domain }).then(function () {
                self._updateRfqDashboardActiveSquare();
            });
        },

        _updateRfqDashboardActiveSquare: function () {
            var $dashboard = this.$('.o_purchase_dashboard');
            if (!$dashboard.length) {
                return;
            }
            var $squares = $dashboard.find('.o_rfq_dashboard_square');
            $squares.removeClass('o_rfq_dashboard_active');
            if (this._rfqActiveState) {
                $dashboard
                    .find('.o_rfq_dashboard_square[data-state=\"' + this._rfqActiveState + '\"]')
                    .addClass('o_rfq_dashboard_active');
            }
        },

        _update: function () {
            var self = this;
            return this._super.apply(this, arguments).then(function () {
                self._updateRfqDashboardActiveSquare();
            });
        },
    });

});

