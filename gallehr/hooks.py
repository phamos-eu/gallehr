app_name = "gallehr"
app_title = "Gallehr"
app_publisher = "phamos.eu"
app_description = "Gallehr Custom App"
app_email = "support@phamos.eu"
app_license = "MIT"

# include js in doctype views
doctype_js = {
    "Contact" : "public/js/contact.js",
    "Leave Application" : "public/js/leave_application.js",
    # "Sales Order" : "public/js/sales_order.js",
    "Web Form" : "public/js/web_form.js",
}
fixtures = [
	{"dt": "Print Format", "filters": 
		[
			["module", "=", "Gallehr"],
			["standard", "!=", "Yes"]
		
		]
	},
	{"dt": "Custom Field", "filters":
		[
			["module", "=", "Gallehr"]
		]
	},
	{"dt": "Property Setter", "filters":
		[
			["module", "=", "Gallehr"]
		]
	}
]

override_whitelisted_methods = {
	"frappe.desk.search.search_link": "gallehr.override.search.search_link",
}