from odoo import models, fields, api


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    egypt_ereceipt_enabled = fields.Boolean(
        related='company_id.egypt_ereceipt_enabled',
        readonly=False,
    )

    pos_client_code = fields.Char(related='pos_config_id.pos_client_code', readonly=False)
    pos_secret_code = fields.Char(related='pos_config_id.pos_secret_code', readonly=False)
    pos_serial = fields.Char(related='pos_config_id.pos_serial', readonly=False)
    pos_branch_code = fields.Char(related='pos_config_id.pos_branch_code', readonly=False)
    pos_os_version = fields.Char(related='pos_config_id.pos_os_version', readonly=False)
    pos_model_framework = fields.Char(related='pos_config_id.pos_model_framework', readonly=False)
    pre_shared_key = fields.Char(related='pos_config_id.pre_shared_key', readonly=False)


class ResCompany(models.Model):
    _inherit = 'res.company'

    egypt_ereceipt_enabled = fields.Boolean(
        string='Enable e-Receipt',
        default=False,
        help='Enable automatic e-receipt submission for POS orders'
    )


class PosConfig(models.Model):
    _inherit = 'pos.config'

    pos_client_code = fields.Char(string="POS Client ID")
    pos_secret_code = fields.Char(string="POS Secret ID")
    pos_serial = fields.Char(string="POS Serial Number")
    pos_branch_code = fields.Char(string="POS Branch Code")
    pos_os_version = fields.Char(string="POS OS Version", default='windows')
    pos_model_framework = fields.Char(string="POS Model Framework", default='1')
    pre_shared_key = fields.Char(string="Pre-Shared Key", default='')

    access_token = fields.Text('Access Token')
    token_expiration_date = fields.Datetime('Token Expiration Date')
