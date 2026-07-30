"""One-off dev script: generate additional, realistic (not real) Quotations,
Sales Orders and Sales Invoices on top of the real Companies/Customers/Items/
Projects imported by seed_from_live.import_seed_data -- fills in the Finanz
Dashboard's Quotation/Outstanding-Report-driven tiles, which the live export
couldn't populate (the sampled live Sales Orders/Invoices/Quotations
referenced Customers/Leads that no longer exist on the live system itself).
Not wired into hooks.py, run via:

    bench --site gallehr-dev.localhost execute gallehr.setup.generate_more_data.run
"""

import random

import frappe
from frappe.utils import add_days, getdate

MAIN_ITEM = "Dienstleistung"
EXTRA_ITEMS = ["Hotel", "RK PKW"]
PRICE_LIST = "Standard-Vertrieb"

# Deal-size ranges roughly matching each company's real scale (Company.total_monthly_sales
# showed G at ~132k/mo vs GSS at ~1.8k/mo) -- and how many docs of each type to generate.
COMPANY_PROFILES = {
	"Gallehr Sustainable Risk Management GmbH": {
		"quotations": 10, "sales_orders": 8, "sales_invoices": 8, "deal_range": (4000, 55000),
	},
	"Gallehr Sustainable Strategies GmbH": {
		"quotations": 3, "sales_orders": 2, "sales_invoices": 2, "deal_range": (1200, 18000),
	},
}

DATE_RANGE = (getdate("2026-04-01"), getdate("2026-07-29"))


def run(seed=42):
	random.seed(seed)

	customers = frappe.get_all("Customer", pluck="name")
	if not customers:
		print("No local Customers found -- run seed_from_live.import_seed_data first.")
		return

	ensure_fiscal_year()

	counts = {"Quotation": 0, "Sales Order": 0, "Sales Invoice": 0}
	for company, profile in COMPANY_PROFILES.items():
		if not frappe.db.exists("Company", company):
			print(f"  ! skipping {company}: not found locally")
			continue

		# The 18 real imported Projects all reference live customer IDs that
		# don't exist locally (same orphaned-reference issue as the live SO/SI/
		# Quotation slice) -- generate a few fresh ones tied to real, locally-
		# valid customers instead of fighting that mismatch.
		invoice_projects = ensure_projects(company, customers, 4)

		# The imported Item Default's income_account for GSS is a SKR04-style
		# account that only exists for company G's chart of accounts -- use
		# each company's own real, auto-created default instead.
		income_account = frappe.db.get_value("Company", company, "default_income_account")

		for _ in range(profile["quotations"]):
			if create_quotation(company, customers, profile["deal_range"]):
				counts["Quotation"] += 1
		for _ in range(profile["sales_orders"]):
			if create_sales_order(company, customers, income_account, profile["deal_range"]):
				counts["Sales Order"] += 1
		for _ in range(profile["sales_invoices"]):
			if create_sales_invoice(company, invoice_projects, income_account, profile["deal_range"]):
				counts["Sales Invoice"] += 1

	frappe.db.commit()
	for doctype, n in counts.items():
		print(f"{doctype}: created {n}")
	print("Done.")


def ensure_fiscal_year():
	name = "2026"
	if frappe.db.exists("Fiscal Year", name):
		return
	doc = frappe.get_doc({
		"doctype": "Fiscal Year",
		"year": name,
		"year_start_date": "2026-01-01",
		"year_end_date": "2026-12-31",
	})
	doc.insert(ignore_permissions=True, ignore_mandatory=True)
	print(f"Fiscal Year: created {name}")


def ensure_projects(company, customers, count):
	"""Returns a list of (project_name, customer) tuples."""
	results = []
	for i in range(count):
		customer = random.choice(customers)
		project_name = f"{customer} - Generated {i + 1}"
		existing = frappe.db.get_value("Project", {"project_name": project_name, "company": company}, "name")
		if existing:
			results.append((existing, customer))
			continue
		try:
			doc = frappe.get_doc({
				"doctype": "Project",
				"project_name": project_name,
				"company": company,
				"customer": customer,
				"status": "Open",
			})
			doc.flags.ignore_links = True
			doc.insert(ignore_permissions=True, ignore_mandatory=True)
			results.append((doc.name, doc.customer))
		except Exception as e:
			print(f"  ! Project for {customer} ({company}) failed: {e}")
	return results


def random_date():
	start, end = DATE_RANGE
	return add_days(start, random.randint(0, (end - start).days))


def build_items(deal_range, income_account=None):
	total = random.randint(*deal_range)
	rows = [{"item_code": MAIN_ITEM, "qty": 1, "rate": total}]
	if random.random() < 0.3:
		rows.append({"item_code": random.choice(EXTRA_ITEMS), "qty": 1, "rate": random.randint(80, 900)})
	if income_account:
		for row in rows:
			row["income_account"] = income_account
	return rows


def create_quotation(company, customers, deal_range):
	date = random_date()
	try:
		doc = frappe.get_doc({
			"doctype": "Quotation",
			"quotation_to": "Customer",
			"party_name": random.choice(customers),
			"company": company,
			"transaction_date": date,
			"valid_till": add_days(date, 30),
			"currency": "EUR",
			"selling_price_list": PRICE_LIST,
			"items": build_items(deal_range),
		})
		doc.flags.ignore_links = True
		doc.insert(ignore_permissions=True, ignore_mandatory=True)
		doc.submit()
		return True
	except Exception as e:
		print(f"  ! Quotation ({company}) failed: {e}")
		return False


def create_sales_order(company, customers, income_account, deal_range):
	# No project here -- the Outstanding Report's Sales Order branch doesn't
	# filter on it, and this sidesteps the customer/company/project matching
	# ERPNext otherwise enforces.
	date = random_date()
	try:
		doc = frappe.get_doc({
			"doctype": "Sales Order",
			"customer": random.choice(customers),
			"company": company,
			"transaction_date": date,
			"delivery_date": add_days(date, 30),
			"currency": "EUR",
			"selling_price_list": PRICE_LIST,
			"items": build_items(deal_range, income_account),
		})
		doc.flags.ignore_links = True
		doc.insert(ignore_permissions=True, ignore_mandatory=True)
		doc.submit()
		return True
	except Exception as e:
		print(f"  ! Sales Order ({company}) failed: {e}")
		return False


def create_sales_invoice(company, invoice_projects, income_account, deal_range):
	if not invoice_projects:
		return False
	date = random_date()
	project, customer = random.choice(invoice_projects)
	try:
		doc = frappe.get_doc({
			"doctype": "Sales Invoice",
			"customer": customer,
			"company": company,
			"posting_date": date,
			"currency": "EUR",
			"selling_price_list": PRICE_LIST,
			# required for the Outstanding Report's "Invoiced Not Paid" bucket,
			# and must match the project's own customer
			"project": project,
			"items": build_items(deal_range, income_account),
		})
		doc.flags.ignore_links = True
		doc.insert(ignore_permissions=True, ignore_mandatory=True)
		doc.submit()
		return True
	except Exception as e:
		print(f"  ! Sales Invoice ({company}) failed: {e}")
		return False
