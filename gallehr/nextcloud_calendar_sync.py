"""Mirrors approved Leave Applications into a Nextcloud calendar via CalDAV (see Nextcloud Calendar Settings)."""

import datetime
from urllib.parse import quote, urljoin
from xml.etree import ElementTree

import frappe
import requests
from frappe import _
from frappe.utils import getdate
from frappe.utils.password import get_decrypted_password

SETTINGS = "Nextcloud Calendar Settings"
NEUTRAL_TITLE = "Abwesend"
TIMEOUT = 30
NS = {"d": "DAV:", "cal": "urn:ietf:params:xml:ns:caldav"}
PROPFIND_BODY = (
	'<?xml version="1.0" encoding="utf-8"?>'
	'<d:propfind xmlns:d="DAV:"><d:prop><d:displayname/><d:resourcetype/></d:prop></d:propfind>'
)


def on_leave_application_change(doc, method=None):
	"""doc_events hook: queue a sync after commit, so Nextcloud can never block or break an approval."""
	settings = frappe.get_cached_doc(SETTINGS)
	if not settings.enabled:
		return
	if settings.employee_filter and settings.employee_filter.lower() not in (doc.employee_name or "").lower():
		return
	frappe.enqueue(
		"gallehr.nextcloud_calendar_sync.sync_leave_event",
		queue="short",
		enqueue_after_commit=True,
		leave_name=doc.name,
	)


def sync_leave_event(leave_name):
	"""Decides from the leave's state at run time, so approve-then-quick-cancel still ends with no event."""
	try:
		settings = frappe.get_single(SETTINGS)
		if not settings.enabled:
			return
		session = caldav_session(settings)
		event_url = urljoin(base_url(settings), find_calendar_href(session, settings)) + event_uid(leave_name) + ".ics"
		leave = frappe.db.get_value(
			"Leave Application",
			leave_name,
			["employee_name", "leave_type", "from_date", "to_date", "status", "docstatus"],
			as_dict=True,
		)
		if leave and leave.docstatus == 1 and leave.status == "Approved":
			r = session.put(
				event_url,
				data=build_ics(leave_name, leave),
				headers={"Content-Type": "text/calendar; charset=utf-8"},
				timeout=TIMEOUT,
			)
			r.raise_for_status()
		else:
			r = session.delete(event_url, timeout=TIMEOUT)
			if r.status_code != 404:
				r.raise_for_status()
	except Exception:
		frappe.log_error(
			title="Nextcloud Urlaubskalender Sync",
			reference_doctype="Leave Application",
			reference_name=leave_name,
		)


def test_connection():
	settings = frappe.get_single(SETTINGS)
	missing = [
		label
		for fieldname, label in (("server_url", "Nextcloud URL"), ("username", "Bot Username"), ("calendar_name", "Calendar Name"))
		if not settings.get(fieldname)
	]
	if not get_decrypted_password(SETTINGS, SETTINGS, "app_password", raise_exception=False):
		missing.append("App Password")
	if missing:
		return {"ok": False, "error": _("Please fill in: {0}").format(", ".join(missing))}
	try:
		r = propfind_calendars(caldav_session(settings), settings)
		if r.status_code == 401:
			return {"ok": False, "error": _("Login rejected (401): check the bot username and the app password.")}
		r.raise_for_status()
	except requests.RequestException as e:
		return {"ok": False, "error": _("Nextcloud not reachable: {0}").format(str(e))}
	names = [name for name, href in list_calendars(r.content)]
	return {"ok": settings.calendar_name in names, "calendars": names, "calendar_name": settings.calendar_name}


def caldav_session(settings):
	session = requests.Session()
	session.auth = (settings.username, get_decrypted_password(SETTINGS, SETTINGS, "app_password"))
	return session


def base_url(settings):
	return settings.server_url.rstrip("/") + "/"


def propfind_calendars(session, settings):
	return session.request(
		"PROPFIND",
		urljoin(base_url(settings), f"remote.php/dav/calendars/{quote(settings.username)}/"),
		data=PROPFIND_BODY,
		headers={"Depth": "1", "Content-Type": "application/xml; charset=utf-8"},
		timeout=TIMEOUT,
	)


def list_calendars(xml_bytes):
	calendars = []
	for response in ElementTree.fromstring(xml_bytes).findall("d:response", NS):
		if response.find(".//d:resourcetype/cal:calendar", NS) is not None:
			calendars.append((response.findtext(".//d:displayname", "", NS), response.findtext("d:href", "", NS)))
	return calendars


def find_calendar_href(session, settings):
	r = propfind_calendars(session, settings)
	r.raise_for_status()
	for name, href in list_calendars(r.content):
		if name == settings.calendar_name:
			return href
	frappe.throw(_("Calendar {0} not found for {1}").format(settings.calendar_name, settings.username))


def event_uid(leave_name):
	return f"erp-leave-{leave_name}"


def is_private_type(leave_type):
	"""Sick leave (GDPR Art. 9) and unpaid leave are published only as "Abwesend"."""
	name = (leave_type or "").lower()
	return name.startswith("krank") or "sick" in name or "unbezahlt" in name or "without pay" in name


def event_title(leave):
	shown_type = NEUTRAL_TITLE if is_private_type(leave.leave_type) else leave.leave_type
	return f"{leave.employee_name}: {shown_type}"


def escape_ics_text(text):
	return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def build_ics(leave_name, leave):
	"""All-day event; DTEND is exclusive, hence the extra day. The leave's reason is never included."""
	start = getdate(leave.from_date)
	end = getdate(leave.to_date) + datetime.timedelta(days=1)
	stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
	lines = [
		"BEGIN:VCALENDAR",
		"VERSION:2.0",
		"PRODID:-//Gallehr//ERPNext Urlaubskalender//DE",
		"BEGIN:VEVENT",
		f"UID:{event_uid(leave_name)}",
		f"DTSTAMP:{stamp}",
		f"DTSTART;VALUE=DATE:{start:%Y%m%d}",
		f"DTEND;VALUE=DATE:{end:%Y%m%d}",
		f"SUMMARY:{escape_ics_text(event_title(leave))}",
		f"DESCRIPTION:ERPNext {leave_name}",
		"TRANSP:OPAQUE",
		"END:VEVENT",
		"END:VCALENDAR",
	]
	return ("\r\n".join(lines) + "\r\n").encode("utf-8")
