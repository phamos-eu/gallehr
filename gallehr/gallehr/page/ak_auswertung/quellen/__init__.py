"""Quellen der AK Auswertung.

Jede Quelle liefert "Kostenzeilen" in derselben Form (siehe eingangsrechnung.zeilen). Aggregation, Filter, Tabelle und
Excel-Export arbeiten nur auf dieser Form -- eine weitere Quelle (v2: Versicherung, Gehaelter ohne Bankbuchung) braucht
deshalb nur eine neue Datei hier plus einen Eintrag in QUELLEN, sonst nichts.
"""

import frappe

from . import bankbuchung, eingangsrechnung

QUELLEN = {"Eingangsrechnung": eingangsrechnung.zeilen, "Bankbuchung": bankbuchung.zeilen}
# Je Quelle das DocType, dessen Leserecht sie braucht -- fehlt es, wird diese eine Quelle stillschweigend
# ausgelassen (nicht die ganze Seite blockiert). Wir kennen Ricardas live Rollen/Rechte fuer Journal Entry nicht
# sicher; lieber auf v1-Verhalten zurueckfallen als ihr die bestehende Seite kaputt machen.
QUELLEN_BERECHTIGUNG = {"Eingangsrechnung": "Purchase Invoice", "Bankbuchung": "Journal Entry"}


def alle_zeilen(von, bis, unternehmen=None):
	zeilen = []
	for quelle, zeilen_fn in QUELLEN.items():
		if not frappe.has_permission(QUELLEN_BERECHTIGUNG[quelle], "read"):
			continue
		zeilen.extend(zeilen_fn(von, bis, unternehmen))
	return zeilen
