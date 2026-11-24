"""Creates the project folder tree in Nextcloud via WebDAV when a Project is created (see Nextcloud Settings).

Replaces the x22 shell scripts projects.sh/projects2.sh (project.log watcher + davfs mkdir on ownCloud).
Names are pieced together by the system, so they are right even if a project name ignores the convention
"Kurzname | Projektname": one top folder Kurzname-Projektname, in it Kurzname-Akquisition (filled by hand) and the
project folder Kurzname-Projektname-<Kunden-Nr>-<Projekt-Nr> with the subfolders of the old scripts.
"""

import frappe
from frappe import _

from gallehr.nextcloud_client import SETTINGS, TIMEOUT, files_url, session

# Order and spelling as in projects2.sh, including "An_Gutachter" without the dash.
WORK_RESULTS = [
	"An_Behoerde-{nr}",
	"An_Gutachter{nr}",
	"An_Kunden-{nr}",
	"Vollmacht-{nr}",
	"Vom_Gutachter-{nr}",
	"Vom_Kunden-{nr}",
	"Von_Behoerde-{nr}",
	"Workshops-{nr}",
]


def on_project_insert(doc, method=None):
	"""doc_events hook: queue the folders after commit, so Nextcloud can never block creating a project."""
	settings = frappe.get_cached_doc(SETTINGS)
	if not settings.folders_enabled:
		return
	if settings.project_filter and settings.project_filter.lower() not in (doc.project_name or "").lower():
		return
	frappe.enqueue(
		"gallehr.nextcloud_project_folders.create_project_folders",
		queue="short",
		enqueue_after_commit=True,
		project=doc.name,
	)


def create_project_folders(project):
	try:
		create_folders(project)
	except Exception:
		frappe.log_error(title="Nextcloud Projektordner", reference_doctype="Project", reference_name=project)


@frappe.whitelist()
def create_folders_now(project):
	"""Button on the Project form: (re)creates missing folders, e.g. after an outage or for older projects."""
	frappe.has_permission("Project", "write", project, throw=True)
	if not frappe.get_cached_doc(SETTINGS).folders_enabled:
		frappe.throw(_("Project folders are switched off in Nextcloud Settings."))
	return create_folders(project)


def create_folders(project):
	settings = frappe.get_single(SETTINGS)
	dav = session(settings)
	root = root_segments(settings)
	r = dav.request("PROPFIND", files_url(settings, root), headers={"Depth": "0"}, timeout=TIMEOUT)
	if r.status_code == 404:
		frappe.throw(_("Folder {0} does not exist for {1} in Nextcloud.").format(settings.folder_root, settings.username))
	r.raise_for_status()

	p = frappe.db.get_value("Project", project, ["project_name", "customer"], as_dict=True)
	result = {"created": 0, "existing": 0}
	for path in folder_paths(project, p.project_name, p.customer, kurzname(p.project_name, p.customer)):
		r = dav.request("MKCOL", files_url(settings, root + path), timeout=TIMEOUT)
		if r.status_code == 405:
			result["existing"] += 1
			continue
		r.raise_for_status()
		result["created"] += 1
	return result


def root_segments(settings):
	return [s.strip() for s in (settings.folder_root or "").split("/") if s.strip()]


def clean(name):
	"""A slash would make an extra folder level, so it becomes a dash like the other separators."""
	return str(name or "").strip().replace("/", "-").replace("\\", "-")


def slug(name):
	"""Folder-safe form: " | " and "|" become "-" (Windows can't store "|"), spaces become "_"."""
	return clean(name).replace(" | ", "-").replace("|", "-").replace(" ", "_")


def kurzname(project_name, customer=None):
	"""The customer's field "Kurzname" (shortname, Settings tab, mandatory); without one the part before "|" of
	"Kurzname | Projektname"; without that the customer name. Since 2025 the typed part equals the field in almost
	every project; where it differs, the mandatory field wins."""
	if customer and frappe.get_meta("Customer").has_field("shortname"):
		code = clean(frappe.db.get_value("Customer", customer, "shortname"))
		if code:
			return code
	name = clean(project_name)
	if "|" in name and name.split("|", 1)[0].strip():
		return name.split("|", 1)[0].strip()
	return clean(frappe.db.get_value("Customer", customer, "customer_name")) if customer else ""


def project_part(project_name, code):
	"""The project's own name: the part after the first "|" (the part before it if nothing follows), without a
	leading Kurzname (only as a whole word), so the Kurzname is never doubled."""
	name = clean(project_name)
	if "|" in name:
		before, after = name.split("|", 1)
		name = after.strip() or before.strip()
	rest = name[len(code) :]
	if code and name.lower().startswith(code.lower()) and (not rest or rest[0] in " -_|"):
		name = rest.lstrip(" -_|")
	return name


def folder_paths(project, project_name, customer, code):
	"""All folders in creation order, parents first, as lists of names below the root. The customer number is added
	to the project folder when the project has a customer."""
	nr = project.replace("PROJ-", "")
	part = project_part(project_name, code)
	base = slug(f"{code}-{part}" if code and part else code or part)
	project_dir = [base, f"{base}-{slug(customer)}-{nr}" if customer else f"{base}-{nr}"]
	work_results = [*project_dir, f"Arbeitsergebnisse-{nr}"]
	return [
		[base],
		[base, f"{slug(code or part)}-Akquisition"],
		project_dir,
		work_results,
		[*project_dir, f"PM-{nr}"],
		[*project_dir, f"Vertraege-{nr}"],
		*[[*work_results, name.format(nr=nr)] for name in WORK_RESULTS],
	]
