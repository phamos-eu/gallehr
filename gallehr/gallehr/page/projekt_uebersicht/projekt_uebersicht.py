"""Backend fuer das Aufklappen der Zeilen auf der "Projekt Uebersicht"-Seite.

Die Zahlen der Seite kommen aus dem Script-Report "Projekt Übersicht". Hier
wird dieselbe Logik (Zeitraum, Zombie-Tag, Status/Unternehmen, Kennzahl)
nochmal je Zeile heruntergebrochen, damit die Unterzeilen sich exakt auf die
Zahl der aufgeklappten Zeile aufsummieren:

  - Projekt -> Sales Orders (je nach Kennzahl: Auftragswert der Positionen mit
    Liefertermin im Zeitraum, bzw. ueber die Rechnungspositionen fakturierter
    Betrag je Sales Order)
  - PM      -> Projekte dieses PM (jedes Projekt klappt dann selbst zu
    seinen Sales Orders auf)
"""

import frappe
from frappe import _
from frappe.utils import flt

ABGESCHLOSSEN_STATUS = ("Completed", "Cancelled")

PM_KEY = "JSON_UNQUOTE(JSON_EXTRACT(p.`_assign`, '$[0]'))"


def _check_permission():
	if not frappe.has_permission("Sales Order", "read"):
		frappe.throw(_("Keine Berechtigung fuer Sales Orders"), frappe.PermissionError)


@frappe.whitelist()
def get_auftraege(scope, key, von, bis, kennzahl="Auftragswert", status="Offen",
		unternehmen="", projektauswahl="Projekt-Laufzeit"):
	"""scope 'projekt': key = Project.name -> Sales Orders.
	scope 'pm': key = User.name des PM ('-' = kein PM zugewiesen) -> Projekte."""
	_check_permission()
	if kennzahl not in ("Auftragswert", "Fakturiert"):
		frappe.throw(_("Unbekannte Kennzahl"))

	if scope == "projekt":
		rows = _auftraege_je_projekt(key, von, bis, kennzahl)
	elif scope == "pm":
		rows = _projekte_je_pm(key, von, bis, kennzahl, status, unternehmen, projektauswahl)
	else:
		frappe.throw(_("Unbekannter Bereich"))

	gesamt = sum(r["umsatz"] for r in rows)
	for r in rows:
		r["anteil"] = (r["umsatz"] / gesamt * 100.0) if gesamt else 0.0
	rows.sort(key=lambda r: r["umsatz"], reverse=True)
	return {"scope": scope, "gesamt": gesamt, "rows": rows}


def _auftraege_je_projekt(projekt, von, bis, kennzahl):
	params = {"projekt": projekt, "von": von, "bis": bis}

	if kennzahl == "Auftragswert":
		raw = frappe.db.sql(
			"SELECT so.name AS name, so.transaction_date AS datum, "
			"SUM(soi.base_net_amount) AS umsatz, COUNT(*) AS positionen "
			"FROM `tabSales Order Item` soi "
			"JOIN `tabSales Order` so ON so.name = soi.parent "
			"WHERE so.docstatus = 1 AND so.project = %(projekt)s "
			"AND COALESCE(soi.delivery_date, so.delivery_date, so.transaction_date) BETWEEN %(von)s AND %(bis)s "
			"AND so.name NOT IN ("
			"  SELECT document_name FROM `tabTag Link`"
			"  WHERE document_type = 'Sales Order' AND tag = 'Zombie'"
			") GROUP BY so.name, so.transaction_date",
			params, as_dict=True,
		)
		return [{
			"name": r.name, "datum": str(r.datum or ""), "umsatz": flt(r.umsatz),
			"positionen": r.positionen,
		} for r in raw]

	# Fakturiert: der Report summiert Sales Invoice.net_total je Rechnung. Die
	# Zuordnung zu Sales Orders laeuft ueber die Rechnungspositionen
	# (sales_order); was keinem Auftrag zugeordnet ist (bzw. Waehrungs-/
	# Rundungsdifferenz zu net_total), landet in einer eigenen Zeile, damit die
	# Summe exakt zur Projektzeile passt.
	zombie = (
		" AND si.name NOT IN (SELECT document_name FROM `tabTag Link`"
		" WHERE document_type = 'Sales Invoice' AND tag = 'Zombie')"
	)
	gesamt = flt(frappe.db.sql(
		"SELECT SUM(si.net_total) FROM `tabSales Invoice` si "
		"WHERE si.docstatus = 1 AND si.project = %(projekt)s "
		"AND si.posting_date BETWEEN %(von)s AND %(bis)s" + zombie,
		params,
	)[0][0])
	raw = frappe.db.sql(
		"SELECT sii.sales_order AS name, so.transaction_date AS datum, "
		"SUM(sii.base_net_amount) AS umsatz, COUNT(*) AS positionen "
		"FROM `tabSales Invoice Item` sii "
		"JOIN `tabSales Invoice` si ON si.name = sii.parent "
		"LEFT JOIN `tabSales Order` so ON so.name = sii.sales_order "
		"WHERE si.docstatus = 1 AND si.project = %(projekt)s "
		"AND si.posting_date BETWEEN %(von)s AND %(bis)s" + zombie +
		" AND IFNULL(sii.sales_order, '') != '' "
		"GROUP BY sii.sales_order, so.transaction_date",
		params, as_dict=True,
	)
	rows = [{
		"name": r.name, "datum": str(r.datum or ""), "umsatz": flt(r.umsatz),
		"positionen": r.positionen,
	} for r in raw]
	rest = gesamt - sum(r["umsatz"] for r in rows)
	if abs(rest) >= 0.005:
		rows.append({"name": "", "datum": "", "umsatz": rest, "positionen": 0, "ohne_auftrag": 1})
	return rows


