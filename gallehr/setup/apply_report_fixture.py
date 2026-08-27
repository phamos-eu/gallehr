"""One-off dev script: applies gallehr/fixtures/report.json to the current site,
the same way `bench migrate` does on deploy. Not wired into hooks.py.

Run via:
    bench --site gallehr-dev.localhost execute gallehr.setup.apply_report_fixture.run
"""

import json
import os

import frappe


def run():
	path = os.path.join(frappe.get_app_path("gallehr"), "fixtures", "report.json")
	with open(path) as f:
		records = json.load(f)

	for rec in records:
		name = rec["name"]
		if frappe.db.exists("Report", name):
			doc = frappe.get_doc("Report", name)
		else:
			doc = frappe.new_doc("Report")
			doc.report_name = name
		for field in ("report_script", "report_type", "module", "ref_doctype",
				"disabled", "prepared_report", "add_total_row", "javascript"):
			if field in rec:
				doc.set(field, rec[field])
		if "filters" in rec:
			doc.filters = []
			for frow in rec["filters"]:
				doc.append("filters", {
					k: v for k, v in frow.items()
					if k in ("fieldname", "label", "fieldtype", "options", "default", "mandatory", "wildcard_filter")
				})
		doc.save(ignore_permissions=True)
		print(f"applied: {name} ({len(rec.get('report_script') or '')} chars)")

	frappe.db.commit()
