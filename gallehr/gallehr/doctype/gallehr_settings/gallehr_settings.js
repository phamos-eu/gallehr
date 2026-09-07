// Copyright (c) 2026, phamos.eu and contributors
// For license information, please see license.txt

frappe.ui.form.on("Gallehr Settings", {
	refresh(frm) {
		frappe.realtime.off("gallehr_christmas_list_done");
		frappe.realtime.on("gallehr_christmas_list_done", (data) => {
			frm.reload_doc();
			frappe.msgprint({
				title: __("Christmas List"),
				message: `<pre style="white-space: pre-wrap">${frappe.utils.escape_html(data.report)}</pre>`,
				indicator: "green",
			});
		});
	},

	run_christmas_list_resolution(frm) {
		const start = () => {
			frappe
				.call({
					method: "gallehr.gallehr.doctype.gallehr_settings.gallehr_settings.run_christmas_list_resolution",
					freeze: true,
					freeze_message: __("Starting…"),
				})
				.then((r) => {
					if (!r.message) return;
					frappe.show_alert({
						message: r.message.dry_run
							? __("Dry run started. The result appears below when it finishes.")
							: __("Address resolution started. The result appears below when it finishes."),
						indicator: "blue",
					});
				});
		};

		if (frm.doc.christmas_dry_run) {
			start();
			return;
		}

		frappe.confirm(
			__(
				"This writes to the Contact records. Fields that already have a value are not touched. Continue?"
			),
			start
		);
	},
});
