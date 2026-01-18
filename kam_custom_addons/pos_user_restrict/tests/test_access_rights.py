from odoo import Command
from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from odoo.exceptions import AccessError
from odoo.addons.point_of_sale.tests.common import CommonPosTest


@tagged('post_install', '-at_install', 'pos_restricted_rights')
class TestPosUser(CommonPosTest, TransactionCase):

    def setUp(self):
        super(TestPosUser, self).setUp()
        self.pos_1 = self.pos_config_eur
        self.pos_2 = self.pos_config_usd
        self.user_internal = self._create_new_internal_user()
        self.user_internal.group_ids = [
            (4, self.env.ref('point_of_sale.group_pos_user').id),
            (4, self.env.ref('pos_user_restrict.group_pos_restricted_user').id),
        ]

    def test_01_no_allowed_pos(self):
        with self.assertRaises(AccessError):
            self.pos_1.with_user(self.user_internal).read(['name'])
        with self.assertRaises(AccessError):
            self.pos_2.with_user(self.user_internal).read(['name'])

    def test_02_pos_1_allowed(self):
        self.user_internal.pos_config_ids = [Command.link(self.pos_1.id)]
        # Check the access to POS 1
        self.pos_1.with_user(self.user_internal).read(['name'])
        # Check the access to POS 2
        with self.assertRaises(AccessError):
            self.pos_2.with_user(self.user_internal).read(['name'])

        # Remove access
        self.user_internal.pos_config_ids = [Command.unlink(self.pos_1.id)]
        # Check the access to POS 1
        with self.assertRaises(AccessError):
            self.pos_1.with_user(self.user_internal).read(['name'])
