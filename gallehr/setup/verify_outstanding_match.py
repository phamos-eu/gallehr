"""One-off dev script: proves the dashboard's Outstanding numbers and the Outstanding Report
agree, including the split at the Stichtag (31.12. of the selected Jahr).

Both must use the model's single Brutto->Netto convention (flat MWST 1.19, as in
the Excel original) and the same document scope. Before the alignment they
differed by ~105k EUR on this dataset: the report used each invoice's actual
net_total/grand_total ratio and additionally excluded invoices without a project.

Checks per Jahr (dashboard) / Stichtag (report):
  1. all-years total: dashboard "Outstanding bestehende Auftraege" == report Total Expected
  2. year bucket:     dashboard "Outstanding bis 31.12.<Jahr>"     == report "bis Stichtag"
  3. partition:       bis Stichtag + Folgejahre == all-years total (nothing lost, nothing doubled)
  4. gaps:            Reale Umsatzluecke == Ist + Outstanding(bis Stichtag) - Soll

Run via:
    bench --site gallehr-dev.localhost execute gallehr.setup.verify_outstanding_match.run
"""

from frappe.desk.query_report import run as run_report

JAHRE = ("2025", "2026", "2027")


def _row(fd, label_start):
	return next((r["prognose_eur"] for r in fd if r["monat"].startswith(label_start)), None)


def _report_sums(stichtag):
	out = run_report("Outstanding Report", filters={"stichtag": stichtag})["result"]
	unbilled = invoiced = unbilled_later = invoiced_later = 0.0
	for r in out:
		rtype = r.get("type") if isinstance(r, dict) else None
		if rtype in ("Not Yet Invoiced", "Partially Invoiced"):
			unbilled += r.get("unbilled_netto") or 0
			unbilled_later += r.get("unbilled_spaeter_netto") or 0
		elif rtype == "Invoiced Not Paid":
			invoiced += r.get("invoice_outstanding_netto") or 0
			invoiced_later += r.get("invoice_spaeter_netto") or 0
	return {
		"rows": len(out),
		"unbilled": unbilled,
		"invoiced": invoiced,
		"total": unbilled + invoiced,
		"later": unbilled_later + invoiced_later,
		"bis": unbilled + invoiced - unbilled_later - invoiced_later,
		# the report's own "Total Expected bis Stichtag" column, summed independently
		"bis_col": sum((r.get("bis_stichtag_netto") or 0) for r in out if isinstance(r, dict)),
	}


def _check(label, ok, detail):
	print(f"    {'PASS' if ok else 'FAIL'}  {label:<44} {detail}")
	return ok


def run():
	all_ok = True
	prev_later = None
	for jahr in JAHRE:
		stichtag = f"{jahr}-12-31"
		fd = run_report("Finanz Dashboard", filters={"jahr": jahr})["result"]
		rep = _report_sums(stichtag)

		d_total = _row(fd, "Outstanding bestehende")
		d_bis = _row(fd, "Outstanding bis")
		d_later = _row(fd, "Outstanding Folgejahre")
		ist = _row(fd, "Umsatz Ist")
		soll = _row(fd, "Umsatz Soll")
		reale = _row(fd, "Reale Umsatzluecke")

		print(f"\nJahr {jahr}  (Stichtag {stichtag}, {rep['rows']} report rows)")
		print(f"    dashboard: alle Jahre {d_total:>14,.2f} | bis Stichtag {d_bis:>14,.2f} | Folgejahre {d_later:>14,.2f}")
		print(f"    report   : alle Jahre {rep['total']:>14,.2f} | bis Stichtag {rep['bis']:>14,.2f} | Folgejahre {rep['later']:>14,.2f}")
		print(f"               davon Unbilled {rep['unbilled']:,.2f}, Invoiced not paid {rep['invoiced']:,.2f}")

		all_ok &= _check("1. all-years: dashboard == report", abs(d_total - rep["total"]) < 0.01, f"diff {d_total - rep['total']:+,.2f}")
		all_ok &= _check("2. year bucket: dashboard == report", abs(d_bis - rep["bis"]) < 0.01, f"diff {d_bis - rep['bis']:+,.2f}")
		all_ok &= _check("   report column 'bis Stichtag' == derived", abs(rep["bis_col"] - rep["bis"]) < 0.01, f"diff {rep['bis_col'] - rep['bis']:+,.2f}")
		all_ok &= _check("3. partition: bis + Folgejahre == alle", abs(rep["bis"] + rep["later"] - rep["total"]) < 0.01 and abs(d_bis + d_later - d_total) < 0.01, "")
		all_ok &= _check("4. Reale Umsatzluecke == Ist + bis - Soll", abs(reale - (ist + d_bis - soll)) < 0.01, f"diff {reale - (ist + d_bis - soll):+,.2f}")
		# a later Stichtag can only move money from "Folgejahre" into "bis Stichtag", never the reverse
		if prev_later is not None:
			all_ok &= _check("   Folgejahre shrinks as Stichtag grows", rep["later"] <= prev_later + 0.01, f"{prev_later:,.2f} -> {rep['later']:,.2f}")
		prev_later = rep["later"]

	print("\nRESULT:", "PASS -- Dashboard und Report stimmen ueberein, Aufteilung ist lueckenlos"
		if all_ok else "FAIL -- mindestens eine Pruefung weicht ab (siehe oben)")
