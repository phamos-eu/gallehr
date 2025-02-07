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
			"width": 180
		},
		{
			"label": _("Payment Request"),
			"fieldname": "payment_request",
			"fieldtype": "Link",
			"options": "Payment Request",
			"width": 180
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
	
	query = (
		frappe.qb.from_(PurchaseInvoice)
		.select(
			PurchaseInvoice.name,
			PurchaseInvoice.grand_total,
			PurchaseInvoice.due_date
		)
		.where(PurchaseInvoice.docstatus == 1)
		.orderby(PurchaseInvoice.creation, order=frappe.qb.asc)
		.orderby(PurchaseInvoice.name, order=frappe.qb.asc)
	)

	if filters.supplier:
		query = query.where(PurchaseInvoice.supplier == filters.supplier)

	if filters.purchase_invoices_with_payment_requests:
		PaymentRequest = frappe.qb.DocType("Payment Request")
		data = (
			query
			.inner_join(PaymentRequest)
			.on(PaymentRequest.reference_name == PurchaseInvoice.name)
			.select(PaymentRequest.name.as_("payment_request"))
			.where(PaymentRequest.docstatus == 1)
			.where(PaymentRequest.reference_doctype == "Purchase Invoice")
		).run(as_dict=True)

		if filters.supplier:
			query = query.where(PaymentRequest.party_type == "Supplier").where(PaymentRequest.party == filters.supplier)

		
		if filters.nested_report:
			report_data = []
			seen_invoices = set()


			for entry in data:
				invoice_key = (entry["name"], entry["grand_total"], entry["due_date"])
				
				if invoice_key not in seen_invoices:
					report_data.append({
						"name": entry["name"],
						"grand_total": entry["grand_total"],
						"due_date": entry["due_date"],
						"indent": 0
					})
					seen_invoices.add(invoice_key)

				report_data.append({
					"payment_request": entry["payment_request"],
					"indent": 1
				})

			return report_data
		else:
			return data

	else:
		return query.run(as_dict=True)
