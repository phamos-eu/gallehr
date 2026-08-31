"""Backend fuer die "AK Auswertung"-Seite (feature/AK_auswertung_v1).

v1: eine Kostenstelle (Haupt - G, siehe ak-auswertung-feature Notiz),
clustert die Aufwandskonten dieser Kostenstelle und zeigt je Konto, wie
viel davon nachweislich ueber eine echte Bank Transaction geflossen ist.

Der Abgleich (ABGLEICH_EXISTS) prueft zwei Wege, weil ein Aufwand auf
zwei Arten "bankabgeglichen" sein kann:
  1. der Beleg selbst (Payment Entry/Journal Entry) steht in
     Bank Transaction Payments, oder
  2. der Beleg ist eine Purchase Invoice/Expense Claim, die spaeter ueber
     eine Payment Entry bezahlt wurde (verknuepft ueber Payment Entry
     Reference), und DIESE Payment Entry steht in Bank Transaction
     Payments.
Details/Hintergrund: ~/Desktop/work/ricarda_feature/docu_v1_lokale_testdaten.md
"""

import frappe
from frappe import _
from frappe.utils import add_months, cint, flt, nowdate

DEFAULT_COST_CENTER = "Haupt - G"

ABGLEICH_EXISTS = """EXISTS (
	SELECT 1 FROM `tabBank Transaction Payments` btp
	WHERE (btp.payment_document = gl.voucher_type AND btp.payment_entry = gl.voucher_no)
	OR EXISTS (
		SELECT 1 FROM `tabPayment Entry Reference` per
		WHERE per.reference_doctype = gl.voucher_type AND per.reference_name = gl.voucher_no
		AND btp.payment_document = 'Payment Entry' AND btp.payment_entry = per.parent
	)
)"""


def _check_permission():
	if not frappe.has_permission("GL Entry", "read"):
		frappe.throw(_("Keine Berechtigung fuer Buchhaltungsdaten"), frappe.PermissionError)


def _default_range():
	return add_months(nowdate(), -12), nowdate()


def _rows(cost_center, von, bis):
	return frappe.db.sql(
		f"""
		SELECT gl.account, ac.account_name,
			COUNT(*) AS anzahl,
			SUM(gl.debit - gl.credit) AS summe_netto,
			SUM(CASE WHEN {ABGLEICH_EXISTS} THEN gl.debit - gl.credit ELSE 0 END) AS summe_abgeglichen,
			SUM(CASE WHEN {ABGLEICH_EXISTS} THEN 1 ELSE 0 END) AS anzahl_abgeglichen
		FROM `tabGL Entry` gl
		JOIN `tabAccount` ac ON ac.name = gl.account
		WHERE gl.cost_center = %(cc)s AND gl.is_cancelled = 0 AND ac.root_type = 'Expense'
		AND gl.posting_date BETWEEN %(von)s AND %(bis)s
		GROUP BY gl.account, ac.account_name
		ORDER BY summe_netto DESC
		""",
		{"cc": cost_center, "von": von, "bis": bis},
		as_dict=True,
	)


def _build(cost_center, von, bis):
	cost_center = cost_center or DEFAULT_COST_CENTER
	default_von, default_bis = _default_range()
	von = von or default_von
	bis = bis or default_bis

	rows = _rows(cost_center, von, bis)
	for r in rows:
		r["summe_netto"] = flt(r["summe_netto"])
		r["summe_abgeglichen"] = flt(r["summe_abgeglichen"])
		r["anzahl"] = cint(r["anzahl"])
		r["anzahl_abgeglichen"] = cint(r["anzahl_abgeglichen"])
		r["abdeckung_pct"] = round(r["anzahl_abgeglichen"] / r["anzahl"] * 100, 1) if r["anzahl"] else 0.0

	summe_gesamt = sum(r["summe_netto"] for r in rows)
	for r in rows:
		r["anteil_pct"] = round(r["summe_netto"] / summe_gesamt * 100, 1) if summe_gesamt else 0.0

	return {
		"rows": rows,
		"cost_center": cost_center,
		"von": von,
		"bis": bis,
		"summe_gesamt": summe_gesamt,
	}


@frappe.whitelist()
def get_data(cost_center=None, von=None, bis=None):
	_check_permission()
	return _build(cost_center, von, bis)


@frappe.whitelist()
def export_excel(cost_center=None, von=None, bis=None):
	_check_permission()
	from frappe.utils.xlsxutils import make_xlsx

	data = _build(cost_center, von, bis)
	header = [
		"Aufwandskonto", "Kontobezeichnung", "Anzahl Buchungen", "Netto EUR",
		"Anteil an Gesamt %", "Davon bankabgeglichen EUR", "Abgleich-Abdeckung %",
	]
	xlsx_rows = [header]
	for r in data["rows"]:
		xlsx_rows.append([
			r["account"], r["account_name"], r["anzahl"], r["summe_netto"],
			r["anteil_pct"], r["summe_abgeglichen"], r["abdeckung_pct"],
		])
	xlsx_rows.append(["", "Gesamt", "", data["summe_gesamt"], 100.0, "", ""])

	xlsx = make_xlsx(xlsx_rows, "AK Auswertung")
	filename = f"AK_Auswertung_{data['cost_center']}_{data['von']}_{data['bis']}.xlsx".replace(" ", "_")
	frappe.response["filename"] = filename
	frappe.response["filecontent"] = xlsx.getvalue()
	frappe.response["type"] = "binary"
