odoo.define('pos_wholesale_control.models', function (require) {
    'use strict';

    var models = require('point_of_sale.models');

    var COMPANY_FIELDS = [
        'wholesale_control_active',
        'wholesale_previous_month_min',
        'wholesale_current_order_min',
        'wholesale_timezone',
        'wholesale_retail_pricelist_id',
        'wholesale_pricelist_id',
    ];

    // customer_type already exists on the partner. The register needs it to
    // pick Club Mayorista versus the distributor list without a second read.
    models.load_fields('res.partner', ['customer_type']);
    models.load_fields('res.company', COMPANY_FIELDS);

    models.load_models([{
        label: 'wholesale_company',
        loaded: function (self) {
            var companyId = self.config.company_id && self.config.company_id[0];
            if (self.company && self.company.id === companyId) {
                self.wholesale_company = self.company;
                return Promise.resolve();
            }
            if (!companyId) {
                self.wholesale_company = self.company;
                return Promise.resolve();
            }
            // The session company and the register company can differ. Thresholds
            // belong to the register, so read that company instead of reusing
            // the first allowed company loaded by point_of_sale.
            return self.rpc({
                model: 'res.company',
                method: 'read',
                args: [[companyId], ['id'].concat(COMPANY_FIELDS)],
            }).then(function (rows) {
                self.wholesale_company = (rows && rows[0]) || self.company;
            }, function () {
                self.wholesale_company = false;
            });
        },
    }, {
        model: 'pos.wholesale.pricelist.mapping',
        fields: ['customer_type', 'pricelist_id', 'company_id'],
        domain: function (self) {
            var company = self.wholesale_company || self.company;
            return [
                ['company_id', '=', company && company.id],
                ['active', '=', true],
            ];
        },
        loaded: function (self, mappings) {
            self.wholesale_mappings = mappings || [];
            self.wholesale_mapping_by_type = {};
            self.wholesale_mappings.forEach(function (mapping) {
                self.wholesale_mapping_by_type[mapping.customer_type] = mapping;
            });
            // Point of Sale already marks the logged-in user as manager when
            // they belong to point_of_sale.group_pos_manager.
            self.wholesale_is_manager = !!(self.user && self.user.role === 'manager');
        },
    }], {after: 'res.users'});

    models.PosModel.prototype.wholesaleControlActive = function () {
        var company = this.wholesale_company || this.company;
        return !!(company && company.wholesale_control_active);
    };

    models.PosModel.prototype.wholesaleFindPricelist = function (pricelistId) {
        if (!pricelistId) {
            return null;
        }
        var lists = this.pricelists || [];
        for (var index = 0; index < lists.length; index++) {
            if (lists[index].id === pricelistId) {
                return lists[index];
            }
        }
        return null;
    };

    var _super_order = models.Order.prototype;
    models.Order = models.Order.extend({
        initialize: function () {
            this.wholesale = this._wholesaleBlankState();
            this._wholesaleRestoring = false;
            _super_order.initialize.apply(this, arguments);
        },
        _wholesaleBlankState: function () {
            return {
                requestVersion: 0,
                loading: false,
                months: [],
                automaticDecision: 'retail',
                reasonCode: 'no_identified_customer',
                reasonText: '',
                retailAmount: 0,
                previousMonthAmount: 0,
                previousMonthMin: 0,
                currentOrderMin: 0,
                expectedPricelistId: false,
                retailPricelistId: false,
                override: false,
                error: false,
                validationError: false,
                customerId: false,
                customerType: false,
                timezone: false,
                currency: false,
                historyLoaded: false,
            };
        },
        set_client: function (client) {
            var previous = this.get_client();
            var previousId = previous && previous.id;
            _super_order.set_client.apply(this, arguments);
            var nextId = client && client.id;
            if (this._wholesaleRestoring || !this.wholesale || previousId === nextId) {
                return;
            }
            // An override belongs to one customer. The next customer needs a
            // new authorization even when the ticket is the same.
            this.wholesale.override = false;
            this.wholesale.historyLoaded = false;
            this.wholesale.customerId = false;
            this.wholesale.customerType = false;
            this.wholesale.months = [];
            this.wholesale.previousMonthAmount = 0;
            this.wholesale.error = false;
            this.wholesale.validationError = false;
        },
        init_from_JSON: function (json) {
            this._wholesaleRestoring = true;
            _super_order.init_from_JSON.apply(this, arguments);
            this._wholesaleRestoring = false;
            this._wholesaleRestoreState(json && json.wholesale_control);
        },
        export_as_JSON: function () {
            var json = _super_order.export_as_JSON.apply(this, arguments);
            // Nested on purpose. The server ignores this block and recalculates
            // the decision at payment. It only lets an unpaid ticket recover
            // after the browser restarts.
            json.wholesale_control = this._wholesaleExportState();
            return json;
        },
        _wholesaleExportState: function () {
            var state = this.wholesale || this._wholesaleBlankState();
            return {
                months: state.months || [],
                automatic_decision: state.automaticDecision,
                reason_code: state.reasonCode,
                reason_text: state.reasonText,
                retail_amount: state.retailAmount || 0,
                previous_month_amount: state.previousMonthAmount || 0,
                previous_month_min: state.previousMonthMin || 0,
                current_order_min: state.currentOrderMin || 0,
                expected_pricelist_id: state.expectedPricelistId || false,
                retail_pricelist_id: state.retailPricelistId || false,
                override: state.override || false,
                error: state.error || false,
                validation_error: state.validationError || false,
                customer_id: state.customerId || false,
                customer_type: state.customerType || false,
                timezone: state.timezone || false,
                currency: state.currency || false,
                history_loaded: !!state.historyLoaded,
            };
        },
        _wholesaleRestoreState: function (saved) {
            if (!saved) {
                return;
            }
            var state = this.wholesale || this._wholesaleBlankState();
            state.months = saved.months || [];
            state.automaticDecision = saved.automatic_decision || 'retail';
            state.reasonCode = saved.reason_code || 'no_identified_customer';
            state.reasonText = saved.reason_text || '';
            state.retailAmount = saved.retail_amount || 0;
            state.previousMonthAmount = saved.previous_month_amount || 0;
            state.previousMonthMin = saved.previous_month_min || 0;
            state.currentOrderMin = saved.current_order_min || 0;
            state.expectedPricelistId = saved.expected_pricelist_id || false;
            state.retailPricelistId = saved.retail_pricelist_id || false;
            state.override = saved.override || false;
            state.error = saved.error || false;
            state.validationError = saved.validation_error || false;
            state.customerId = saved.customer_id || false;
            state.customerType = saved.customer_type || false;
            state.timezone = saved.timezone || false;
            state.currency = saved.currency || false;
            state.historyLoaded = !!saved.history_loaded;
            state.loading = false;
            state.requestVersion = 0;
            this.wholesale = state;
        },
    });
});
