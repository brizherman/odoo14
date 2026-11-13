odoo.define('pos_ticket_image.tests', function (require) {
    'use strict';

    const ticket = require('pos_ticket_image.models');

    QUnit.module('pos_ticket_image');

    const campaign = {
        name: 'Fiesta 13-16',
        date_start: '2026-11-13',
        date_end: '2026-11-16',
        position: 'bottom',
        image_src: 'data:image/png;base64,abc',
    };

    function order(validationDate, total) {
        return {
            validation_date: validationDate,
            get_total_with_tax: function () {
                return total;
            },
        };
    }

    QUnit.test('13 through 16 November 2026 match the campaign', function (assert) {
        const dates = ['2026-11-13', '2026-11-14', '2026-11-15', '2026-11-16'];
        dates.forEach(function (day) {
            const match = ticket.matchTicketCampaign(order(day, 10), [campaign]);
            assert.strictEqual(match && match.name, 'Fiesta 13-16', day);
        });
    });

    QUnit.test('12 November and 17 November match nothing', function (assert) {
        assert.strictEqual(
            ticket.matchTicketCampaign(order('2026-11-12', 10), [campaign]),
            null
        );
        assert.strictEqual(
            ticket.matchTicketCampaign(order('2026-11-17', 10), [campaign]),
            null
        );
    });

    QUnit.test('a reprint uses validation_date when the clock is 20 November', function (assert) {
        const RealDate = Date;
        const frozen = new RealDate('2026-11-20T18:00:00Z');

        function Clock() {
            if (!(this instanceof Clock)) {
                return new Clock();
            }
            if (arguments.length === 0) {
                return new RealDate(frozen.getTime());
            }
            return new (Function.prototype.bind.apply(
                RealDate,
                [null].concat(Array.prototype.slice.call(arguments))
            ))();
        }
        Clock.now = function () {
            return frozen.getTime();
        };
        Clock.parse = RealDate.parse;
        Clock.UTC = RealDate.UTC;
        Clock.prototype = RealDate.prototype;
        // eslint-disable-next-line no-global-assign
        Date = Clock;
        try {
            const match = ticket.matchTicketCampaign(
                order('2026-11-15 21:30:00', 10),
                [campaign]
            );
            assert.strictEqual(match && match.name, 'Fiesta 13-16');
        } finally {
            Date = RealDate;
        }
    });

    QUnit.test('a late evening on 16 November in Tijuana still matches', function (assert) {
        // 06:30 UTC on 17 November is 22:30 on 16 November in America/Tijuana.
        const evening = new Date('2026-11-17T06:30:00Z');
        const match = ticket.matchTicketCampaign(order(evening, 10), [campaign]);
        assert.strictEqual(match && match.name, 'Fiesta 13-16');
        assert.strictEqual(ticket.saleCalendarDate(evening), '2026-11-16');
    });

    QUnit.test('midnight on 17 November in Tijuana matches nothing', function (assert) {
        // 08:00 UTC on 17 November is 00:00 on 17 November in America/Tijuana.
        const nextDay = new Date('2026-11-17T08:00:00Z');
        assert.strictEqual(
            ticket.matchTicketCampaign(order(nextDay, 10), [campaign]),
            null
        );
        assert.strictEqual(ticket.saleCalendarDate(nextDay), '2026-11-17');
    });

    QUnit.test('a negative total matches nothing even when the date matches', function (assert) {
        assert.strictEqual(
            ticket.matchTicketCampaign(order('2026-11-15', -1), [campaign]),
            null
        );
    });
});
