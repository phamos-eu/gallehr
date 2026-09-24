"""Backend der Seite "AK Auswertung" (feature/AK_auswertung_v1): Kosten aus Eingangsrechnungen.

Aufbau:  quellen/  liefert Kostenzeilen (v1: Eingangsrechnungen; v2 weitere Quellen ohne Umbau)
         auswertung.py  filtert/gruppiert/sortiert diese Zeilen (eine Quelle der Wahrheit fuer Seite und Excel)
         dieses Modul  = duenne, whitelisted API fuer die Seite
Hintergrund/Entscheidungen: ~/Desktop/work/ricarda_feature/v1_eingangsrechnungen/
"""

import frappe
from frappe import _

from gallehr.gallehr.page.ak_auswertung import auswertung, quellen
from gallehr.gallehr.page.ak_auswertung.quellen.eingangsrechnung import NICHT_ZUGEORDNET


def _check_permission():
	if not frappe.has_permission("Purchase Invoice", "read"):
		frappe.throw(_("Keine Berechtigung fuer Eingangsrechnungen"), frappe.PermissionError)


def _zeilen(f):
	return quellen.alle_zeilen(f["von"], f["bis"], f["unternehmen"] or None)


@frappe.whitelist()
def get_optionen():
	_check_permission()
	unternehmen = frappe.db.sql_list("SELECT DISTINCT company FROM `tabPurchase Invoice` WHERE docstatus = 1 ORDER BY company")
	kostenstellen = frappe.get_all("Cost Center", filters={"is_group": 0, "disabled": 0}, pluck="name", order_by="name")
	return {"unternehmen": unternehmen, "kostenstellen": kostenstellen + [NICHT_ZUGEORDNET], "gruppen": auswertung.FAMILIEN_REIHE}


@frappe.whitelist()
def get_data(filters=None, limit=25, offset=0):
	_check_permission()
	f = auswertung.normalisiere(filters)
	return auswertung.bericht(_zeilen(f), f, limit=frappe.utils.cint(limit) or 25, offset=frappe.utils.cint(offset))


@frappe.whitelist()
def export_excel(filters=None):
	_check_permission()
	from frappe.utils.xlsxutils import make_xlsx

	f = auswertung.normalisiere(filters)
	zeilen = auswertung.alle_gefiltert_sortiert(_zeilen(f), f)
	kopf = ["Datum", "Beleg", "Lieferant", "Konto", "Kontobezeichnung", "Item", "Item Group", "Unternehmen", "Kostenstelle",
		"Kostenstelle aus", "Netto EUR", "Brutto EUR", "Bank-Status", "Bank Transaction", "Tags", "Rueckgabe"]
	rows = [kopf]
	for z in zeilen:
		rows.append([z["datum"], z["beleg"], z["lieferant"], z["konto_nr"], z["konto_name"], z["item"], z["item_group"],
			z["unternehmen"], z["kostenstelle"], z["kostenstelle_quelle"], z["netto"], z["brutto"],
			"Bank bestaetigt" if z["bank_status"] == "bank" else "Ohne Bank-Bestaetigung", z["bt"], ", ".join(z["tags"]),
			"ja" if z["rueckgabe"] else ""])
	rows.append(["", "Summe", "", "", "", "", "", "", "", "", sum(z["netto"] for z in zeilen), sum(z["brutto"] for z in zeilen)])
	xlsx = make_xlsx(rows, "AK Auswertung")
	frappe.response["filename"] = "AK_Auswertung_Eingangsrechnungen_%s_%s.xlsx" % (f["von"], f["bis"])
	frappe.response["filecontent"] = xlsx.getvalue()
	frappe.response["type"] = "binary"
