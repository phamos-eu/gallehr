"""Filter, Gruppierung, Sortierung der Kostenzeilen (Quelle-unabhaengig).

Alles, was die Seite zeigt (Kopfsumme, Karten, Tabelle, Excel), wird aus derselben gefilterten Zeilenmenge berechnet --
deshalb stimmen die Summen ueberall ueberein. Die Karten "Kostenstelle", "Konto", "Tags" und die Bank-Leiste rechnen
ihren eigenen Filter heraus (ohne=...), damit man die Alternativen weiter sieht und umschalten kann.
"""

import re

import frappe
from frappe.utils import flt

OHNE_TAG = "(ohne Tag)"
UNGEKLAERT = "Kontext (ungeklärt)"
# Tag-Gruppen (Zuordnung im Code, siehe docu): Tags sind nur Kontext und aendern nie die Summe
FAMILIEN = {
	"Zahlungsart": ["Lastschrift", "Lastschrift PayPal", "PP-Lastschrift", "Lastschrift AMZ pay", "Lastschrift Payone",
		"Lastschrift - Gutschrift", "Lastschrift PayPal - Gutschrift"],
	"Weiterbelastung": ["bereits weiterbelastet", "Weiterbelasten RK", "nicht an Kunden"],
	"Standort": ["Büro Wiesbaden", "Standort Wiesbaden", "nEZ Handel"],
	"Konzern": ["Umbuchung", "Verrechnung"],
	"Sonderfall / Thema": ["Fortbildung", "SW Öffentlichkeitsarbeit", "VIK-2025", "Marketing", "Fachveranstaltung 2025", "Mitarbeitersuche"],
}
TAG_FAMILIE = {tag: fam for fam, tags in FAMILIEN.items() for tag in tags}
FAMILIEN_REIHE = list(FAMILIEN) + [UNGEKLAERT]


def familie(tag):
	return TAG_FAMILIE.get(tag, UNGEKLAERT)


def normalisiere(filters):
	f = frappe.parse_json(filters) if filters else {}
	f = f or {}
	sort = f.get("sortierung") or {}
	return {
		"von": f.get("von") or "2000-01-01",
		"bis": f.get("bis") or "2099-12-31",
		"unternehmen": f.get("unternehmen") or "",
		"kostenstelle": f.get("kostenstelle") or "",
		"bank": f.get("bank") or "",
		"kennzahl": "brutto" if f.get("kennzahl") == "brutto" else "netto",
		"konzern_ausblenden": 0 if f.get("konzern_ausblenden") in (0, "0", False) else 1,
		"gruppen": [g for g in (f.get("gruppen") or []) if g],
		"tag": f.get("tag") or "",
		"konto": f.get("konto") or "",
		"spalten": {k: str(v).strip() for k, v in (f.get("spalten") or {}).items() if str(v).strip()},
		"sortierung": {"k": sort.get("k") or "betrag", "richtung": -1 if flt(sort.get("richtung", -1)) < 0 else 1, "abs": bool(sort.get("abs", True))},
	}


def betrag(z, f):
	return z["brutto"] if f["kennzahl"] == "brutto" else z["netto"]


# ---- Spaltenfilter (wie Report View): Text = "enthaelt", Zahl mit Vergleich/Bereich, Datum mit Vergleich ---------------
_NUM_NACKT = re.compile(r"^-?\d+(,\d+)?$")
_NUM_OP = re.compile(r"^(>=|<=|>|<|=)?\s*(-?\d+(?:\.\d+)?)$")
_NUM_BEREICH = re.compile(r"^(-?\d+(?:\.\d+)?)\s*-\s*(-?\d+(?:\.\d+)?)$")
_DATUM_OP = re.compile(r"^(>=|<=|>|<)\s*(\d{4}-\d{2}(?:-\d{2})?)$")


def _betrag_passt(q, v):
	nackt = q.strip().replace(".", ",", 1)
	if _NUM_NACKT.match(nackt):  # nackte Zahl = Textsuche im (gerundeten oder Cent-)Betrag, wie angezeigt
		a, ziffern = abs(v), nackt.replace("-", "")
		return ziffern in str(int(a + 0.5)) or ziffern in ("%.2f" % a).replace(".", ",")
	s = q.strip().replace(",", ".")
	m = _NUM_OP.match(s)
	if m:
		n = float(m.group(2))
		op = m.group(1)
		return {">": v > n, "<": v < n, ">=": v >= n, "<=": v <= n}.get(op, abs(v - n) < 0.5)
	m = _NUM_BEREICH.match(s)
	if m:
		return float(m.group(1)) <= v <= float(m.group(2))
	return True  # nicht lesbar: ignorieren statt alles auszublenden


def _datum_passt(q, datum):
	m = _DATUM_OP.match(q.lower())
	if m:
		d = datum[: len(m.group(2))]
		return {">": d > m.group(2), "<": d < m.group(2), ">=": d >= m.group(2)}.get(m.group(1), d <= m.group(2))
	return q.lower() in datum


def _spalten_text(z, spalte):
	if spalte == "beleg":
		return z["beleg"]
	if spalte == "lieferant":
		return z["lieferant"]
	if spalte == "konto":
		return "%s %s" % (z["konto_nr"], z["konto_name"])
	if spalte == "item":
		return z["item"]
	if spalte == "tags":
		return " ".join(z["tags"])
	return ""


