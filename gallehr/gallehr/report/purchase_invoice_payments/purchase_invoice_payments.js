// Copyright (c) 2025, phamos.eu and contributors
// For license information, please see license.txt
/* eslint-disable */

frappe.query_reports["Purchase Invoice Payments"] = {
	"filters": [
		{
			fieldname:"purchase_invoices_with_payment_requests",
			label: __("Purchase Invoices with Payment Requests"),
			fieldtype: "Check"
		}
	]
};