def _projekte_je_pm(pm, von, bis, kennzahl, status, unternehmen, projektauswahl):
	status_clause = ""
	if status == "Abgeschlossen":
		status_clause = " AND p.status IN %(abgeschlossen)s"
	elif status == "Offen":
		status_clause = " AND (p.status NOT IN %(abgeschlossen)s OR p.status IS NULL)"

	unternehmen_clause = ""
	if unternehmen and unternehmen != "Alle":
		unternehmen_clause = " AND p.company = %(unternehmen)s"

	if pm in ("", "-"):
		pm_clause = " AND " + PM_KEY + " IS NULL"
	else:
		pm_clause = " AND " + PM_KEY + " = %(pm)s"

	params = {
		"von": von, "bis": bis, "pm": pm, "unternehmen": unternehmen,
		"abgeschlossen": ABGESCHLOSSEN_STATUS,
	}
	common = status_clause + unternehmen_clause + pm_clause

	if kennzahl == "Auftragswert":
		raw = frappe.db.sql(
			"SELECT p.name AS key_, IFNULL(p.project_name, p.name) AS label, "
			"SUM(soi.base_net_amount) AS umsatz "
			"FROM `tabSales Order Item` soi "
			"JOIN `tabSales Order` so ON so.name = soi.parent "
			"JOIN `tabProject` p ON p.name = so.project "
			"WHERE so.docstatus = 1 "
			"AND COALESCE(soi.delivery_date, so.delivery_date, so.transaction_date) BETWEEN %(von)s AND %(bis)s "
			"AND so.name NOT IN ("
			"  SELECT document_name FROM `tabTag Link`"
			"  WHERE document_type = 'Sales Order' AND tag = 'Zombie'"
			") " + common + " GROUP BY p.name, p.project_name",
			params, as_dict=True,
		)
	else:
		raw = frappe.db.sql(
			"SELECT p.name AS key_, IFNULL(p.project_name, p.name) AS label, "
			"SUM(b.net_total) AS umsatz "
			"FROM `tabSales Invoice` b "
			"JOIN `tabProject` p ON p.name = b.project "
			"WHERE b.docstatus = 1 AND b.posting_date BETWEEN %(von)s AND %(bis)s "
			"AND b.name NOT IN ("
			"  SELECT document_name FROM `tabTag Link`"
			"  WHERE document_type = 'Sales Invoice' AND tag = 'Zombie'"
			") " + common + " GROUP BY p.name, p.project_name",
			params, as_dict=True,
		)
	rows = [{"key": r.key_, "label": r.label, "umsatz": flt(r.umsatz)} for r in raw]

	# Projekt-Laufzeit: wie im Report auch Projekte ohne Beleg im Zeitraum
	# (Betrag 0), sofern Start oder Ende in den Zeitraum faellt.
	if projektauswahl == "Projekt-Laufzeit":
		vorhanden = set(r["key"] for r in rows)
		zusatz = frappe.db.sql(
			"SELECT p.name AS key_, IFNULL(p.project_name, p.name) AS label "
			"FROM `tabProject` p "
			"WHERE (p.expected_start_date BETWEEN %(von)s AND %(bis)s "
			"    OR p.expected_end_date BETWEEN %(von)s AND %(bis)s)" + common,
			params, as_dict=True,
		)
		for z in zusatz:
			if z.key_ not in vorhanden:
				rows.append({"key": z.key_, "label": z.label, "umsatz": 0.0})
	return rows
