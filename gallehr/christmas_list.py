# Copyright (c) 2026, phamos.eu and contributors
# For license information, please see license.txt

"""Christmas list (Weihnachtsliste) address resolution.

Fills the custom_* address fields on Contact that the Weihnachtsliste report
exports.

Resolution priority:

    1. a value already in the Contact field  -> never touched (manual override)
    2. the Address linked to the Contact     -> is_primary_address, else is_shipping_address
    3. an Address of the linked party        -> Customer / Supplier / Lead / ...
    4. nothing resolvable                    -> left empty and counted as missing

Country is written as an ISO 3166-1 alpha-3 code.
"""

import pycountry

import frappe
from frappe.utils import cint

FIELDS = (
	"custom_firmenname",
	"custom_straße",
	"custom_hausnummer",
	"custom_plz",
	"custom_stadt",
	"custom_land",
)

# Non-ISO values found in the live data, plus German country names.
# NDL / CHF / UK are wrong codes typed by hand -- CHF is a currency, not a country.
COUNTRY_OVERRIDES = {
	"NDL": "NLD",
	"CHF": "CHE",
	"UK": "GBR",
	"EN": "GBR",
	"DEUTSCHLAND": "DEU",
	"OESTERREICH": "AUT",
	"ÖSTERREICH": "AUT",
	"SCHWEIZ": "CHE",
	"NIEDERLANDE": "NLD",
	"BELGIEN": "BEL",
	"FRANKREICH": "FRA",
	"ITALIEN": "ITA",
	"SPANIEN": "ESP",
	"POLEN": "POL",
	"TSCHECHIEN": "CZE",
	"DAENEMARK": "DNK",
	"DÄNEMARK": "DNK",
	"SCHWEDEN": "SWE",
	"NORWEGEN": "NOR",
	"FINNLAND": "FIN",
	"GRIECHENLAND": "GRC",
	"IRLAND": "IRL",
	"LUXEMBURG": "LUX",
	"UNGARN": "HUN",
	"RUMAENIEN": "ROU",
	"RUMÄNIEN": "ROU",
	"TUERKEI": "TUR",
	"TÜRKEI": "TUR",
	"RUSSLAND": "RUS",
	"GROSSBRITANNIEN": "GBR",
	"GROBRITANNIEN": "GBR",
	"VEREINIGTES KOENIGREICH": "GBR",
	"VEREINIGTES KÖNIGREICH": "GBR",
	"VEREINIGTE STAATEN": "USA",
	"KANADA": "CAN",
	"INDIEN": "IND",
	"SUEDAFRIKA": "ZAF",
	"SÜDAFRIKA": "ZAF",
}


# All target fields are Data, i.e. varchar(140). A few foreign address lines are
# longer than that and would raise "Data too long for column" on write.
MAX_LENGTH = 140


def has_value(value):
	return bool((value or "").strip())


def clip(value):
	"""Trim to what a Data field can hold, or None if there is nothing to store."""
	if not has_value(value):
		return None
	return value.strip()[:MAX_LENGTH]


# ---------------------------------------------------------------------------
# country codes
# ---------------------------------------------------------------------------


@frappe.request_cache
def _country_codes():
	"""Country record name (upper case) -> alpha-2 code, loaded once per request."""
	return {
		(row.name or "").strip().upper(): row.code
		for row in frappe.get_all("Country", fields=["name", "code"])
	}


@frappe.request_cache
def _alpha3_codes():
	return {country.alpha_3 for country in pycountry.countries}


def alpha3_from_alpha2(code):
	if not has_value(code):
		return None
	country = pycountry.countries.get(alpha_2=code.strip().upper())
	return country.alpha_3 if country else None