def anwenden(zeilen, f, ohne=()):
	"""Filtert die Zeilen; ohne = Filter, die uebersprungen werden ('kostenstelle', 'bank', 'tag', 'konto')."""
	out = []
	for z in zeilen:
		if f["konzern_ausblenden"] and z["konzern"]:
			continue
		if f["unternehmen"] and z["unternehmen"] != f["unternehmen"]:
			continue
		if "kostenstelle" not in ohne and f["kostenstelle"] and z["kostenstelle"] != f["kostenstelle"]:
			continue
		if "bank" not in ohne and f["bank"] and z["bank_status"] != f["bank"]:
			continue
		if "konto" not in ohne and f["konto"] and z["konto_nr"] != f["konto"]:
			continue
		if "tag" not in ohne:
			if any(not any(familie(t) == g for t in z["tags"]) for g in f["gruppen"]):
				continue
			if f["tag"] == OHNE_TAG:
				if z["tags"]:
					continue
			elif f["tag"] and f["tag"] not in z["tags"]:
				continue
		if not _spalten_passen(z, f):
			continue
		out.append(z)
	return out


def _spalten_passen(z, f):
	for spalte, q in f["spalten"].items():
		if spalte == "datum":
			if not _datum_passt(q, z["datum"]):
				return False
		elif spalte == "betrag":
			if not _betrag_passt(q, betrag(z, f)):
				return False
		elif q.lower() not in _spalten_text(z, spalte).lower():
			return False
	return True


def gruppiere(zeilen, schluessel, f):
	m = {}
	for z in zeilen:
		k = schluessel(z)
		e = m.setdefault(k, {"k": k, "v": 0.0, "n": 0})
		e["v"] += betrag(z, f)
		e["n"] += 1
	for e in m.values():
		e["v"] = flt(e["v"], 2)
	return sorted(m.values(), key=lambda e: -abs(e["v"]))


def _sortiert(zeilen, f):
	s = f["sortierung"]
	k = s["k"]

	def schluessel(z):
		if k == "betrag":
			v = betrag(z, f)
			return abs(v) if s["abs"] else v
		if k == "datum":
			return z["datum"]
		if k == "kostenstelle":
			return z["kostenstelle"].lower()
		if k == "bank":
			return (z["bt"] or z["bank_status"]).lower()
		return _spalten_text(z, k).lower()

	return sorted(zeilen, key=schluessel, reverse=s["richtung"] < 0)


def zeile_fuer_tabelle(z, f):
	return {"datum": z["datum"], "beleg": z["beleg"], "beleg_typ": z["beleg_typ"], "lieferant": z["lieferant"],
		"konto_nr": z["konto_nr"], "konto_name": z["konto_name"], "item": z["item"], "kostenstelle": z["kostenstelle"],
		"kostenstelle_quelle": z["kostenstelle_quelle"], "betrag": betrag(z, f), "bt": z["bt"], "bank_status": z["bank_status"],
		"tags": z["tags"]}


def bericht(zeilen, f, limit=25, offset=0):
	a = anwenden(zeilen, f)
	summe = flt(sum(betrag(z, f) for z in a), 2)

	b = anwenden(zeilen, f, ohne=("bank",))
	bank = {"bank": 0.0, "ohne": 0.0}
	for z in b:
		bank[z["bank_status"]] += betrag(z, f)

	k_zeilen = anwenden(zeilen, f, ohne=("kostenstelle",))
	kostenstellen = gruppiere(k_zeilen, lambda z: z["kostenstelle"], f)

	ko_zeilen = anwenden(zeilen, f, ohne=("konto",))
	konten = []
	namen = {}
	for z in ko_zeilen:
		namen[z["konto_nr"]] = z["konto_name"]
	for e in gruppiere(ko_zeilen, lambda z: z["konto_nr"], f):
		items = gruppiere([z for z in ko_zeilen if z["konto_nr"] == e["k"]], lambda z: z["item"], f)
		e.update({"label": "%s · %s" % (e["k"], namen.get(e["k"], "")), "items": items})
		konten.append(e)

	t_zeilen = anwenden(zeilen, f, ohne=("tag",))
	tags = {}
	for z in t_zeilen:
		for t in (z["tags"] or [OHNE_TAG]):
			fam = "" if t == OHNE_TAG else familie(t)
			e = tags.setdefault((fam, t), {"familie": fam, "k": t, "v": 0.0, "n": 0})
			e["v"] += betrag(z, f)
			e["n"] += 1
	tag_liste = sorted(tags.values(), key=lambda e: -abs(e["v"]))[:12]
	for e in tag_liste:
		e["v"] = flt(e["v"], 2)

	monate = sorted(gruppiere(a, lambda z: z["datum"][:7], f), key=lambda e: e["k"])
	sortiert = _sortiert(a, f)
	return {
		"kennzahl": f["kennzahl"], "von": f["von"], "bis": f["bis"], "summe": summe,
		"belege": len({z["beleg"] for z in a}), "zeilen_anzahl": len(a),
		"bank": {k: flt(v, 2) for k, v in bank.items()},
		"kostenstellen": kostenstellen, "konten": konten, "tags": tag_liste, "monate": monate,
		"zeilen": [zeile_fuer_tabelle(z, f) for z in sortiert[offset: offset + limit]],
	}


def alle_gefiltert_sortiert(zeilen, f):
	return _sortiert(anwenden(zeilen, f), f)
