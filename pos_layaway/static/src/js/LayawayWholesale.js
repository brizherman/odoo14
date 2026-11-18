odoo.define('pos_layaway.LayawayWholesale', function (require) {
    'use strict';

    require('pos_wholesale_control.wholesale_eligibility');
    const models = require('point_of_sale.models');
    const { _t } = require('web.core');
    const Order = models.Order.prototype;
    const campaignReason = 'layaway_payment';

    models.Order = models.Order.extend({
        _wholesaleApplyServer(response) {
            this.wholesale.layawayPricelistId = response.layaway_wholesale_pricelist_id || false;
            return Order._wholesaleApplyServer.apply(this, arguments);
        },
        _wholesaleDecide(previousAmount, retailAmount) {
            if (this._wholesaleCustomerIsDistributor()) {
                const months = this.wholesale.months;
                const previous = months && months[months.length - 2];
                if (previous && typeof previous.ordinary_amount === 'number') {
                    previousAmount = previous.ordinary_amount;
                }
            }
            const decision = Order._wholesaleDecide.call(this, previousAmount, retailAmount);
            if (decision.decision === 'retail' && this.wholesale.layawayPricelistId) {
                return { decision: 'wholesale', reason: campaignReason, program: 'wholesale' };
            }
            return decision;
        },
        _wholesaleCurrentMonthAmount() {
            const current = (this.wholesale.months || []).find((month) => month.is_current);
            if (this._wholesaleCustomerIsDistributor() &&
                current && typeof current.ordinary_amount === 'number') {
                return current.ordinary_amount;
            }
            return Order._wholesaleCurrentMonthAmount.apply(this, arguments);
        },
        _wholesaleApplyDecision(decision, reasonCode, program) {
            this.wholesale.reasonCode = reasonCode;
            return Order._wholesaleApplyDecision.call(this, decision, reasonCode, program);
        },
        _wholesalePricelistForDecision(decision) {
            if (decision === 'wholesale' && this.wholesale.reasonCode === campaignReason) {
                return this.pos.wholesaleFindPricelist(this.wholesale.layawayPricelistId);
            }
            return Order._wholesalePricelistForDecision.apply(this, arguments);
        },
        _wholesaleReasonText(reasonCode) {
            if (reasonCode === campaignReason) {
                return _t('Los cobros confirmados del apartado habilitan mayoreo.');
            }
            return Order._wholesaleReasonText.apply(this, arguments);
        },
    });
});
