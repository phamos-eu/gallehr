"""Creates the project folder tree in Nextcloud via WebDAV when a Project is created (see Nextcloud Settings).

Replaces the x22 shell scripts projects.sh/projects2.sh (project.log watcher + davfs mkdir on ownCloud);
folder names are kept exactly as those scripts made them, so old and new folders look the same.
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
		if frappe.db.get_value("Project", project, "customer"):
			create_folders(project)
	except Exception:
		frappe.log_error(title="Nextcloud Projektordner", reference_doctype="Project", reference_name=project)


@frappe.whitelist()
def create_folders_now(project):
	"""Button on the Project form: (re)creates missing folders, e.g. after an outage or for older projects."""
	frappe.has_permission("Project", "write", project, throw=True)
	if not frappe.get_cached_doc(SETTINGS).folders_enabled:
		frappe.throw(_("Project folders are switched off in Nextcloud Settings."))
	if not frappe.db.get_value("Project", project, "customer"):
		frappe.throw(_("The project has no customer, the folder name needs the customer number."))
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
	for path in folder_paths(project, p.project_name, p.customer, client_code(p.customer)):
		r = dav.request("MKCOL", files_url(settings, root + path), timeout=TIMEOUT)
		if r.status_code == 405:
			result["existing"] += 1
			continue
		r.raise_for_status()
		result["created"] += 1
	return result


def client_code(customer):
	"""<clientcodes> of the old project.log line: the customer's "Kurzname" (custom field shortname, only in the
	site database). Without one the customer name is used, instead of a folder called "-<number>"."""
	if frappe.get_meta("Customer").has_field("shortname"):
		code = frappe.db.get_value("Customer", customer, "shortname")
		if code:
			return code
	return frappe.db.get_value("Customer", customer, "customer_name")


def root_segments(settings):
	return [s.strip() for s in (settings.folder_root or "").split("/") if s.strip()]


def clean(name):
	"""A slash would make an extra folder level, so it becomes a dash like the other separators."""
	return str(name or "").strip().replace("/", "-").replace("\\", "-")


def folder_paths(project, project_name, customer, code):
	"""All folders in creation order, parents first, as lists of names below the root."""
	nr = project.replace("PROJ-", "")
	code = clean(code)
	client = f"{code}-{customer}"
	project_dir = [client, clean(project_name).replace(" | ", "-").replace(" ", "_") + f"-{customer}-{nr}"]
	work_results = [*project_dir, f"Arbeitsergebnisse-{nr}"]
	return [
		[client],
		[client, f"{code}-Akquisition"],
		project_dir,
		work_results,
		[*project_dir, f"PM-{nr}"],
		[*project_dir, f"Vertraege-{nr}"],
		*[[*work_results, name.format(nr=nr)] for name in WORK_RESULTS],
	]
