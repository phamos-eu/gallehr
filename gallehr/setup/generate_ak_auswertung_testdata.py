"""Erzeugt lokale Testdaten fuer die "AK Auswertung"-Seite (feature/AK_auswertung_v1).

Nicht in hooks.py eingebunden. Aufruf:
    bench --site gallehr-dev.localhost execute gallehr.setup.generate_ak_auswertung_testdata.run
    bench --site gallehr-dev.localhost execute gallehr.setup.generate_ak_auswertung_testdata.run --kwargs "{'cleanup': True}"

Wozu: v1 soll gegen "Haupt - G" gebaut werden (siehe ak-auswertung-feature
Notiz), aber das ist Live-Firmendaten. Damit lokal entwickelt/getestet
werden kann und das Ergebnis auf Live uebertraegt ("was hier funktioniert,
funktioniert dort"), bildet dieses Skript dieselbe STRUKTUR nach -- nicht
die exakten Zahlen: dieselben echten Aufwandskonten, aehnliche Verteilung
von Buchungsanzahl/Betrag, und je Konto dieselbe Abgleich-Abdeckung wie
live gemessen (skript_haupt_g_coverage_breakdown.py, korrigierte Version).
Kleinere Stueckzahl (Faktor SKALIERUNG) als live, gleiche Struktur.

Weg: echte Purchase Invoices + echte Payment Entries (ueber die
Standard-ERPNext-Funktion get_payment_entry, damit Payment Entry
Reference und alle GL Entries genauso entstehen wie live) gegen einen
dedizierten Test-Lieferanten. Fuer den Bankabgleich-Teil: eine
vereinfachte Verknuepfung -- eine Bank Transaction pro bezahlter Payment
Entry, direkt in Bank Transaction Payments verlinkt. Das bildet NICHT
das volle Bank-Reconciliation-Tool nach (Betragsabgleich, Clearance-
Datum), sondern nur genau das, was unsere Abfragen tatsaechlich pruefen:
"ist dieser Beleg mit einer Bank Transaction verknuepft?".

Alle erzeugten Dokumente tragen GENERATED_HISTORY in Name/Beschreibung
und lassen sich damit vollstaendig entfernen: run(cleanup=True)
"""

import random

import frappe
from frappe.utils import add_days, flt, nowdate

MARKER = "GENERATED_HISTORY"
COMPANY = "Gallehr Sustainable Risk Management GmbH"
COST_CENTER = "Haupt - G"
SUPPLIER = f"{MARKER} Testlieferant"
ITEM = f"{MARKER} Testleistung"

# (Konto, echte Buchungsanzahl live, echter Netto-Betrag live, Abgleich-Abdeckung live)
# Quelle: skript_haupt_g_coverage_breakdown.py (korrigiert), 2026-08-31 gegen Live gelaufen.
# Bewusst eine Auswahl mit Spannbreite: gross/klein, viele/wenige Buchungen, 1%-100% Abdeckung.
KONTEN_LIVE = [
	("5906 - Fremdleistungen 19% Vorsteuer - G", 105, 481_102.16, 0.13),
	("6495 - Wartungskosten f. Hard- und Software - G", 182, 220_998.58, 0.71),
	("6825 - Rechts- und Beratungskosten - G", 88, 162_984.80, 0.55),
	("6325 - Gas, Strom, Wasser - G", 148, 96_716.59, 0.97),
	("6663 - Reisekosten Arbeitnehmer Fahrtkosten - G", 404, 26_343.78, 0.61),
	("6643 - Aufmerksamkeiten - G", 458, 8_467.19, 0.17),
	("6330 - Reinigung - G", 84, 1_036.75, 0.01),
	("6310 - Miete (unbewegliche Wirtschaftsgüter) - G", 35, 38_822.90, 1.00),
	("6805 - Telefon - G", 242, 9_204.06, 0.52),
	("6640 - Bewirtungskosten - G", 262, 17_648.10, 0.51),
]
SKALIERUNG = 6  # Ziel: ~1/6 der Live-Stueckzahl, gleiche Struktur
TAGE_ZURUECK = 240  # Fiscal Year 2025 fehlt lokal (nur 2024 + 2026 vorhanden) -- innerhalb 2026 bleiben


def ensure_supplier():
	if not frappe.db.exists("Supplier", SUPPLIER):
		frappe.get_doc({
			"doctype": "Supplier", "supplier_name": SUPPLIER,
			"supplier_group": frappe.db.get_value("Supplier Group", {}, "name"),
			"supplier_type": "Company",
		}).insert(ignore_permissions=True, ignore_mandatory=True)


def ensure_item():
	if not frappe.db.exists("Item", ITEM):
		frappe.get_doc({
			"doctype": "Item", "item_code": ITEM, "item_name": ITEM,
			"item_group": frappe.db.get_value("Item Group", {}, "name"),
			"is_stock_item": 0, "stock_uom": "Nos",
		}).insert(ignore_permissions=True, ignore_mandatory=True)


def split_amount(total, n, rng):
	weights = [rng.uniform(0.4, 2.6) for _ in range(n)]
	s = sum(weights)
	out = [round(total * w / s, 2) for w in weights]
	out[0] = round(out[0] + (total - sum(out)), 2)
	return out


