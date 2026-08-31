# Copyright (c) 2026, phamos.eu and contributors
# For license information, please see license.txt

import frappe


def execute(filters=None):
	columns = get_columns()
	data = get_data(filters, columns)
	return columns, data


def get_columns():
	return [
		{"label": "Monat",              "fieldname": "monat",            "fieldtype": "Data",     "width": 90},
		{"label": "Jahr",               "fieldname": "jahr",             "fieldtype": "Data",     "width": 60},
		{"label": "Prognose (EUR)",     "fieldname": "prognose_eur",     "fieldtype": "Currency", "width": 150},
		{"label": "Prognose (Zahl)",    "fieldname": "prognose_zahl",    "fieldtype": "Float",    "width": 140},
		{"label": "Einnahmen Brutto",   "fieldname": "einnahmen_brutto", "fieldtype": "Currency", "width": 140},
		{"label": "Ausgaben Brutto",    "fieldname": "ausgaben_brutto",  "fieldtype": "Currency", "width": 140},
		{"label": "Saldo Brutto",       "fieldname": "saldo_brutto",     "fieldtype": "Currency", "width": 120},
		{"label": "Liquiditaet Brutto", "fieldname": "liq_brutto",       "fieldtype": "Currency", "width": 150},
		{"label": "Einnahmen Netto",    "fieldname": "einnahmen_netto",  "fieldtype": "Currency", "width": 140},
		{"label": "Ausgaben Netto",     "fieldname": "ausgaben_netto",   "fieldtype": "Currency", "width": 140},
		{"label": "Saldo Netto",        "fieldname": "saldo_netto",      "fieldtype": "Currency", "width": 120},
		{"label": "Ausgaben/Tag Brutto","fieldname": "ausgaben_tag",     "fieldtype": "Currency", "width": 150},
		{"label": "Burnrate/M Brutto",  "fieldname": "burnrate_m",       "fieldtype": "Currency", "width": 140},
	]


def parse_de_float(val):
	# handle German decimal comma (e.g. "480522,72" -> 480522.72)
	if not val:
		return 0.0
	try:
		return float(str(val).replace(",", "."))
	except (ValueError, TypeError):
		return 0.0


