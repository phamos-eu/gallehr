frappe.ui.form.on("Sales Order", {
	refresh: function(frm) {
	frm.fields_dict["items"].grid.get_field("project").get_query = function() {
		return {
		filters: [
			["Project", "status", "=", "Open"]
		]
		}
	}
	frm.fields_dict["items"].grid.on("grid_rows_render", function(e) {
		var grid_row = $(e.row);
		var project_field = grid_row.find("[data-fieldname=project]");
		var project_name_field = grid_row.find("[data-fieldname=project_name]");
		project_field.on("change", function() {
		var project = project_field.val();
		frappe.call({
			method: "frappe.client.get",
			args: {
			doctype: "Project",
			name: project,
			},
			callback: function(r) {
			if (r.message) {
				project_name_field.text(r.message.project_name);
			}
			}
		});
		});
	});
	}
});