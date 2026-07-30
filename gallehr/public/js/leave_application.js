frappe.ui.form.on("Leave Application", {
	leave_type: function(frm) {
		if(frm.doc.leave_type) {
			frappe.call({
				method: 'frappe.client.get_value',
				args: {
					'doctype': 'Leave Type',
					'filters': {'name': frm.doc.leave_type},
					'fieldname': ['color']
				},
				callback: function(r) {
					if (!r.exc) {
						frm.set_value("color", r.message.color);
					}
				}
			});
		} else {
			frm.set_value("color", " ");
		}
	}
});