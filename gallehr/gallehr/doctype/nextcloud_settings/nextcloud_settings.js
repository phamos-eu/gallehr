// Copyright (c) 2026, phamos.eu and contributors
// For license information, please see license.txt

frappe.ui.form.on("Nextcloud Settings", {
	test_connection(frm) {
		if (frm.is_dirty()) {
			frappe.msgprint(__("Please save the settings first, the test uses the saved values."));
			return;
		}
		frappe
			.call({
				method: "gallehr.gallehr.doctype.nextcloud_settings.nextcloud_settings.test_connection",
				freeze: true,
				freeze_message: __("Connecting to Nextcloud…"),
			})
			.then((r) => {
				const result = r.message || {};
				const bold = (text) => `<b>${frappe.utils.escape_html(text || "")}</b>`;
				let message;
				if (result.error) {
					message = frappe.utils.escape_html(result.error);
				} else {
					const calendars = (result.calendars || [])
						.map((name) => `<li>${frappe.utils.escape_html(name)}</li>`)
						.join("");
					const calendar = result.calendar_found
						? __("The calendar {0} was found.", [bold(result.calendar_name)])
						: __("The calendar {0} was not found.", [bold(result.calendar_name)]);
					const folders = result.folder_root_found
						? __("The folder root {0} was found.", [bold(result.folder_root)])
						: __("The folder root {0} was not found.", [bold(result.folder_root)]);
					message =
						`${__("Connected.")}<br><br>${calendar}<br>${folders}` +
						`<br><br>${__("Calendars the bot can see:")}<ul>${calendars}</ul>`;
				}
				frappe.msgprint({
					title: __("Connection Test"),
					message: message,
					indicator: result.ok ? "green" : "red",
				});
			});
	},
});
