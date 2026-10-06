"""Befuellt 4 read-only Felder auf Bank Transaction (ak_kategorie, ak_aufwandskonto, ak_zuordnung, ak_stand), damit
Ricarda in der Report View von Bank Transaction direkt filtern/gruppieren kann, ohne die AK-Auswertung-Seite
aufzurufen. Rechnet NIE etwas um -- nur Anzeige dessen, was die Seite ohnehin aus den Belegen berechnet.

Klassifiziert JEDE Zuordnungszeile einer BT (Bank Transaction Payments) + den Restbetrag (unallocated_amount),
Regeln siehe Plan-Tabelle; fuer Journal-Entry-Zeilen wird dieselbe Regeltabelle wie auf der Seite verwendet
(quellen/bank_klassifikation.py) -- eine Stelle fuer die Logik, zwei Verbraucher (Seite + diese Felder).

Herkunft/Live-Verifikation der Regeln (0 Abweichungen auf 2811 Bank Transactions, 06.10.2026):
~/Desktop/work/ricarda_feature/v2_bankbuchungen/skripte/skript_E_bt_lueckenlos.py

Drei Aufrufer (siehe hooks.py): doc_events bei jeder Aenderung einer BT, ein taeglicher Scheduler-Job (faengt
Direktschreiben durch den Abgleich-Wizard und spaetere Aenderungen wie "Anzahlung -> spaeter Rechnung"), und
after_migrate (Erstbefuellung bei jedem Deploy, keine Handarbeit).
"""

import frappe
from frappe.utils import flt, now_datetime

from gallehr.gallehr.page.ak_auswertung.quellen import bank_klassifikation as k

FELDER = ["ak_kategorie", "ak_aufwandskonto", "ak_zuordnung", "ak_stand"]
_RUNDUNG = 0.005


def _bankkonten():
	return set(frappe.db.sql_list("SELECT DISTINCT account FROM `tabBank Account` WHERE account IS NOT NULL"))


def _lade_bts(bt_namen=None):
	filter_sql = "WHERE bt.docstatus = 1"
	params = {}
	if bt_namen:
		filter_sql += " AND bt.name IN %(namen)s"
		params["namen"] = tuple(bt_namen)
	bts = {}
	for r in frappe.db.sql(
		f"""
		SELECT bt.name, bt.withdrawal, bt.deposit, bt.unallocated_amount, ba.account AS bank_konto,
			EXISTS (SELECT 1 FROM `tabTag Link` tl WHERE tl.document_type = 'Bank Transaction'
				AND tl.document_name = bt.name AND tl.tag = 'Umbuchung') AS umbuchung_tag
		FROM `tabBank Transaction` bt
		LEFT JOIN `tabBank Account` ba ON ba.name = bt.bank_account
		{filter_sql}""",
		params, as_dict=True,
	):
		bewegung = float(r.withdrawal or 0) - float(r.deposit or 0)
		bts[r.name] = {
			"bewegung": bewegung, "bank_konto": r.bank_konto, "umbuchung_tag": bool(r.umbuchung_tag),
			"unallocated": float(r.unallocated_amount or 0), "zeilen": [],
		}
	return bts


def _lade_btp(bt_namen):
	if not bt_namen:
		return []
	return frappe.db.sql(
		"""SELECT btp.parent AS bt, btp.payment_document AS art, btp.payment_entry AS beleg,
			btp.allocated_amount AS betrag
		FROM `tabBank Transaction Payments` btp WHERE btp.parent IN %(n)s""",
		{"n": tuple(bt_namen)}, as_dict=True,
	)


def _lade_pe_info(pe_namen):
	pe = {}
	if not pe_namen:
		return pe
	for r in frappe.db.sql(
		"SELECT name, payment_type FROM `tabPayment Entry` WHERE name IN %(n)s", {"n": tuple(pe_namen)}, as_dict=True,
	):
		pe[r.name] = {"payment_type": r.payment_type, "referenzen": set()}
	for r in frappe.db.sql(
		"SELECT parent, reference_doctype FROM `tabPayment Entry Reference` WHERE parent IN %(n)s",
		{"n": tuple(pe_namen)}, as_dict=True,
	):
		if r.parent in pe:
			pe[r.parent]["referenzen"].add(r.reference_doctype)
	return pe


