from odoo import models, fields, api, _
from dateutil.relativedelta import relativedelta
from odoo.exceptions import AccessError, LockError, MissingError, ValidationError, UserError


class OrderTag(models.Model):
    _name = 'custom.order.tag'
    # _description = 'Purchase Template'
    name = fields.Char(string="Name", required=False, )
