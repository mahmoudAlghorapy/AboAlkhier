# Copyright 2024 Dixmit
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import models, api
from odoo.tools.safe_eval import safe_eval


class AccountBankStatement(models.Model):
    _inherit = "account.bank.statement"

    def action_open_statement(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "account_reconcile_oca.account_bank_statement_action_edit"
        )
        action["res_id"] = self.id
        return action

    @api.model
    def default_get(self, fields):
        res = super().default_get(fields)

        if not res.get("journal_id") and self.env.context.get("default_journal_id"):
            res["journal_id"] = self.env.context["default_journal_id"]
        return res

    def action_open_statement_lines(self):
        """Open in reconciling view directly"""
        self.ensure_one()
        if not self:
            return {}

        action = self.env["ir.actions.act_window"]._for_xml_id(
            "account_reconcile_oca.action_bank_statement_line_reconcile"
        )
        action["domain"] = [("statement_id", "=", self.id)]

        # Get the context string from action
        context_str = action.get("context", "{}")

        # Odoo 19: Use safe_eval with locals_dict to define active_id

        # Define active_id in locals_dict for safe_eval
        locals_dict = {
            'active_id': self._context.get("active_id", self.id)
        }

        try:
            # Evaluate the context string with active_id available
            current_context = safe_eval(context_str, globals_dict=None, locals_dict=locals_dict)
        except Exception as e:
            # If evaluation fails, use default context
            current_context = {}

        # Ensure context is a dictionary
        if not isinstance(current_context, dict):
            current_context = {}

        # Update context with any additional values if needed
        current_context['active_id'] = self._context.get("active_id", self.id)

        action["context"] = current_context
        return action
