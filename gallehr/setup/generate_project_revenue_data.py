"""Lokale Testdaten fuer "Projekt Uebersicht" (nur gallehr-dev.localhost, NIE Live).

Verlinkt Sales Orders an die 26 real importierten Projects (project_type,
Kunde bleiben wie vorhanden), setzt project_type wo leer, weist ein paar
generierte PM-Test-User per _assign zu -- damit die neue Seite hier lokal
mit plausibel aussehenden Zahlen sichtbar getestet werden kann.

Alle erzeugten Sales Orders tragen den Tag GENERATED_REVENUE_DATA (gleicher
Mechanismus wie "Zombie"/"Umbuchung" im Rest der App) und lassen sich damit
wieder entfernen: run(cleanup=True). project_type/PM-Zuweisungen, die wir
selbst gesetzt haben, werden beim Cleanup ebenfalls zurueckgenommen (nur bei
Projects, die wir angefasst haben -- an bereits vorhandenen Werten ruehren
wir nicht). Project.customer wird bei Bedarf auf einen echten lokalen Kunden
umgebogen (Sales Order erzwingt Customer==Project.customer) und beim Cleanup
NICHT zurueckgesetzt, da der urspruengliche Wert lokal ohnehin nicht aufloest
(siehe Skript A).

Aufruf:
    bench --site gallehr-dev.localhost execute gallehr.setup.generate_project_revenue_data.run
"""

import random

import frappe
from frappe.desk.doctype.tag.tag import add_tag
from frappe.desk.form.assign_to import add as assign_to_add
from frappe.desk.form.assign_to import remove as assign_to_remove
from frappe.utils import add_days, getdate

MARKER = "GENERATED_REVENUE_DATA"
MAIN_ITEM = "Dienstleistung"
PRICE_LIST = "Standard-Vertrieb"
DATE_RANGE = (getdate("2025-01-01"), getdate("2026-08-25"))

# Die 11 echten project_type-Werte, bestaetigt per Skript A gegen Live
# (25.08.2026): EU-ETS 44x, nEHS 26x, CBAM 26x, SPK 25x, Transformation 16x,
# Mgmnt Systeme 13x, Other 8x, BECV 3x, Foerdermittel 3x, External 2x,
# EU-ETS-2 1x (425 Projects ohne Typ).
PROJECT_TYPES = [
	"EU-ETS", "nEHS", "CBAM", "SPK", "Transformation", "Mgmnt Systeme",
	"Other", "BECV", "Foerdermittel", "External", "EU-ETS-2",
]

PM_USERS = [
	("nina.vogt@gallehr-test.local", "Nina Vogt"),
	("jonas.bergmann@gallehr-test.local", "Jonas Bergmann"),
	("lea.hoffmann@gallehr-test.local", "Lea Hoffmann"),
	("tom.schreiber@gallehr-test.local", "Tom Schreiber"),
]


def existing_generated():
	return frappe.get_all(
		"Tag Link",
		filters={"document_type": "Sales Order", "tag": MARKER},
		pluck="document_name",
	)


def ensure_pm_users():
	users = []
	for email, full_name in PM_USERS:
		if not frappe.db.exists("User", email):
			doc = frappe.get_doc({
				"doctype": "User",
				"email": email,
				"first_name": full_name.split(" ")[0],
				"last_name": full_name.split(" ")[-1],
				"send_welcome_email": 0,
			})
			doc.flags.ignore_links = True
			doc.insert(ignore_permissions=True, ignore_mandatory=True)
		users.append(email)
	return users


def random_date(rng):
	start, end = DATE_RANGE
	return add_days(start, rng.randint(0, (end - start).days))


def build_items(rng, deal_range=(1500, 42000)):
	total = rng.randint(*deal_range)
	return [{"item_code": MAIN_ITEM, "qty": 1, "rate": total}]


def ensure_valid_project_customer(project, fallback_customers, own_companies, rng):
	"""Aeltere, aus Live importierte Projects referenzieren teils Kunden-IDs,
	die lokal nicht existieren (Import-Artefakt, siehe Skript A -- auf Live
	loesen dieselben IDs vermutlich sauber auf). Sales Order erzwingt aber
	Customer == Project.customer, also wird das Project hier auf einen echten
	lokalen Kunden umgebogen (getaggt, damit run(cleanup=True) es sieht --
	Cleanup setzt hier nur project_type zurueck, nicht customer, siehe Hinweis
	unten in run()). Zaehlt auch als "ungueltig", wenn customer zufaellig ein
	eigenes Unternehmen ist (kann von einem frueheren Lauf stammen, bevor der
	Fallback-Pool eigene Unternehmen ausschloss).
	"""
	if frappe.db.exists("Customer", project.customer) and project.customer not in own_companies:
		return project.customer
	fixed = rng.choice(fallback_customers)
	frappe.db.set_value("Project", project.name, "customer", fixed)
	add_tag(MARKER, "Project", project.name)
	return fixed


