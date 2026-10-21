# Copyright (c) 2026, phamos.eu and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from gallehr import nextcloud_calendar_sync


class NextcloudCalendarSettings(Document):
	pass


@frappe.whitelist()
def test_connection():
	frappe.only_for("System Manager")
	return nextcloud_calendar_sync.test_connection()
