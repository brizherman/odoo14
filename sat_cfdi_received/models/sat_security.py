# -*- coding: utf-8 -*-
from odoo import _
from odoo.exceptions import AccessError

SAT_MANAGER_XMLID = 'sat_cfdi_received.group_sat_manager'
SAT_FROM_PACKAGE_CTX = 'sat_from_package'


def is_sat_manager(env):
    return env.user.has_group(SAT_MANAGER_XMLID)


def check_sat_manager(env):
    if not is_sat_manager(env):
        raise AccessError(_('Solo los administradores SAT pueden realizar esta acción.'))
