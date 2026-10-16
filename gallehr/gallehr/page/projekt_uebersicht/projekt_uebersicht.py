"""Backend fuer das Aufklappen der Zeilen auf der "Projekt Uebersicht"-Seite.

Die Zahlen der Seite kommen aus dem Script-Report "Projekt Übersicht". Hier
wird dieselbe Logik (Zeitraum, Zombie-Tag, Status/Unternehmen, Kennzahl)
nochmal je Zeile heruntergebrochen, damit die Unterzeilen sich exakt auf die
Zahl der aufgeklappten Zeile aufsummieren:

  - Projekt -> Sales Orders (je nach Kennzahl: Auftragswert der Positionen mit
    Liefertermin im Zeitraum, bzw. ueber die Rechnungspositionen fakturierter
    Betrag je Sales Order)
  - PM      -> Projekte dieses PM (jedes Projekt klappt dann selbst zu
    seinen Sales Orders auf)
"""

import frappe
from frappe import _
from frappe.utils import flt, formatdate

ABGESCHLOSSEN_STATUS = ("Completed", "Cancelled")

PM_KEY = "JSON_UNQUOTE(JSON_EXTRACT(p.`_assign`, '$[0]'))"

# Reihenfolge = Prioritaet fuer das Badge, wenn ein Projekt mehrere Gruende hat.
GRUND_PRIORITAET = ["nach_zeitraum", "vor_zeitraum", "entwurf", "zombie", "nur_position", "ohne_datum"]


def _check_permission():
	if not frappe.has_permission("Sales Order", "read"):
		frappe.throw(_("Keine Berechtigung fuer Sales Orders"), frappe.PermissionError)


def grund_fuer_position(docstatus, zombie, datum, von, bis):
	"""Warum zaehlt ein Beleg bzw. eine Position NICHT in den Zeitraum? None = zaehlt.

	Dieselbe Regel wie der Report (bestaetigt, kein Zombie-Tag, Stichtag im
	Zeitraum, Grenzen inklusive) -- einzige Quelle fuer die grauen Zeilen und die
	Badges, damit eine 0-EUR-Zeile nie ohne Erklaerung bleibt."""
	if docstatus != 1:
		return "entwurf"
	if zombie:
		return "zombie"
	if not datum:
		return "ohne_datum"
	datum = str(datum)
	if datum < str(von):
		return "vor_zeitraum"
	if datum > str(bis):
		return "nach_zeitraum"
	return None


def _datum_text(werte):
	werte = sorted(set(str(w) for w in werte))
	if len(werte) == 1:
		return formatdate(werte[0], "dd.mm.yyyy")
	return formatdate(werte[0], "dd.mm.yyyy") + " bis " + formatdate(werte[-1], "dd.mm.yyyy")


def _grund_text(grund, stichtage, datum_label):
	if grund == "entwurf":
		return _("Entwurf, nicht bestätigt")
	if grund == "zombie":
		return _("Zombie-markiert")
	if grund == "nur_position":
		return _("Projekt nur an der Position gesetzt, nicht im Kopf des Belegs")
	if grund == "ohne_datum":
		return _("ohne Datum")
	lage = _("nach dem Zeitraum") if grund == "nach_zeitraum" else _("vor dem Zeitraum")
	return datum_label + " " + _datum_text(stichtage) + " – " + lage


