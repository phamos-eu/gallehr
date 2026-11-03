frappe.ui.form.on("Project", {
	refresh(frm) {
		if (frm.is_new() || !frappe.user.has_role(["Projects Manager", "System Manager"])) return;
		frm.add_custom_button(__("Create Nextcloud Folders"), () => {
			frappe
				.call({
					method: "gallehr.nextcloud_project_folders.create_folders_now",
					args: { project: frm.doc.name },
					freeze: true,
					freeze_message: __("Creating folders in Nextcloud…"),
				})
				.then((r) => {
					const result = r.message || {};
					frappe.msgprint({
						title: __("Nextcloud Folders"),
						message: __("{0} folders created, {1} already existed.", [result.created, result.existing]),
						indicator: "green",
					});
				});
		});
	},
});
