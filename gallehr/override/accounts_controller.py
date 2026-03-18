# Copyright (c) 2025, Gallehr and contributors
# For license information, please see license.txt

"""
Override AccountsController.validate_company so that for the Project dimension
we allow a project when the document company equals the project's company OR
the project is shared and the document company is in allowed_companies (Option A).
"""

import frappe
from frappe import _

from gallehr.project_sharing import project_allowed_for_company


def _patched_validate_company(self, dimension_list, child=None):
	"""Validate that accounting dimension values (Project, Cost Center, etc.) belong to doc company.
	For Project, use project_allowed_for_company (shared across companies). Others unchanged.
	"""
	for dimension in dimension_list:
		if not child:
			dimension_value = self.get(frappe.scrub(dimension))
		else:
			dimension_value = child.get(frappe.scrub(dimension))

		if dimension_value:
			if dimension == "Project":
				if not project_allowed_for_company(dimension_value, self.company):
					frappe.throw(
						_("{0}: {1} does not belong to the Company: {2}").format(
							dimension, frappe.bold(dimension_value), self.company
						)
					)
			else:
				company = frappe.get_cached_value(dimension, dimension_value, "company")
				if company and company != self.company:
					frappe.throw(
						_("{0}: {1} does not belong to the Company: {2}").format(
							dimension, frappe.bold(dimension_value), self.company
						)
					)


def patch_accounts_controller():
	from erpnext.controllers import accounts_controller

	accounts_controller.AccountsController.validate_company = _patched_validate_company


# Apply patch when this module is loaded (gallehr app loads after erpnext)
patch_accounts_controller()
