# -*- coding: utf-8 -*-
# pylint: disable=import-error,missing-function-docstring,protected-access,too-many-arguments
"""Date range, overlap, required fields, and access rights."""
import psycopg2

from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import SavepointCase

# 1x1 PNG. The Image field keeps this format because it is already small.
PNG = (
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8'
    'z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='
)
# 1x1 GIF. The Image field does not resize GIFs, so the format check sees it.
GIF = 'R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7'


@tagged('pos_ticket_image', 'post_install', '-at_install')
class TestPosTicketImage(SavepointCase):
    """Campaigns are global. One inclusive range may be saved at a time."""

    @classmethod
    def setUpClass(cls):  # pylint: disable=invalid-name
        super().setUpClass()
        cls.campaign = cls.env['pos.ticket.image'].create(
            cls._values('Fiesta 13-16', '2026-11-13', '2026-11-16')
        )
        cls.cashier = cls.env['res.users'].with_context(
            no_reset_password=True,
        ).create({
            'name': 'POS Ticket Cashier',
            'login': 'pos_ticket_image_cashier',
            'groups_id': [(6, 0, [
                cls.env.ref('point_of_sale.group_pos_user').id,
            ])],
        })
        cls.manager = cls.env['res.users'].with_context(
            no_reset_password=True,
        ).create({
            'name': 'POS Ticket Manager',
            'login': 'pos_ticket_image_manager',
            'groups_id': [(6, 0, [
                cls.env.ref('point_of_sale.group_pos_manager').id,
            ])],
        })

    @classmethod
    def _values(cls, name, date_start, date_end, image=None, position='bottom'):
        return {
            'name': name,
            'image': image or PNG,
            'date_start': date_start,
            'date_end': date_end,
            'position': position,
        }

    def test_backwards_range_is_rejected(self):
        with self.assertRaises(ValidationError) as error:
            self.env['pos.ticket.image'].create(
                self._values('Backwards', '2026-11-16', '2026-11-13')
            )
        self.assertIn('end date', str(error.exception).lower())

    def test_overlap_names_the_other_campaign(self):
        with self.assertRaises(ValidationError) as error:
            self.env['pos.ticket.image'].create(
                self._values('Overlap', '2026-11-16', '2026-11-18')
            )
        self.assertIn(self.campaign.name, str(error.exception))

    def test_range_after_the_campaign_saves(self):
        later = self.env['pos.ticket.image'].create(
            self._values('After', '2026-11-17', '2026-11-18')
        )
        self.assertEqual(later.date_start.isoformat(), '2026-11-17')
        self.assertEqual(later.date_end.isoformat(), '2026-11-18')

    def test_name_and_image_are_required(self):
        # name is a real column. Odoo inserts the row and PostgreSQL rejects it.
        with self.assertRaises(psycopg2.IntegrityError):
            with self.cr.savepoint():
                self.env['pos.ticket.image'].create({
                    'image': PNG,
                    'date_start': '2027-03-01',
                    'date_end': '2027-03-02',
                    'position': 'bottom',
                })
        # The image is stored in ir.attachment, so the form is what requires it.
        arch = self.env.ref('pos_ticket_image.view_pos_ticket_image_form').arch
        image_at = arch.find('name="image"')
        self.assertGreater(image_at, -1)
        self.assertIn('required="1"', arch[image_at:image_at + 80])

    def test_gif_is_rejected(self):
        with self.assertRaises(ValidationError) as error:
            self.env['pos.ticket.image'].create(
                self._values('Gif', '2027-04-01', '2027-04-02', image=GIF)
            )
        self.assertIn('PNG or JPG', str(error.exception))

    def test_pos_user_reads_and_cannot_create(self):
        names = self.campaign.with_user(self.cashier).read(['name'])
        self.assertEqual(names[0]['name'], self.campaign.name)
        with self.assertRaises(AccessError):
            self.env['pos.ticket.image'].with_user(self.cashier).create(
                self._values('Cashier', '2027-01-01', '2027-01-02')
            )

    def test_pos_manager_can_create(self):
        created = self.env['pos.ticket.image'].with_user(self.manager).create(
            self._values('Manager', '2027-02-01', '2027-02-02')
        )
        self.assertTrue(created.id)

    def test_model_has_no_company(self):
        self.assertNotIn('company_id', self.env['pos.ticket.image']._fields)
