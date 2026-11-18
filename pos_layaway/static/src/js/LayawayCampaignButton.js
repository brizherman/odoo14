odoo.define('pos_layaway.LayawayCampaignButton', function (require) {
    'use strict';

    const PosComponent = require('point_of_sale.PosComponent');
    const ProductScreen = require('point_of_sale.ProductScreen');
    const Registries = require('point_of_sale.Registries');
    const { useListener } = require('web.custom_hooks');
    const { useState } = owl.hooks;

    class LayawayCampaignButton extends PosComponent {
        constructor() {
            super(...arguments);
            useListener('click', this.onClick);
            this.selection = useState({ campaign: this.env.pos.layawayCampaign || null });
        }

        async onClick() {
            if (this.selecting) {
                return;
            }
            this.selecting = true;
            try {
                await this.selectCampaign();
            } finally {
                this.selecting = false;
            }
        }

        async selectCampaign() {
            const title = this.env._t('Campañas de apartados');
            let campaigns;
            try {
                campaigns = await this.rpc({
                    model: 'pos.session',
                    method: 'get_layaway_campaigns',
                    args: [[this.env.pos.pos_session.id]],
                }, { shadow: true });
            } catch (error) {
                this.setCampaign(null);
                await this.showPopup('ErrorPopup', {
                    title,
                    body: this.env._t('No se pudieron consultar las campañas. Intenta de nuevo.'),
                });
                return;
            }
            const currentId = this.selection.campaign && this.selection.campaign.id;
            if (!campaigns.some(campaign => campaign.id === currentId)) {
                this.setCampaign(null);
            }
            if (!campaigns.length) {
                await this.showPopup('SelectionPopup', {
                    title: this.env._t('No hay campañas disponibles en esta caja.'),
                    list: [],
                    cancelText: this.env._t('Cerrar'),
                });
                return;
            }
            const { confirmed, payload } = await this.showPopup('SelectionPopup', {
                title,
                list: campaigns.map(campaign => ({
                    id: campaign.id,
                    label: `${campaign.name} (${campaign.code})`,
                    item: campaign,
                    isSelected: campaign.id === currentId,
                })),
            });
            if (confirmed) {
                this.setCampaign(payload);
            }
        }

        setCampaign(campaign) {
            this.selection.campaign = campaign;
            this.env.pos.layawayCampaign = campaign;
        }
    }

    LayawayCampaignButton.template = 'pos_layaway.LayawayCampaignButton';
    ProductScreen.addControlButton({
        component: LayawayCampaignButton,
        condition: function () {
            return Boolean(this.env.pos.pos_session);
        },
    });
    Registries.Component.add(LayawayCampaignButton);
});
