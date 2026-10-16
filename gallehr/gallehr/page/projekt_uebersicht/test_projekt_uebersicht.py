import unittest
from datetime import date

from gallehr.gallehr.page.projekt_uebersicht.projekt_uebersicht import grund_fuer_position

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