def _ausserhalb(keys, von, bis, kennzahl):
	"""{projekt: [eintrag]} -- Belege, die NICHT in die Zahl der Zeile einfliessen, mit Grund.

	Partitioniert zusammen mit den SQLs in _auftraege_je_projekt: jede Position
	bzw. Rechnung des Projekts landet entweder dort (zaehlt) oder hier (mit Grund)."""
	out = {k: [] for k in keys}
	if not keys:
		return out
	params = {"keys": tuple(keys), "von": von, "bis": bis}
	auftragswert = kennzahl == "Auftragswert"
	doctype = "Sales Order" if auftragswert else "Sales Invoice"
	datum_label = _("Liefertermin") if auftragswert else _("Rechnungsdatum")
	zombie_sql = (
		"EXISTS (SELECT 1 FROM `tabTag Link` tl WHERE tl.document_type = '" + doctype +
		"' AND tl.document_name = {alias}.name AND tl.tag = 'Zombie') AS zombie"
	)

	if auftragswert:
		rows = frappe.db.sql(
			"SELECT so.project AS projekt, so.name AS name, so.docstatus AS docstatus, "
			"so.transaction_date AS datum, soi.base_net_amount AS betrag, "
			"COALESCE(soi.delivery_date, so.delivery_date, so.transaction_date) AS stichtag, "
			+ zombie_sql.format(alias="so") + " "
			"FROM `tabSales Order Item` soi JOIN `tabSales Order` so ON so.name = soi.parent "
			"WHERE so.project IN %(keys)s AND so.docstatus < 2",
			params, as_dict=True,
		)
		fremd = frappe.db.sql(
			"SELECT soi.project AS projekt, so.name AS name, so.transaction_date AS datum, "
			"SUM(soi.base_net_amount) AS betrag "
			"FROM `tabSales Order Item` soi JOIN `tabSales Order` so ON so.name = soi.parent "
			"WHERE soi.project IN %(keys)s AND IFNULL(so.project, '') != soi.project AND so.docstatus < 2 "
			"GROUP BY soi.project, so.name, so.transaction_date",
			params, as_dict=True,
		)
	else:
		rows = frappe.db.sql(
			"SELECT si.project AS projekt, si.name AS name, si.docstatus AS docstatus, "
			"si.posting_date AS datum, si.net_total AS betrag, si.posting_date AS stichtag, "
			+ zombie_sql.format(alias="si") + " "
			"FROM `tabSales Invoice` si WHERE si.project IN %(keys)s AND si.docstatus < 2",
			params, as_dict=True,
		)
		fremd = frappe.db.sql(
			"SELECT sii.project AS projekt, si.name AS name, si.posting_date AS datum, "
			"SUM(sii.base_net_amount) AS betrag "
			"FROM `tabSales Invoice Item` sii JOIN `tabSales Invoice` si ON si.name = sii.parent "
			"WHERE sii.project IN %(keys)s AND IFNULL(si.project, '') != sii.project AND si.docstatus < 2 "
			"GROUP BY sii.project, si.name, si.posting_date",
			params, as_dict=True,
		)

	agg = {}
	for r in rows:
		grund = grund_fuer_position(r.docstatus, r.zombie, r.stichtag, von, bis)
		if not grund:
			continue
		e = agg.setdefault((r.projekt, r.name), {
			"doctype": doctype, "name": r.name, "datum": str(r.datum or ""), "umsatz": 0.0, "gruende": {},
		})
		e["umsatz"] += flt(r.betrag)
		e["gruende"].setdefault(grund, []).append(r.stichtag)
	for r in fremd:
		agg[(r.projekt, r.name)] = {
			"doctype": doctype, "name": r.name, "datum": str(r.datum or ""), "umsatz": flt(r.betrag),
			"gruende": {"nur_position": []},
		}

	for (projekt, _name), e in agg.items():
		gruende = e.pop("gruende")
		reihenfolge = [g for g in GRUND_PRIORITAET if g in gruende]
		e["grund"] = reihenfolge[0]
		e["hinweis"] = " · ".join(_grund_text(g, gruende[g], datum_label) for g in reihenfolge)
		out[projekt].append(e)
	for eintraege in out.values():
		eintraege.sort(key=lambda e: (e["datum"], e["name"]))
	return out


def _laufzeit(projekt, von, bis):
	p = frappe.db.get_value("Project", projekt, ["expected_start_date", "expected_end_date"], as_dict=True) or {}
	start, ende = p.get("expected_start_date"), p.get("expected_end_date")
	im_zeitraum = any(d and str(von) <= str(d) <= str(bis) for d in (start, ende))
	return {"start": str(start or ""), "ende": str(ende or ""), "im_zeitraum": im_zeitraum}


@frappe.whitelist()
def get_nullzeilen_hinweise(keys, von, bis, kennzahl="Auftragswert"):
	"""Badge-Texte fuer Projektzeilen mit 0 EUR: {projekt: {text, title}}.
	Nur fuer Zeilen aufrufen, die in der Kennzahl tatsaechlich 0 EUR zeigen.

	Beantwortet "warum steht das Projekt hier, obwohl es nichts zaehlt?" --
	entweder Belege ausserhalb des Zeitraums (mit Beleg und Datum im Tooltip)
	oder nur wegen der geplanten Projektlaufzeit."""
	_check_permission()
	if kennzahl not in ("Auftragswert", "Fakturiert"):
		frappe.throw(_("Unbekannte Kennzahl"))
	keys = frappe.parse_json(keys) if isinstance(keys, str) else keys
	keys = [k for k in (keys or []) if k][:300]

	beleg = _("Auftrag") if kennzahl == "Auftragswert" else _("Rechnung")
	texte = {
		"nach_zeitraum": beleg + " " + _("außerhalb Zeitraum"),
		"vor_zeitraum": beleg + " " + _("außerhalb Zeitraum"),
		"entwurf": beleg + " " + _("nur Entwurf"),
		"zombie": _("Zombie-markiert"),
		"nur_position": _("Projekt nur an Position"),
		"ohne_datum": beleg + " " + _("ohne Datum"),
	}
	ausser = _ausserhalb(keys, von, bis, kennzahl)
	out = {}
	for k in keys:
		eintraege = ausser[k]
		if eintraege:
			erster = min(eintraege, key=lambda e: GRUND_PRIORITAET.index(e["grund"]))
			title = "\n".join(e["name"] + ": " + e["hinweis"] for e in eintraege[:5])
			if len(eintraege) > 5:
				title += "\n… +" + str(len(eintraege) - 5)
			out[k] = {"text": texte[erster["grund"]], "title": title}
			continue
		lz = _laufzeit(k, von, bis)
		if lz["im_zeitraum"]:
			out[k] = {
				"text": _("nur Projektlaufzeit"),
				"title": _("Kein Beleg im Zeitraum – das Projekt steht hier nur wegen der geplanten Laufzeit (Start {0}, Ende {1}).").format(
					formatdate(lz["start"], "dd.mm.yyyy") if lz["start"] else "–",
					formatdate(lz["ende"], "dd.mm.yyyy") if lz["ende"] else "–",
				),
			}
	return out


