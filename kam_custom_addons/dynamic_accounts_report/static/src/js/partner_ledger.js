/** @odoo-module */
const { Component } = owl;
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useRef, useState } from "@odoo/owl";
import { BlockUI } from "@web/core/ui/block_ui";
import { download } from "@web/core/network/download";
const actionRegistry = registry.category("actions");

class PartnerLedger extends Component {
    setup() {
        super.setup(...arguments);
        this.initial_render = true;
        this.orm = useService('orm');
        this.action = useService('action');
        this.tbody = useRef('tbody');
        this.unfoldButton = useRef('unfoldButton');
        this.dialog = useService("dialog");
        this.state = useState({
            partners: [],
            data: {},
            total: {},
            title: null,
            currency: null,
            filter_applied: null,
            selected_partner: [],
            selected_partner_rec: [],
            total_debit: 0,
            total_debit_display: "0.00",
            total_credit: 0,
            total_credit_display: "0.00",
            partner_list: [],
            total_list: {},
            date_range: null,
            account: {},
            options: {},
            message_list: [],
        });
        this.load_data();
    }

    formatNumberWithSeparators(number) {
        const parsedNumber = parseFloat(number);
        if (isNaN(parsedNumber)) {
            return "0.00";
        }
        return parsedNumber.toLocaleString('en-US', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        });
    }

    async load_data() {
        try {
            const self = this;
            const action_title = self.props.action.display_name;

            // Load data from backend
            self.state.data = await self.orm.call("account.partner.ledger", "view_report", [[], action_title]);

            const dataArray = self.state.data;
            let partner_list = [];
            let partner_totals = {};
            let totalDebitSum = 0;
            let totalCreditSum = 0;
            let currency = null;

            // Process data
            Object.entries(dataArray).forEach(([key, value]) => {
                if (key !== 'partner_totals') {
                    partner_list.push(key);

                    // Calculate running balance for each partner
                    let runningBalance = 0;

                    // Check initial balance
                    if (partner_totals[key] && partner_totals[key].initial_balance !== undefined) {
                        runningBalance = partner_totals[key].initial_balance;
                    }

                    // Process each entry
                    value.forEach(entry => {
                        if (entry && entry[0]) {
                            const line = entry[0];

                            // Calculate running balance
                            const debit = parseFloat(line.debit) || 0;
                            const credit = parseFloat(line.credit) || 0;
                            runningBalance = debit - credit;

                            // Store balance in the entry
                            line.balance = runningBalance;

                            // Format display values
                            line.debit_display = this.formatNumberWithSeparators(debit);
                            line.credit_display = this.formatNumberWithSeparators(credit);
                            line.amount_currency_display = this.formatNumberWithSeparators(line.amount_currency || 0);
                            line.balance_display = this.formatNumberWithSeparators(runningBalance);
                        }
                    });
                } else {
                    partner_totals = value;
                }
            });

            // Process partner totals
            Object.entries(partner_totals).forEach(([partnerName, partner]) => {
                if (partner) {
                    currency = partner.currency_id || currency;
                    const totalDebit = parseFloat(partner.total_debit) || 0;
                    const totalCredit = parseFloat(partner.total_credit) || 0;

                    totalDebitSum += totalDebit;
                    totalCreditSum += totalCredit;

                    // Format display values
                    partner.total_debit_display = this.formatNumberWithSeparators(totalDebit);
                    partner.total_credit_display = this.formatNumberWithSeparators(totalCredit);

                    if (partner.initial_balance !== undefined) {
                        partner.initial_balance_display = this.formatNumberWithSeparators(partner.initial_balance);
                    }
                    if (partner.initial_debit !== undefined) {
                        partner.initial_debit_display = this.formatNumberWithSeparators(partner.initial_debit);
                    }
                    if (partner.initial_credit !== undefined) {
                        partner.initial_credit_display = this.formatNumberWithSeparators(partner.initial_credit);
                    }
                }
            });

            // Update state
            self.state.partners = partner_list;
            self.state.total = partner_totals;
            self.state.currency = currency;
            self.state.total_debit = totalDebitSum;
            self.state.total_debit_display = this.formatNumberWithSeparators(totalDebitSum);
            self.state.total_credit = totalCreditSum;
            self.state.total_credit_display = this.formatNumberWithSeparators(totalCreditSum);
            self.state.title = action_title;

        } catch (error) {
            console.error("Error loading data:", error);
        }
    }

    async printPdf(ev) {
        ev.preventDefault();
        let totals = {
            'total_debit': this.state.total_debit,
            'total_debit_display': this.state.total_debit_display,
            'total_credit': this.state.total_credit,
            'total_credit_display': this.state.total_credit_display,
            'currency': this.state.currency,
        };

        var action_title = this.props.action.display_name;
        return this.action.doAction({
            'type': 'ir.actions.report',
            'report_type': 'qweb-pdf',
            'report_name': 'dynamic_accounts_report.partner_ledger',
            'report_file': 'dynamic_accounts_report.partner_ledger',
            'data': {
                'partners': this.state.partners,
                'filters': this.filter(),
                'grand_total': totals,
                'data': this.state.data,
                'total': this.state.total,
                'title': action_title,
                'report_name': this.props.action.display_name
            },
            'display_name': this.props.action.display_name,
        });
    }

    filter() {
        var self = this;
        let startDate, endDate;
        let startYear, startMonth, startDay, endYear, endMonth, endDay;

        if (self.state.date_range) {
            const today = new Date();
            if (self.state.date_range === 'year') {
                startDate = new Date(today.getFullYear(), 0, 1);
                endDate = new Date(today.getFullYear(), 11, 31);
            } else if (self.state.date_range === 'quarter') {
                const currentQuarter = Math.floor(today.getMonth() / 3);
                startDate = new Date(today.getFullYear(), currentQuarter * 3, 1);
                endDate = new Date(today.getFullYear(), (currentQuarter + 1) * 3, 0);
            } else if (self.state.date_range === 'month') {
                startDate = new Date(today.getFullYear(), today.getMonth(), 1);
                endDate = new Date(today.getFullYear(), today.getMonth() + 1, 0);
            } else if (self.state.date_range === 'last-month') {
                startDate = new Date(today.getFullYear(), today.getMonth() - 1, 1);
                endDate = new Date(today.getFullYear(), today.getMonth(), 0);
            } else if (self.state.date_range === 'last-year') {
                startDate = new Date(today.getFullYear() - 1, 0, 1);
                endDate = new Date(today.getFullYear() - 1, 11, 31);
            } else if (self.state.date_range === 'last-quarter') {
                const lastQuarter = Math.floor((today.getMonth() - 3) / 3);
                startDate = new Date(today.getFullYear(), lastQuarter * 3, 1);
                endDate = new Date(today.getFullYear(), (lastQuarter + 1) * 3, 0);
            }

            if (startDate) {
                startYear = startDate.getFullYear();
                startMonth = startDate.getMonth() + 1;
                startDay = startDate.getDate();
            }
            if (endDate) {
                endYear = endDate.getFullYear();
                endMonth = endDate.getMonth() + 1;
                endDay = endDate.getDate();
            }
        }

        let filters = {
            'partner': self.state.selected_partner_rec,
            'account': self.state.account,
            'options': self.state.options,
            'start_date': null,
            'end_date': null,
        };

        if (startYear !== undefined && startMonth !== undefined && startDay !== undefined &&
            endYear !== undefined && endMonth !== undefined && endDay !== undefined) {
            filters['start_date'] = `${startYear}-${startMonth < 10 ? '0' : ''}${startMonth}-${startDay < 10 ? '0' : ''}${startDay}`;
            filters['end_date'] = `${endYear}-${endMonth < 10 ? '0' : ''}${endMonth}-${endDay < 10 ? '0' : ''}${endDay}`;
        }

        return filters;
    }

    async print_xlsx() {
        var self = this;
        let totals = {
            'total_debit': this.state.total_debit,
            'total_credit': this.state.total_credit,
            'currency': this.state.currency,
        };

        var action_title = self.props.action.display_name;
        var datas = {
            'partners': self.state.partners,
            'data': self.state.data,
            'total': self.state.total,
            'title': action_title,
            'filters': this.filter(),
            'grand_total': totals,
        };

        var action = {
            'data': {
                'model': 'account.partner.ledger',
                'data': JSON.stringify(datas),
                'output_format': 'xlsx',
                'report_action': self.props.action.xml_id,
                'report_name': action_title,
            },
        };

        BlockUI;
        await download({
            url: '/xlsx_report',
            data: action.data,
            complete: () => unblockUI,
            error: (error) => self.call('crash_manager', 'rpc_error', error),
        });
    }

    gotoJournalEntry(ev) {
        return this.action.doAction({
            type: "ir.actions.act_window",
            res_model: 'account.move',
            res_id: parseInt(ev.target.attributes["data-id"].value, 10),
            views: [[false, "form"]],
            target: "current",
        });
    }

    gotoJournalItem(ev) {
        return this.action.doAction({
            type: "ir.actions.act_window",
            res_model: 'account.move.line',
            name: "Journal Items",
            views: [[false, "list"]],
            domain: [["partner_id", "=", parseInt(ev.target.attributes["data-id"].value, 10)], ['account_type', 'in', ['liability_payable', 'asset_receivable']]],
            target: "current",
        });
    }

    openPartner(ev) {
        return this.action.doAction({
            type: "ir.actions.act_window",
            res_model: 'res.partner',
            res_id: parseInt(ev.target.attributes["data-id"].value, 10),
            views: [[false, "form"]],
            target: "current",
        });
    }

    async applyFilter(val, ev, is_delete = false) {
        let partner_list = [];
        let partner_totals = {};
        let totalDebitSum = 0;
        let totalCreditSum = 0;

        // Reset state
        this.state.partners = [];
        this.state.data = {};
        this.state.total = {};
        this.state.filter_applied = true;

        if (ev) {
            if (ev.input && ev.input.attributes.placeholder.value == 'Partner' && !is_delete) {
                this.state.selected_partner.push(val[0].id);
                this.state.selected_partner_rec.push(val[0]);
            } else if (is_delete) {
                let index = this.state.selected_partner_rec.indexOf(val);
                this.state.selected_partner_rec.splice(index, 1);
                this.state.selected_partner = this.state.selected_partner_rec.map((rec) => rec.id);
            }
        } else {
            if (val.target.name === 'start_date') {
                this.state.date_range = {
                    ...this.state.date_range,
                    start_date: val.target.value
                };
            } else if (val.target.name === 'end_date') {
                this.state.date_range = {
                    ...this.state.date_range,
                    end_date: val.target.value
                };
            } else if (['month', 'year', 'quarter', 'last-month', 'last-year', 'last-quarter'].includes(val.target.attributes["data-value"].value)) {
                this.state.date_range = val.target.attributes["data-value"].value;
            } else if (val.target.attributes["data-value"].value === 'receivable') {
                if (val.target.classList.contains("selected-filter")) {
                    const { Receivable, ...updatedAccount } = this.state.account;
                    this.state.account = updatedAccount;
                    val.target.classList.remove("selected-filter");
                } else {
                    this.state.account = {
                        ...this.state.account,
                        'Receivable': true
                    };
                    val.target.classList.add("selected-filter");
                }
            } else if (val.target.attributes["data-value"].value === 'payable') {
                if (val.target.classList.contains("selected-filter")) {
                    const { Payable, ...updatedAccount } = this.state.account;
                    this.state.account = updatedAccount;
                    val.target.classList.remove("selected-filter");
                } else {
                    this.state.account = {
                        ...this.state.account,
                        'Payable': true
                    };
                    val.target.classList.add("selected-filter");
                }
            } else if (val.target.attributes["data-value"].value === 'draft') {
                if (val.target.classList.contains("selected-filter")) {
                    const { draft, ...updatedOptions } = this.state.options;
                    this.state.options = updatedOptions;
                    val.target.classList.remove("selected-filter");
                } else {
                    this.state.options = {
                        ...this.state.options,
                        'draft': true
                    };
                    val.target.classList.add("selected-filter");
                }
            }
        }

        // Load filtered data
        let filtered_data = await this.orm.call("account.partner.ledger", "get_filter_values", [
            this.state.selected_partner,
            this.state.date_range,
            this.state.account,
            this.state.options
        ]);

        // Process filtered data
        Object.entries(filtered_data).forEach(([key, value]) => {
            if (key !== 'partner_totals') {
                partner_list.push(key);

                let runningBalance = 0;
                if (partner_totals[key] && partner_totals[key].initial_balance !== undefined) {
                    runningBalance = partner_totals[key].initial_balance;
                }

                // Process each entry
                value.forEach(entry => {
                    if (entry && entry[0]) {
                        const line = entry[0];
                        const debit = parseFloat(line.debit) || 0;
                        const credit = parseFloat(line.credit) || 0;
                        runningBalance = debit - credit;

                        line.balance = runningBalance;
                        line.debit_display = this.formatNumberWithSeparators(debit);
                        line.credit_display = this.formatNumberWithSeparators(credit);
                        line.amount_currency_display = this.formatNumberWithSeparators(line.amount_currency || 0);
                        line.balance_display = this.formatNumberWithSeparators(runningBalance);
                    }
                });
            } else {
                partner_totals = value;
            }
        });

        // Process totals
        Object.entries(partner_totals).forEach(([partnerName, partner]) => {
            if (partner) {
                const totalDebit = parseFloat(partner.total_debit) || 0;
                const totalCredit = parseFloat(partner.total_credit) || 0;

                totalDebitSum += totalDebit;
                totalCreditSum += totalCredit;

                partner.total_debit_display = this.formatNumberWithSeparators(totalDebit);
                partner.total_credit_display = this.formatNumberWithSeparators(totalCredit);

                if (partner.initial_balance !== undefined) {
                    partner.initial_balance_display = this.formatNumberWithSeparators(partner.initial_balance);
                }
                if (partner.initial_debit !== undefined) {
                    partner.initial_debit_display = this.formatNumberWithSeparators(partner.initial_debit);
                }
                if (partner.initial_credit !== undefined) {
                    partner.initial_credit_display = this.formatNumberWithSeparators(partner.initial_credit);
                }
            }
        });

        // Update state
        this.state.partners = partner_list;
        this.state.data = filtered_data;
        this.state.total = partner_totals;
        this.state.total_debit = totalDebitSum;
        this.state.total_credit = totalCreditSum;
        this.state.total_debit_display = this.formatNumberWithSeparators(totalDebitSum);
        this.state.total_credit_display = this.formatNumberWithSeparators(totalCreditSum);

        if (this.unfoldButton.el && this.unfoldButton.el.classList.contains("selected-filter")) {
            this.unfoldButton.el.classList.remove("selected-filter");
        }
    }

    getDomain() {
        return [];
    }

    async unfoldAll(ev) {
        if (this.tbody.el) {
            const children = this.tbody.el.children;
            if (!ev.target.classList.contains("selected-filter")) {
                for (let i = 0; i < children.length; i++) {
                    children[i].classList.add('show');
                }
                ev.target.classList.add("selected-filter");
            } else {
                for (let i = 0; i < children.length; i++) {
                    children[i].classList.remove('show');
                }
                ev.target.classList.remove("selected-filter");
            }
        }
    }
}

PartnerLedger.defaultProps = {
    resIds: [],
};

PartnerLedger.template = 'pl_template_new';
actionRegistry.add("p_l", PartnerLedger);