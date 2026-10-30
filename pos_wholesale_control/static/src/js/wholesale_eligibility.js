odoo.define('pos_wholesale_control.wholesale_eligibility', function (require) {
    'use strict';

    var core = require('web.core');
    var utils = require('web.utils');
    var models = require('point_of_sale.models');

    var _t = core._t;
    var roundPrecision = utils.round_precision;
    var REEVALUATE_DELAY_MS = 50;

    function many2oneId(value) {
        if (!value || value === true) {
            return false;
        }
        if (Object.prototype.toString.call(value) === '[object Array]') {
            return value[0] || false;
        }
        if (typeof value === 'number') {
            return value;
        }
        return false;
    }

    function currencyRounding(order) {
        var currency = order.pos && order.pos.currency;
        return (currency && currency.rounding) || 0.01;
    }

    function roundAmount(amount, rounding) {
        return roundPrecision(amount || 0, rounding || 0.01);
    }

    // Same half-rounding rule as odoo.tools.float_utils.float_compare.
    function floatCompare(left, right, rounding) {
        var epsilon = (rounding || 0.01) / 2;
        if (Math.abs(left - right) < epsilon) {
            return 0;
        }
        return left < right ? -1 : 1;
    }

    var _super_order = models.Order.prototype;
    models.Order = models.Order.extend({
        initialize: function () {
            _super_order.initialize.apply(this, arguments);
            this._wholesaleTimer = null;
            this._wholesaleDestroyed = false;
            this.orderlines.on('add remove change', this._wholesaleOnLinesChanged, this);
            if (this.temporary || this.locked || this.finalized) {
                return;
            }
            if (!this.pos.wholesaleControlActive()) {
                return;
            }
            if (this.get_client()) {
                this._wholesaleFetch();
            } else {
                this._wholesaleApplyUnidentified();
            }
        },
        destroy: function () {
            this._wholesaleDestroyed = true;
            this._wholesaleClearTimer();
            if (this.orderlines) {
                this.orderlines.off(null, this._wholesaleOnLinesChanged, this);
            }
            return _super_order.destroy.apply(this, arguments);
        },
        updatePricelist: function (newClient) {
            if (!this.pos.wholesaleControlActive()) {
                return _super_order.updatePricelist.apply(this, arguments);
            }
            // The customer's own pricelist is not used. Eligibility chooses
            // the list after the fiscal position is in place, because taxes
            // change the retail reference total.
            this._wholesaleApplyFiscalPosition(newClient);
            this._wholesaleFetch();
        },
        set_pricelist: function (pricelist) {
            // uid is assigned after the first set_pricelist inside Order.initialize.
            // Forcing a list before that would save an unpaid order with no uid.
            if (!this.uid || !this.pos.wholesaleControlActive() || this._wholesaleApplying || this._wholesaleRestoring) {
                return _super_order.set_pricelist.apply(this, arguments);
            }
            var allowed = this._wholesaleAllowedPricelist();
            if (allowed && pricelist && pricelist.id === allowed.id) {
                this.wholesale.validationError = false;
                return _super_order.set_pricelist.apply(this, arguments);
            }
            if (allowed) {
                this._wholesaleUsePricelist(allowed);
            }
            this.wholesale.validationError = _t('Esta caja elige la lista de precios. No se puede cambiar manualmente.');
            this.trigger('change', this);
            this.save_to_db();
            return undefined;
        },
        wholesaleScheduleReevaluate: function () {
            this._wholesaleOnLinesChanged();
        },
        _wholesaleOnLinesChanged: function () {
            if (this._wholesaleDestroyed || this._wholesaleRepricing || this._wholesaleApplying || this._wholesaleRestoring) {
                return;
            }
            if (!this.pos.wholesaleControlActive() || this.temporary || this.locked || this.finalized) {
                return;
            }
            var order = this;
            this._wholesaleClearTimer();
            this._wholesaleTimer = setTimeout(function () {
                order._wholesaleTimer = null;
                if (!order._wholesaleDestroyed) {
                    order._wholesaleReevaluateLocal();
                }
            }, REEVALUATE_DELAY_MS);
        },
        _wholesaleClearTimer: function () {
            if (this._wholesaleTimer) {
                clearTimeout(this._wholesaleTimer);
                this._wholesaleTimer = null;
            }
        },
        _wholesaleApplyFiscalPosition: function (client) {
            var config = this.pos.config || {};
            var defaultId = config.default_fiscal_position_id && config.default_fiscal_position_id[0];
            var fiscalPosition = this._wholesaleFindFiscalPosition(defaultId);
            if (client && client.property_account_position_id) {
                fiscalPosition = this._wholesaleFindFiscalPosition(client.property_account_position_id[0]) || fiscalPosition;
            }
            this.fiscal_position = fiscalPosition;
        },
        _wholesaleFindFiscalPosition: function (positionId) {
            if (!positionId) {
                return undefined;
            }
            var positions = this.pos.fiscal_positions || [];
            for (var index = 0; index < positions.length; index++) {
                if (positions[index].id === positionId) {
                    return positions[index];
                }
            }
            return undefined;
        },
        _wholesaleRememberThresholds: function () {
            var company = this.pos.wholesale_company || this.pos.company || {};
            if (typeof company.wholesale_previous_month_min === 'number') {
                this.wholesale.previousMonthMin = company.wholesale_previous_month_min;
            } else if (!this.wholesale.previousMonthMin) {
                this.wholesale.previousMonthMin = 800;
            }
            if (typeof company.wholesale_current_order_min === 'number') {
                this.wholesale.currentOrderMin = company.wholesale_current_order_min;
            } else if (!this.wholesale.currentOrderMin) {
                this.wholesale.currentOrderMin = 1500;
            }
            this.wholesale.timezone = company.wholesale_timezone || this.wholesale.timezone || 'America/Tijuana';
            var retailId = many2oneId(company.wholesale_retail_pricelist_id);
            if (retailId) {
                this.wholesale.retailPricelistId = retailId;
            }
        },
        _wholesaleRetailPricelist: function () {
            return this.pos.wholesaleFindPricelist(this.wholesale.retailPricelistId);
        },
        _wholesalePricelistForDecision: function (decision) {
            if (decision !== 'wholesale') {
                return this._wholesaleRetailPricelist();
            }
            var client = this.get_client();
            var customerType = client && client.customer_type;
            var mapping = customerType && this.pos.wholesale_mapping_by_type
                ? this.pos.wholesale_mapping_by_type[customerType]
                : null;
            var mapped = mapping && this.pos.wholesaleFindPricelist(many2oneId(mapping.pricelist_id));
            if (mapped) {
                return mapped;
            }
            var company = this.pos.wholesale_company || this.pos.company || {};
            return this.pos.wholesaleFindPricelist(many2oneId(company.wholesale_pricelist_id));
        },
        _wholesaleAllowedPricelist: function () {
            var override = this.wholesale && this.wholesale.override;
            if (override && override.pricelist_id) {
                return this.pos.wholesaleFindPricelist(override.pricelist_id) || this._wholesaleRetailPricelist();
            }
            if (this.wholesale.automaticDecision === 'wholesale' && !this.wholesale.error) {
                return this._wholesalePricelistForDecision('wholesale') || this._wholesaleRetailPricelist();
            }
            return this._wholesaleRetailPricelist();
        },
        _wholesaleReasonText: function (reasonCode) {
            var texts = {
                previous_month: _t('El mes anterior alcanza el mínimo de mayoreo.'),
                current_order: _t('El pedido actual, a precio de menudeo, alcanza el mínimo de mayoreo.'),
                below_threshold: _t('Ni el mes anterior ni este pedido alcanzan el mínimo de mayoreo.'),
                no_identified_customer: _t('Seleccione un cliente para evaluar el precio de mayoreo.'),
                history_unavailable: _t('No se pudo consultar el historial de compras. El pedido queda en menudeo.'),
            };
            return texts[reasonCode] || '';
        },
        _wholesaleLineRetailTotal: function (line, pricelist) {
            var product = line.get_product();
            var quantity = line.get_quantity();
            if (!product || !pricelist || !quantity) {
                return 0;
            }
            var discount = line.get_discount() || 0;
            if (discount < 0) {
                discount = 0;
            } else if (discount > 100) {
                discount = 100;
            }
            // The server prices the product from the retail list and ignores a
            // typed unit price. Attribute extras are not part of that total.
            var unit = product.get_price(pricelist, Math.abs(quantity));
            var fixed = line.compute_fixed_price(unit);
            var discounted = fixed * (1.0 - (discount / 100.0));
            var taxIds = [];
            var productTaxes = product.taxes_id || [];
            for (var taxIndex = 0; taxIndex < productTaxes.length; taxIndex++) {
                if (productTaxes[taxIndex] in line.pos.taxes_by_id) {
                    taxIds.push(productTaxes[taxIndex]);
                }
            }
            var taxes = line.get_taxes_after_fp(taxIds);
            var totals = line.compute_all(
                taxes,
                discounted,
                quantity,
                currencyRounding(this)
            );
            return totals.total_included || 0;
        },
        _wholesaleRetailAmount: function () {
            var pricelist = this._wholesaleRetailPricelist();
            if (!pricelist) {
                return 0;
            }
            var lines = this.get_orderlines();
            var total = 0;
            for (var index = 0; index < lines.length; index++) {
                total += this._wholesaleLineRetailTotal(lines[index], pricelist);
            }
            return roundAmount(total, currencyRounding(this));
        },
        _wholesaleDecide: function (previousAmount, retailAmount) {
            var rounding = currencyRounding(this);
            var previous = roundAmount(previousAmount, rounding);
            var retail = roundAmount(retailAmount, rounding);
            var previousMin = roundAmount(this.wholesale.previousMonthMin, rounding);
            var currentMin = roundAmount(this.wholesale.currentOrderMin, rounding);
            if (floatCompare(previous, previousMin, rounding) >= 0) {
                return {decision: 'wholesale', reason: 'previous_month'};
            }
            if (floatCompare(retail, currentMin, rounding) >= 0) {
                return {decision: 'wholesale', reason: 'current_order'};
            }
            return {decision: 'retail', reason: 'below_threshold'};
        },
        _wholesaleUsePricelist: function (pricelist) {
            if (!pricelist) {
                this.wholesale.expectedPricelistId = false;
                this.wholesale.validationError = _t('No hay lista de menudeo disponible en esta caja.');
                this.trigger('change', this);
                this.save_to_db();
                return;
            }
            this.wholesale.expectedPricelistId = pricelist.id;
            if (this.pricelist && this.pricelist.id === pricelist.id) {
                this.trigger('change', this);
                this.save_to_db();
                return;
            }
            // set_pricelist skips lines the cashier priced by hand, including
            // tips. A decision change still reprices every automatic line.
            this._wholesaleRepricing = true;
            this._wholesaleApplying = true;
            try {
                _super_order.set_pricelist.call(this, pricelist);
            } finally {
                this._wholesaleApplying = false;
                this._wholesaleRepricing = false;
            }
            this.save_to_db();
        },
        _wholesaleApplyDecision: function (decision, reasonCode) {
            var list = this._wholesalePricelistForDecision(decision);
            if (decision === 'wholesale' && !list) {
                this.wholesale.automaticDecision = 'retail';
                this.wholesale.reasonCode = reasonCode;
                this.wholesale.error = _t('La lista de mayoreo no está disponible en esta caja. El pedido queda en menudeo.');
                this.wholesale.reasonText = this.wholesale.error;
                this._wholesaleUsePricelist(this._wholesaleRetailPricelist());
                return;
            }
            this.wholesale.automaticDecision = decision;
            this.wholesale.reasonCode = reasonCode;
            this.wholesale.reasonText = this._wholesaleReasonText(reasonCode);
            this.wholesale.error = false;
            this._wholesaleUsePricelist(list);
        },
        _wholesaleApplyUnidentified: function () {
            this._wholesaleClearTimer();
            this._wholesaleRememberThresholds();
            this.wholesale.loading = false;
            this.wholesale.historyLoaded = false;
            this.wholesale.months = [];
            this.wholesale.previousMonthAmount = 0;
            this.wholesale.customerId = false;
            this.wholesale.customerType = false;
            this.wholesale.error = false;
            this.wholesale.automaticDecision = 'retail';
            this.wholesale.reasonCode = 'no_identified_customer';
            this.wholesale.reasonText = this._wholesaleReasonText('no_identified_customer');
            this.wholesale.retailAmount = this._wholesaleRetailAmount();
            this._wholesaleUsePricelist(this._wholesaleRetailPricelist());
        },
        _wholesaleApplyHistoryFailure: function () {
            this.wholesale.loading = false;
            this.wholesale.historyLoaded = false;
            this.wholesale.months = [];
            this.wholesale.previousMonthAmount = 0;
            this.wholesale.error = this._wholesaleReasonText('history_unavailable');
            this.wholesale.automaticDecision = 'retail';
            this.wholesale.reasonCode = 'history_unavailable';
            this.wholesale.reasonText = this.wholesale.error;
            this.wholesale.retailAmount = this._wholesaleRetailAmount();
            // The automatic result stays retail. A manager override already
            // stored on this ticket is the only list that may stay wholesale.
            if (this.wholesale.override && this.wholesale.override.pricelist_id) {
                this._wholesaleUsePricelist(this._wholesaleAllowedPricelist());
                return;
            }
            this._wholesaleUsePricelist(this._wholesaleRetailPricelist());
        },
        _wholesaleApplyServer: function (response) {
            var client = this.get_client();
            this.wholesale.loading = false;
            this.wholesale.customerId = (client && client.id) || response.customer_id || false;
            this.wholesale.customerType = response.customer_type || (client && client.customer_type) || false;
            this.wholesale.months = response.months || [];
            this.wholesale.previousMonthAmount = response.previous_month_amount || 0;
            this.wholesale.previousMonthMin = response.previous_month_min || this.wholesale.previousMonthMin;
            this.wholesale.currentOrderMin = response.current_order_min || this.wholesale.currentOrderMin;
            this.wholesale.timezone = response.timezone || this.wholesale.timezone;
            this.wholesale.currency = response.currency || false;
            if (response.retail_pricelist && response.retail_pricelist.id) {
                this.wholesale.retailPricelistId = response.retail_pricelist.id;
            }
            var retailAmount = this._wholesaleRetailAmount();
            this.wholesale.retailAmount = retailAmount;
            if (response.reason_code === 'history_unavailable') {
                this._wholesaleApplyHistoryFailure();
                return;
            }
            if (this.wholesale.override && this.wholesale.override.pricelist_id) {
                this.wholesale.historyLoaded = true;
                this.wholesale.loading = false;
                this.wholesale.error = false;
                var overridden = this._wholesaleDecide(this.wholesale.previousMonthAmount, retailAmount);
                this.wholesale.automaticDecision = overridden.decision;
                this.wholesale.reasonCode = overridden.reason;
                this.wholesale.reasonText = response.reason_text || this._wholesaleReasonText(overridden.reason);
                this._wholesaleUsePricelist(this._wholesaleAllowedPricelist());
                return;
            }
            if (response.error) {
                this.wholesale.historyLoaded = true;
                this.wholesale.error = response.error;
                this.wholesale.automaticDecision = 'retail';
                this.wholesale.reasonCode = response.reason_code || 'below_threshold';
                this.wholesale.reasonText = response.reason_text || response.error;
                var retailList = this.pos.wholesaleFindPricelist(this.wholesale.retailPricelistId) || this._wholesaleRetailPricelist();
                this._wholesaleUsePricelist(retailList);
                return;
            }
            this.wholesale.historyLoaded = true;
            this.wholesale.error = false;
            var decision = this._wholesaleDecide(this.wholesale.previousMonthAmount, retailAmount);
            if (decision.decision === response.automatic_decision && response.expected_pricelist) {
                var serverList = this.pos.wholesaleFindPricelist(response.expected_pricelist.id);
                if (serverList) {
                    this.wholesale.automaticDecision = decision.decision;
                    this.wholesale.reasonCode = decision.reason;
                    this.wholesale.reasonText = response.reason_text || this._wholesaleReasonText(decision.reason);
                    this._wholesaleUsePricelist(serverList);
                    return;
                }
            }
            this._wholesaleApplyDecision(decision.decision, decision.reason);
        },
        _wholesaleFetch: function () {
            if (this._wholesaleDestroyed || !this.pos.wholesaleControlActive()) {
                return;
            }
            if (this.temporary || this.locked || this.finalized) {
                return;
            }
            this._wholesaleClearTimer();
            this._wholesaleRememberThresholds();
            var client = this.get_client();
            if (!client || !client.id) {
                this._wholesaleApplyUnidentified();
                return;
            }
            var version = (this.wholesale.requestVersion || 0) + 1;
            this.wholesale.requestVersion = version;
            var keepPrice = (this.wholesale.historyLoaded && this.wholesale.customerId === client.id)
                || !!(this.wholesale.override && this.wholesale.override.pricelist_id);
            this.wholesale.loading = true;
            this.wholesale.customerId = client.id;
            this.wholesale.customerType = client.customer_type || false;
            this.wholesale.validationError = false;
            if (!keepPrice) {
                this.wholesale.historyLoaded = false;
                this.wholesale.months = [];
                this.wholesale.previousMonthAmount = 0;
                this.wholesale.error = false;
                this.wholesale.automaticDecision = 'retail';
                this.wholesale.reasonCode = 'below_threshold';
                this.wholesale.reasonText = '';
                this.wholesale.retailAmount = this._wholesaleRetailAmount();
                this._wholesaleUsePricelist(this._wholesaleRetailPricelist());
            }
            var company = this.pos.wholesale_company || this.pos.company || {};
            if (!company.id) {
                this._wholesaleApplyHistoryFailure();
                return;
            }
            var retailAmount = this._wholesaleRetailAmount();
            this.wholesale.retailAmount = retailAmount;
            var order = this;
            var requestedCustomerId = client.id;
            this.pos.rpc({
                model: 'res.partner',
                method: 'get_wholesale_eligibility',
                args: [
                    requestedCustomerId,
                    company.id,
                    retailAmount,
                    this.pos.config && this.pos.config.id,
                ],
            }, {
                shadow: true,
                timeout: 5000,
            }).then(function (response) {
                order._wholesaleAcceptResponse(version, requestedCustomerId, response);
            }, function () {
                order._wholesaleAcceptFailure(version, requestedCustomerId);
            });
            this.trigger('change', this);
        },
        _wholesaleAcceptResponse: function (version, customerId, response) {
            if (this._wholesaleDestroyed || version !== this.wholesale.requestVersion) {
                return;
            }
            var client = this.get_client();
            if (!client || client.id !== customerId) {
                return;
            }
            if (!response || response.customer_id !== customerId) {
                this._wholesaleApplyHistoryFailure();
                return;
            }
            this._wholesaleApplyServer(response);
        },
        _wholesaleAcceptFailure: function (version, customerId) {
            if (this._wholesaleDestroyed || version !== this.wholesale.requestVersion) {
                return;
            }
            var client = this.get_client();
            if (!client || client.id !== customerId) {
                return;
            }
            this._wholesaleApplyHistoryFailure();
        },
        _wholesaleReevaluateLocal: function () {
            if (this._wholesaleDestroyed || !this.pos.wholesaleControlActive()) {
                return;
            }
            if (this.temporary || this.locked || this.finalized) {
                return;
            }
            var client = this.get_client();
            if (!client || !client.id) {
                this._wholesaleApplyUnidentified();
                return;
            }
            this._wholesaleRememberThresholds();
            this.wholesale.retailAmount = this._wholesaleRetailAmount();
            if (this.wholesale.override && this.wholesale.override.pricelist_id) {
                this._wholesaleUsePricelist(this._wholesaleAllowedPricelist());
                return;
            }
            // A missing history stays on retail, including when this ticket
            // would otherwise cross the current-order minimum.
            if (!this.wholesale.historyLoaded || this.wholesale.reasonCode === 'history_unavailable') {
                this.trigger('change', this);
                this.save_to_db();
                return;
            }
            if (this.wholesale.error) {
                this.wholesale.automaticDecision = 'retail';
                this._wholesaleUsePricelist(this._wholesaleRetailPricelist());
                return;
            }
            var decision = this._wholesaleDecide(
                this.wholesale.previousMonthAmount,
                this.wholesale.retailAmount
            );
            this._wholesaleApplyDecision(decision.decision, decision.reason);
        },
    });
});
