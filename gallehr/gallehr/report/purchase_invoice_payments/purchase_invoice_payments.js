// Copyright (c) 2025, phamos.eu and contributors
// For license information, please see license.txt
/* eslint-disable */

frappe.query_reports["Purchase Invoice Payments"] = {
	"filters": [
		{
			fieldname:"supplier",
			label: __("Supplier"),
			fieldtype: "Link",
			options: "Supplier",
		},
		{
			fieldname:"purchase_invoices_with_payment_requests",
			label: __("Purchase Invoices with Payment Requests"),
			fieldtype: "Check"
		},
		{
			fieldname:"nested_report",
			label: __("Nested Report"),
			fieldtype: "Check"
		}
	]
};
