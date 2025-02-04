# Copyright (c) 2025, phamos.eu and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def execute(filters=None):
	columns = get_column()
	data = get_data(filters)
	return columns, data


def get_column():
	return [
		{
			"label": _("Purchase Invoice"),
			"fieldname": "name",
			"fieldtype": "Link",
			"options": "Purchase Invoice",
			"width": 160
		},
		{
			"label": _("Payment Request"),
			"fieldname": "payment_request",
			"fieldtype": "Link",
			"options": "Payment Request",
			"width": 160
		},
		{
			"label": _("Invoice Amount"),
			"fieldname": "grand_total",
			"fieldtype": "Float",
			"width": 160
		},
		{
			"label": _("Due Date"),
			"fieldname": "due_date",
			"fieldtype": "Date",
			"width": 160
		},
	]


def get_data(filters):
	PurchaseInvoice = frappe.qb.DocType("Purchase Invoice")

	data = (
		frappe.qb.from_(PurchaseInvoice)
		.select(
			PurchaseInvoice.name,
			PurchaseInvoice.grand_total,
			PurchaseInvoice.due_date
		)
		.where(PurchaseInvoice.docstatus == 1)
		.orderby(PurchaseInvoice.creation, order=frappe.qb.asc)
		.orderby(PurchaseInvoice.name, order=frappe.qb.asc)
		.run(as_dict=1, debug=1)
	)

	return data