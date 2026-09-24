"""Quelle "Eingangsrechnung": jede Position (Purchase Invoice Item) einer gebuchten Eingangsrechnung mit Aufwandskonto.

Kostenzeile (Schluessel):
  quelle, beleg_typ, beleg, zeile, datum (ISO), unternehmen, kostenstelle, kostenstelle_quelle (Kopf | Tag | -),
  konto_nr, konto_name, item, item_group, lieferant, netto, brutto, bank_status (bank | ohne), bt, tags, konzern, rueckgabe

Entscheidungen (Mockup-Abnahme 2026-09-24):
- nur Konten der Kontenart Aufwand (Account.root_type = 'Expense'); Anlagevermoegen/Durchlauf/Ertrag gehoeren nicht dazu
- Kostenstelle = Kopf der Rechnung; ist er leer, ordnet ein Standort-Tag zu, sonst "(nicht zugeordnet)"
- bank_status "bank" = Zahlung der Rechnung haengt an einer Bank Transaction, sonst "ohne"; Rueckgaben erben den Status
  ihrer Originalrechnung
- brutto der Zeile = netto der Zeile * (Brutto/Netto der Rechnung)
"""

import frappe
from frappe.utils import flt

NICHT_ZUGEORDNET = "(nicht zugeordnet)"
# Standort-Tags ordnen eine Rechnung ohne Kostenstelle im Kopf zu (Tags sind sonst nur Kontext)
STANDORT_TAGS = {"Büro Wiesbaden": "Wiesbaden - G", "Standort Wiesbaden": "Wiesbaden - G", "nEZ Handel": "nEZ Handel - G"}
KONZERN_TAGS = ("Umbuchung",)


def zeilen(von, bis, unternehmen=None):
	firma = " AND pi.company = %(firma)s" if unternehmen else ""
	rows = frappe.db.sql(
		f"""
		SELECT pii.name AS zeile, pi.name AS beleg, pi.posting_date AS datum, pi.company AS unternehmen,
			IFNULL(pi.cost_center, '') AS kopf_kst, ac.account_number AS konto_nr, ac.account_name AS konto_name,
			pii.item_code AS item, pii.item_group AS item_group, pii.base_net_amount AS netto,
			pi.base_net_total AS beleg_netto, pi.base_grand_total AS beleg_brutto,
			pi.supplier_name AS lieferant, pi.supplier AS lieferant_id, pi.is_return, pi.return_against
		FROM `tabPurchase Invoice Item` pii
		JOIN `tabPurchase Invoice` pi ON pi.name = pii.parent
		JOIN `tabAccount` ac ON ac.name = pii.expense_account
		WHERE pi.docstatus = 1 AND ac.root_type = 'Expense' AND pi.posting_date BETWEEN %(von)s AND %(bis)s{firma}
		ORDER BY pi.posting_date, pi.name, pii.idx""",
		{"von": von, "bis": bis, "firma": unternehmen},
		as_dict=True,
	)
	belege = {r.beleg for r in rows}
	originale = {r.return_against for r in rows if r.is_return and r.return_against}
	bank = _bank_zuordnung(belege | originale)
	tags = _tags(belege)
	eigene = _eigene_gesellschaften()

	out = []
	for r in rows:
		t = tags.get(r.beleg, [])
		kst, quelle = r.kopf_kst, "Kopf"
		if not kst:
			abgeleitet = [STANDORT_TAGS[x] for x in t if x in STANDORT_TAGS]
			kst, quelle = (abgeleitet[0], "Tag") if abgeleitet else (NICHT_ZUGEORDNET, "-")
		beleg_fuer_bank = r.return_against if r.is_return and r.return_against else r.beleg
		bt = bank.get(beleg_fuer_bank, "")
		faktor = flt(r.beleg_brutto) / flt(r.beleg_netto) if flt(r.beleg_netto) else 1.0
		out.append({
			"quelle": "Eingangsrechnung", "beleg_typ": "Purchase Invoice", "beleg": r.beleg, "zeile": r.zeile,
			"datum": str(r.datum), "unternehmen": r.unternehmen, "kostenstelle": kst, "kostenstelle_quelle": quelle,
			"konto_nr": r.konto_nr or "", "konto_name": r.konto_name or "", "item": r.item or "", "item_group": r.item_group or "",
			"lieferant": r.lieferant or "", "netto": flt(r.netto, 2), "brutto": flt(flt(r.netto) * faktor, 2),
			"bank_status": "bank" if bt else "ohne", "bt": bt, "tags": t,
			"konzern": bool(r.lieferant in eigene or r.lieferant_id in eigene or any(x in KONZERN_TAGS for x in t)),
			"rueckgabe": bool(r.is_return),
		})
	return out


def _bank_zuordnung(belege):
	"""Rechnung -> Name der Bank Transaction. Zwei getrennte Abfragen (ueber Payment Entry / direkt an der Rechnung)
	statt eines OR ueber mehrere EXISTS -- so ist jeder Weg einzeln pruefbar."""
	if not belege:
		return {}
	zuordnung = {}
	ueber_payment_entry = frappe.db.sql(
		"""
		SELECT per.reference_name AS beleg, btp.parent AS bt
		FROM `tabPayment Entry Reference` per
		JOIN `tabPayment Entry` pe ON pe.name = per.parent AND pe.docstatus = 1
		JOIN `tabBank Transaction Payments` btp ON btp.payment_document = 'Payment Entry' AND btp.payment_entry = pe.name
		JOIN `tabBank Transaction` bt ON bt.name = btp.parent AND bt.docstatus = 1
		WHERE per.reference_doctype = 'Purchase Invoice' AND per.reference_name IN %(belege)s
		ORDER BY bt.date, btp.parent""",
		{"belege": tuple(belege)},
		as_dict=True,
	)
	direkt = frappe.db.sql(
		"""
		SELECT btp.payment_entry AS beleg, btp.parent AS bt
		FROM `tabBank Transaction Payments` btp
		JOIN `tabBank Transaction` bt ON bt.name = btp.parent AND bt.docstatus = 1
		WHERE btp.payment_document = 'Purchase Invoice' AND btp.payment_entry IN %(belege)s
		ORDER BY bt.date, btp.parent""",
		{"belege": tuple(belege)},
		as_dict=True,
	)
	for r in ueber_payment_entry + direkt:
		zuordnung.setdefault(r.beleg, r.bt)
	return zuordnung


def _tags(belege):
	if not belege:
		return {}
	out = {}
	for r in frappe.db.sql(
		"SELECT document_name, tag FROM `tabTag Link` WHERE document_type = 'Purchase Invoice' AND document_name IN %(belege)s ORDER BY tag",
		{"belege": tuple(belege)}, as_dict=True,
	):
		out.setdefault(r.document_name, []).append(r.tag)
	return out


def _eigene_gesellschaften():
	namen = set()
	for c in frappe.get_all("Company", fields=["name", "company_name"]):
		namen.add(c.name)
		if c.company_name:
			namen.add(c.company_name)
	return namen
