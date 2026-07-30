"""Dynamische Konsistenzsimulation des Finanz-Dashboard-Modells.

Nicht in hooks.py eingebunden. Aufruf:
    bench --site gallehr-dev.localhost execute gallehr.setup.model_simulation.run

Zweck: nicht nur pruefen, dass das Modell im Ruhezustand stimmt, sondern dass es
sich *unter Veraenderung* korrekt verhaelt. Fuer jede Veraenderung wird vorher
analytisch vorhergesagt, welche Kennzahl sich in welche Richtung und um welchen
Betrag bewegen muss, und danach gegen den tatsaechlichen Report verglichen.

Aufbau:
  TEIL A  Einzelaenderungen mit exakter Betragsvorhersage
  TEIL B  Umbuchung: Markieren muss die Buchung vollstaendig herausrechnen
  TEIL C  Projektion bis Jahresende (Aug-Dez) -- veraendert die Anzahl der
          Monate mit Daten und damit die Mittelwertbildung
Jede Simulation raeumt hinter sich auf und prueft die Rueckkehr zum Ausgangswert.
"""

import frappe
from frappe.desk.doctype.tag.tag import add_tag
from frappe.desk.query_report import run as run_report

MWST = 1.19
TAGE_PRO_MONAT = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30,
                  7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}

KEYS = [
	"Umsatz Ist (Einnahmen YTD Netto)",
	"Umsatz Soll (Brutto/Jahr)",
	"Outstanding bestehende Auftraege",
	"Liegende Angebote",
	"Reale Umsatzluecke (Ist+Out-Soll)",
	"Vorraussichtliche Umsatzluecke (Absehbar-Soll)",
	"Liquiditaet aktuell (Brutto)",
	"Burnrate/Monat (Brutto)",
]

COMPANY = "Gallehr Sustainable Risk Management GmbH"


def snap(filters=None):
	f = {"jahr": "2026"}
	f.update(filters or {})
	rows = run_report("Finanz Dashboard", filters=f)["result"]
	out = {}
	for k in KEYS:
		out[k] = next((r["prognose_eur"] for r in rows if r["monat"] == k), 0.0)
	bt = next((r["prognose_eur"] for r in rows if r["monat"].startswith("Burnrate/Tag verwendet")), 0.0)
	out["Burnrate/Tag verwendet"] = bt
	tage = next((r["prognose_zahl"] for r in rows if r["monat"] == "Tage ohne Zahlungseingang"), 0.0)
	out["Tage ohne Zahlungseingang"] = tage
	return out


def bank_tx(date, deposit=0.0, withdrawal=0.0):
	doc = frappe.get_doc({
		"doctype": "Bank Transaction",
		"naming_series": "ACC-BTN-.YYYY.-",
		"date": date,
		"deposit": deposit,
		"withdrawal": withdrawal,
		"currency": "EUR",
		"company": COMPANY,
		"description": "SIMULATION",
	})
	doc.flags.ignore_links = True
	doc.insert(ignore_permissions=True, ignore_mandatory=True)
	doc.submit()
	return doc.name


def drop(name):
	doc = frappe.get_doc("Bank Transaction", name)
	doc.cancel()
	doc.delete()


def months_with_data():
	rows = frappe.db.sql(
		'SELECT MONTH(date) m FROM `tabBank Transaction`'
		' WHERE docstatus = 1 AND YEAR(date) = 2026 AND status != "Cancelled"'
		' AND withdrawal > 0'
		' AND name NOT IN (SELECT document_name FROM `tabTag Link`'
		'   WHERE document_type = "Bank Transaction" AND tag = "Umbuchung")'
		' GROUP BY MONTH(date)', as_dict=True)
	return [r["m"] for r in rows]


def report(label, before, after, expect):
	"""expect: {key: (richtung, betrag_oder_None)} -- richtung in '+','-','0'."""
	print(f"\n--- {label} ---")
	ok = True
	for key, (direction, amount) in expect.items():
		b, a = before[key], after[key]
		delta = a - b
		if direction == "0":
			good = abs(delta) < 0.01
			exp_txt = "unveraendert"
		else:
			sign_ok = (delta > 0) if direction == "+" else (delta < 0)
			if amount is None:
				good = sign_ok and abs(delta) >= 0.01
				exp_txt = f"{direction} (Richtung)"
			else:
				good = sign_ok and abs(abs(delta) - abs(amount)) < 0.75
				exp_txt = f"{direction}{abs(amount):,.2f}"
		if not good:
			ok = False
		print(f"  {key:47s} {delta:>+13,.2f}  erwartet {exp_txt:>18s}  {'OK' if good else 'FEHLER'}")
	print(f"  => {'PASS' if ok else 'FAIL'}")
	return ok