def create_sales_order(rng, project, customer):
	date = random_date(rng)
	try:
		doc = frappe.get_doc({
			"doctype": "Sales Order",
			"customer": customer,
			"company": project.company,
			"project": project.name,
			"transaction_date": date,
			"delivery_date": add_days(date, 30),
			"currency": "EUR",
			"selling_price_list": PRICE_LIST,
			"items": build_items(rng),
		})
		doc.flags.ignore_links = True
		doc.insert(ignore_permissions=True, ignore_mandatory=True)
		doc.submit()
		add_tag(MARKER, "Sales Order", doc.name)
		return doc.name
	except Exception as e:
		print(f"  ! Sales Order fuer Project {project.name} fehlgeschlagen: {e}")
		return None


def run(cleanup=False, seed=11):
	if cleanup:
		names = existing_generated()
		for n in names:
			doc = frappe.get_doc("Sales Order", n)
			if doc.docstatus == 1:
				doc.cancel()
			doc.delete()
		touched = frappe.get_all(
			"Tag Link", filters={"document_type": "Project", "tag": MARKER}, pluck="document_name"
		)
		for p in touched:
			frappe.db.set_value("Project", p, "project_type", None)
			for email, _ in PM_USERS:
				try:
					assign_to_remove("Project", p, email)
				except Exception:
					pass
			frappe.db.sql(
				"DELETE FROM `tabTag Link` WHERE document_type='Project' AND document_name=%s AND tag=%s",
				(p, MARKER),
			)
		frappe.db.commit()
		print(f"entfernt: {len(names)} Sales Orders, project_type/Assignment auf {len(touched)} Projects zurueckgesetzt")
		return

	already = existing_generated()
	if already:
		print(f"Es existieren bereits {len(already)} erzeugte Sales Orders.")
		print("Erst aufraeumen:  run(cleanup=True)")
		return

	rng = random.Random(seed)
	pm_emails = ensure_pm_users()
	own_companies = frappe.get_all("Company", pluck="name")
	# Gallehrs eigene Unternehmen existieren teils auch als Customer-Datensatz
	# (intercompany) -- als Fallback-Kunde fuer ein orphaned Project.customer
	# darf das nicht vorkommen, sonst sieht ein eigenes Unternehmen im Report
	# wie ein echter Kunde aus (siehe Skript B Live, 25.08.2026).
	customers = [
		c for c in frappe.get_all("Customer", pluck="name")
		if c not in own_companies
	]

	projects = frappe.get_all(
		"Project", fields=["name", "customer", "company", "project_type", "status"]
	)
	if not projects:
		print("Keine Projects gefunden.")
		return

	created_so = 0
	touched_type = 0
	assigned = 0

	for project in projects:
		# ~20% der Projekte bleiben ohne Auftrag/Umsatz -- realistisch (nicht
		# jedes Projekt hat schon einen Auftrag).
		if rng.random() < 0.2:
			continue

		if not project.project_type:
			project.project_type = rng.choice(PROJECT_TYPES)
			frappe.db.set_value("Project", project.name, "project_type", project.project_type)
			add_tag(MARKER, "Project", project.name)
			touched_type += 1

		customer = ensure_valid_project_customer(project, customers, own_companies, rng)
		n_orders = rng.choice([1, 1, 1, 2, 2, 3])
		for _ in range(n_orders):
			if create_sales_order(rng, project, customer):
				created_so += 1

		if rng.random() < 0.75:
			pm = rng.choice(pm_emails)
			try:
				assign_to_add({"assign_to": [pm], "doctype": "Project", "name": project.name})
				add_tag(MARKER, "Project", project.name)
				assigned += 1
			except Exception as e:
				print(f"  ! Assignment fuer Project {project.name} fehlgeschlagen: {e}")

	frappe.db.commit()
	print(f"Sales Orders erzeugt: {created_so}")
	print(f"project_type gesetzt (vorher leer): {touched_type}")
	print(f"PM zugewiesen: {assigned}")
	print("Done.")