@frappe.whitelist()
def get_auftraege(scope, key, von, bis, kennzahl="Auftragswert", status="Offen",
		unternehmen="", projektauswahl="Projekt-Laufzeit"):
	"""scope 'projekt': key = Project.name -> Sales Orders.
	scope 'pm': key = User.name des PM ('-' = kein PM zugewiesen) -> Projekte."""
	_check_permission()
	if kennzahl not in ("Auftragswert", "Fakturiert"):
		frappe.throw(_("Unbekannte Kennzahl"))

	if scope == "projekt":
		rows = _auftraege_je_projekt(key, von, bis, kennzahl)
	elif scope == "pm":
		rows = _projekte_je_pm(key, von, bis, kennzahl, status, unternehmen, projektauswahl)
	else:
		frappe.throw(_("Unbekannter Bereich"))

	gesamt = sum(r["umsatz"] for r in rows)
	for r in rows:
		r["anteil"] = (r["umsatz"] / gesamt * 100.0) if gesamt else 0.0
	rows.sort(key=lambda r: r["umsatz"], reverse=True)
	result = {"scope": scope, "kennzahl": kennzahl, "gesamt": gesamt, "rows": rows}
	if scope == "projekt":
		# Alles, was NICHT in gesamt einfliesst, inkl. Grund -- gesamt/anteil bleiben
		# davon unberuehrt (siehe _ausserhalb).
		result["ausserhalb"] = _ausserhalb([key], von, bis, kennzahl)[key]
		result["laufzeit"] = _laufzeit(key, von, bis)
	return result


def _auftraege_je_projekt(projekt, von, bis, kennzahl):
	params = {"projekt": projekt, "von": von, "bis": bis}

	if kennzahl == "Auftragswert":
		raw = frappe.db.sql(
			"SELECT so.name AS name, so.transaction_date AS datum, "
			"SUM(soi.base_net_amount) AS umsatz, COUNT(*) AS positionen "
			"FROM `tabSales Order Item` soi "
			"JOIN `tabSales Order` so ON so.name = soi.parent "
			"WHERE so.docstatus = 1 AND so.project = %(projekt)s "
			"AND COALESCE(soi.delivery_date, so.delivery_date, so.transaction_date) BETWEEN %(von)s AND %(bis)s "
			"AND so.name NOT IN ("
			"  SELECT document_name FROM `tabTag Link`"
			"  WHERE document_type = 'Sales Order' AND tag = 'Zombie'"
			") GROUP BY so.name, so.transaction_date",
			params, as_dict=True,
		)
		return [{
			"name": r.name, "datum": str(r.datum or ""), "umsatz": flt(r.umsatz),
			"positionen": r.positionen,
		} for r in raw]

	# Fakturiert: der Report summiert Sales Invoice.net_total je Rechnung. Die
	# Zuordnung zu Sales Orders laeuft ueber die Rechnungspositionen
	# (sales_order); was keinem Auftrag zugeordnet ist (bzw. Waehrungs-/
	# Rundungsdifferenz zu net_total), landet in einer eigenen Zeile, damit die
	# Summe exakt zur Projektzeile passt.
	zombie = (
		" AND si.name NOT IN (SELECT document_name FROM `tabTag Link`"
		" WHERE document_type = 'Sales Invoice' AND tag = 'Zombie')"
	)
	gesamt = flt(frappe.db.sql(
		"SELECT SUM(si.net_total) FROM `tabSales Invoice` si "
		"WHERE si.docstatus = 1 AND si.project = %(projekt)s "
		"AND si.posting_date BETWEEN %(von)s AND %(bis)s" + zombie,
		params,
	)[0][0])
	raw = frappe.db.sql(
		"SELECT sii.sales_order AS name, so.transaction_date AS datum, "
		"SUM(sii.base_net_amount) AS umsatz, COUNT(*) AS positionen "
		"FROM `tabSales Invoice Item` sii "
		"JOIN `tabSales Invoice` si ON si.name = sii.parent "
		"LEFT JOIN `tabSales Order` so ON so.name = sii.sales_order "
		"WHERE si.docstatus = 1 AND si.project = %(projekt)s "
		"AND si.posting_date BETWEEN %(von)s AND %(bis)s" + zombie +
		" AND IFNULL(sii.sales_order, '') != '' "
		"GROUP BY sii.sales_order, so.transaction_date",
		params, as_dict=True,
	)
	rows = [{
		"name": r.name, "datum": str(r.datum or ""), "umsatz": flt(r.umsatz),
		"positionen": r.positionen,
	} for r in raw]
	rest = gesamt - sum(r["umsatz"] for r in rows)
	if abs(rest) >= 0.005:
		rows.append({"name": "", "datum": "", "umsatz": rest, "positionen": 0, "ohne_auftrag": 1})
	return rows


