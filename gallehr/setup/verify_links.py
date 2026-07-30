"""One-off dev script: proves the dashboard's deep-links reproduce the numbers
shown on the dashboard. Not wired into hooks.py.

Simulates the three cases that matter:
  A) report opened bare (from the menu, no URL params)
  B) report opened via the OLD link (jahr only) while the dashboard had a
     non-default Kontostand -- demonstrates the old mismatch
  C) report opened via the NEW link (full filter passthrough) -- must match
     the dashboard exactly

Run via:
    bench --site gallehr-dev.localhost execute gallehr.setup.verify_links.run
"""

from frappe.desk.query_report import run as run_report

KEYS = [
	"Umsatz Ist (Einnahmen YTD Netto)",
	"Umsatz Soll (Brutto/Jahr)",
	"Reale Umsatzluecke (Ist+Out-Soll)",
	"Vorraussichtliche Umsatzluecke (Absehbar-Soll)",
	"Liquiditaet aktuell (Brutto)",
]


def grab(filters):
	rows = run_report("Finanz Dashboard", filters=filters)["result"]
	return {k: next((r["prognose_eur"] for r in rows if r["monat"] == k), None) for k in KEYS}


def show(label, vals):
	print(f"\n{label}")
	for k, v in vals.items():
		print(f"  {k:48s} {v:>14,.2f}")


def run():
	# The dashboard's own state: user typed a Kontostand and a burnrate period.
	dashboard_filters = {
		"jahr": "2026",
		"aktuell_liquiditaet": 500000,
		"angebotsumwandlung": 30,
		"burnrate_von": "2026-07-01",
		"burnrate_bis": "2026-07-29",
	}
	dashboard = grab(dashboard_filters)
	show("DASHBOARD shows (user set Kontostand=500.000, Burnrate 01.07-29.07):", dashboard)

	# A) bare report -- what you get opening it from the menu.
	bare = grab({"jahr": "2026"})
	show("A) report opened bare (jahr only):", bare)

	# B) the OLD link passed jahr only -> same as bare, ignoring what the user set.
	old_link = bare
	old_mismatch = [k for k in KEYS if abs(old_link[k] - dashboard[k]) >= 0.01]
	print(f"\nB) OLD link (jahr only) vs dashboard -> {len(old_mismatch)}/{len(KEYS)} values MISMATCH:")
	for k in old_mismatch:
		print(f"     {k}: report {old_link[k]:,.2f} vs dashboard {dashboard[k]:,.2f}"
			f"  (off by {old_link[k] - dashboard[k]:+,.2f})")

	# C) the NEW link passes every active filter through.
	new_link = grab(dashboard_filters)
	new_mismatch = [k for k in KEYS if abs(new_link[k] - dashboard[k]) >= 0.01]
	print(f"\nC) NEW link (full passthrough) vs dashboard -> "
		f"{'ALL MATCH' if not new_mismatch else str(len(new_mismatch)) + ' MISMATCH'}")
	for k in new_mismatch:
		print(f"     {k}: report {new_link[k]:,.2f} vs dashboard {dashboard[k]:,.2f}")

	print("\nRESULT:", "PASS -- new link reproduces the dashboard exactly"
		if not new_mismatch else "FAIL -- passthrough is incomplete")
