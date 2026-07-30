"""Ergaenzt die fehlenden Monate an Bankbewegungen in der Entwicklungsumgebung.

Nicht in hooks.py eingebunden. Aufruf:
    bench --site gallehr-dev.localhost execute gallehr.setup.generate_bank_history.run

Hintergrund: der Import aus dem Live-System war auf die 250 neuesten Buchungen
begrenzt und lieferte daher nur 22.05.-29.07. Das hatte zwei Folgen:

  1. Das Burnrate-Diagramm hatte nur zwei Punkte (Juli faellt als laufender
     Monat heraus) und war damit zwangslaeufig eine Gerade -- es konnte gar
     nicht schwanken.
  2. Der Mai begann am 22., seine Ausgaben wurden aber durch 31 Tage geteilt.
     Dadurch lag der Mai bei 1.065 EUR/Tag statt realistischer ~5.000 EUR/Tag
     und zog den Jahresdurchschnitt um rund 26 % nach unten -- die
     Umsatzluecken erschienen zu optimistisch.

Dieses Skript erzeugt Jan-Apr vollstaendig und fuellt den Mai von Tag 1-21 auf.
Juni und Juli bleiben unberuehrt (echte Daten). Die Monatssummen orientieren
sich an den echten Juni/Juli-Werten und an der Schwankungsbreite des
Live-Systems, damit die Kurve realistisch aussieht.

Zusaetzlich werden drei Umbuchungs-Paare zwischen den beiden Gesellschaften
erzeugt und als "Umbuchung" markiert -- damit ist der Ausschluss-Mechanismus
lokal ueberhaupt sichtbar (aus dem Live-Import kam keine markierte Buchung mit).

Alle erzeugten Buchungen tragen GENERATED_HISTORY in der Beschreibung und
lassen sich damit jederzeit wieder entfernen: run(cleanup=True)
"""

import random

import frappe
from frappe.desk.doctype.tag.tag import add_tag

MARKER = "GENERATED_HISTORY"
GSR = "Gallehr Sustainable Risk Management GmbH"
GSS = "Gallehr Sustainable Strategies GmbH"

# Zielwerte je Monat: (Ausgaben, Einnahmen, Tage im Monat, erster Tag)
# Ausgaben orientiert an der Live-Schwankungsbreite (siehe Modul-Docstring),
# Einnahmen bewusst volatiler -- so verhaelt sich das Geschaeft tatsaechlich.
ZIELE = [
	# Einnahmen so bemessen, dass Umsatz Ist rund 41 % von Umsatz Soll erreicht --
	# dasselbe Verhaeltnis wie im Live-System. Sonst zeigt das Dashboard einen
	# Ueberschuss, wo in Wirklichkeit eine Umsatzluecke besteht.
	(1, 163_267,  96_000, 31, 1),
	(2, 128_800,  75_000, 28, 1),
	(3, 201_500, 140_000, 31, 1),
	(4, 107_000,  51_000, 30, 1),
	(5, 158_133, 112_000, 31, 1),   # Mai nur Tag 1-21 auffuellen
]
MAI_MAX_TAG = 21


def existing_generated():
	return frappe.get_all("Bank Transaction",
		filters={"description": ["like", f"%{MARKER}%"]}, pluck="name")


def make(date, deposit, withdrawal, company, text):
	doc = frappe.get_doc({
		"doctype": "Bank Transaction",
		"naming_series": "ACC-BTN-.YYYY.-",
		"date": date,
		"deposit": deposit,
		"withdrawal": withdrawal,
		"currency": "EUR",
		"company": company,
		"description": f"{text} {MARKER}",
	})
	doc.flags.ignore_links = True
	doc.insert(ignore_permissions=True, ignore_mandatory=True)
	doc.submit()
	return doc.name


