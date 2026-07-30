"""One-off validation script (not wired into hooks.py): empirically proves
the Finanz Dashboard's Reale/Vorr. Umsatzluecke formulas respond correctly
to isolated input changes, using the seeded data as a controlled fixture.
Creates one throwaway Quotation and one throwaway Sales Order, snapshots the
Prognose block before/after each, then cleans up after itself. Run via:

    bench --site gallehr-dev.localhost execute gallehr.setup.logic_audit.run
"""

import frappe
from frappe.desk.query_report import run as run_report

COMPANY = "Gallehr Sustainable Risk Management GmbH"
CUSTOMER = "Daimler Truck AG"
ITEM = "Dienstleistung"
PROBE_AMOUNT = 10000


SNAPSHOT_KEYS = [
	"Umsatz Ist (Einnahmen YTD Netto)",
	"Outstanding bestehende Auftraege",
	"Liegende Angebote",
	"Angebots-Anteil",
	"Reale Umsatzluecke (Ist+Out-Soll)",
	"Vorraussichtliche Umsatzluecke (Absehbar-Soll)",
	"Liquiditaet aktuell (Brutto)",
	"Abgeleiteter Start Jan (Brutto)",
	"Umsatz Soll (Brutto/Jahr)",
	"Burnrate/Monat (Brutto)",
]


def snapshot(extra_filters=None):
	filters = {"jahr": "2026"}
	filters.update(extra_filters or {})
	rows = run_report("Finanz Dashboard", filters=filters)["result"]
	values = {k: next((r["prognose_eur"] for r in rows if r["monat"] == k), None) for k in SNAPSHOT_KEYS}
	tage_row = next((r for r in rows if r["monat"] == "Tage ohne Zahlungseingang"), None)
	monate_row = next((r for r in rows if r["monat"] == "Monate ohne Zahlungseingang"), None)
	burnrate_row = next((r for r in rows if r["monat"].startswith("Burnrate/Tag verwendet")), None)
	values["Tage ohne Zahlungseingang"] = tage_row["prognose_zahl"] if tage_row else None
	values["Monate ohne Zahlungseingang"] = monate_row["prognose_zahl"] if monate_row else None
	values["Burnrate/Tag verwendet"] = burnrate_row["prognose_eur"] if burnrate_row else None
	return values


def print_diff(label, before, after):
	print(f"\n--- {label} ---")
	for k in before:
		b, a = before[k], after[k]
		delta = a - b
		flag = "" if abs(delta) < 0.01 else f"  <-- changed by {delta:+,.2f}"
		print(f"  {k:50s} {b:>14,.2f} -> {a:>14,.2f}{flag}")


def make_quotation():
	doc = frappe.get_doc({
		"doctype": "Quotation",
		"quotation_to": "Customer",
		"party_name": CUSTOMER,
		"company": COMPANY,
		"transaction_date": "2026-07-20",
		"valid_till": "2026-08-20",
		"currency": "EUR",
		"selling_price_list": "Standard-Vertrieb",
		"items": [{"item_code": ITEM, "qty": 1, "rate": PROBE_AMOUNT}],
	})
	doc.flags.ignore_links = True
	doc.insert(ignore_permissions=True, ignore_mandatory=True)
	doc.submit()
	return doc


def make_sales_order():
	income_account = frappe.db.get_value("Company", COMPANY, "default_income_account")
	doc = frappe.get_doc({
		"doctype": "Sales Order",
		"customer": CUSTOMER,
		"company": COMPANY,
		"transaction_date": "2026-07-20",
		"delivery_date": "2026-08-20",
		"currency": "EUR",
		"selling_price_list": "Standard-Vertrieb",
		"items": [{"item_code": ITEM, "qty": 1, "rate": PROBE_AMOUNT, "income_account": income_account}],
	})
	doc.flags.ignore_links = True
	doc.insert(ignore_permissions=True, ignore_mandatory=True)
	doc.submit()
	return doc


def undo(doc):
	doc.reload()
	doc.cancel()
	doc.delete()


