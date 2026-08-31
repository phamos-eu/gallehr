frappe.pages['ak-auswertung'].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'AK Auswertung',
		single_column: true
	});

	$(frappe.render_template('ak_auswertung', {})).appendTo(page.body);

	var today = frappe.datetime.get_today();
	$('#ak-bis').val(today);
	$('#ak-von').val(frappe.datetime.add_months(today, -12));

	bindEvents();
	loadData();
};

function bindEvents() {
	$(document).on('click', '.ak-refresh-btn', loadData);
	$(document).on('click', '.ak-export-btn', exportExcel);
	$(document).on('keydown', '#ak-von, #ak-bis', function (e) {
		if (e.key === 'Enter') {
			e.preventDefault();
			loadData();
		}
	});
}

function currentFilters() {
	return { von: $('#ak-von').val(), bis: $('#ak-bis').val() };
}

function loadData() {
	$('#ak-tbody').html('<tr><td colspan="5" class="text-muted">Lade...</td></tr>');
	frappe.call({
		method: 'gallehr.gallehr.page.ak_auswertung.ak_auswertung.get_data',
		args: currentFilters(),
		callback: function (r) {
			renderData(r.message);
		}
	});
}

function exportExcel() {
	var url = '/api/method/gallehr.gallehr.page.ak_auswertung.ak_auswertung.export_excel?' +
		$.param(currentFilters());
	window.open(url);
}

function renderData(data) {
	if (!data || !data.rows) return;
	var fmt = function (n) { return format_currency(n, 'EUR'); };

	$('#ak-summe-gesamt').text(fmt(data.summe_gesamt));
	var summeAbgeglichen = data.rows.reduce(function (s, r) { return s + r.summe_abgeglichen; }, 0);
	$('#ak-summe-abgeglichen').text(fmt(summeAbgeglichen));
	$('#ak-anzahl-konten').text(data.rows.length);

	if (!data.rows.length) {
		$('#ak-tbody').html('<tr><td colspan="5" class="text-muted">Keine Buchungen im Zeitraum.</td></tr>');
		return;
	}

	var rowsHtml = data.rows.map(function (r) {
		var warnClass = r.abdeckung_pct < 20 ? ' ak-row-warn' : '';
		return (
			'<tr class="' + warnClass.trim() + '">' +
			'<td>' + frappe.utils.escape_html(r.account_name || r.account) + '</td>' +
			'<td class="ak-num">' + r.anzahl + '</td>' +
			'<td class="ak-num">' + fmt(r.summe_netto) + '</td>' +
			'<td class="ak-num">' + r.anteil_pct.toFixed(1) + '%</td>' +
			'<td>' +
				'<div class="ak-bar"><div class="ak-bar-fill" style="width:' + r.abdeckung_pct + '%"></div></div>' +
				'<span class="ak-bar-label">' + r.abdeckung_pct.toFixed(0) + '% (' + r.anzahl_abgeglichen + '/' + r.anzahl + ')</span>' +
			'</td>' +
			'</tr>'
		);
	}).join('');

	$('#ak-tbody').html(rowsHtml);
}
