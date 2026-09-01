# Copyright (c) 2026, phamos.eu and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import cint, now_datetime
from frappe.utils.background_jobs import is_job_enqueued

from gallehr import christmas_list

JOB_ID = "gallehr-christmas-list-resolution"
REALTIME_EVENT = "gallehr_christmas_list_done"


class GallehrSettings(Document):
	pass


@frappe.whitelist()
def run_christmas_list_resolution():
	"""Queue the Christmas list address resolution."""

	if is_job_enqueued(JOB_ID):
		frappe.throw(frappe._("The address resolution is already running. Please wait for it to finish."))

	settings = frappe.get_single("Gallehr Settings")

	frappe.enqueue(
		execute_christmas_list_resolution,
		queue="long",
		timeout=3600,
		job_id=JOB_ID,
		dry_run=settings.christmas_dry_run,
		only_active=settings.christmas_only_active_addresses,
		user=frappe.session.user,
	)

	return {"dry_run": cint(settings.christmas_dry_run)}


def execute_christmas_list_resolution(dry_run=1, only_active=0, user=None):
	try:
		result = christmas_list.run(dry_run=dry_run, only_active=only_active)
		report = christmas_list.format_report(result)
	except Exception:
		report = frappe.get_traceback()
		frappe.db.rollback()
		frappe.log_error(title="Christmas list address resolution failed")

	settings = frappe.get_single("Gallehr Settings")
	settings.christmas_last_run = now_datetime()
	settings.christmas_last_result = report
	settings.save(ignore_permissions=True)
	frappe.db.commit()

	if user:
		frappe.publish_realtime(REALTIME_EVENT, {"report": report}, user=user)
