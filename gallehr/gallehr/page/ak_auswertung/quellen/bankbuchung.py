"""Quelle "Bankbuchung" (v2): Kosten, die nur als Journal-Entry-Zeile einer mit einer Bank Transaction
verknuepften Buchung existieren -- Versicherung, Gebuehren, Personalkosten u.ae. ohne Eingangsrechnung.
Gleiche Kostenzeilen-Form wie eingangsrechnung.zeilen() (siehe dort), damit auswertung.py unveraendert bleibt.

Nur Zeilen der Kategorien aus bank_klassifikation.KOSTEN_KATEGORIEN erzeugen hier eine Kostenzeile; alle anderen
Kategorien (Umbuchung, Einnahme, Steuer-Durchlauf, Lieferant/Kunde ohne Rechnung, ...) sind bewusst keine Kosten
und tauchen deshalb hier nicht auf -- sie werden trotzdem lueckenlos auf der Bank Transaction selbst sichtbar
(siehe bank_zuordnung.py).

Aufteilung eines Journal Entry auf mehrere Bank Transactions (oder umgekehrt): jede "Gegenzeile" (nicht das
Bankkonto der jeweiligen BT) wird anteilig nach ihrem Gewicht (abs(debit-credit) relativ zur Summe aller
Gegenzeilen des Belegs) auf die `allocated_amount` jeder BT-Verknuepfung verteilt -- identisch zur Methode aus
Skript E (~/Desktop/work/ricarda_feature/v2_bankbuchungen/skripte/), dort mit 0 Abweichungen gegen die
BT-Bewegung verifiziert (lokal und live).

Datum = Buchungsdatum des Journal Entry (Entscheidung 06.10.2026), nicht das Datum der Bank Transaction.
"""

import frappe
from frappe.utils import flt

from gallehr.gallehr.page.ak_auswertung.quellen import bank_klassifikation
from gallehr.gallehr.page.ak_auswertung.quellen.eingangsrechnung import NICHT_ZUGEORDNET

QUELLE = "Bankbuchung"


def zeilen(von, bis, unternehmen=None):
	firma = " AND je.company = %(firma)s" if unternehmen else ""
	je_namen = frappe.db.sql_list(
		f"""
		SELECT je.name FROM `tabJournal Entry` je
		WHERE je.docstatus = 1 AND je.posting_date BETWEEN %(von)s AND %(bis)s{firma}
		AND EXISTS (
			SELECT 1 FROM `tabBank Transaction Payments` btp
			JOIN `tabBank Transaction` bt ON bt.name = btp.parent AND bt.docstatus = 1
			WHERE btp.payment_document = 'Journal Entry' AND btp.payment_entry = je.name)""",
		{"von": von, "bis": bis, "firma": unternehmen},
	)
	if not je_namen:
		return []

	klassifiziert = bank_klassifikation.klassifiziere_je_zeilen(je_namen)
	if not any(z["kategorie"] in bank_klassifikation.KOSTEN_KATEGORIEN for z in klassifiziert):
		return []

	je_info = {
		r.name: r for r in frappe.db.sql(
			"SELECT name, posting_date, company FROM `tabJournal Entry` WHERE name IN %(n)s",
			{"n": tuple(je_namen)}, as_dict=True,
		)
	}
	links = frappe.db.sql(
		"""
		SELECT btp.payment_entry AS je, btp.parent AS bt, btp.allocated_amount AS allocated,
			ba.account AS bankkonto, bt.bank_party_name AS bank_party_name
		FROM `tabBank Transaction Payments` btp
		JOIN `tabBank Transaction` bt ON bt.name = btp.parent AND bt.docstatus = 1
		LEFT JOIN `tabBank Account` ba ON ba.name = bt.bank_account
		WHERE btp.payment_document = 'Journal Entry' AND btp.payment_entry IN %(n)s""",
		{"n": tuple(je_namen)}, as_dict=True,
	)
	links_je = {}
	for link in links:
		links_je.setdefault(link.je, []).append(link)

	zeilen_je = {}
	for z in klassifiziert:
		zeilen_je.setdefault(z["je"], []).append(z)

	parteien = _partei_namen(klassifiziert)

	out = []
	for je, link_liste in links_je.items():
		info = je_info.get(je)
		if not info:
			continue
		bankkonten_je = {link.bankkonto for link in link_liste if link.bankkonto}
		gegenzeilen = [z for z in zeilen_je.get(je, []) if z["konto_voll"] not in bankkonten_je]
		gesamt_gewicht = sum(abs(z["betrag"]) for z in gegenzeilen)
		if gesamt_gewicht <= 0:
			continue
		for link in link_liste:
			for z in gegenzeilen:
				if z["kategorie"] not in bank_klassifikation.KOSTEN_KATEGORIEN:
					continue
				anteil = flt(link.allocated) * (z["betrag"] / gesamt_gewicht)
				if anteil == 0:
					continue
				lieferant, lieferant_id = parteien.get(z["zeile"], ("", ""))
				if not lieferant and link.bank_party_name:
					lieferant = link.bank_party_name
				out.append({
					"quelle": QUELLE, "beleg_typ": "Journal Entry", "beleg": je,
					"zeile": "%s-%s" % (z["zeile"], link.bt),
					"datum": str(info.posting_date), "unternehmen": info.company,
					"kostenstelle": z.get("cost_center") or NICHT_ZUGEORDNET,
					"kostenstelle_quelle": "Zeile" if z.get("cost_center") else "-",
					"konto_nr": z["account_number"] or "", "konto_name": z["account_name"] or "",
					"item": "", "item_group": "",
					"lieferant": lieferant, "lieferant_id": lieferant_id,
					"netto": flt(anteil, 2), "brutto": flt(anteil, 2),
					"bank_status": "bank", "bt": link.bt, "tags": [],
					"konzern": False, "rueckgabe": anteil < 0,
				})
	return out


def _partei_namen(zeilen):
	"""Zeile -> (Name, ID) fuer Supplier/Employee; bei anderen Partei-Arten oder ohne Partei bleibt die Zeile
	leer und bankbuchung.zeilen() faellt auf den freien Bank-Gegenparteinamen der BT zurueck."""
	out = {}
	supplier_ids = {z["party"] for z in zeilen if z["party_type"] == "Supplier" and z["party"]}
	employee_ids = {z["party"] for z in zeilen if z["party_type"] == "Employee" and z["party"]}
	supplier_namen, employee_namen = {}, {}
	if supplier_ids:
		for r in frappe.db.sql(
			"SELECT name, supplier_name FROM `tabSupplier` WHERE name IN %(n)s",
			{"n": tuple(supplier_ids)}, as_dict=True,
		):
			supplier_namen[r.name] = r.supplier_name
	if employee_ids:
		for r in frappe.db.sql(
			"SELECT name, employee_name FROM `tabEmployee` WHERE name IN %(n)s",
			{"n": tuple(employee_ids)}, as_dict=True,
		):
			employee_namen[r.name] = r.employee_name
	for z in zeilen:
		if z["party_type"] == "Supplier" and z["party"]:
			out[z["zeile"]] = (supplier_namen.get(z["party"], z["party"]), z["party"])
		elif z["party_type"] == "Employee" and z["party"]:
			out[z["zeile"]] = (employee_namen.get(z["party"], z["party"]), z["party"])
	return out