def split_amount(total, n, rng):
	"""Teilt einen Monatsbetrag auf n Buchungen mit realistischer Streuung auf."""
	weights = [rng.uniform(0.4, 2.6) for _ in range(n)]
	s = sum(weights)
	out = [round(total * w / s, 2) for w in weights]
	# Rundungsdifferenz auf die erste Buchung legen
	out[0] = round(out[0] + (total - sum(out)), 2)
	return out


def run(cleanup=False, seed=7):
	if cleanup:
		names = existing_generated()
		for n in names:
			doc = frappe.get_doc("Bank Transaction", n)
			if doc.docstatus == 1:
				doc.cancel()
			doc.delete()
		frappe.db.commit()
		print(f"entfernt: {len(names)} erzeugte Buchungen")
		return

	already = existing_generated()
	if already:
		print(f"Es existieren bereits {len(already)} erzeugte Buchungen.")
		print("Erst aufraeumen:  run(cleanup=True)")
		return

	rng = random.Random(seed)
	created = 0

	for monat, ausgaben, einnahmen, tage, ab_tag in ZIELE:
		max_tag = MAI_MAX_TAG if monat == 5 else tage

		# Ausgaben: viele kleine + einige groessere Posten, wie im echten Auszug
		n_aus = rng.randint(18, 30)
		for betrag in split_amount(ausgaben, n_aus, rng):
			tag = rng.randint(ab_tag, max_tag)
			firma = GSR if rng.random() < 0.9 else GSS
			created += 1 if make(f"2026-{monat:02d}-{tag:02d}", 0, betrag, firma, "Ausgabe") else 0

		# Einnahmen: weniger, dafuer groessere Betraege (Kundenzahlungen)
		n_ein = rng.randint(4, 9)
		for betrag in split_amount(einnahmen, n_ein, rng):
			tag = rng.randint(ab_tag, max_tag)
			firma = GSR if rng.random() < 0.85 else GSS
			created += 1 if make(f"2026-{monat:02d}-{tag:02d}", betrag, 0, firma, "Zahlungseingang") else 0

		print(f"  Monat {monat:02d}: {n_aus} Ausgaben ({ausgaben:,.0f}) + "
			f"{n_ein} Einnahmen ({einnahmen:,.0f})")

	# Umbuchungen: Abgang bei einer Gesellschaft, gleicher Betrag als Zugang bei
	# der anderen, beide markiert -- so wie ein echter Uebertrag aussieht.
	print("\n  Umbuchungen:")
	for monat, tag, betrag in [(2, 12, 25_000.0), (3, 20, 40_000.0), (4, 8, 15_000.0)]:
		datum = f"2026-{monat:02d}-{tag:02d}"
		ab = make(datum, 0, betrag, GSR, "Umbuchung an verbundene Gesellschaft")
		zu = make(datum, betrag, 0, GSS, "Umbuchung von verbundener Gesellschaft")
		add_tag("Umbuchung", "Bank Transaction", ab)
		add_tag("Umbuchung", "Bank Transaction", zu)
		created += 2
		print(f"    {datum}  {betrag:>10,.2f} EUR  {ab} -> {zu}  (beide markiert)")

	# creation auf das Buchungsdatum setzen. Die Liquiditaets-Formel des Reports
	# zaehlt Bewegungen "nach dem Snapshot" ueber das Feld `creation`, nicht ueber
	# `date`. Im Live-System laufen die Bankimporte taeglich, dort ist creation
	# also praktisch gleich date. Hier entstehen alle Buchungen heute -- ohne diese
	# Korrektur wuerden auch Januar-Buchungen als "seit dem Snapshot" gelten und
	# die Liquiditaet verfaelschen.
	frappe.db.sql("""UPDATE `tabBank Transaction`
		SET creation = TIMESTAMP(date, '09:00:00')
		WHERE description LIKE %(marker)s""", {"marker": f"%{MARKER}%"})

	frappe.db.commit()
	print(f"\nerzeugt: {created} Buchungen (alle mit {MARKER} gekennzeichnet)")
	print("creation an das Buchungsdatum angeglichen (siehe Kommentar im Code)")