def make_purchase_invoice(account, amount, tag_date):
	doc = frappe.get_doc({
		"doctype": "Purchase Invoice",
		"supplier": SUPPLIER,
		"company": COMPANY,
		"posting_date": tag_date,
		"set_posting_time": 1,  # sonst wird posting_date beim Insert stillschweigend auf heute zurueckgesetzt
		"due_date": add_days(tag_date, 14),
		"cost_center": COST_CENTER,
		"remarks": MARKER,
		"items": [{
			"item_code": ITEM, "qty": 1, "rate": amount,
			"expense_account": account, "cost_center": COST_CENTER,
		}],
	})
	doc.insert(ignore_permissions=True)
	doc.submit()
	return doc.name


def make_payment_entry(purchase_invoice_name, tag_date):
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
	pe = get_payment_entry("Purchase Invoice", purchase_invoice_name)
	pe.reference_no = f"{MARKER}-{purchase_invoice_name}"
	pe.reference_date = tag_date
	pe.posting_date = tag_date
	pe.remarks = MARKER
	pe.insert(ignore_permissions=True)
	pe.submit()
	return pe.name, flt(pe.paid_amount)


def make_bank_transaction(tag_date, amount):
	doc = frappe.get_doc({
		"doctype": "Bank Transaction", "naming_series": "ACC-BTN-.YYYY.-",
		"date": tag_date, "deposit": 0, "withdrawal": amount,
		"currency": "EUR", "company": COMPANY, "description": f"Zahlung {MARKER}",
	})
	doc.flags.ignore_links = True
	doc.insert(ignore_permissions=True, ignore_mandatory=True)
	doc.submit()
	return doc.name


def link_bank_transaction(bt_name, payment_entry_name, amount):
	"""Vereinfachte Verknuepfung -- siehe Modul-Docstring: bildet nur die
	Existenz der Verknuepfung nach, nicht den vollen Allocation-Mechanismus
	des Bank Reconciliation Tools (der ein konfiguriertes Bank Account mit
	verknuepftem GL-Konto braucht, das dieses Testsetup nicht hat)."""
	child = frappe.get_doc({
		"doctype": "Bank Transaction Payments",
		"parent": bt_name, "parenttype": "Bank Transaction", "parentfield": "payment_entries",
		"payment_document": "Payment Entry", "payment_entry": payment_entry_name,
		"allocated_amount": amount,
	})
	child.insert(ignore_permissions=True, ignore_mandatory=True)


def existing_generated():
	return frappe.get_all("Purchase Invoice", filters={"remarks": MARKER}, pluck="name")


def run(cleanup=False, seed=7):
	if cleanup:
		for name in frappe.get_all("Bank Transaction", filters={"description": ["like", f"%{MARKER}%"]}, pluck="name"):
			doc = frappe.get_doc("Bank Transaction", name)
			if doc.docstatus == 1:
				doc.cancel()
			doc.delete()
		for name in frappe.get_all("Payment Entry", filters={"remarks": MARKER}, pluck="name"):
			doc = frappe.get_doc("Payment Entry", name)
			if doc.docstatus == 1:
				doc.cancel()
			doc.delete()
		pis = existing_generated()
		for name in pis:
			doc = frappe.get_doc("Purchase Invoice", name)
			if doc.docstatus == 1:
				doc.cancel()
			doc.delete()
		for dt, dn in [("Item", ITEM), ("Supplier", SUPPLIER)]:
			if frappe.db.exists(dt, dn):
				frappe.delete_doc(dt, dn, force=True, ignore_permissions=True)
		frappe.db.commit()
		print(f"entfernt: {len(pis)} Purchase Invoices + zugehoerige Payment Entries/Bank Transactions")
		return

	if existing_generated():
		print(f"Es existieren bereits generierte Testdaten. Erst aufraeumen:  run(cleanup=True)")
		return

	ensure_supplier()
	ensure_item()
	rng = random.Random(seed)
	pis_erzeugt = pes_erzeugt = bts_erzeugt = 0

	for account, live_anzahl, live_netto, abdeckung in KONTEN_LIVE:
		n = max(3, round(live_anzahl / SKALIERUNG))
		netto = live_netto / SKALIERUNG
		betraege = split_amount(netto, n, rng)
		n_abgeglichen = round(n * abdeckung)

		pi_liste = []
		for i, betrag in enumerate(betraege):
			tag = add_days(nowdate(), -rng.randint(1, TAGE_ZURUECK))  # innerhalb der aktiven Fiscal Year bleiben
			pi_liste.append(make_purchase_invoice(account, max(betrag, 1.0), tag))
			pis_erzeugt += 1

		for pi_name in rng.sample(pi_liste, n_abgeglichen):
			tag = frappe.db.get_value("Purchase Invoice", pi_name, "posting_date")
			pe_name, betrag = make_payment_entry(pi_name, add_days(tag, rng.randint(1, 10)))
			pes_erzeugt += 1
			bt_name = make_bank_transaction(add_days(tag, rng.randint(1, 10)), betrag)
			link_bank_transaction(bt_name, pe_name, betrag)
			bts_erzeugt += 1

		print(f"  {account}: {n} Purchase Invoices (Ziel-Netto={netto:,.2f} EUR), "
			  f"{n_abgeglichen} davon bezahlt+bankabgeglichen ({abdeckung:.0%} Ziel-Abdeckung)")

	frappe.db.commit()
	print(f"\nerzeugt: {pis_erzeugt} Purchase Invoices, {pes_erzeugt} Payment Entries, "
		  f"{bts_erzeugt} Bank Transactions (alle mit {MARKER} markiert)")
	print(f"Kostenstelle: {COST_CENTER} | Company: {COMPANY}")
	print("Zum Entfernen:  run(cleanup=True)")
