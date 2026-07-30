"""Simulation: Outstanding wird so gross, dass die Reale Umsatzluecke die Null
ueberschreitet -- ohne jede Mitwirkung von Angeboten (Angebots-Anteil bleibt
unveraendert). Prueft, ob das Modell den Vorzeichenwechsel korrekt behandelt.

Nicht in hooks.py eingebunden. Aufruf:
    bench --site gallehr-dev.localhost execute gallehr.setup.simulate_sign_flip.run
"""

import frappe
from frappe.desk.query_report import run as run_report

COMPANY = "Gallehr Sustainable Risk Management GmbH"
CUSTOMER = "Daimler Truck AG"
ITEM = "Dienstleistung"

KEYS = ["Umsatz Ist (Einnahmen YTD Netto)", "Umsatz Soll (Brutto/Jahr)",
	"Outstanding bestehende Auftraege", "Liegende Angebote", "Angebots-Anteil",
	"Reale Umsatzluecke (Ist+Out-Soll)", "Vorraussichtliche Umsatzluecke (Absehbar-Soll)"]


def snap():
	rows = run_report("Finanz Dashboard", filters={"jahr": "2026"})["result"]
	return {k: next((r["prognose_eur"] for r in rows if r["monat"] == k), 0.0) for k in KEYS}


def make_so(betrag):
	income_account = frappe.db.get_value("Company", COMPANY, "default_income_account")
	doc = frappe.get_doc({
		"doctype": "Sales Order", "customer": CUSTOMER, "company": COMPANY,
		"transaction_date": "2026-07-20", "delivery_date": "2026-08-20",
		"currency": "EUR", "selling_price_list": "Standard-Vertrieb",
		"items": [{"item_code": ITEM, "qty": 1, "rate": betrag, "income_account": income_account}],
	})
	doc.flags.ignore_links = True
	doc.insert(ignore_permissions=True, ignore_mandatory=True)
	doc.submit()
	return doc.name


def undo(name):
	doc = frappe.get_doc("Sales Order", name)
	doc.cancel()
	doc.delete()


def run():
	base = snap()
	print("AUSGANGSLAGE")
	for k, v in base.items():
		print(f"  {k:47s} {v:>14,.2f}")

	luecke = base["Reale Umsatzluecke (Ist+Out-Soll)"]
	assert luecke < 0, "Ausgangslage ist bereits positiv -- Szenario nicht sinnvoll testbar"
	betrag = round(-luecke + 5000, 2)  # genug, um sicher ueber Null zu kommen

	print(f"\nErzeuge einen Auftrag ueber {betrag:,.2f} EUR (deckt die Luecke von "
		f"{-luecke:,.2f} EUR plus 5.000 EUR Puffer) -- OHNE ein Angebot anzuruehren.")
	so = make_so(betrag)
	after = snap()

	print("\nNACHHER")
	for k, v in after.items():
		delta = v - base[k]
		flag = f"  <-- {delta:+,.2f}" if abs(delta) > 0.01 else ""
		print(f"  {k:47s} {v:>14,.2f}{flag}")

	print("\nPRUEFUNG")
	checks = []

	c1 = after["Liegende Angebote"] == base["Liegende Angebote"] and after["Angebots-Anteil"] == base["Angebots-Anteil"]
	checks.append(c1)
	print(f"  Angebote/Angebots-Anteil unberuehrt (isoliert der Test):", "OK" if c1 else "FEHLER")

	c2 = after["Reale Umsatzluecke (Ist+Out-Soll)"] > 0
	checks.append(c2)
	print(f"  Reale Umsatzluecke jetzt POSITIV ({after['Reale Umsatzluecke (Ist+Out-Soll)']:,.2f}):", "OK" if c2 else "FEHLER")

	c3 = after["Vorraussichtliche Umsatzluecke (Absehbar-Soll)"] > 0
	checks.append(c3)
	print(f"  Vorr. Umsatzluecke folgt und ist ebenfalls POSITIV ({after['Vorraussichtliche Umsatzluecke (Absehbar-Soll)']:,.2f}):", "OK" if c3 else "FEHLER")

	# Die Identitaet muss auch beim Vorzeichenwechsel exakt gelten
	diff = after["Vorraussichtliche Umsatzluecke (Absehbar-Soll)"] - after["Reale Umsatzluecke (Ist+Out-Soll)"]
	c4 = abs(diff - after["Angebots-Anteil"]) < 0.01
	checks.append(c4)
	print(f"  Identitaet Vorr - Real == Angebots-Anteil haelt auch hier ({diff:,.2f} == {after['Angebots-Anteil']:,.2f}):", "OK" if c4 else "FEHLER")

	# Reale Umsatzluecke > 0 bedeutet per Definition: Ist+Outstanding allein
	# decken das Soll, unabhaengig von jedem Angebot. Das ist exakt die vom
	# Nutzer gesuchte Kennzahl -- kein neues Feld noetig, siehe Antworttext.
	c5 = after["Umsatz Ist (Einnahmen YTD Netto)"] + after["Outstanding bestehende Auftraege"] >= after["Umsatz Soll (Brutto/Jahr)"]
	checks.append(c5)
	print(f"  Ist + Outstanding >= Soll (Definition 'ausreichend ohne Angebote'):", "OK" if c5 else "FEHLER")

	undo(so)
	cleanup = snap()
	c6 = all(abs(cleanup[k] - base[k]) < 0.01 for k in KEYS)
	checks.append(c6)
	print(f"  Ruecknahme -> exakt Ausgangslage:", "OK" if c6 else "FEHLER")

	print("\nGESAMT:", f"{sum(checks)}/{len(checks)} PASS -- Modell behandelt den Vorzeichenwechsel korrekt"
		if all(checks) else "FAIL")