def to_alpha3(text):
	"""Anything a human might have typed -> ISO 3166-1 alpha-3, or None."""
	if not has_value(text):
		return None

	value = text.strip()
	upper = value.upper()

	# already a valid alpha-3
	if upper in _alpha3_codes():
		return upper

	# a Country record name -> its alpha-2 code -> alpha-3
	alpha3 = alpha3_from_alpha2(_country_codes().get(upper))
	if alpha3:
		return alpha3

	# a bare alpha-2 code
	if len(value) == 2:
		alpha3 = alpha3_from_alpha2(value)
		if alpha3:
			return alpha3

	# German spellings and known-bad hand-typed values
	return COUNTRY_OVERRIDES.get(upper)


# ---------------------------------------------------------------------------
# address resolution
# ---------------------------------------------------------------------------


def get_contact_links(contact):
	return frappe.get_all(
		"Dynamic Link",
		filters={"parenttype": "Contact", "parent": contact},
		fields=["link_doctype", "link_name", "link_title"],
	)


def get_address(contact, links, only_active=False):
	"""The Address a Contact's Christmas list entry should be built from."""
	disabled_clause = "AND a.disabled = 0" if only_active else ""

	address = frappe.db.get_value("Contact", contact, "address")
	if has_value(address):
		if not only_active or not frappe.db.get_value("Address", address, "disabled"):
			return address

	# an Address linked directly on the Contact
	linked = [link.link_name for link in links if link.link_doctype == "Address" and has_value(link.link_name)]
	if linked:
		rows = frappe.db.sql(
			f"""
			SELECT a.name
			FROM `tabAddress` a
			WHERE a.name IN %(names)s {disabled_clause}
			ORDER BY a.is_primary_address DESC, a.is_shipping_address DESC
			LIMIT 1
			""",
			{"names": tuple(linked)},
			as_dict=True,
		)
		if rows:
			return rows[0].name

	# otherwise an Address of the linked party (Customer / Supplier / Lead / ...)
	for link in links:
		if link.link_doctype == "Address" or not has_value(link.link_name):
			continue
		rows = frappe.db.sql(
			f"""
			SELECT a.name
			FROM `tabAddress` a
			JOIN `tabDynamic Link` dl ON dl.parent = a.name
			WHERE dl.parenttype = 'Address'
			  AND dl.link_doctype = %(doctype)s
			  AND dl.link_name = %(name)s
			  {disabled_clause}
			ORDER BY a.is_primary_address DESC, a.is_shipping_address DESC
			LIMIT 1
			""",
			{"doctype": link.link_doctype, "name": link.link_name},
			as_dict=True,
		)
		if rows:
			return rows[0].name

	return None


def split_street(address):
	"""
	Gallehr keeps street and number in address_line2; address_line1 is a
	placeholder ('?') on most records.  Foreign addresses do not follow the
	German 'street number' order, so when the last token holds no digit the
	whole line becomes the street and the house number stays empty
	"""
	line = (address.address_line2 or "").strip()
	if not line or line == "?":
		line = (address.address_line1 or "").strip()
	if not line or line == "?":
		return None, None

	parts = line.rsplit(" ", 1)
	if len(parts) == 2 and any(char.isdigit() for char in parts[1]):
		return parts[0].strip(), parts[1].strip()

	return line, None


def get_company_name(contact_doc, links, address):
	"""Firmenname, preferring the party name over the address title."""
	if has_value(contact_doc.company_name):
		return contact_doc.company_name.strip()

	for link in links:
		if link.link_doctype != "Address" and has_value(link.link_title):
			return link.link_title.strip()

	if address and has_value(address.address_title) and address.address_title.strip() != "?":
		return address.address_title.strip()

	return None


