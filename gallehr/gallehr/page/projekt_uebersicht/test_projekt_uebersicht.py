import unittest
from datetime import date

from gallehr.gallehr.page.projekt_uebersicht.projekt_uebersicht import (
	grund_fuer_position,
	positionstext,
	positionstext_voll,
)

VON, BIS = "2026-01-01", "2026-10-16"


class TestGrundFuerPosition(unittest.TestCase):
	def test_im_zeitraum_zaehlt(self):
		self.assertIsNone(grund_fuer_position(1, 0, date(2026, 5, 8), VON, BIS))

	def test_grenzen_sind_inklusive(self):
		self.assertIsNone(grund_fuer_position(1, 0, "2026-01-01", VON, BIS))
		self.assertIsNone(grund_fuer_position(1, 0, "2026-10-16", VON, BIS))

	def test_einen_tag_ausserhalb(self):
		self.assertEqual(grund_fuer_position(1, 0, "2025-12-31", VON, BIS), "vor_zeitraum")
		self.assertEqual(grund_fuer_position(1, 0, "2026-10-17", VON, BIS), "nach_zeitraum")

	def test_telmetal_muster_liefertermin_2027(self):
		self.assertEqual(grund_fuer_position(1, 0, date(2027, 5, 31), VON, BIS), "nach_zeitraum")

	def test_entwurf_schlaegt_alles(self):
		self.assertEqual(grund_fuer_position(0, 1, date(2026, 5, 8), VON, BIS), "entwurf")

	def test_zombie(self):
		self.assertEqual(grund_fuer_position(1, 1, date(2026, 5, 8), VON, BIS), "zombie")

	def test_ohne_datum(self):
		self.assertEqual(grund_fuer_position(1, 0, None, VON, BIS), "ohne_datum")


class TestPositionstext(unittest.TestCase):
	def test_einfache_beschreibung(self):
		self.assertEqual(positionstext("CBAM-Meldung 2025", "Dienstleistungen"), "CBAM-Meldung 2025")

	def test_html_aus_dem_texteditor(self):
		html = '<div class="ql-editor read-mode"><p>ETS-Beratung Q3</p><p>inkl. Reise &amp; Spesen</p></div>'
		self.assertEqual(positionstext(html, "Dienstleistungen"), "ETS-Beratung Q3")
		self.assertEqual(positionstext_voll(html, "Dienstleistungen"), "ETS-Beratung Q3\ninkl. Reise & Spesen")

	def test_ohne_beschreibung_faellt_auf_artikelname_zurueck(self):
		self.assertEqual(positionstext("", "Dienstleistungen"), "Dienstleistungen")
		self.assertEqual(positionstext(None, "Dienstleistungen"), "Dienstleistungen")
		self.assertEqual(positionstext("<p> </p>", "Dienstleistungen"), "Dienstleistungen")

	def test_zeilenumbruch_und_leerraum(self):
		self.assertEqual(positionstext("Zeile  eins<br>Zeile zwei", ""), "Zeile eins")

	def test_lange_texte_werden_gekuerzt(self):
		text = positionstext("x" * 300, "")
		self.assertEqual(len(text), 140)
		self.assertTrue(text.endswith("…"))

	def test_nichts_vorhanden(self):
		self.assertEqual(positionstext(None, None), "")