def run():
	print(f"Probe amount: {PROBE_AMOUNT:,} EUR")
	angebotsumwandlung = 30  # dashboard default

	baseline = snapshot()

	print("\n### TEST 1: add one Quotation only (isolates Liegende Angebote / Angebots-Anteil) ###")
	q = make_quotation()
	after_q = snapshot()
	print_diff("Baseline -> +1 Quotation", baseline, after_q)
	expected_angebots_delta = PROBE_AMOUNT * angebotsumwandlung / 100
	print(f"\n  expected: Outstanding unchanged, Reale Umsatzluecke unchanged,")
	print(f"            Liegende Angebote +{PROBE_AMOUNT:,.2f}, Vorr. Umsatzluecke +{expected_angebots_delta:,.2f}")
	ok = (
		abs(after_q["Outstanding bestehende Auftraege"] - baseline["Outstanding bestehende Auftraege"]) < 0.01
		and abs(after_q["Reale Umsatzluecke (Ist+Out-Soll)"] - baseline["Reale Umsatzluecke (Ist+Out-Soll)"]) < 0.01
		and abs(after_q["Liegende Angebote"] - baseline["Liegende Angebote"] - PROBE_AMOUNT) < 0.01
		and abs(after_q["Vorraussichtliche Umsatzluecke (Absehbar-Soll)"] - baseline["Vorraussichtliche Umsatzluecke (Absehbar-Soll)"] - expected_angebots_delta) < 0.01
	)
	print(f"  RESULT: {'PASS -- matches formula exactly' if ok else 'FAIL -- see deltas above, this is a real logic error'}")
	undo(q)

	after_cleanup_q = snapshot()
	clean_ok = all(abs(after_cleanup_q[k] - baseline[k]) < 0.01 for k in baseline)
	print(f"  cleanup check: {'back to baseline' if clean_ok else 'MISMATCH -- cleanup left residue'}")

	print("\n### TEST 2: add one Sales Order only, unbilled (isolates Outstanding) ###")
	so = make_sales_order()
	after_so = snapshot()
	print_diff("Baseline -> +1 Sales Order", baseline, after_so)
	print(f"\n  expected: Outstanding +{PROBE_AMOUNT:,.2f}, Reale Umsatzluecke +{PROBE_AMOUNT:,.2f},")
	print(f"            Liegende Angebote unchanged, Vorr. Umsatzluecke +{PROBE_AMOUNT:,.2f} (same delta as Reale)")
	ok2 = (
		abs(after_so["Outstanding bestehende Auftraege"] - baseline["Outstanding bestehende Auftraege"] - PROBE_AMOUNT) < 0.01
		and abs(after_so["Reale Umsatzluecke (Ist+Out-Soll)"] - baseline["Reale Umsatzluecke (Ist+Out-Soll)"] - PROBE_AMOUNT) < 0.01
		and abs(after_so["Liegende Angebote"] - baseline["Liegende Angebote"]) < 0.01
		and abs(after_so["Vorraussichtliche Umsatzluecke (Absehbar-Soll)"] - baseline["Vorraussichtliche Umsatzluecke (Absehbar-Soll)"] - PROBE_AMOUNT) < 0.01
	)
	print(f"  RESULT: {'PASS -- matches formula exactly' if ok2 else 'FAIL -- see deltas above, this is a real logic error'}")
	undo(so)

	after_cleanup_so = snapshot()
	clean_ok2 = all(abs(after_cleanup_so[k] - baseline[k]) < 0.01 for k in baseline)
	print(f"  cleanup check: {'back to baseline' if clean_ok2 else 'MISMATCH -- cleanup left residue'}")

	print("\n### TEST 3: vary 'Aktuelle Kontostand Brutto' filter only (isolates the liquidity anchor) ###")
	base_kontostand = baseline["Liquiditaet aktuell (Brutto)"]
	base_liq = snapshot({"aktuell_liquiditaet": base_kontostand})
	bumped_liq = snapshot({"aktuell_liquiditaet": base_kontostand + PROBE_AMOUNT})
	print_diff(f"Kontostand {base_kontostand:,.2f} -> {base_kontostand + PROBE_AMOUNT:,.2f}", base_liq, bumped_liq)

	avg_aus_tag = base_liq["Burnrate/Tag verwendet"]
	expected_tage_delta = PROBE_AMOUNT / avg_aus_tag if avg_aus_tag else 0
	expected_monate_delta = expected_tage_delta / 30
	print(f"\n  expected: Umsatz/Outstanding/Angebote unchanged, Reale & Vorr. Umsatzluecke unchanged,")
	print(f"            Liquiditaet aktuell +{PROBE_AMOUNT:,.2f} (1:1), Abgeleiteter Start Jan +{PROBE_AMOUNT:,.2f} (1:1),")
	print(f"            Tage ohne Zahlung +{expected_tage_delta:,.2f}, Monate ohne Zahlung +{expected_monate_delta:,.4f}")
	ok3 = (
		abs(bumped_liq["Umsatz Ist (Einnahmen YTD Netto)"] - base_liq["Umsatz Ist (Einnahmen YTD Netto)"]) < 0.01
		and abs(bumped_liq["Outstanding bestehende Auftraege"] - base_liq["Outstanding bestehende Auftraege"]) < 0.01
		and abs(bumped_liq["Liegende Angebote"] - base_liq["Liegende Angebote"]) < 0.01
		and abs(bumped_liq["Reale Umsatzluecke (Ist+Out-Soll)"] - base_liq["Reale Umsatzluecke (Ist+Out-Soll)"]) < 0.01
		and abs(bumped_liq["Vorraussichtliche Umsatzluecke (Absehbar-Soll)"] - base_liq["Vorraussichtliche Umsatzluecke (Absehbar-Soll)"]) < 0.01
		and abs(bumped_liq["Liquiditaet aktuell (Brutto)"] - base_liq["Liquiditaet aktuell (Brutto)"] - PROBE_AMOUNT) < 0.01
		and abs(bumped_liq["Abgeleiteter Start Jan (Brutto)"] - base_liq["Abgeleiteter Start Jan (Brutto)"] - PROBE_AMOUNT) < 0.01
		and abs(bumped_liq["Tage ohne Zahlungseingang"] - base_liq["Tage ohne Zahlungseingang"] - expected_tage_delta) < 0.05
		and abs(bumped_liq["Monate ohne Zahlungseingang"] - base_liq["Monate ohne Zahlungseingang"] - expected_monate_delta) < 0.01
	)
	print(f"  RESULT: {'PASS -- matches formula exactly' if ok3 else 'FAIL -- see deltas above, this is a real logic error'}")

	print("\n### TEST 4: Burnrate-Zeitraum filter (burnrate_von/burnrate_bis) ###")
	von, bis = "2026-07-01", "2026-07-29"
	periode_check = frappe.db.sql(
		'SELECT SUM(CASE WHEN withdrawal > 0 THEN withdrawal ELSE 0 END) AS ausgaben,'
		' DATEDIFF(%(bis)s, %(von)s) + 1 AS tage'
		' FROM `tabBank Transaction`'
		' WHERE docstatus = 1 AND date BETWEEN %(von)s AND %(bis)s AND status != "Cancelled"'
		' AND name NOT IN ('
		'  SELECT document_name FROM `tabTag Link`'
		'  WHERE document_type = "Bank Transaction" AND tag = "Umbuchung"'
		' )',
		{"von": von, "bis": bis}, as_dict=True)[0]
	expected_avg = float(periode_check["ausgaben"] or 0) / periode_check["tage"]

	without_periode = snapshot()
	with_periode = snapshot({"burnrate_von": von, "burnrate_bis": bis})
	print_diff(f"No period -> Burnrate-Zeitraum {von}..{bis}", without_periode, with_periode)

	expected_soll_delta = (expected_avg - without_periode["Burnrate/Tag verwendet"]) * 365
	print(f"\n  independently computed avg daily burn for {von}..{bis}: {expected_avg:,.2f}")
	print(f"  expected: Burnrate/Tag verwendet == {expected_avg:,.2f} exactly,")
	print(f"            Burnrate/Monat unaffected (still pure auto average),")
	print(f"            Umsatz Soll shifts by {expected_soll_delta:+,.2f}, Reale & Vorr. Umsatzluecke shift by {-expected_soll_delta:+,.2f} (same amount, opposite sign)")
	ok4 = (
		abs(with_periode["Burnrate/Tag verwendet"] - expected_avg) < 0.01
		and abs(with_periode["Burnrate/Monat (Brutto)"] - without_periode["Burnrate/Monat (Brutto)"]) < 0.01
		and abs(with_periode["Umsatz Soll (Brutto/Jahr)"] - without_periode["Umsatz Soll (Brutto/Jahr)"] - expected_soll_delta) < 0.5
		and abs(with_periode["Reale Umsatzluecke (Ist+Out-Soll)"] - without_periode["Reale Umsatzluecke (Ist+Out-Soll)"] + expected_soll_delta) < 0.5
		and abs(with_periode["Vorraussichtliche Umsatzluecke (Absehbar-Soll)"] - without_periode["Vorraussichtliche Umsatzluecke (Absehbar-Soll)"] + expected_soll_delta) < 0.5
		and abs(with_periode["Outstanding bestehende Auftraege"] - without_periode["Outstanding bestehende Auftraege"]) < 0.01
		and abs(with_periode["Liegende Angebote"] - without_periode["Liegende Angebote"]) < 0.01
	)
	print(f"  RESULT: {'PASS -- matches formula exactly' if ok4 else 'FAIL -- see deltas above, this is a real logic error'}")

	frappe.db.commit()
	print("\nDone.")
