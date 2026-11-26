// Filter des Finanz Dashboard Reports. Diese Datei hat Vorrang vor den Filtern
// in finanz_dashboard.json. Sie existiert, damit die Jahr-Auswahl dieselben
// Jahre zeigt wie die Dashboard-Seite (Vorjahr, aktuelles Jahr, Folgejahr), ohne
// jaehrliche Pflege. Sonst laeuft ein "Zum Bericht"-Link mit jahr=2027 ins Leere.

(function () {
	var y = new Date().getFullYear();

	frappe.query_reports["Finanz Dashboard"] = {
		filters: [
			{
				fieldname: "jahr",
				label: __("Jahr"),
				fieldtype: "Select",
				options: [String(y - 1), String(y), String(y + 1)],
				default: String(y),
			},
			{
				fieldname: "aktuell_liquiditaet",
				label: __("Aktueller Kontostand (Brutto)"),
				fieldtype: "Float",
			},
			{
				fieldname: "start_liquiditaet",
				label: __("Start Liquidität Jan (Brutto)"),
				fieldtype: "Float",
			},
			{
				fieldname: "angebotsumwandlung",
				label: __("Angebotsumwandlung %"),
				fieldtype: "Float",
				default: "30",
			},
			{
				fieldname: "burnrate_von",
				label: __("Burnrate von"),
				fieldtype: "Date",
			},
			{
				fieldname: "burnrate_bis",
				label: __("Burnrate bis"),
				fieldtype: "Date",
			},
		],
	};
})();
