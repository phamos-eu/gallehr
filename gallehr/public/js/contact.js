frappe.ui.form.on('Contact', {
	onload(frm) {
		var v_user = frappe.user.name;
		var v_phone = "";
		
		frappe.call({
			method: 'frappe.client.get_value',
			args: {
				doctype: 'User',
				fieldname: '*',
				filters: {name: v_user}
			},
			callback: function(r){						
				v_user = r.message.phone;
				frappe.call({
					"method": "frappe.client.get",
					args: {
						doctype: "Contact",
						name: frm.doc.name,
						fieldname: '*'
					},
					callback: function (data) {
						v_phone = data.message.phone;
						v_phone = v_phone.replace("+","00");
						frm.add_custom_button(__('Festnetz'), function(){
							frappe.prompt([
								{
									label: 'Anschluss',
									fieldname: 'nst',
									default: v_user,
									fieldtype: 'Data',
									maxlength: 3
								},
								{
									label: 'Nummer',
									fieldname: 'nummer',
									default: v_phone,
									fieldtype: 'Data',
									maxlength: 3
								},
							], (values) => {
								var url = 'https://phone.gallehr.de/call.php?exten='+values.nst+'&number='+values.nummer;
								window.open(url);
							});
						});

						frm.add_custom_button(__('Mobil'), function(){
							v_phone = data.message.mobile_no;
							v_phone = v_phone.replace("+","00");
							frappe.prompt([
								{
									label: 'Nebenstelle',
									fieldname: 'nst',
									default: v_user,
									fieldtype: 'Data',
									maxlength: 3
								},
								{
									label: 'Nummer',
									fieldname: 'nummer',
									default: v_phone,
									fieldtype: 'Data',
									maxlength: 3
								},
							], (values) => {
								var url = 'https://phone.gallehr.de/call.php?exten='+values.nst+'&number='+values.nummer;
								window.open(url);
							});
						});
					}
				});
			}
		});
	},

	refresh(frm) {
		cur_frm.set_value("custom_kontakt_erstellt_am", frm.doc.creation);
		cur_frm.set_value("custom_letztes_update_kontakt", frm.doc.modified);
	}
})
