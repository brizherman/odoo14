odoo.define('pos_ticket_image.OrderReceipt', function (require) {
    'use strict';

    const OrderReceipt = require('point_of_sale.OrderReceipt');
    const Registries = require('point_of_sale.Registries');
    const ticket = require('pos_ticket_image.models');

    const PosTicketOrderReceipt = (OrderReceiptClass) => class extends OrderReceiptClass {
        get ticketCampaign() {
            const campaigns = (this.env.pos && this.env.pos.ticket_images) || [];
            const match = ticket.matchTicketCampaign(this.props.order, campaigns);
            if (!match || !match.image_src) {
                return null;
            }
            return match;
        }
    };

    Registries.Component.extend(OrderReceipt, PosTicketOrderReceipt);

    return OrderReceipt;
});