def klassifiziere_bts(bt_namen=None):
	"""Liefert {bt_name: {"zeilen": [(kategorie, betrag_signiert), ...], "bewegung": float}}. `betrag_signiert`
	traegt immer das Vorzeichen der BT-Bewegung (>0 Auszahlung/Kosten, <0 Gutschrift/Erstattung)."""
	bts = _lade_bts(bt_namen)
	if not bts:
		return {}
	btp = [r for r in _lade_btp(list(bts)) if r.bt in bts]
	pe_namen = {r.beleg for r in btp if r.art == "Payment Entry"}
	je_namen = {r.beleg for r in btp if r.art == "Journal Entry"}
	pe_info = _lade_pe_info(pe_namen)
	je_zeilen_klassifiziert = k.klassifiziere_je_zeilen(list(je_namen)) if je_namen else []
	je_zeilen_je = {}
	for z in je_zeilen_klassifiziert:
		je_zeilen_je.setdefault(z["je"], []).append(z)
	alle_bankkonten = _bankkonten()

	for r in btp:
		b = bts[r.bt]
		vorzeichen = 1.0 if b["bewegung"] >= 0 else -1.0
		betrag = vorzeichen * flt(r.betrag)
		if r.art == "Purchase Invoice":
			b["zeilen"].append((k.EINGANGSRECHNUNG, betrag, None))
		elif r.art == "Sales Invoice":
			b["zeilen"].append((k.EINNAHME, betrag, None))
		elif r.art == "Bank Transaction":
			b["zeilen"].append((k.GEGENBUCHUNG, betrag, None))
		elif r.art == "Payment Entry":
			info = pe_info.get(r.beleg)
			if not info:
				b["zeilen"].append((k.UNKLASSIFIZIERT, betrag, None))
			elif "Purchase Invoice" in info["referenzen"]:
				b["zeilen"].append((k.EINGANGSRECHNUNG, betrag, None))
			elif "Sales Invoice" in info["referenzen"]:
				b["zeilen"].append((k.EINNAHME, betrag, None))
			elif "Expense Claim" in info["referenzen"]:
				b["zeilen"].append((k.KOSTEN_OHNE_RECHNUNG, betrag, None))
			elif info["payment_type"] == "Internal Transfer":
				b["zeilen"].append((k.UMBUCHUNG, betrag, None))
			elif info["payment_type"] == "Receive":
				b["zeilen"].append((k.EINNAHME, betrag, None))
			else:
				b["zeilen"].append((k.ZAHLUNG_OHNE_RECHNUNG, betrag, None))
		elif r.art == "Journal Entry":
			zeilen = [z for z in je_zeilen_je.get(r.beleg, []) if z["konto_voll"] != b["bank_konto"]]
			gewicht_summe = sum(abs(z["betrag"]) for z in zeilen)
			if not zeilen or gewicht_summe == 0:
				b["zeilen"].append((k.UNKLASSIFIZIERT, betrag, None))
			else:
				for z in zeilen:
					gewicht = abs(z["betrag"]) / gewicht_summe
					kat = z["kategorie"] if not b["umbuchung_tag"] else k.UMBUCHUNG
					konto = z["konto_voll"] if kat in k.KOSTEN_KATEGORIEN else None
					b["zeilen"].append((kat, betrag * gewicht, konto))
		else:
			b["zeilen"].append((k.UNKLASSIFIZIERT, betrag, None))

	for name, b in bts.items():
		vorzeichen = 1.0 if b["bewegung"] >= 0 else -1.0
		rest = vorzeichen * b["unallocated"]
		if abs(rest) > _RUNDUNG:
			b["zeilen"].append((k.OHNE_BELEG, rest, None))

	return bts


def ak_felder(bt_zeilen):
	"""Aus der Zeilenliste einer einzelnen BT die 4 Feldwerte ableiten."""
	kategorien = {z[0] for z in bt_zeilen["zeilen"]}
	if len(kategorien) == 1:
		ak_kategorie = next(iter(kategorien))
	elif not kategorien:
		ak_kategorie = k.OHNE_BELEG
	else:
		ak_kategorie = "gemischt"

	konten = {z[2] for z in bt_zeilen["zeilen"] if z[2]}
	ak_aufwandskonto = next(iter(konten)) if len(konten) == 1 else None

	summen = {}
	for kat, betrag, _konto in bt_zeilen["zeilen"]:
		summen[kat] = summen.get(kat, 0.0) + betrag
	zuordnung = " | ".join("%s: %s" % (kat, "%.2f" % flt(summe, 2)) for kat, summe in sorted(summen.items(), key=lambda kv: -abs(kv[1])))

	return {"ak_kategorie": ak_kategorie, "ak_aufwandskonto": ak_aufwandskonto, "ak_zuordnung": zuordnung,
		"ak_stand": now_datetime()}


def sync(bt_namen=None):
	"""Berechnet neu und schreibt nur, was sich geaendert hat (db_set, update_modified=False -- siehe Plan:
	nur die 4 ak_*-Felder, nie ein Beleg/Betrag). Gibt die Anzahl tatsaechlich geaenderter BTs zurueck."""
	klassifiziert = klassifiziere_bts(bt_namen)
	geaendert = 0
	for name, bt_zeilen in klassifiziert.items():
		neu = ak_felder(bt_zeilen)
		alt = frappe.db.get_value("Bank Transaction", name, FELDER, as_dict=True) or {}
		if alt.get("ak_kategorie") == neu["ak_kategorie"] and alt.get("ak_aufwandskonto") == neu["ak_aufwandskonto"] \
				and (alt.get("ak_zuordnung") or "") == neu["ak_zuordnung"]:
			continue
		frappe.db.set_value("Bank Transaction", name, neu, update_modified=False)
		geaendert += 1
	return geaendert


# ---- Aufrufer (hooks.py) -------------------------------------------------------------------------------------

def bei_aenderung(doc, method=None):
	sync([doc.name])


def taeglich():
	alle = frappe.db.sql_list("SELECT name FROM `tabBank Transaction` WHERE docstatus = 1")
	return sync(alle)


def nach_migration():
	return taeglich()
