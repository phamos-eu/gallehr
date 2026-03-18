# Copyright (c) 2025, Gallehr and contributors
# For license information, please see license.txt

"""
Override get_project_name so the project dropdown shows projects allowed for the
document's company (Option A: primary company or shared with company in allowed_companies).
"""

import frappe
from frappe import qb
from frappe.query_builder import Criterion, CustomFunction
from frappe.query_builder.functions import Locate
from pypika import Order

from erpnext.controllers.queries import get_project_name as _original_get_project_name
from erpnext.controllers.queries import get_fields

from gallehr.project_sharing import get_project_names_allowed_for_company


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_project_name(doctype, txt, searchfield, start, page_len, filters):
	"""Return projects allowed for the document's company (primary or shared)."""
	if not (filters and filters.get("company")):
		return _original_get_project_name(doctype, txt, searchfield, start, page_len, filters)

	company = filters.get("company")
	allowed_names = get_project_names_allowed_for_company(company, status_filter=True)
	if not allowed_names:
		return []

	# Show all projects allowed for this company; do not filter by customer so that
	# shared projects appear regardless of the form's customer (e.g. Sales Invoice customer).
	proj = qb.DocType("Project")
	qb_filter_and_conditions = [proj.name.isin(allowed_names)]

	qb_filter_or_conditions = []
	ifelse = CustomFunction("IF", ["condition", "then", "else"])

	fields = get_fields(doctype, ["name", "project_name"])
	searchfields = [
		x for x in frappe.get_meta(doctype).get_search_fields() if x not in ["customer", "status"]
	]
	if txt:
		for x in searchfields:
			qb_filter_or_conditions.append(proj[x].like(f"%{txt}%"))

	q = qb.from_(proj)
	for x in fields:
		q = q.select(proj[x])

	q = q.where(Criterion.all(qb_filter_and_conditions))
	if qb_filter_or_conditions:
		q = q.where(Criterion.any(qb_filter_or_conditions))

	if txt:
		q = q.orderby(ifelse(Locate(txt, proj.project_name) > 0, Locate(txt, proj.project_name), 99999))
	q = q.orderby(proj.idx, order=Order.desc).orderby(proj.name)

	if page_len:
		q = q.limit(page_len)
	if start:
		q = q.offset(start)

	return q.run()
