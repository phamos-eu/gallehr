// Copyright (c) 2026, phamos.eu and contributors
// For license information, please see license.txt

frappe.ui.form.on("Nextcloud Calendar Settings", {
	test_connection(frm) {
		if (frm.is_dirty()) {
			frappe.msgprint(__("Please save the settings first, the test uses the saved values."));
			return;
		}
		frappe
			.call({
				method: "gallehr.gallehr.doctype.nextcloud_calendar_settings.nextcloud_calendar_settings.test_connection",
				freeze: true,
				freeze_message: __("Connecting to Nextcloud…"),
			})
			.then((r) => {
				const result = r.message || {};
				let message;
				if (result.error) {
					message = frappe.utils.escape_html(result.error);
				} else {
					const calendars = (result.calendars || [])
						.map((name) => `<li>${frappe.utils.escape_html(name)}</li>`)
						.join("");
					message =
						(result.ok
							? __("Connected. The calendar {0} was found.", [
									`<b>${frappe.utils.escape_html(result.calendar_name)}</b>`,
							  ])
							: __("Connected, but the calendar {0} was not found.", [
									`<b>${frappe.utils.escape_html(result.calendar_name)}</b>`,
							  ])) + `<br><br>${__("Calendars the bot can see:")}<ul>${calendars}</ul>`;
				}
				frappe.msgprint({
					title: __("Connection Test"),
					message: message,
					indicator: result.ok ? "green" : "red",
				});
			});
	},
});