def get_data(filters, columns):
	filters = filters or {}
	current_year = str(filters.get("jahr") or "2026")
	angebotsumwandlung = float(filters.get("angebotsumwandlung") or 30)

	# Burnrate-Zeitraum: replaces the old manual Burnrate/Tag override. If both
	# dates are set (either resolved from a preset -- 3/6/12 Monate -- or a
	# custom range in the UI), the average daily burn is computed strictly from
	# that window instead of the year-to-date auto-average. Empty -> unchanged
	# behaviour: full year since Jahresbeginn.
	burnrate_von = str(filters.get("burnrate_von") or "")
	burnrate_bis = str(filters.get("burnrate_bis") or "")
	use_burnrate_periode = bool(burnrate_von) and bool(burnrate_bis)

	aktuell_liq = parse_de_float(filters.get("aktuell_liquiditaet"))
	start_liq = parse_de_float(filters.get("start_liquiditaet"))
	use_aktuell = aktuell_liq > 0

	snapshot_datum = None
	if not use_aktuell and not start_liq:
		snap_result = frappe.db.sql(
			"SELECT kontostand_brutto, datum FROM `tabLiquiditaet Snapshot`"
			" WHERE als_standard = 1 ORDER BY datum DESC LIMIT 1",
			as_dict=True)
		if snap_result:
			aktuell_liq = float(snap_result[0].get("kontostand_brutto") or 0)
			snapshot_datum = snap_result[0].get("datum")
			use_aktuell = aktuell_liq > 0

	# Store the raw snapshot value separately for display in dashboard
	snapshot_liq = aktuell_liq

	# Calculate current_liq_brutto as: snapshot + all transactions AFTER snapshot date
	# This is Sebastian's formula: simpler, correct, no backwards/forwards derivation needed.
	# Filters on the transaction's own `date`, not `creation` (import timestamp) -- a
	# late-imported historical transaction must not be re-counted as "since the snapshot"
	# just because it landed in the DB after the snapshot was taken.
	# Compared at day granularity (DATE(...) on both sides): Bank Transaction.date has no
	# time-of-day component, so comparing it against the snapshot's full datetime would let
	# MySQL coerce same-day transactions to midnight and silently drop the whole snapshot day.
	liq_seit_snapshot = 0
	if snapshot_liq > 0 and snapshot_datum:
		seit_result = frappe.db.sql(
			"SELECT"
			" SUM(CASE WHEN deposit > 0 THEN deposit ELSE 0 END) AS ein,"
			" SUM(CASE WHEN withdrawal > 0 THEN withdrawal ELSE 0 END) AS aus"
			" FROM `tabBank Transaction`"
			" WHERE docstatus = 1 AND status != 'Cancelled'"
			" AND DATE(date) > DATE(%(datum)s)"
			" AND name NOT IN ("
			"  SELECT document_name FROM `tabTag Link`"
			"  WHERE document_type = 'Bank Transaction' AND tag = 'Umbuchung'"
			" )",
			{"datum": snapshot_datum}, as_dict=True)
		if seit_result and seit_result[0].get("ein") is not None:
			ein_seit = float(seit_result[0].get("ein") or 0)
			aus_seit = float(seit_result[0].get("aus") or 0)
			liq_seit_snapshot = ein_seit - aus_seit

	mwst = 1.19
	monatsnamen = ["Jan", "Feb", "Mar", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]
	tage_pro_monat = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]

	bank_data = frappe.db.sql(
		"SELECT MONTH(date) AS monat_num,"
		" SUM(CASE WHEN deposit > 0 THEN deposit ELSE 0 END) AS einnahmen,"
		" SUM(CASE WHEN withdrawal > 0 THEN withdrawal ELSE 0 END) AS ausgaben"
		" FROM `tabBank Transaction`"
		" WHERE docstatus = 1 AND YEAR(date) = %(jahr)s AND status != 'Cancelled'"
		" AND name NOT IN ("
		"  SELECT document_name FROM `tabTag Link`"
		"  WHERE document_type = 'Bank Transaction' AND tag = 'Umbuchung'"
		" )"
		" GROUP BY MONTH(date) ORDER BY MONTH(date)",
		{"jahr": int(current_year)}, as_dict=True)

	bank_by_month = {row.monat_num: row for row in bank_data}

	salden_brutto = []
	for m in range(1, 13):
		bdata = bank_by_month.get(m, {})
		ein_b = float(bdata.get("einnahmen") or 0)
		aus_b = float(bdata.get("ausgaben") or 0)
		salden_brutto.append(ein_b - aus_b)

	if use_aktuell:
		total_salden = 0
		for m in range(1, 13):
			bdata = bank_by_month.get(m, {})
			has_data = float(bdata.get("einnahmen") or 0) > 0 or float(bdata.get("ausgaben") or 0) > 0
			if has_data:
				total_salden += salden_brutto[m - 1]
		start_jan_brutto = aktuell_liq - total_salden
		liq_quelle = "aktuell"
	else:
		start_jan_brutto = start_liq
		liq_quelle = "start"

	rows = []
	liq_brutto = start_jan_brutto
	for m in range(1, 13):
		monat_name = monatsnamen[m - 1]
		tage = tage_pro_monat[m - 1]
		bdata = bank_by_month.get(m, {})

		ein_brutto = float(bdata.get("einnahmen") or 0)
		aus_brutto = float(bdata.get("ausgaben") or 0)
		saldo_brutto = ein_brutto - aus_brutto

		ein_netto = ein_brutto / mwst
		aus_netto = aus_brutto / mwst
		saldo_netto = ein_netto - aus_netto

		aus_tag_brutto = aus_brutto / tage if tage else 0
		burnrate_m_brutto = aus_tag_brutto * 30

		# Excel-Logik: start_liq ist der Ende-Januar Kontostand (hardcoded wie Excel H18)
		# Januar wird nicht akkumuliert — nur als Startwert gesetzt
		# Ab Februar wird normal akkumuliert
		if m == 1 and start_liq > 0:
			liq_brutto = start_jan_brutto  # = start_liq, kein Saldo addiert
		else:
			liq_brutto = liq_brutto + saldo_brutto

		rows.append({
			"monat": monat_name, "jahr": current_year,
			"prognose_eur": 0, "prognose_zahl": 0,
			"einnahmen_brutto": ein_brutto, "ausgaben_brutto": aus_brutto,
			"saldo_brutto": saldo_brutto, "liq_brutto": liq_brutto,
			"einnahmen_netto": ein_netto, "ausgaben_netto": aus_netto,
			"saldo_netto": saldo_netto,
			"ausgaben_tag": aus_tag_brutto,
			"burnrate_m": burnrate_m_brutto,
		})

	# Excel-Logik: AVERAGEIF(I18:I29,"<>#NV") schliesst alle Monate MIT Daten ein,
	# auch den laufenden Monat (partial). "<>#NV" schliesst nur Monate ohne Daten aus.
	# Dasselbe gilt fuer Liquiditaet und Umsatz Ist. Kein "current month exclusion".
	umsatz_ist = 0
	current_liq_brutto_derived = 0
	aus_tag_brutto_sum = 0
	aus_brutto_sum = 0
	months_with_data = 0
	for r in rows:
		if r["einnahmen_brutto"] > 0 or r["ausgaben_brutto"] > 0:
			# Umsatz Ist: inkl. laufenden Monat (wie Excel E col SUMIF)
			umsatz_ist += r["einnahmen_netto"]
			# Liquiditaet: immer updaten, auch laufender Monat (wie Excel Spalte H)
			current_liq_brutto_derived = r["liq_brutto"]
			# Burnrate: alle Monate MIT Daten inkl. laufendem Monat
			# wie Excel AVERAGEIF(I18:I29,"<>#NV") — schliesst nur leere Monate aus
			if r["ausgaben_tag"] > 0:
				aus_tag_brutto_sum += r["ausgaben_tag"]
				aus_brutto_sum += r["ausgaben_brutto"]
				months_with_data += 1

	# I5-Aequivalent: Ø Ausgaben/Tag (wie Excel I5 = AVERAGEIF(I18:I29,"<>#NV")) -- year-to-date fallback
	avg_aus_tag_brutto_auto = aus_tag_brutto_sum / months_with_data if months_with_data else 0
	# J5-Aequivalent: Ø echte Monatsausgaben (wie Excel J5 = AVERAGEIF(J18:J29,"<>#NV"))
	# Echter Monatsdurchschnitt, NICHT Tag*30 (Monate haben 28-31 Tage) -- always
	# the pure year-to-date auto value, independent of the Burnrate-Zeitraum below.
	avg_aus_m_brutto_auto = aus_brutto_sum / months_with_data if months_with_data else 0

	# Sebastian's formula: snapshot + saldo since snapshot date (Snapshot-Modus)
	# Falls back to accumulated running balance if no snapshot available (Start-Liq-Modus)
	if snapshot_liq > 0 and snapshot_datum:
		current_liq_brutto = snapshot_liq + liq_seit_snapshot
	else:
		current_liq_brutto = current_liq_brutto_derived

	# Burnrate-Zeitraum: average daily burn over an explicit von/bis window,
	# independent of `jahr` (can span a year boundary), same Umbuchung exclusion
	# as the main bank_data query above. Replaces the old avg_aus_tag_manuell.
	avg_aus_tag_brutto_periode = 0
	avg_aus_m_brutto_periode = 0
	monate_im_zeitraum = 0.0
	if use_burnrate_periode:
		periode_result = frappe.db.sql(
			"SELECT SUM(CASE WHEN withdrawal > 0 THEN withdrawal ELSE 0 END) AS ausgaben,"
			" DATEDIFF(%(bis)s, %(von)s) + 1 AS tage"
			" FROM `tabBank Transaction`"
			" WHERE docstatus = 1 AND date BETWEEN %(von)s AND %(bis)s AND status != 'Cancelled'"
			" AND name NOT IN ("
			"  SELECT document_name FROM `tabTag Link`"
			"  WHERE document_type = 'Bank Transaction' AND tag = 'Umbuchung'"
			" )",
			{"von": burnrate_von, "bis": burnrate_bis}, as_dict=True)
		if periode_result:
			p_ausgaben = float(periode_result[0].get("ausgaben") or 0)
			p_tage = periode_result[0].get("tage") or 0
			avg_aus_tag_brutto_periode = p_ausgaben / p_tage if p_tage else 0

			# Monate im Zeitraum EXAKT: je beruehrtem Monat der Anteil seiner
			# tatsaechlichen Tage, statt pauschal mit 30 zu rechnen. 01.07.-29.07.
			# sind 29 von 31 Julitagen = 0,935 Monate, nicht 29/30.
			# Schaltjahre werden beruecksichtigt.
			von_j, von_m, von_t = int(burnrate_von[0:4]), int(burnrate_von[5:7]), int(burnrate_von[8:10])
			bis_j, bis_m, bis_t = int(burnrate_bis[0:4]), int(burnrate_bis[5:7]), int(burnrate_bis[8:10])
			jj, mm = von_j, von_m
			while (jj < bis_j) or (jj == bis_j and mm <= bis_m):
				if mm == 2:
					schaltjahr = jj % 4 == 0 and (jj % 100 != 0 or jj % 400 == 0)
					dim = 29 if schaltjahr else 28
				else:
					dim = tage_pro_monat[mm - 1]
				start_tag = von_t if (jj == von_j and mm == von_m) else 1
				end_tag = bis_t if (jj == bis_j and mm == bis_m) else dim
				if end_tag >= start_tag:
					monate_im_zeitraum += float(end_tag - start_tag + 1) / dim
				mm += 1
				if mm > 12:
					mm = 1
					jj += 1
			avg_aus_m_brutto_periode = p_ausgaben / monate_im_zeitraum if monate_im_zeitraum else 0

	if use_burnrate_periode:
		avg_aus_tag_brutto_final = avg_aus_tag_brutto_periode
		burnrate_quelle = "periode " + burnrate_von + " bis " + burnrate_bis
	else:
		avg_aus_tag_brutto_final = avg_aus_tag_brutto_auto
		burnrate_quelle = "auto"

	# Burnrate/Monat: ohne Burnrate-Zeitraum der echte Monatsdurchschnitt
	# (wie Excel J5 = AVERAGEIF(J18:J29)) -- NICHT Tag*30, da Monate 28-31 Tage
	# haben. Mit gesetztem Zeitraum gibt es kein Excel-Aequivalent (Teilmonate
	# lassen sich nicht als Monatsmittel bilden), daher dort Ausgaben geteilt
	# durch die exakte Anzahl Monate im Zeitraum (anteilige echte Monatstage).
	# Die Dashboard-Kachel liest genau diesen Wert aus dem Report, damit Kachel
	# und Report nicht auseinanderlaufen koennen.
	if use_burnrate_periode:
		burnrate_m_brutto_final = avg_aus_m_brutto_periode
	else:
		burnrate_m_brutto_final = avg_aus_m_brutto_auto

	umsatz_soll = avg_aus_tag_brutto_final * 365

	tage_ohne = current_liq_brutto / avg_aus_tag_brutto_final if avg_aus_tag_brutto_final else 0
	monate_ohne = tage_ohne / 30

	outstanding_result = frappe.db.sql(
		"SELECT"
		" IFNULL((SELECT SUM(so.net_total - IFNULL("
		"  (SELECT SUM(si_item.net_amount) FROM `tabSales Invoice Item` si_item"
		"   JOIN `tabSales Invoice` si ON si.name = si_item.parent"
		"   WHERE si_item.sales_order = so.name AND si.docstatus = 1), 0))"
		" FROM `tabSales Order` so"
		" WHERE so.docstatus = 1"
		" AND so.status NOT IN ('Completed', 'Cancelled', 'Closed')"
		" AND so.per_billed < 100"
		" AND so.name NOT IN (SELECT document_name FROM `tabTag Link`"
		"  WHERE document_type = 'Sales Order' AND tag = 'Zombie')), 0)"
		" + IFNULL((SELECT SUM(si.outstanding_amount / 1.19)"
		" FROM `tabSales Invoice` si"
		" WHERE si.docstatus = 1 AND si.outstanding_amount > 0"
		" AND si.name NOT IN (SELECT document_name FROM `tabTag Link`"
		"  WHERE document_type = 'Sales Invoice' AND tag = 'Zombie')), 0)"
		" AS total_outstanding",
		as_dict=True)
	outstanding = float(outstanding_result[0].get("total_outstanding") or 0) if outstanding_result else 0

	angebote_result = frappe.db.sql(
		"SELECT IFNULL(SUM(net_total), 0) AS total FROM `tabQuotation`"
		" WHERE docstatus = 1 AND status NOT IN ('Ordered', 'Partially Ordered', 'Cancelled', 'Lost')",
		as_dict=True)
	liegende_angebote = float(angebote_result[0].get("total") or 0) if angebote_result else 0

	angebots_anteil = liegende_angebote * (angebotsumwandlung / 100)
	absehbarer_umsatz = umsatz_ist + outstanding + angebots_anteil

	reale_umsatzluecke = umsatz_ist + outstanding - umsatz_soll
	vorr_umsatzluecke = absehbarer_umsatz - umsatz_soll

	empty = {"einnahmen_brutto": 0, "ausgaben_brutto": 0, "saldo_brutto": 0, "liq_brutto": 0,
		"einnahmen_netto": 0, "ausgaben_netto": 0, "saldo_netto": 0,
		"ausgaben_tag": 0, "burnrate_m": 0}

	prows = [
		dict(empty, monat="---",                                              jahr="", prognose_eur=0,                                          prognose_zahl=0),
		dict(empty, monat="PROGNOSE " + current_year,                         jahr="", prognose_eur=0,                                          prognose_zahl=0),
		dict(empty, monat="Liq-Quelle (" + liq_quelle + ")",                  jahr="", prognose_eur=aktuell_liq if use_aktuell else start_jan_brutto, prognose_zahl=0),
		dict(empty, monat="Abgeleiteter Start Jan (Brutto)",                  jahr="", prognose_eur=start_jan_brutto,                           prognose_zahl=0),
		dict(empty, monat="Burnrate/Tag auto (Brutto)",                       jahr="", prognose_eur=avg_aus_tag_brutto_auto,                    prognose_zahl=0),
		dict(empty, monat="Burnrate/Tag verwendet (" + burnrate_quelle + ")", jahr="", prognose_eur=avg_aus_tag_brutto_final,                   prognose_zahl=0),
		dict(empty, monat="Burnrate/Monat (Brutto)",                          jahr="", prognose_eur=burnrate_m_brutto_final,                    prognose_zahl=0),
		dict(empty, monat="Umsatz Soll (Brutto/Jahr)",                        jahr="", prognose_eur=umsatz_soll,                                prognose_zahl=0),
		dict(empty, monat="Umsatz Ist (Einnahmen YTD Netto)",                 jahr="", prognose_eur=umsatz_ist,                                 prognose_zahl=0),
		dict(empty, monat="Liquiditaet aktuell (Brutto)",                     jahr="", prognose_eur=current_liq_brutto,                         prognose_zahl=0),
		dict(empty, monat="Snapshot Kontostand (Brutto)",                     jahr="", prognose_eur=snapshot_liq,                               prognose_zahl=0),
		dict(empty, monat="Tage ohne Zahlungseingang",                       jahr="", prognose_eur=0,                                          prognose_zahl=tage_ohne),
		dict(empty, monat="Monate ohne Zahlungseingang",                     jahr="", prognose_eur=0,                                          prognose_zahl=monate_ohne),
		dict(empty, monat="Outstanding bestehende Auftraege",                jahr="", prognose_eur=outstanding,                                prognose_zahl=0),
		dict(empty, monat="Reale Umsatzluecke (Ist+Out-Soll)",               jahr="", prognose_eur=reale_umsatzluecke,                         prognose_zahl=0),
		dict(empty, monat="---",                                              jahr="", prognose_eur=0,                                          prognose_zahl=0),
		dict(empty, monat="Liegende Angebote",                               jahr="", prognose_eur=liegende_angebote,                          prognose_zahl=0),
		dict(empty, monat="Angebotsumwandlung %",                            jahr="", prognose_eur=0,                                          prognose_zahl=angebotsumwandlung),
		dict(empty, monat="Angebots-Anteil",                                 jahr="", prognose_eur=angebots_anteil,                            prognose_zahl=0),
		dict(empty, monat="Absehbarer Umsatz (Ist+Out+Angebote)",            jahr="", prognose_eur=absehbarer_umsatz,                          prognose_zahl=0),
		dict(empty, monat="Vorraussichtliche Umsatzluecke (Absehbar-Soll)",  jahr="", prognose_eur=vorr_umsatzluecke,                          prognose_zahl=0),
	]

	return rows + prows
