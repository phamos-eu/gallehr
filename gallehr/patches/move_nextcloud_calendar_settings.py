import frappe

OLD = "Nextcloud Calendar Settings"
NEW = "Nextcloud Settings"


def execute():
	"""The Single was renamed; its saved values and encrypted app password move to the new name.

	Runs before migrate removes the orphaned old DocType, which would otherwise delete those values.
	"""
	if not frappe.db.sql("select 1 from tabSingles where doctype=%s limit 1", OLD):
		return
	frappe.db.sql("delete from tabSingles where doctype=%s", NEW)
	frappe.db.sql("update tabSingles set doctype=%s where doctype=%s", (NEW, OLD))
	frappe.db.sql("update tabSingles set value=%s where doctype=%s and field='name'", (NEW, NEW))
	frappe.db.sql("update `__Auth` set doctype=%s, name=%s where doctype=%s and name=%s", (NEW, NEW, OLD, OLD))
	# Defaults of new fields are not applied to an already saved Single.
	frappe.db.set_single_value(NEW, "folder_root", "ERPNext/Temp-Projektverzeichnisse")
	frappe.clear_cache(doctype=NEW)
