# Copyright (c) 2026, phamos.eu and Contributors
# See license.txt

"""Unit-Test der reinen Regeltabelle (kategorie()) -- keine DB, jede Kategorie + Grenzfall einzeln.
Reihenfolge der Faelle folgt bewusst der Rangfolge in bank_klassifikation.kategorie()."""

import unittest

from gallehr.gallehr.page.ak_auswertung.quellen import bank_klassifikation as k

BANKKONTEN = {"1800 - Bank - G", "1810 - Bank 2 - G"}


def zeile(**kw):
	basis = {"konto_voll": "9999 - Sonstiges - G", "reference_type": None, "root_type": None,
		"account_type": None, "account_number": "9999", "account_name": "Sonstiges",
		"party_type": None, "supplier_group": None}
	basis.update(kw)
	return basis


class TestKategorie(unittest.TestCase):
	def test_purchase_invoice_referenz_geht_vor_allem_anderen(self):
		z = zeile(reference_type="Purchase Invoice", root_type="Expense")
		self.assertEqual(k.kategorie(z, BANKKONTEN), k.EINGANGSRECHNUNG)

	def test_gegenkonto_ist_ein_bankkonto_ist_umbuchung(self):
		z = zeile(konto_voll="1810 - Bank 2 - G", root_type="Asset")
		self.assertEqual(k.kategorie(z, BANKKONTEN), k.UMBUCHUNG)

	def test_aufwandskonto_ist_kosten_ohne_rechnung(self):
		z = zeile(root_type="Expense", account_number="6800", account_name="Buerobedarf")
		self.assertEqual(k.kategorie(z, BANKKONTEN), k.KOSTEN_OHNE_RECHNUNG)

	def test_verbindlichkeit_mit_lohn_stichwort_ist_personalkosten(self):
		z = zeile(root_type="Liability", account_name="Verb. Lohn/Gehalt")
		self.assertEqual(k.kategorie(z, BANKKONTEN), k.PERSONALKOSTEN)

	def test_verbindlichkeit_sozialversicherung_variante_ist_personalkosten(self):
		z = zeile(root_type="Liability", account_name="Verb. i. R. d. sozialen Sicherheit")
		self.assertEqual(k.kategorie(z, BANKKONTEN), k.PERSONALKOSTEN)

	def test_vorsteuer_stichwort_ist_steuer_durchlauf(self):
		z = zeile(root_type="Liability", account_name="Vorsteuer 19%")
		self.assertEqual(k.kategorie(z, BANKKONTEN), k.STEUER_DURCHLAUF)

	def test_account_type_tax_ist_steuer_durchlauf_auch_ohne_stichwort(self):
		z = zeile(root_type="Liability", account_type="Tax", account_name="Sonderfall")
		self.assertEqual(k.kategorie(z, BANKKONTEN), k.STEUER_DURCHLAUF)

	def test_supplier_gruppe_mitarbeiter_ist_personalkosten(self):
		z = zeile(root_type="Liability", party_type="Supplier", supplier_group="Mitarbeiter")
		self.assertEqual(k.kategorie(z, BANKKONTEN), k.PERSONALKOSTEN)

	def test_supplier_gruppe_krankenkasse_ist_personalkosten(self):
		z = zeile(root_type="Liability", party_type="Supplier", supplier_group="Krankenkasse")
		self.assertEqual(k.kategorie(z, BANKKONTEN), k.PERSONALKOSTEN)

	def test_supplier_gruppe_behoerde_ist_steuer_durchlauf(self):
		z = zeile(root_type="Liability", party_type="Supplier", supplier_group="Behörde")
		self.assertEqual(k.kategorie(z, BANKKONTEN), k.STEUER_DURCHLAUF)

	def test_supplier_gruppe_bank_ist_umbuchung(self):
		z = zeile(root_type="Liability", party_type="Supplier", supplier_group="Bank")
		self.assertEqual(k.kategorie(z, BANKKONTEN), k.UMBUCHUNG)

	def test_supplier_gruppe_dienstleistungen_bleibt_lieferant_ohne_rechnung(self):
		z = zeile(root_type="Liability", party_type="Supplier", supplier_group="Dienstleistungen")
		self.assertEqual(k.kategorie(z, BANKKONTEN), k.LIEFERANT_OHNE_RECHNUNG)

	def test_verbindlichkeit_mit_partei_ohne_passende_gruppe_ist_lieferant_ohne_rechnung(self):
		z = zeile(root_type="Liability", party_type="Employee")
		self.assertEqual(k.kategorie(z, BANKKONTEN), k.LIEFERANT_OHNE_RECHNUNG)

	def test_ertragskonto_ist_einnahme(self):
		z = zeile(root_type="Income")
		self.assertEqual(k.kategorie(z, BANKKONTEN), k.EINNAHME)

	def test_vermoegenskonto_ist_durchlauf_investition(self):
		z = zeile(root_type="Asset")
		self.assertEqual(k.kategorie(z, BANKKONTEN), k.DURCHLAUF_INVESTITION)

	def test_eigenkapitalkonto_ist_durchlauf_investition(self):
		z = zeile(root_type="Equity")
		self.assertEqual(k.kategorie(z, BANKKONTEN), k.DURCHLAUF_INVESTITION)

	def test_sonst_unklassifiziert_nie_stillschweigend_verschluckt(self):
		z = zeile(root_type=None)
		self.assertEqual(k.kategorie(z, BANKKONTEN), k.UNKLASSIFIZIERT)

	def test_kosten_kategorien_enthalten_genau_die_zwei_kosten_erzeugenden(self):
		self.assertEqual(k.KOSTEN_KATEGORIEN, {k.KOSTEN_OHNE_RECHNUNG, k.PERSONALKOSTEN})


if __name__ == "__main__":
	unittest.main()
