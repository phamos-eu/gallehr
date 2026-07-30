"""One-off dev script: import Companies + a slice of Bank Transactions,
Sales Orders, Sales Invoices, Quotations and Liquiditaet Snapshots (plus
their dependent masters) exported from the live server via a System
Console script run there, saved locally as private/files/gallehr_seed_export.json.
Not wired into hooks.py -- this is a one-off dev-environment script, run via:

    bench --site gallehr-dev.localhost execute gallehr.setup.seed_from_live.import_seed_data
"""

import json

import frappe

DEFAULT_PATH = frappe.get_site_path("private", "files", "gallehr_seed_export.json")

# These fields on Company point at Account/Cost Center records that don't
# exist yet in a fresh site -- ERPNext creates them itself (from
# chart_of_accounts) as a side effect of a normal Company insert, and its
# own validate_default_accounts() throws if they're pre-populated with
# references that don't resolve yet.
COMPANY_SELF_REF_FIELDS = [
	"default_bank_account", "default_cash_account", "default_receivable_account",
	"default_payable_account", "write_off_account", "unrealized_profit_loss_account",
	"default_expense_account", "default_income_account", "default_discount_account",
	"cost_center", "exchange_gain_loss_account", "unrealized_exchange_gain_loss_account",
	"round_off_account", "round_off_cost_center", "default_deferred_revenue_account",
	"default_deferred_expense_account", "default_advance_received_account",
	"default_advance_paid_account", "accumulated_depreciation_account",
	"depreciation_expense_account", "disposal_account", "depreciation_cost_center",
	"capital_work_in_progress_account", "asset_received_but_not_billed",
	"default_inventory_account", "stock_adjustment_account",
	"stock_received_but_not_billed", "expenses_included_in_valuation",
	"default_provisional_account", "default_operating_cost_account",
	"default_expense_claim_payable_account", "default_employee_advance_account",
	"default_payroll_payable_account",
]

TREE_DOCTYPES = [
	("customer_groups", "Customer Group"),
	("territories", "Territory"),
	("item_groups", "Item Group"),
	("cost_centers", "Cost Center"),
	("accounts", "Account"),
]

SIMPLE_DOCTYPES = [
	("uoms", "UOM"),
	("price_lists", "Price List"),
	("payment_terms_templates", "Payment Terms Template"),
	("terms_and_conditions", "Terms and Conditions"),
	("tax_templates", "Sales Taxes and Charges Template"),
	("customers", "Customer"),
	("items", "Item"),
	("projects", "Project"),
]

TRANSACTION_DOCTYPES = [
	("liquiditaet_snapshots", "Liquiditaet Snapshot", {}),
	("bank_transactions", "Bank Transaction", {"naming_series": "ACC-BTN-.YYYY.-"}),
	("sales_orders", "Sales Order", {}),
	("sales_invoices", "Sales Invoice", {}),
	("quotations", "Quotation", {}),
]


def import_seed_data(path=None):
	with open(path or DEFAULT_PATH) as f:
		data = json.load(f)

	insert_companies(data.get("companies", []))

	for key, doctype in TREE_DOCTYPES:
		docs = data.get(key, [])
		if doctype == "Cost Center":
			docs = fix_cost_center_docs(docs)
		insert_with_retries(doctype, docs)

	for key, doctype in SIMPLE_DOCTYPES:
		insert_with_retries(doctype, data.get(key, []))

	for key, doctype, defaults in TRANSACTION_DOCTYPES:
		insert_transactions(doctype, data.get(key, []), defaults)

	frappe.db.commit()
	print("Done.")


def strip(d, keep_name=False):
	d = dict(d)
	keys = ["owner", "creation", "modified", "modified_by", "idx", "lft", "rgt", "old_parent"]
	if not keep_name:
		keys.append("name")
	for key in keys:
		d.pop(key, None)
	for k, v in list(d.items()):
		if isinstance(v, list):
			d[k] = [strip(row, keep_name) if isinstance(row, dict) else row for row in v]
	return d


