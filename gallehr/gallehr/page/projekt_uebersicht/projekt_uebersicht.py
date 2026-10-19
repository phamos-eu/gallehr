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

Zeilen sind einzelne Positionen mit ihrem Beschreibungstext (nicht nur die
Auftragsnummer), damit man auf einen Blick sieht, was unter dem Projekt steckt.

Zweiter Modus "offen" (Zeitraum-Option "Alle offenen Auftraege"): alle noch
nicht abgeschlossenen Auftraege, egal aus welchem Jahr. Auftragswert = voller
Wert der Positionen, Fakturiert = was ueber Rechnungspositionen schon in
Rechnung gestellt ist (Zuordnung ueber das Feld sales_order).
"""

import html
import re

import frappe
from frappe import _
from frappe.utils import flt, formatdate

ABGESCHLOSSEN_STATUS = ("Completed", "Cancelled")

# Sales Order Status, die einen Auftrag als "abgeschlossen" gelten lassen
# (alles andere -- inkl. On Hold -- ist offen).
AUFTRAG_ABGESCHLOSSEN = ("Completed", "Closed", "Cancelled")

PM_KEY = "JSON_UNQUOTE(JSON_EXTRACT(p.`_assign`, '$[0]'))"

# Reihenfolge = Prioritaet fuer das Badge, wenn ein Projekt mehrere Gruende hat.
GRUND_PRIORITAET = ["nach_zeitraum", "vor_zeitraum", "entwurf", "zombie", "nur_position", "ohne_datum"]


def _check_permission():
	if not frappe.has_permission("Sales Order", "read"):
		frappe.throw(_("Keine Berechtigung fuer Sales Orders"), frappe.PermissionError)


def _klartext_zeilen(beschreibung):
	"""Beschreibung (meist HTML aus dem Texteditor) als Liste bereinigter Zeilen."""
	text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</h[1-6]>", "\n", beschreibung or "")
	text = html.unescape(re.sub(r"<[^>]+>", "", text))
	return [" ".join(z.split()) for z in text.split("\n") if z.strip()]


def positionstext(beschreibung, artikelname, max_len=140):
	"""Kurztext einer Position: erste Zeile der Beschreibung, sonst der Artikelname."""
	zeilen = _klartext_zeilen(beschreibung)
	text = zeilen[0] if zeilen else (artikelname or "").strip()
	return text if len(text) <= max_len else text[: max_len - 1].rstrip() + "…"


def positionstext_voll(beschreibung, artikelname, max_len=600):
	"""Voller Text fuer den Tooltip (Zeilen untereinander)."""
	zeilen = _klartext_zeilen(beschreibung)
	text = "\n".join(zeilen) if zeilen else (artikelname or "").strip()
	return text if len(text) <= max_len else text[: max_len - 1].rstrip() + "…"


def _zeile(name, datum, betrag, item_name, beschreibung):
	return {
		"name": name, "datum": str(datum or ""), "umsatz": flt(betrag),
		"text": positionstext(beschreibung, item_name),
		"text_voll": positionstext_voll(beschreibung, item_name),
	}


def _position_row(r):
	return _zeile(r.name, r.datum, r.umsatz, r.item_name, r.beschreibung)


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
			"soi.item_name AS item_name, soi.description AS beschreibung, "
			"COALESCE(soi.delivery_date, so.delivery_date, so.transaction_date) AS stichtag, "
			+ zombie_sql.format(alias="so") + " "
			"FROM `tabSales Order Item` soi JOIN `tabSales Order` so ON so.name = soi.parent "
			"WHERE so.project IN %(keys)s AND so.docstatus < 2 ORDER BY so.transaction_date, so.name, soi.idx",
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
			"doctype": doctype, "name": r.name, "datum": str(r.datum or ""), "umsatz": 0.0, "gruende": {}, "texte": [],
		})
		e["umsatz"] += flt(r.betrag)
		e["gruende"].setdefault(grund, []).append(r.stichtag)
		if auftragswert:
			e["texte"].append(positionstext(r.beschreibung, r.item_name))
	for r in fremd:
		agg[(r.projekt, r.name)] = {
			"doctype": doctype, "name": r.name, "datum": str(r.datum or ""), "umsatz": flt(r.betrag),
			"gruende": {"nur_position": []}, "texte": [],
		}

	if not auftragswert and agg:
		items = frappe.db.sql(
			"SELECT parent, item_name, description AS beschreibung FROM `tabSales Invoice Item` "
			"WHERE parent IN %(namen)s ORDER BY parent, idx",
			{"namen": tuple(set(n for (_p, n) in agg))}, as_dict=True,
		)
		for it in items:
			for (_p, n), e in agg.items():
				if n == it.parent:
					e["texte"].append(positionstext(it.beschreibung, it.item_name))

	for (projekt, _name), e in agg.items():
		gruende = e.pop("gruende")
		texte = []
		for t in e.pop("texte"):
			if t and t not in texte:
				texte.append(t)
		e["text"] = (texte[0] + (" (+" + str(len(texte) - 1) + " weitere)" if len(texte) > 1 else "")) if texte else ""
		e["text_voll"] = "\n".join(texte)[:600]
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
def get_auftraege(scope, key, von="", bis="", kennzahl="Auftragswert", status="Offen",
		unternehmen="", projektauswahl="Projekt-Laufzeit", modus="zeitraum"):
	"""scope 'projekt': key = Project.name -> Positionen der Sales Orders.
	scope 'pm': key = User.name des PM ('-' = kein PM zugewiesen) -> Projekte.
	modus 'offen': alle offenen Auftraege, von/bis werden ignoriert."""
	_check_permission()
	if kennzahl not in ("Auftragswert", "Fakturiert"):
		frappe.throw(_("Unbekannte Kennzahl"))
	if scope not in ("projekt", "pm"):
		frappe.throw(_("Unbekannter Bereich"))
	offen = modus == "offen"

	if offen:
		rows = _offene_zeilen(scope, key, kennzahl, status, unternehmen)
	elif scope == "projekt":
		rows = _auftraege_je_projekt(key, von, bis, kennzahl)
	else:
		rows = _projekte_je_pm(key, von, bis, kennzahl, status, unternehmen, projektauswahl)

	gesamt = sum(r["umsatz"] for r in rows)
	for r in rows:
		r["anteil"] = (r["umsatz"] / gesamt * 100.0) if gesamt else 0.0
	rows.sort(key=lambda r: r["umsatz"], reverse=True)
	result = {"scope": scope, "kennzahl": kennzahl, "modus": modus, "gesamt": gesamt, "rows": rows}
	if scope == "projekt" and not offen:
		# Alles, was NICHT in gesamt einfliesst, inkl. Grund -- gesamt/anteil bleiben
		# davon unberuehrt (siehe _ausserhalb).
		result["ausserhalb"] = _ausserhalb([key], von, bis, kennzahl)[key]
		result["laufzeit"] = _laufzeit(key, von, bis)
	return result


def _auftraege_je_projekt(projekt, von, bis, kennzahl):
	params = {"projekt": projekt, "von": von, "bis": bis}

	if kennzahl == "Auftragswert":
		raw = frappe.db.sql(
			"SELECT so.name AS name, so.transaction_date AS datum, soi.base_net_amount AS umsatz, "
			"soi.item_name AS item_name, soi.description AS beschreibung "
			"FROM `tabSales Order Item` soi "
			"JOIN `tabSales Order` so ON so.name = soi.parent "
			"WHERE so.docstatus = 1 AND so.project = %(projekt)s "
			"AND COALESCE(soi.delivery_date, so.delivery_date, so.transaction_date) BETWEEN %(von)s AND %(bis)s "
			"AND so.name NOT IN ("
			"  SELECT document_name FROM `tabTag Link`"
			"  WHERE document_type = 'Sales Order' AND tag = 'Zombie'"
			") ORDER BY so.transaction_date, so.name, soi.idx",
			params, as_dict=True,
		)
		return [_position_row(r) for r in raw]

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
		"SELECT sii.sales_order AS name, so.transaction_date AS datum, sii.base_net_amount AS umsatz, "
		"sii.item_name AS item_name, sii.description AS beschreibung "
		"FROM `tabSales Invoice Item` sii "
		"JOIN `tabSales Invoice` si ON si.name = sii.parent "
		"LEFT JOIN `tabSales Order` so ON so.name = sii.sales_order "
		"WHERE si.docstatus = 1 AND si.project = %(projekt)s "
		"AND si.posting_date BETWEEN %(von)s AND %(bis)s" + zombie +
		" AND IFNULL(sii.sales_order, '') != '' "
		"ORDER BY so.transaction_date, sii.sales_order, sii.idx",
		params, as_dict=True,
	)
	rows = [_position_row(r) for r in raw]
	rest = gesamt - sum(r["umsatz"] for r in rows)
	if abs(rest) >= 0.005:
		rows.append({"name": "", "datum": "", "umsatz": rest, "ohne_auftrag": 1, "text": "", "text_voll": ""})
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


# --- Modus "Alle offenen Auftraege" -----------------------------------------

def _offene_daten(status, unternehmen, pm=None, projekt=None):
	"""Positionen aller offenen Auftraege (jedes Jahr) samt zugeordneter Rechnungspositionen.

	offen = bestaetigter Auftrag, Status nicht Completed/Closed/Cancelled, kein
	Zombie-Tag, Projekt gemaess Statusfilter (Seite: Offen) und Unternehmen.
	Auftragswert je Auftrag = Summe der Positionen, Fakturiert je Auftrag = Summe
	der Rechnungspositionen mit sales_order = dieser Auftrag (bestaetigte Rechnung,
	kein Zombie-Tag). Rechnungen ohne Auftragsbezug kommen hier bewusst nicht vor."""
	status_clause = ""
	if status == "Abgeschlossen":
		status_clause = " AND p.status IN %(abgeschlossen)s"
	elif status == "Offen":
		status_clause = " AND (p.status NOT IN %(abgeschlossen)s OR p.status IS NULL)"
	unternehmen_clause = ""
	if unternehmen and unternehmen != "Alle":
		unternehmen_clause = " AND p.company = %(unternehmen)s"
	params = {
		"abgeschlossen": ABGESCHLOSSEN_STATUS, "zu": AUFTRAG_ABGESCHLOSSEN, "unternehmen": unternehmen,
	}

	pos = frappe.db.sql(
		"SELECT so.name AS name, so.transaction_date AS datum, soi.base_net_amount AS betrag, "
		"soi.item_name AS item_name, soi.description AS beschreibung, "
		"IFNULL(p.project_type, 'Ohne Typ') AS typ, p.name AS proj_key, IFNULL(p.project_name, p.name) AS proj_label, "
		"p.customer AS kunde_key, "
		"CASE WHEN EXISTS ("
		"    SELECT 1 FROM `tabCompany` co WHERE co.name = p.customer OR co.name = c.customer_name"
		"  ) THEN CONCAT(IFNULL(c.customer_name, p.customer, 'Unbekannt'), ' (eigenes Unternehmen)')"
		"  ELSE IFNULL(c.customer_name, p.customer, 'Unbekannt')"
		"END AS kunde_label, "
		+ PM_KEY + " AS pm_key, IFNULL(u.full_name, 'Kein PM zugewiesen') AS pm_label "
		"FROM `tabSales Order Item` soi "
		"JOIN `tabSales Order` so ON so.name = soi.parent "
		"JOIN `tabProject` p ON p.name = so.project "
		"LEFT JOIN `tabCustomer` c ON c.name = p.customer "
		"LEFT JOIN `tabUser` u ON u.name = " + PM_KEY + " "
		"WHERE so.docstatus = 1 AND IFNULL(so.status, '') NOT IN %(zu)s "
		"AND so.name NOT IN ("
		"  SELECT document_name FROM `tabTag Link`"
		"  WHERE document_type = 'Sales Order' AND tag = 'Zombie'"
		") " + status_clause + unternehmen_clause +
		" ORDER BY so.transaction_date, so.name, soi.idx",
		params, as_dict=True,
	)
	if projekt is not None:
		pos = [r for r in pos if r.proj_key == projekt]
	if pm is not None:
		pm_norm = None if pm in ("", "-") else pm
		pos = [r for r in pos if r.pm_key == pm_norm]

	namen = tuple(set(r.name for r in pos))
	rech = []
	if namen:
		rech = frappe.db.sql(
			"SELECT sii.sales_order AS name, si.posting_date AS datum, sii.base_net_amount AS betrag, "
			"sii.item_name AS item_name, sii.description AS beschreibung "
			"FROM `tabSales Invoice Item` sii JOIN `tabSales Invoice` si ON si.name = sii.parent "
			"WHERE si.docstatus = 1 AND sii.sales_order IN %(namen)s AND si.name NOT IN ("
			"  SELECT document_name FROM `tabTag Link`"
			"  WHERE document_type = 'Sales Invoice' AND tag = 'Zombie'"
			") ORDER BY si.posting_date, si.name, sii.idx",
			{"namen": namen}, as_dict=True,
		)

	auftragswert, fakturiert, attr = {}, {}, {}
	for r in pos:
		auftragswert[r.name] = auftragswert.get(r.name, 0.0) + flt(r.betrag)
		attr.setdefault(r.name, r)
	for r in rech:
		fakturiert[r.name] = fakturiert.get(r.name, 0.0) + flt(r.betrag)
	return {"pos": pos, "rech": rech, "auftragswert": auftragswert, "fakturiert": fakturiert, "attr": attr}


def _offene_buckets(d, kennzahl):
	"""{view: {key: {key, label, umsatz}}} fuer typ/projekt/kunde/pm -- jedes Projekt mit
	offenem Auftrag erscheint, auch mit 0 EUR Fakturiert."""
	views = {
		"typ": ("typ", "typ"), "projekt": ("proj_key", "proj_label"),
		"kunde": ("kunde_key", "kunde_label"), "pm": ("pm_key", "pm_label"),
	}
	buckets = {v: {} for v in views}
	for r in d["pos"]:
		for view, (kf, lf) in views.items():
			k = r[kf] or "-"
			b = buckets[view].setdefault(k, {"key": k, "label": r[lf] or "-", "umsatz": 0.0})
			if kennzahl == "Auftragswert":
				b["umsatz"] += flt(r.betrag)
	if kennzahl == "Fakturiert":
		for so_name, f in d["fakturiert"].items():
			r = d["attr"][so_name]
			for view, (kf, _lf) in views.items():
				buckets[view][r[kf] or "-"]["umsatz"] += f
	return buckets


def _offene_zeilen(scope, key, kennzahl, status, unternehmen):
	if scope == "pm":
		d = _offene_daten(status, unternehmen, pm=key)
		return sorted(_offene_buckets(d, kennzahl)["projekt"].values(), key=lambda b: b["umsatz"], reverse=True)

	d = _offene_daten(status, unternehmen, projekt=key)
	if kennzahl == "Auftragswert":
		return [_zeile(r.name, r.datum, r.betrag, r.item_name, r.beschreibung) for r in d["pos"]]
	return [
		_zeile(r.name, d["attr"][r.name].datum, r.betrag, r.item_name, r.beschreibung)
		for r in d["rech"]
	]


@frappe.whitelist()
def get_offene_auftraege(unternehmen="", kennzahl="Auftragswert", status="Offen"):
	"""Hauptansicht fuer die Zeitraum-Option "Alle offenen Auftraege".

	Liefert Zeilen im selben Format wie der Report (view/label/umsatz/anteil/key),
	damit die Seite sie wie Report-Zeilen verarbeiten kann, plus die Kopfzahlen:
	Auftragswert, Fakturiert und "noch nicht fakturiert" (je Auftrag max(0, Auftrags-
	wert - Fakturiert), ueberfakturierte Auftraege werden nicht gegengerechnet)."""
	_check_permission()
	if kennzahl not in ("Auftragswert", "Fakturiert"):
		frappe.throw(_("Unbekannte Kennzahl"))
	d = _offene_daten(status, unternehmen)
	buckets = _offene_buckets(d, kennzahl)

	rows = []
	for view, b in buckets.items():
		liste = sorted(b.values(), key=lambda x: x["umsatz"], reverse=True)
		gesamt = sum(x["umsatz"] for x in liste)
		for x in liste:
			rows.append({
				"view": view, "label": x["label"], "umsatz": x["umsatz"],
				"anteil": (x["umsatz"] / gesamt * 100.0) if gesamt else 0.0, "key": x["key"],
				"kontinuierlich_hinweis": "", "ueberfakturiert_hinweis": "", "ohne_auftrag_hinweis": "",
			})
	nicht_fakturiert = sum(
		max(0.0, a - d["fakturiert"].get(n, 0.0)) for n, a in d["auftragswert"].items()
	)
	return {
		"rows": rows,
		"auftragswert": sum(d["auftragswert"].values()),
		"fakturiert": sum(d["fakturiert"].values()),
		"nicht_fakturiert": nicht_fakturiert,
		"auftraege": len(d["auftragswert"]),
	}
