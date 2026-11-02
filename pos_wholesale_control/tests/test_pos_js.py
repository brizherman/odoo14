# -*- coding: utf-8 -*-
"""Run the POS QUnit files in Chrome against the installed module assets."""
from odoo.addons.login_user_detail.models.login_user_details import LoginUserDetail
from odoo.tests import HttpCase, tagged


@tagged('pos_wholesale_control', 'post_install', '-at_install')
class TestWholesaleJavascript(HttpCase):
    """The JavaScript suite is served by /pos/ui/tests, not by the Python loader."""

    def test_qunit_wholesale(self):
        def _check_credentials(self, password, user_agent_env):
            # The installed login tracker reads request.httprequest. The test
            # client authenticates before a request exists.
            return super(LoginUserDetail, self)._check_credentials(
                password, user_agent_env,
            )

        self.patch(LoginUserDetail, '_check_credentials', _check_credentials)
        user = self.env['res.users'].sudo().create({
            'name': 'Wholesale QUnit',
            'login': 'wholesale.qunit',
            'password': 'wholesale.qunit',
            'groups_id': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('point_of_sale.group_pos_user').id,
            ])],
            'company_id': self.env.company.id,
            'company_ids': [(6, 0, [self.env.company.id])],
        })
        user.flush()
        self.browser_js(
            '/pos/ui/tests?filter=pos_wholesale_control&failfast',
            '',
            login='wholesale.qunit',
            timeout=900,
        )
