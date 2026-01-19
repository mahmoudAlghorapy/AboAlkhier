from odoo import models, fields, api, _
from dateutil.relativedelta import relativedelta
from odoo.exceptions import AccessError, LockError, MissingError, ValidationError, UserError
from random import randint


class OrderTag(models.Model):
    _name = 'custom.order.tag'
    # _description = 'Purchase Template'
    name = fields.Char(string="Name", required=False, )

    def _get_default_color(self):
        return randint(1, 11)

    color = fields.Integer(string='Color Index', default=_get_default_color)

