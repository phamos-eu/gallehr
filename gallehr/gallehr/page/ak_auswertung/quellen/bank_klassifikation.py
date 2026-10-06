"""Regeltabelle "lückenlos": jede Journal-Entry-Zeile einer mit einer Bank Transaction verknüpften Buchung
bekommt genau eine Kategorie. `kategorie()` ist eine reine Funktion (unit-testbar); `klassifiziere_je_zeilen()`
holt dazu die nötigen Joins (Account, Supplier.supplier_group) in gebündelten Abfragen.

Herkunft der Regeln: ~/Desktop/work/ricarda_feature/v2_bankbuchungen/ (Skripte E/F/H, 06.10.2026, Live-Daten).
Reihenfolge ist bewusst strikt -- die erste zutreffende Regel gewinnt.
"""

import frappe

EINGANGSRECHNUNG = "Eingangsrechnung"
UMBUCHUNG = "Umbuchung"
EINNAHME = "Einnahme"
GEGENBUCHUNG = "Gegenbuchung (BT zu BT)"
ZAHLUNG_OHNE_RECHNUNG = "Zahlung ohne Rechnung"
KOSTEN_OHNE_RECHNUNG = "Kosten ohne Rechnung"
PERSONALKOSTEN = "Personalkosten"
STEUER_DURCHLAUF = "Steuer-Durchlauf"
LIEFERANT_OHNE_RECHNUNG = "Lieferant/Kunde ohne Rechnung"
DURCHLAUF_INVESTITION = "Durchlauf/Investition"
OHNE_BELEG = "ohne Beleg"
UNKLASSIFIZIERT = "unklassifiziert"

# Vollstaendige Liste, in der Reihenfolge der Plan-Tabelle -- einzige Quelle fuer das Select-Feld ak_kategorie
# auf Bank Transaction (siehe gallehr/fixtures/custom_field.json) und fuer bank_zuordnung.py.
ALLE_KATEGORIEN = [EINGANGSRECHNUNG, UMBUCHUNG, EINNAHME, GEGENBUCHUNG, ZAHLUNG_OHNE_RECHNUNG, KOSTEN_OHNE_RECHNUNG,
	PERSONALKOSTEN, STEUER_DURCHLAUF, LIEFERANT_OHNE_RECHNUNG, DURCHLAUF_INVESTITION, OHNE_BELEG, UNKLASSIFIZIERT]

# Kategorien, die in v2 tatsaechlich eine Kostenzeile auf der Seite erzeugen (siehe bankbuchung.py)
KOSTEN_KATEGORIEN = {KOSTEN_OHNE_RECHNUNG, PERSONALKOSTEN}

PERSONAL_STICHWORTE = ["lohn", "gehalt", "sozialversich", "sozialen sicherheit", "lohnsteuer", "kirchensteuer",
	"solidarit", "berufsgenossen"]
STEUER_STICHWORTE = ["vorsteuer", "umsatzsteuer", "ust", "13b"]

# Lieferantengruppen, bei denen die Partei selbst die Kategorie bestimmt (Skript F/H, Live-Daten 06.10.2026):
# Mitarbeiter/Krankenkasse = Personalkosten; Behoerde = Finanzamt/Kommune, also Steuer-Durchlauf;
# Bank = zweite Bankbeziehung ohne eigenes Bank-Account-Dokument, also Umbuchung.
PERSONAL_LIEFERANTENGRUPPEN = {"Mitarbeiter", "Krankenkasse"}
STEUER_LIEFERANTENGRUPPEN = {"Behörde"}
UMBUCHUNG_LIEFERANTENGRUPPEN = {"Bank"}


def _enthaelt(text, stichworte):
	t = (text or "").lower()
	return any(s in t for s in stichworte)


def kategorie(zeile, bankkonten):
	"""Reine Funktion. `zeile` braucht: konto_voll, reference_type, root_type, account_type, account_number,
	account_name, party_type, supplier_group (None wenn nicht Supplier). `bankkonten` = set aller
	Bank-Account.account-Werte."""
	if zeile.get("reference_type") == "Purchase Invoice":
		return EINGANGSRECHNUNG
	if zeile.get("konto_voll") in bankkonten:
		return UMBUCHUNG
	if zeile.get("root_type") == "Expense":
		return KOSTEN_OHNE_RECHNUNG

	kontotext = "%s %s" % (zeile.get("account_number") or "", zeile.get("account_name") or "")
	if zeile.get("root_type") == "Liability" and _enthaelt(kontotext, PERSONAL_STICHWORTE):
		return PERSONALKOSTEN
	if _enthaelt(kontotext, STEUER_STICHWORTE) or zeile.get("account_type") == "Tax":
		return STEUER_DURCHLAUF

	if zeile.get("party_type") == "Supplier":
		gruppe = zeile.get("supplier_group")
		if gruppe in PERSONAL_LIEFERANTENGRUPPEN:
			return PERSONALKOSTEN
		if gruppe in STEUER_LIEFERANTENGRUPPEN:
			return STEUER_DURCHLAUF
		if gruppe in UMBUCHUNG_LIEFERANTENGRUPPEN:
			return UMBUCHUNG

	if zeile.get("root_type") == "Liability" and zeile.get("party_type"):
		return LIEFERANT_OHNE_RECHNUNG
	if zeile.get("root_type") == "Income":
		return EINNAHME
	if zeile.get("root_type") in ("Asset", "Equity"):
		return DURCHLAUF_INVESTITION
	return UNKLASSIFIZIERT


def bankkonten():
	return set(frappe.db.sql_list("SELECT DISTINCT account FROM `tabBank Account` WHERE account IS NOT NULL"))


def klassifiziere_je_zeilen(je_namen):
	"""Fuer eine Menge von Journal-Entry-Namen: alle Zeilen mit Account-Join + Kategorie. Eine Zeile je
	`Journal Entry Account`-Kindsatz (Schluessel: `zeile` = dessen `name`)."""
	if not je_namen:
		return []

	zeilen = frappe.db.sql(
		"""
		SELECT jea.name AS zeile, jea.parent AS je, jea.account AS konto_voll, jea.debit, jea.credit,
			jea.party_type, jea.party, jea.reference_type, jea.reference_name, jea.cost_center,
			ac.root_type, ac.account_type, ac.account_number, ac.account_name
		FROM `tabJournal Entry Account` jea
		JOIN `tabAccount` ac ON ac.name = jea.account
		WHERE jea.parent IN %(je)s
		ORDER BY jea.parent, jea.idx""",
		{"je": tuple(je_namen)},
		as_dict=True,
	)

	gruppen_je_supplier = {}
	supplier_namen = {z.party for z in zeilen if z.party_type == "Supplier" and z.party}
	if supplier_namen:
		for r in frappe.db.sql(
			"SELECT name, supplier_group FROM `tabSupplier` WHERE name IN %(n)s",
			{"n": tuple(supplier_namen)}, as_dict=True,
		):
			gruppen_je_supplier[r.name] = r.supplier_group

	bk = bankkonten()
	out = []
	for z in zeilen:
		z["supplier_group"] = gruppen_je_supplier.get(z["party"]) if z["party_type"] == "Supplier" else None
		# signiert (nicht abs!): bankbuchung.py braucht das Vorzeichen, um eine Gutschrift auf einem
		# Aufwandskonto als Erstattung (negativer Betrag) statt als normale Kosten zu behandeln.
		z["betrag"] = float(z["debit"] or 0) - float(z["credit"] or 0)
		z["kategorie"] = kategorie(z, bk)
		out.append(z)
	return out
