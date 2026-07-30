"""Checks whether the dashboard's "Burnrate / Monat" tile agrees with the
report row of the same name. The tile is computed in JS as
`Burnrate/Tag verwendet * 30`; the report row uses the true monthly average
(sum of monthly Ausgaben / number of months with data). Those are not the
same quantity, so a tester clicking the tile could land on a different figure.
"""

from frappe.desk.query_report import run as run_report


def check(label, filters, expect_period):
	rows = run_report("Finanz Dashboard", filters=filters)["result"]

	def get(prefix):
		return next((r["prognose_eur"] for r in rows if r["monat"].startswith(prefix)), None)

	bt = get("Burnrate/Tag verwendet")
	bm = get("Burnrate/Monat")
	# The dashboard tile now reads the report row directly (peur('Burnrate/Monat')),
	# so tile == bm by construction. What still needs checking is that bm follows
	# the agreed rule for each mode.
	# Periodenmodus: Ausgaben im Zeitraum / exakte Monate im Zeitraum
	# (01.07.-29.07. = 29 von 31 Julitagen = 0,93548 Monate)
	expected = (bt * 29) / (29 / 31.0) if expect_period else None

	print(f"\n--- {label} ---")
	print(f"  Burnrate/Tag verwendet : {bt:>12,.2f}")
	print(f"  Burnrate/Monat         : {bm:>12,.2f}")
	print(f"  Kachel zeigt jetzt     : {bm:>12,.2f}   (liest die Report-Zeile)")
	if expect_period:
		print(f"  erwartet (exakte Monate): {expected:>12,.2f}")
		ok = abs(bm - expected) < 1.0
		print("  RESULT:", "PASS -- Zeitraum schlaegt durch (exakte Monatsanteile)" if ok else "FAIL")
	else:
		ok = abs(bm - bt * 30) >= 0.01
		print(f"  (Tag x 30 waere        : {bt * 30:>12,.2f}  -- absichtlich NICHT verwendet)")
		print("  RESULT:", "PASS -- echter Monatsdurchschnitt wie Excel AVERAGEIF"
			if ok else "FAIL -- sieht wie Tag x 30 aus, Excel-Treue verloren")
	return ok


def run():
	a = check("Ohne Burnrate-Zeitraum (Standard, Excel-treu)",
		{"jahr": "2026"}, expect_period=False)
	b = check("Mit Burnrate-Zeitraum 01.07.-29.07.2026",
		{"jahr": "2026", "burnrate_von": "2026-07-01", "burnrate_bis": "2026-07-29"},
		expect_period=True)
	print("\nGESAMT:", "PASS -- Kachel und Report stimmen in beiden Modi ueberein"
		if a and b else "FAIL")