def run():
	results = []
	base = snap()
	print("AUSGANGSLAGE")
	for k, v in base.items():
		print(f"  {k:47s} {v:>14,.2f}")
	mwd = months_with_data()
	print(f"\n  Monate mit Ausgaben-Daten: {mwd} (n={len(mwd)})")

	# ---------------- TEIL A: Einzelaenderungen, exakte Vorhersage ----------------
	print("\n" + "=" * 78)
	print("TEIL A  Einzelaenderungen mit exakter Betragsvorhersage")
	print("=" * 78)

	# A1: Einnahme im Juli (Monat hat bereits Daten -> n bleibt gleich)
	X = 11900.0
	tx = bank_tx("2026-07-15", deposit=X)
	after = snap()
	# Einnahme wirkt auf Umsatz Ist (netto) und Liquiditaet (brutto).
	# Ausgaben unberuehrt -> Burnrate und Umsatz Soll unveraendert.
	results.append(report(
		f"A1  Einnahme +{X:,.2f} brutto am 15.07. (Monat mit Daten)", base, after, {
			"Umsatz Ist (Einnahmen YTD Netto)": ("+", X / MWST),
			"Liquiditaet aktuell (Brutto)": ("+", X),
			"Umsatz Soll (Brutto/Jahr)": ("0", None),
			"Burnrate/Tag verwendet": ("0", None),
			"Burnrate/Monat (Brutto)": ("0", None),
			"Outstanding bestehende Auftraege": ("0", None),
			"Reale Umsatzluecke (Ist+Out-Soll)": ("+", X / MWST),
			"Vorraussichtliche Umsatzluecke (Absehbar-Soll)": ("+", X / MWST),
		}))
	drop(tx)
	results.append(report("A1  Rueckkehr nach Loeschen", base, snap(),
		{k: ("0", None) for k in KEYS}))

	# A2: Ausgabe im Juli -- exakte Vorhersage ueber die Mittelwertbildung
	Y = 3100.0
	n = len(mwd)
	d_tag = Y / TAGE_PRO_MONAT[7] / n          # avg Ausgaben/Tag steigt
	d_soll = d_tag * 365                        # Umsatz Soll = Tag * 365
	d_monat = Y / n                             # Excel J5: Summe/n
	tx = bank_tx("2026-07-15", withdrawal=Y)
	after = snap()
	results.append(report(
		f"A2  Ausgabe +{Y:,.2f} brutto am 15.07. (n={n} Monate)", base, after, {
			"Burnrate/Tag verwendet": ("+", d_tag),
			"Burnrate/Monat (Brutto)": ("+", d_monat),
			"Umsatz Soll (Brutto/Jahr)": ("+", d_soll),
			"Umsatz Ist (Einnahmen YTD Netto)": ("0", None),
			"Liquiditaet aktuell (Brutto)": ("-", Y),
			# hoehere Soll-Latte -> Luecke wird schlechter (negativer)
			"Reale Umsatzluecke (Ist+Out-Soll)": ("-", d_soll),
			"Vorraussichtliche Umsatzluecke (Absehbar-Soll)": ("-", d_soll),
			"Tage ohne Zahlungseingang": ("-", None),
		}))
	drop(tx)
	results.append(report("A2  Rueckkehr nach Loeschen", base, snap(),
		{k: ("0", None) for k in KEYS}))

	# ---------------- TEIL B: Umbuchung ----------------
	print("\n" + "=" * 78)
	print("TEIL B  Umbuchung -- Markieren muss die Buchung vollstaendig herausrechnen")
	print("=" * 78)

	Z = 5950.0
	tx = bank_tx("2026-07-16", deposit=Z)
	with_tx = snap()
	results.append(report(
		f"B1  Einnahme +{Z:,.2f} angelegt (noch nicht markiert)", base, with_tx, {
			"Umsatz Ist (Einnahmen YTD Netto)": ("+", Z / MWST),
			"Liquiditaet aktuell (Brutto)": ("+", Z),
		}))

	add_tag("Umbuchung", "Bank Transaction", tx)
	frappe.db.commit()
	tagged = snap()
	# Nach dem Markieren muss der Zustand wieder exakt der Ausgangslage entsprechen:
	# die Buchung existiert weiter, wird aber von allen Aggregaten ausgeschlossen.
	results.append(report(
		"B2  als 'Umbuchung' markiert -> muss wie Ausgangslage sein", base, tagged, {
			"Umsatz Ist (Einnahmen YTD Netto)": ("0", None),
			"Liquiditaet aktuell (Brutto)": ("0", None),
			"Reale Umsatzluecke (Ist+Out-Soll)": ("0", None),
			"Vorraussichtliche Umsatzluecke (Absehbar-Soll)": ("0", None),
			"Burnrate/Monat (Brutto)": ("0", None),
		}))
	drop(tx)
	frappe.db.commit()

	# ---------------- TEIL C: Projektion bis Jahresende ----------------
	print("\n" + "=" * 78)
	print("TEIL C  Projektion Aug-Dez -- veraendert die Anzahl Monate (Mittelwertbildung)")
	print("=" * 78)

	mon_ein = 100000.0
	mon_aus = 90000.0
	created = []
	for m in [8, 9, 10, 11, 12]:
		created.append(bank_tx(f"2026-{m:02d}-15", deposit=mon_ein))
		created.append(bank_tx(f"2026-{m:02d}-20", withdrawal=mon_aus))

	after = snap()
	n_new = len(months_with_data())
	# Analytische Vorhersage des neuen Tagesmittels: Summe der Monats-Tagessaetze / n
	sums = frappe.db.sql(
		'SELECT MONTH(date) m, SUM(withdrawal) aus FROM `tabBank Transaction`'
		' WHERE docstatus = 1 AND YEAR(date) = 2026 AND status != "Cancelled"'
		' AND name NOT IN (SELECT document_name FROM `tabTag Link`'
		'   WHERE document_type = "Bank Transaction" AND tag = "Umbuchung")'
		' GROUP BY MONTH(date) HAVING SUM(withdrawal) > 0', as_dict=True)
	exp_tag = sum(float(r["aus"]) / TAGE_PRO_MONAT[r["m"]] for r in sums) / len(sums)
	exp_soll = exp_tag * 365
	exp_monat = sum(float(r["aus"]) for r in sums) / len(sums)
	exp_ein_delta = 5 * mon_ein / MWST

	print(f"\n  Monate mit Daten: {len(mwd)} -> {n_new}")
	print(f"  analytisch erwartet: Burnrate/Tag {exp_tag:,.2f} | "
		f"Umsatz Soll {exp_soll:,.2f} | Burnrate/Monat {exp_monat:,.2f}")
	ok_c = True
	for key, exp in [("Burnrate/Tag verwendet", exp_tag),
			("Umsatz Soll (Brutto/Jahr)", exp_soll),
			("Burnrate/Monat (Brutto)", exp_monat)]:
		got = after[key]
		good = abs(got - exp) < 1.0
		if not good:
			ok_c = False
		print(f"  {key:47s} ist {got:>14,.2f}  erwartet {exp:>14,.2f}  {'OK' if good else 'FEHLER'}")
	got_ein = after["Umsatz Ist (Einnahmen YTD Netto)"] - base["Umsatz Ist (Einnahmen YTD Netto)"]
	good_ein = abs(got_ein - exp_ein_delta) < 1.0
	if not good_ein:
		ok_c = False
	print(f"  {'Umsatz Ist Zuwachs':47s} ist {got_ein:>+14,.2f}  erwartet {exp_ein_delta:>+14,.2f}"
		f"  {'OK' if good_ein else 'FEHLER'}")
	# Identitaet, die immer gelten muss
	ident = (after["Vorraussichtliche Umsatzluecke (Absehbar-Soll)"]
		- after["Reale Umsatzluecke (Ist+Out-Soll)"])
	ang_anteil = after["Liegende Angebote"] * 0.30
	good_id = abs(ident - ang_anteil) < 0.75
	if not good_id:
		ok_c = False
	print(f"  {'Identitaet Vorr - Real == Angebots-Anteil':47s} ist {ident:>14,.2f}"
		f"  erwartet {ang_anteil:>14,.2f}  {'OK' if good_id else 'FEHLER'}")
	print(f"  => {'PASS' if ok_c else 'FAIL'}")
	results.append(ok_c)

	for name in created:
		drop(name)
	frappe.db.commit()
	results.append(report("C  Rueckkehr nach Loeschen aller Projektionsbuchungen",
		base, snap(), {k: ("0", None) for k in KEYS}))

	print("\n" + "=" * 78)
	print(f"GESAMTERGEBNIS: {sum(1 for r in results if r)}/{len(results)} Simulationen PASS")
	print("=" * 78)
