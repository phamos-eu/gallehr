frappe.ui.form.on('Web Form', {
	onload: function(frm) {
		frm.set_value('employee', frappe.session.user);
	}
});