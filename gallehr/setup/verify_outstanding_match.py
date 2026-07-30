"""One-off dev script: proves the dashboard's "Outstanding bestehende Auftraege"
and the Outstanding Report's "Total Expected (Netto)" now agree.

Both must use the model's single Brutto->Netto convention (flat MWST 1.19, as in
the Excel original) and the same document scope. Before the alignment they
differed by ~105k EUR on this dataset: the report used each invoice's actual
net_total/grand_total ratio and additionally excluded invoices without a project.

Run via:
    bench --site gallehr-dev.localhost execute gallehr.setup.verify_outstanding_match.run
"""

from frappe.desk.query_report import run as run_report


def run():
	fd = run_report("Finanz Dashboard", filters={"jahr": "2026"})["result"]
	dashboard_out = next(
		(r["prognose_eur"] for r in fd if r["monat"] == "Outstanding bestehende Auftraege"), None)

	out = run_report("Outstanding Report", filters={})["result"]
	unbilled = 0.0
	invoiced_not_paid = 0.0
	for r in out:
		rtype = r.get("type") if isinstance(r, dict) else None
		if rtype in ("Not Yet Invoiced", "Partially Invoiced"):
			unbilled += r.get("unbilled_netto") or 0
		elif rtype == "Invoiced Not Paid":
			invoiced_not_paid += r.get("invoice_outstanding_netto") or 0
	report_total = unbilled + invoiced_not_paid

	print(f"Dashboard 'Outstanding bestehende Auftraege' : {dashboard_out:>14,.2f}")
	print(f"Outstanding Report 'Total Expected (Netto)'  : {report_total:>14,.2f}")
	print(f"  davon Unbilled (Auftraege)                 : {unbilled:>14,.2f}")
	print(f"  davon Invoiced not paid (Rechnungen)       : {invoiced_not_paid:>14,.2f}")
	print(f"  rows in report                             : {len(out)}")

	diff = report_total - dashboard_out
	print(f"\nDifferenz: {diff:+,.2f}")
	print("RESULT:", "PASS -- beide Zahlen stimmen ueberein"
		if abs(diff) < 0.01 else "FAIL -- die Zahlen weichen weiterhin ab")
