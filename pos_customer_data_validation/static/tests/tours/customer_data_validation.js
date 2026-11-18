odoo.define('pos_customer_data_validation.tour', function (require) {
    'use strict';
    const tour = require('web_tour.tour');
    tour.register('CustomerDataValidationTour', { test: true, url: '/pos/ui' }, [
        { content: 'Add a product', trigger: '.product:contains("Review product")' },
        { content: 'Open payment', trigger: '.pay' },
        { content: 'Select customer', trigger: '.payment-buttons .customer-button .button' },
        { content: 'Historical customer', trigger: '.client-line:contains("Review historical customer")' },
        { content: 'Set customer', trigger: '.clientlist-screen .next.highlight' },
        { content: 'Add cash payment', trigger: '.paymentmethod:contains("Review Cash")' },
        { content: 'Review before payment', trigger: '.payment-screen .next.highlight' },
        {
            content: 'Fresh values, unknown name date and old mobile date',
            trigger: '.pos-customer-data-popup input[name="name"]',
            run() {
                const popup = document.querySelector('.pos-customer-data-popup');
                if (!popup.textContent.includes('Sin fecha registrada') || !popup.textContent.includes('2021')) {
                    throw new Error('Expected independent historical dates');
                }
            },
        },
        { content: 'Cancel without finalizing', trigger: '.pos-customer-data-popup .cancel' },
        { content: 'Retry must review again', trigger: '.payment-screen .next.highlight' },
        {
            content: 'Missing fields are reported together',
            trigger: '.pos-customer-data-popup input[name="name"]',
            run() {
                for (const name of ['name', 'mobile']) {
                    const input = document.querySelector('.pos-customer-data-popup input[name="' + name + '"]');
                    input.value = '   ';
                    input.dispatchEvent(new Event('input', { bubbles: true }));
                }
                document.querySelector('.pos-customer-data-popup .confirm').click();
            },
        },
        {
            content: 'Keep edits and show errors', trigger: '.pos-customer-data-popup .customer-data-error',
            run() {
                for (const [name, value] of [['name', 'Review historical customer'], ['mobile', '6640000000']]) {
                    const input = document.querySelector('.pos-customer-data-popup input[name="' + name + '"]');
                    input.value = value;
                    input.dispatchEvent(new Event('input', { bubbles: true }));
                }
            },
        },
        { content: 'Confirm old values without edits', trigger: '.pos-customer-data-popup .confirm' },
        { content: 'Payment finished once', trigger: '.receipt-screen', run() {} },
    ]);
});
