"""Quellen der AK Auswertung.

Jede Quelle liefert "Kostenzeilen" in derselben Form (siehe eingangsrechnung.zeilen). Aggregation, Filter, Tabelle und
Excel-Export arbeiten nur auf dieser Form -- eine weitere Quelle (v2: Versicherung, Gehaelter ohne Bankbuchung) braucht
deshalb nur eine neue Datei hier plus einen Eintrag in QUELLEN, sonst nichts.
"""

from . import eingangsrechnung

QUELLEN = {"Eingangsrechnung": eingangsrechnung.zeilen}


def alle_zeilen(von, bis, unternehmen=None):
	zeilen = []
	for zeilen_fn in QUELLEN.values():
		zeilen.extend(zeilen_fn(von, bis, unternehmen))
	return zeilen
