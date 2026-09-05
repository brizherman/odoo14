# -*- coding: utf-8 -*-
"""Add stored last-sale date columns before ORM init so upgrade does not backfill."""


def migrate(cr, version):
    """Create last-sale date columns if they do not exist yet."""
    cr.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'res_partner'
          AND column_name IN ('last_pos_sale_date', 'last_sale_order_date')
    """)
    existing = {row[0] for row in cr.fetchall()}
    if 'last_pos_sale_date' not in existing:
        cr.execute(
            'ALTER TABLE res_partner ADD COLUMN last_pos_sale_date date'
        )
    if 'last_sale_order_date' not in existing:
        cr.execute(
            'ALTER TABLE res_partner ADD COLUMN last_sale_order_date date'
        )
