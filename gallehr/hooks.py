app_name = "gallehr"
app_title = "Gallehr"
app_publisher = "phamos.eu"
app_description = "Gallehr Custom App"
app_email = "support@phamos.eu"
app_license = "MIT"

# include js in doctype views
doctype_js = {
    "Contact": "public/js/contact.js",
    "Leave Application": "public/js/leave_application.js",
    # "Sales Order": "public/js/sales_order.js",
    "Web Form": "public/js/web_form.js",
}

fixtures = [
    {"dt": "Print Format", "filters": [
        ["module", "=", "Gallehr"],
        ["standard", "!=", "Yes"]
    ]},
    {"dt": "Custom Field", "filters": [
        ["module", "=", "Gallehr"]
    ]},
    {"dt": "Property Setter", "filters": [
        ["module", "=", "Gallehr"]
    ]},
    {"dt": "Report", "filters": [
        ["name", "in", ["Outstanding Report", "Projekt Übersicht"]]
    ]}
]

override_whitelisted_methods = {
    "frappe.desk.search.search_link": "gallehr.override.search.search_link",
}

# AK Auswertung v2: haelt ak_kategorie/ak_aufwandskonto/ak_zuordnung/ak_stand auf Bank Transaction aktuell.
# doc_events faengt die normalen Speicherwege (Abgleich, Loesen, Storno eines verknuepften Belegs); der
# taegliche Job faengt Direktschreiben durch den Abgleich-Wizard und spaetere Aenderungen an verknuepften
# Belegen (z.B. Anzahlung -> spaeter Rechnung); after_migrate befuellt bei jedem Deploy, ohne Handarbeit.
doc_events = {
    "Bank Transaction": {
        "on_submit": "gallehr.gallehr.bank_zuordnung.bei_aenderung",
        "on_update_after_submit": "gallehr.gallehr.bank_zuordnung.bei_aenderung",
        "on_cancel": "gallehr.gallehr.bank_zuordnung.bei_aenderung",
    }
}

scheduler_events = {
    "daily": ["gallehr.gallehr.bank_zuordnung.taeglich"],
}

after_migrate = ["gallehr.gallehr.bank_zuordnung.nach_migration"]