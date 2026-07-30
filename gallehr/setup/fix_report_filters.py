"""One-off dev script: brings the 'Finanz Dashboard' Report's declared filters
in line with what its report_script actually reads. Not wired into hooks.py.

Why: the declared filters had drifted from the script -- they still listed the
removed `avg_aus_tag_manuell`, never declared `aktuell_liquiditaet` (which the
script reads), lacked the new `burnrate_von`/`burnrate_bis`, and carried a
hardcoded `start_liquiditaet` default of 448523 that silently skewed the
report whenever it was opened standalone. Declared filters also matter for
deep-linking: the dashboard passes its filter values through the URL, and
Frappe only maps URL params onto *declared* filters.

Run via:
    bench --site gallehr-dev.localhost execute gallehr.setup.fix_report_filters.run
"""

import frappe

# Mirrors exactly what report_script reads out of `filters`, in dashboard order.
FILTERS = [
	{"fieldname": "jahr", "label": "Jahr", "fieldtype": "Select",
		"options": "2024\n2025\n2026", "default": "2026", "mandatory": 0},
	{"fieldname": "aktuell_liquiditaet", "label": "Aktueller Kontostand (Brutto)",
		"fieldtype": "Float", "default": None, "mandatory": 0},
	{"fieldname": "start_liquiditaet", "label": "Start Liquidität Jan (Brutto)",
		"fieldtype": "Float", "default": None, "mandatory": 0},
	{"fieldname": "angebotsumwandlung", "label": "Angebotsumwandlung %",
		"fieldtype": "Float", "default": "30", "mandatory": 0},
	{"fieldname": "burnrate_von", "label": "Burnrate von", "fieldtype": "Date",
		"default": None, "mandatory": 0},
	{"fieldname": "burnrate_bis", "label": "Burnrate bis", "fieldtype": "Date",
		"default": None, "mandatory": 0},
]


def run():
	doc = frappe.get_doc("Report", "Finanz Dashboard")
	before = [f.fieldname for f in doc.filters]

	doc.filters = []
	for f in FILTERS:
		doc.append("filters", f)

	doc.save(ignore_permissions=True)
	frappe.db.commit()

	after = [f.fieldname for f in doc.filters]
	print("before:", before)
	print("after: ", after)
	print("removed:", sorted(set(before) - set(after)))
	print("added:  ", sorted(set(after) - set(before)))
