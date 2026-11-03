# Copyright (c) 2026, phamos.eu and contributors
# For license information, please see license.txt

import frappe
import requests
from frappe import _
from frappe.model.document import Document
from frappe.utils.password import get_decrypted_password

from gallehr import nextcloud_calendar_sync
from gallehr.nextcloud_client import SETTINGS, TIMEOUT, files_url, session
from gallehr.nextcloud_project_folders import root_segments


class NextcloudSettings(Document):
	pass


@frappe.whitelist()
def test_connection():
	frappe.only_for("System Manager")
	settings = frappe.get_single(SETTINGS)
	missing = [
		label
		for fieldname, label in (("server_url", "Nextcloud URL"), ("username", "Bot Username"))
		if not settings.get(fieldname)
	]
	if not get_decrypted_password(SETTINGS, SETTINGS, "app_password", raise_exception=False):
		missing.append("App Password")
	if missing:
		return {"ok": False, "error": _("Please fill in: {0}").format(", ".join(missing))}
	dav = session(settings)
	try:
		r = nextcloud_calendar_sync.propfind_calendars(dav, settings)
		if r.status_code == 401:
			return {"ok": False, "error": _("Login rejected (401): check the bot username and the app password.")}
		r.raise_for_status()
		root = dav.request("PROPFIND", files_url(settings, root_segments(settings)), headers={"Depth": "0"}, timeout=TIMEOUT)
	except requests.RequestException as e:
		return {"ok": False, "error": _("Nextcloud not reachable: {0}").format(str(e))}
	names = [name for name, href in nextcloud_calendar_sync.list_calendars(r.content)]
	result = {
		"calendars": names,
		"calendar_name": settings.calendar_name,
		"calendar_found": settings.calendar_name in names,
		"folder_root": settings.folder_root,
		"folder_root_found": root.status_code == 207,
	}
	result["ok"] = (result["calendar_found"] or not settings.enabled) and (
		result["folder_root_found"] or not settings.folders_enabled
	)
	return result