def _projekte_je_pm(pm, von, bis, kennzahl, status, unternehmen, projektauswahl):
	status_clause = ""
	if status == "Abgeschlossen":
		status_clause = " AND p.status IN %(abgeschlossen)s"
	elif status == "Offen":
		status_clause = " AND (p.status NOT IN %(abgeschlossen)s OR p.status IS NULL)"

	unternehmen_clause = ""
	if unternehmen and unternehmen != "Alle":
		unternehmen_clause = " AND p.company = %(unternehmen)s"

	if pm in ("", "-"):
		pm_clause = " AND " + PM_KEY + " IS NULL"
	else:
		pm_clause = " AND " + PM_KEY + " = %(pm)s"

	params = {
		"von": von, "bis": bis, "pm": pm, "unternehmen": unternehmen,
		"abgeschlossen": ABGESCHLOSSEN_STATUS,
	}
	common = status_clause + unternehmen_clause + pm_clause

	if kennzahl == "Auftragswert":
		raw = frappe.db.sql(
			"SELECT p.name AS key_, IFNULL(p.project_name, p.name) AS label, "
			"SUM(soi.base_net_amount) AS umsatz "
			"FROM `tabSales Order Item` soi "
			"JOIN `tabSales Order` so ON so.name = soi.parent "
			"JOIN `tabProject` p ON p.name = so.project "
			"WHERE so.docstatus = 1 "
			"AND COALESCE(soi.delivery_date, so.delivery_date, so.transaction_date) BETWEEN %(von)s AND %(bis)s "
			"AND so.name NOT IN ("
			"  SELECT document_name FROM `tabTag Link`"
			"  WHERE document_type = 'Sales Order' AND tag = 'Zombie'"
			") " + common + " GROUP BY p.name, p.project_name",
			params, as_dict=True,
		)
	else:
		raw = frappe.db.sql(
			"SELECT p.name AS key_, IFNULL(p.project_name, p.name) AS label, "
			"SUM(b.net_total) AS umsatz "
			"FROM `tabSales Invoice` b "
			"JOIN `tabProject` p ON p.name = b.project "
			"WHERE b.docstatus = 1 AND b.posting_date BETWEEN %(von)s AND %(bis)s "
			"AND b.name NOT IN ("
			"  SELECT document_name FROM `tabTag Link`"
			"  WHERE document_type = 'Sales Invoice' AND tag = 'Zombie'"
			") " + common + " GROUP BY p.name, p.project_name",
			params, as_dict=True,
		)
	rows = [{"key": r.key_, "label": r.label, "umsatz": flt(r.umsatz)} for r in raw]

	# Projekt-Laufzeit: wie im Report auch Projekte ohne Beleg im Zeitraum
	# (Betrag 0), sofern Start oder Ende in den Zeitraum faellt.
	if projektauswahl == "Projekt-Laufzeit":
		vorhanden = set(r["key"] for r in rows)
		zusatz = frappe.db.sql(
			"SELECT p.name AS key_, IFNULL(p.project_name, p.name) AS label "
			"FROM `tabProject` p "
			"WHERE (p.expected_start_date BETWEEN %(von)s AND %(bis)s "
			"    OR p.expected_end_date BETWEEN %(von)s AND %(bis)s)" + common,
			params, as_dict=True,
		)
		for z in zusatz:
			if z.key_ not in vorhanden:
				rows.append({"key": z.key_, "label": z.label, "umsatz": 0.0})
	return rows
