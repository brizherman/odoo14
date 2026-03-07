odoo.define('header_modules.SecondaryNavbar', function (require) {
"use strict";

const core = require('web.core');
const Menu = require('web.Menu');

// XML IDs of the 5 root menus to show in the secondary bar (in display order)
const ROOT_MENU_XMLIDS = [
    'point_of_sale.menu_point_root',
    'purchase.menu_purchase_root',
    'stock.menu_stock_root',
    'account.menu_finance',
    'sale.sale_menu_root',
];

Menu.include({

    start() {
        const res = this._super(...arguments);
        this._renderSecondaryNavbar();
        // Re-highlight active item whenever the menu section changes
        core.bus.on('change_menu_section', this, this._highlightActiveNavbarItem.bind(this));
        return res;
    },

    _renderSecondaryNavbar() {
        // Build the list of top-level items from menu_data filtered by ROOT_MENU_XMLIDS
        const allRoots = this.menu_data ? this.menu_data.children : [];
        this._secondaryNavRoots = ROOT_MENU_XMLIDS
            .map(xmlid => allRoots.find(m => m.xmlid === xmlid))
            .filter(Boolean);

        if (!this._secondaryNavRoots.length) {
            return;
        }

        const $bar = $(core.qweb.render('header_modules.SecondaryNavbar', {
            roots: this._secondaryNavRoots,
        }));

        // Insert after the main navbar
        $bar.insertAfter('.o_main_navbar');
        this.$secondaryNavbar = $bar;

        // Bind dropdown toggle (click on top-level item)
        this.$secondaryNavbar.on('click', '.hn_nav_item > a', (ev) => {
            ev.preventDefault();
            const $item = $(ev.currentTarget).parent();
            const wasOpen = $item.hasClass('hn_open');
            // Close all open dropdowns
            this.$secondaryNavbar.find('.hn_nav_item.hn_open').removeClass('hn_open');
            if (!wasOpen) {
                $item.addClass('hn_open');
            }
        });

        // Close dropdown when clicking outside the bar
        $(document).on('click.hn_secondary', (ev) => {
            if (this.$secondaryNavbar && !this.$secondaryNavbar[0].contains(ev.target)) {
                this.$secondaryNavbar.find('.hn_nav_item.hn_open').removeClass('hn_open');
            }
        });

        // Navigate when a submenu leaf item is clicked
        this.$secondaryNavbar.on('click', '.hn_dropdown_item', (ev) => {
            ev.preventDefault();
            const $a = $(ev.currentTarget);
            const menuId = parseInt($a.data('menu-id'));
            const actionId = parseInt($a.data('action-id'));
            const rootId = parseInt($a.data('parent-id'));
            this.$secondaryNavbar.find('.hn_nav_item.hn_open').removeClass('hn_open');
            // Update main navbar to show the correct module sections
            core.bus.trigger('change_menu_section', rootId);
            this.trigger_up('menu_clicked', {
                action_id: actionId,
                id: menuId,
                previous_menu_id: rootId,
            });
        });

        // Navigate when a top-level item with a direct action is clicked
        this.$secondaryNavbar.on('click', '.hn_nav_item_direct', (ev) => {
            ev.preventDefault();
            const $a = $(ev.currentTarget);
            const menuId = parseInt($a.data('menu-id'));
            const actionId = parseInt($a.data('action-id'));
            core.bus.trigger('change_menu_section', menuId);
            this.trigger_up('menu_clicked', {
                action_id: actionId,
                id: menuId,
                previous_menu_id: menuId,
            });
        });

        this._highlightActiveNavbarItem(this._current_primary_menu);
    },

    _highlightActiveNavbarItem(activeMenuId) {
        if (!this.$secondaryNavbar) {
            return;
        }
        this.$secondaryNavbar.find('.hn_nav_item').removeClass('hn_active');
        if (!activeMenuId) {
            return;
        }
        // Find the root whose subtree contains the active menu id
        const active = this._secondaryNavRoots.find(root => root.id === activeMenuId);
        if (active) {
            this.$secondaryNavbar
                .find('.hn_nav_item[data-root-id="' + active.id + '"]')
                .addClass('hn_active');
        }
    },

    // Override to also highlight secondary navbar when a menu section is set
    _updateMenuBrand() {
        const res = this._super(...arguments);
        this._highlightActiveNavbarItem(this._current_primary_menu);
        return res;
    },

});

});
