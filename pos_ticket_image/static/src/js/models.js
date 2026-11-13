odoo.define('pos_ticket_image.models', function (require) {
    'use strict';

    const models = require('point_of_sale.models');
    const utils = require('web.utils');

    const TIJUANA = 'America/Tijuana';

    /**
     * Calendar date of the sale in America/Tijuana, as YYYY-MM-DD.
     *
     * A string from the server is already the user-timezone wall clock
     * (_export_for_ui). Use its date part as-is. A Date from
     * initialize_validation_date is an absolute instant, so format that
     * instant in America/Tijuana.
     */
    function saleCalendarDate(validationDate) {
        if (!validationDate) {
            return '';
        }
        if (typeof validationDate === 'string') {
            const matched = /^(\d{4}-\d{2}-\d{2})/.exec(validationDate);
            return matched ? matched[1] : '';
        }
        if (validationDate instanceof Date && !isNaN(validationDate.getTime())) {
            const parts = new Intl.DateTimeFormat('en-CA', {
                timeZone: TIJUANA,
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
            }).formatToParts(validationDate);
            const values = {};
            parts.forEach(function (part) {
                values[part.type] = part.value;
            });
            if (!values.year || !values.month || !values.day) {
                return '';
            }
            return values.year + '-' + values.month + '-' + values.day;
        }
        return '';
    }

    function ticketImageSource(value) {
        if (!value || typeof value !== 'string' || utils.is_bin_size(value)) {
            return false;
        }
        let mime = false;
        if (value.indexOf('iVBORw0KGgo') === 0) {
            mime = 'image/png';
        } else if (value.indexOf('/9j/') === 0) {
            mime = 'image/jpeg';
        }
        if (!mime) {
            return false;
        }
        return 'data:' + mime + ';base64,' + value;
    }

    function campaignFromRow(row) {
        let src = false;
        try {
            src = ticketImageSource(row && row.image_512);
        } catch (error) {
            src = false;
        }
        return {
            id: row && row.id,
            name: row && row.name,
            date_start: row && row.date_start,
            date_end: row && row.date_end,
            position: row && row.position,
            image_src: src,
        };
    }

    /**
     * Campaign whose inclusive range contains the sale date of this order.
     * A refund (negative total) matches nothing. The order argument is the
     * order being rendered, which on a reprint is not the open order.
     */
    function matchTicketCampaign(order, campaigns) {
        if (!order || typeof order.get_total_with_tax !== 'function') {
            return null;
        }
        if (order.get_total_with_tax() < 0) {
            return null;
        }
        const saleDate = saleCalendarDate(order.validation_date);
        if (!saleDate) {
            return null;
        }
        const list = campaigns || [];
        for (let index = 0; index < list.length; index++) {
            const campaign = list[index];
            if (!campaign || !campaign.date_start || !campaign.date_end) {
                continue;
            }
            if (campaign.date_start <= saleDate && saleDate <= campaign.date_end) {
                return campaign;
            }
        }
        return null;
    }

    // Loaded once when the session opens. An open session keeps this list
    // until the cashier reloads. The domain is empty on purpose.
    models.load_models({
        model: 'pos.ticket.image',
        label: 'ticket_images',
        fields: ['name', 'image_512', 'date_start', 'date_end', 'position'],
        domain: function () {
            return [];
        },
        context: function () {
            return {bin_size: false};
        },
        loaded: function (self, rows) {
            const images = [];
            const list = rows || [];
            for (let index = 0; index < list.length; index++) {
                images.push(campaignFromRow(list[index]));
            }
            self.ticket_images = images;
        },
    });

    return {
        matchTicketCampaign: matchTicketCampaign,
        saleCalendarDate: saleCalendarDate,
    };
});