def resolve_contact(contact_doc, only_active=False):
	"""Values the Christmas list fields *should* have, ignoring what is set.

	Returns a dict of fieldname -> value.  Missing values are omitted.
	"""
	links = get_contact_links(contact_doc.name)
	address_name = get_address(contact_doc.name, links, only_active=only_active)
	address = frappe.get_doc("Address", address_name) if address_name else None

	values = {}

	company_name = clip(get_company_name(contact_doc, links, address))
	if company_name:
		values["custom_firmenname"] = company_name

	if not address:
		return values

	street, house_number = split_street(address)
	if clip(street):
		values["custom_straße"] = clip(street)
	if clip(house_number):
		values["custom_hausnummer"] = clip(house_number)
	if clip(address.pincode):
		values["custom_plz"] = clip(address.pincode)
	if clip(address.city):
		values["custom_stadt"] = clip(address.city)

	alpha3 = to_alpha3(address.country)
	if alpha3:
		values["custom_land"] = alpha3

	return values


# ---------------------------------------------------------------------------
# bulk run
# ---------------------------------------------------------------------------


def run(dry_run=True, only_active=False, limit=None):
	"""Fill every empty Christmas list field on every Contact.

	Never overwrites a field that already has a value, with one exception:
	custom_land is always rewritten to its alpha-3 code.
	"""
	dry_run = cint(dry_run)
	only_active = cint(only_active)

	contacts = frappe.get_all(
		"Contact",
		fields=["name", "company_name", *FIELDS],
		limit_page_length=cint(limit) or 0,
		order_by="name",
	)

	filled = dict.fromkeys(FIELDS, 0)
	still_empty = dict.fromkeys(FIELDS, 0)
	normalised = 0
	unresolved_country = []
	touched = 0

	for contact in contacts:
		updates = {}

		# custom_land is special: an existing value still has to end up as alpha-3
		if has_value(contact.custom_land):
			alpha3 = to_alpha3(contact.custom_land)
			if not alpha3:
				unresolved_country.append(f"{contact.name}: {contact.custom_land}")
			elif alpha3 != contact.custom_land.strip():
				updates["custom_land"] = alpha3
				normalised += 1

		missing = [field for field in FIELDS if not has_value(contact.get(field))]
		if missing:
			resolved = resolve_contact(contact, only_active=only_active)
			for field in missing:
				if resolved.get(field):
					updates[field] = resolved[field]
					filled[field] += 1
				else:
					still_empty[field] += 1

		if not updates:
			continue

		touched += 1
		if not dry_run:
			frappe.db.set_value("Contact", contact.name, updates, update_modified=False)

	return {
		"dry_run": bool(dry_run),
		"only_active": bool(only_active),
		"contacts_scanned": len(contacts),
		"contacts_updated": touched,
		"filled": filled,
		"still_empty": still_empty,
		"countries_normalised": normalised,
		"unresolved_country": unresolved_country[:100],
		"unresolved_country_count": len(unresolved_country),
	}


def format_report(result):
	"""Human readable version of run()'s return value, for the settings form."""
	labels = {
		"custom_firmenname": "Company Name",
		"custom_straße": "Street",
		"custom_hausnummer": "House Number",
		"custom_plz": "Postal Code",
		"custom_stadt": "City",
		"custom_land": "Country",
	}

	lines = []
	lines.append("** DRY RUN, nothing was written **" if result["dry_run"] else "** WRITTEN **")
	lines.append("")
	lines.append(f"Contacts scanned          : {result['contacts_scanned']}")
	lines.append(f"Contacts updated          : {result['contacts_updated']}")
	lines.append(f"Countries normalised      : {result['countries_normalised']}")
	lines.append(f"Only active addresses     : {result['only_active']}")
	lines.append("")
	lines.append(f"{'field':<14}{'filled':>10}{'still empty':>14}")
	lines.append("-" * 38)
	for field in FIELDS:
		lines.append(f"{labels[field]:<14}{result['filled'][field]:>10}{result['still_empty'][field]:>14}")

	if result["unresolved_country_count"]:
		lines.append("")
		lines.append(f"--- country not recognised ({result['unresolved_country_count']}) ---")
		lines.extend(result["unresolved_country"])
		lines.append("Add these to COUNTRY_OVERRIDES in gallehr/christmas_list.py.")

	return "\n".join(lines)