def fix_cost_center_docs(docs):
	# The live COA has one legacy top-level cost center per company (e.g.
	# "Gallehr+Partner - G") that predates ERPNext's own auto-created root
	# ("<company> - <abbr>") and isn't marked is_group -- reparent it under
	# the real local root instead of trying to insert it as a second root,
	# and force is_group=1 on anything used as someone else's parent.
	docs = [dict(d) for d in docs]
	parents_referenced = {d.get("parent_cost_center") for d in docs if d.get("parent_cost_center")}
	for d in docs:
		if d["name"] in parents_referenced:
			d["is_group"] = 1
		if not d.get("parent_cost_center"):
			# Company.cost_center points at the default *leaf* ("Main - X"),
			# not the tree root -- look up the actual group root directly.
			root = frappe.db.get_value(
				"Cost Center",
				{"company": d.get("company"), "is_group": 1, "parent_cost_center": ["is", "not set"]},
				"name",
			)
			if root and root != d["name"]:
				d["parent_cost_center"] = root
	return docs


def insert_companies(docs):
	inserted = 0
	for raw in docs:
		if frappe.db.exists("Company", raw["name"]):
			inserted += 1
			continue
		d = strip(raw, keep_name=True)
		d["doctype"] = "Company"
		for f in COMPANY_SELF_REF_FIELDS:
			d.pop(f, None)
		try:
			doc = frappe.get_doc(d)
			doc.flags.ignore_links = True
			doc.insert(ignore_permissions=True)
			inserted += 1
		except Exception as e:
			print(f"  ! Company {raw['name']}: {e}")
	print(f"Company: inserted {inserted}/{len(docs)}")


def insert_with_retries(doctype, docs):
	pending = {}
	for raw in docs:
		if not frappe.db.exists(doctype, raw["name"]):
			d = strip(raw, keep_name=True)
			d["doctype"] = doctype
			pending[raw["name"]] = d

	errors = {}
	progress = True
	while pending and progress:
		progress = False
		for name in list(pending):
			d = pending[name]
			try:
				doc = frappe.get_doc(d)
				doc.flags.ignore_links = True
				doc.insert(ignore_permissions=True, ignore_mandatory=True)
				pending.pop(name)
				progress = True
			except Exception as e:
				msg = str(e)
				if "Duplicate entry" in msg:
					# something with a matching unique field (own name, or e.g.
					# project_name) already exists locally -- a re-run hitting
					# already-imported data, not a real failure
					pending.pop(name)
					progress = True
				elif "Group type Customer Group" in msg and "customer_group" in d:
					# a handful of live customers are (unusually) assigned
					# directly to a group node -- drop the field and let
					# ERPNext apply its own default on retry
					d.pop("customer_group")
					progress = True
				else:
					errors[name] = msg

	inserted = len(docs) - len(pending)
	print(f"{doctype}: inserted {inserted}/{len(docs)}")
	for name in pending:
		print(f"  ! {doctype} {name}: {errors.get(name)}")


def insert_transactions(doctype, docs, extra_defaults):
	inserted = 0
	for raw in docs:
		d = strip(raw)
		d["doctype"] = doctype
		target_docstatus = d.pop("docstatus", 0)
		d["docstatus"] = 0
		for k, v in extra_defaults.items():
			d.setdefault(k, v)

		try:
			doc = frappe.get_doc(d)
			doc.flags.ignore_links = True
			doc.insert(ignore_permissions=True, ignore_mandatory=True)
		except Exception as e:
			print(f"  ! {doctype} insert failed (live name {raw.get('name')}): {e}")
			continue

		if target_docstatus == 1:
			try:
				doc.submit()
			except Exception as e:
				print(f"  ~ {doctype} {doc.name} inserted as draft, submit failed: {e}")
				continue

		inserted += 1

	print(f"{doctype}: inserted {inserted}/{len(docs)}")
