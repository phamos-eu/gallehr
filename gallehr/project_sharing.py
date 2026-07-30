import frappe


def project_allowed_for_company(project_name: str, company: str) -> bool:
	"""Return True if the given company is allowed to use this project.

	Allowed when:
	- company equals the project's primary company, or
	- project has custom_shared_across_companies set and company is in allowed_companies child table.
	"""
	if not company or not project_name:
		return False

	project_company = frappe.get_cached_value("Project", project_name, "company")
	if company == project_company:
		return True

	if not frappe.db.has_column("Project", "custom_shared_across_companies"):
		return False

	shared = frappe.get_cached_value("Project", project_name, "custom_shared_across_companies")
	if not shared:
		return False

	# Check allowed_companies child table (Project Allowed Company)
	exists = frappe.db.exists(
		"Project Allowed Company",
		{"parent": project_name, "parenttype": "Project", "company": company},
	)
	return bool(exists)


def get_project_names_allowed_for_company(company: str, status_filter: bool = True) -> list[str]:
	"""Return list of project names that the given company is allowed to use (for dropdowns/reports).

	Includes projects where company is the primary company, or project is shared and company is in
	allowed_companies. Optionally excludes Completed/Cancelled (status_filter=True).
	"""
	if not company:
		return []

	# Projects whose primary company is this company
	if status_filter:
		primary = frappe.get_all(
			"Project",
			filters={"company": company, "status": ["not in", ["Completed", "Cancelled"]]},
			pluck="name",
		)
	else:
		primary = frappe.get_all("Project", filters={"company": company}, pluck="name")

	# Projects shared with this company
	if not frappe.db.has_column("Project", "custom_shared_across_companies"):
		return primary

	shared = frappe.get_all(
		"Project Allowed Company",
		filters={"company": company},
		pluck="parent",
	)
	if not shared:
		return list(set(primary))

	# Only include shared projects that have the flag set
	shared_with_flag = frappe.get_all(
		"Project",
		filters={"name": ["in", shared], "custom_shared_across_companies": 1},
		pluck="name",
	)
	if status_filter and shared_with_flag:
		shared_with_flag = frappe.get_all(
			"Project",
			filters={
				"name": ["in", shared_with_flag],
				"status": ["not in", ["Completed", "Cancelled"]],
			},
			pluck="name",
		)

	return list(set(primary + (shared_with_flag or [])))
