"""
Wrap search_link so that when the Link field requests Project options, we use
Gallehr's get_project_name (shared-across-companies).
"""

import json

import frappe
from frappe.desk.search import build_for_autosuggest
from frappe.desk.search import search_widget as _search_widget

PROJECT_QUERY_ORIGINAL = "erpnext.controllers.queries.get_project_name"
PROJECT_QUERY_GALLEHR = "gallehr.override.queries.get_project_name"


def _filters_has_company(filters) -> bool:
	"""True if filters contain a company value (dict or list of conditions)."""
	if isinstance(filters, dict):
		return bool(filters.get("company"))
	if isinstance(filters, list):
		for f in filters:
			if not isinstance(f, (list, tuple)) or len(f) < 2:
				continue

			field = f[1] if len(f) >= 4 else f[0]
			if field == "company":
				return True
	return False


@frappe.whitelist()
def search_link(
	doctype: str,
	txt: str,
	query: str | None = None,
	filters: str | dict | list = None,
	page_length: int = 10,
	searchfield: str | None = None,
	reference_doctype: str | None = None,
	ignore_user_permissions: bool = False,
):
	"""Use Gallehr get_project_name for Project whenever company is in filters (selling or buying)."""
	if doctype == "Project":
		if filters and isinstance(filters, str):
			try:
				filters = json.loads(filters)
			except Exception:
				pass
		if query == PROJECT_QUERY_ORIGINAL or (not query and _filters_has_company(filters)):
			query = PROJECT_QUERY_GALLEHR
	results = _search_widget(
		doctype,
		txt.strip(),
		query,
		searchfield=searchfield,
		page_length=page_length,
		filters=filters,
		reference_doctype=reference_doctype,
		ignore_user_permissions=ignore_user_permissions,
	)
	return build_for_autosuggest(results, doctype=doctype)
