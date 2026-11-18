from odoo.tests.common import SavepointCase, new_test_user


class CustomerDataCommon(SavepointCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Partner = cls.env["res.partner"]
        cls.public_price = cls.env["product.pricelist"].create({
            "name": "Lista de precios a Publico en General",
            "currency_id": cls.env.company.currency_id.id,
            "company_id": cls.env.company.id,
        })
        cls.wholesale_price = cls.public_price.copy({
            "name": "Lista de precios de Mayorista",
        })
        cls.distributor_price = cls.public_price.copy({
            "name": "Super Precios a Distribuidores",
        })
        cls.prices = cls.public_price | cls.wholesale_price | cls.distributor_price
        cls.config = cls.env["pos.config"].create({
            "name": "Customer review test",
            "pricelist_id": cls.public_price.id,
            "available_pricelist_ids": [(6, 0, cls.prices.ids)],
        })
        cls.partner = cls.Partner.create({
            "name": "Review customer",
            "mobile": "6641234567",
            "customer_type": "publico_general",
            "property_product_pricelist": cls.public_price.id,
        })
        cls.cashier = new_test_user(
            cls.env, login="customer_review_cashier",
            groups=(
                "base.group_user,point_of_sale.group_pos_user,"
                "base.group_partner_manager"
            ),
        )

    def save(self, changes, partner=None, user=None):
        return self.Partner.with_user(user or self.cashier).pos_customer_data_save(
            (partner or self.partner).id, self.config.id, changes,
        )["partner"]
