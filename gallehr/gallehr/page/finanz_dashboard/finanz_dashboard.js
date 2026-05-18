frappe.pages['finanz-dashboard'].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Finanz Dashboard',
		single_column: true
	});

	$(frappe.render_template('finanz_dashboard', {})).appendTo(page.body);

	window.fd_charts = {};
	window.fd_chart_js_loaded = false;

	bindEvents();
	loadAll();

	var script = document.createElement('script');
	script.src = '/assets/gallehr/js/chart.umd.min.js';
	script.onload = function () {
		window.fd_chart_js_loaded = true;
		if (window.fd_chart_data) {
			buildGVChart(window.fd_chart_data.labels, window.fd_chart_data.einnahmen, window.fd_chart_data.ausgaben, window.fd_chart_data.liquiditaet);
			buildBurnChart(window.fd_chart_data.labels, window.fd_chart_data.burnrate);
		}
	};
	document.head.appendChild(script);
};

function bindEvents() {
	$(document).on('click', '.fd-apply-btn, .fd-refresh-btn', function () {
		loadAll();
	});
}

function getFilters() {
	return {
		jahr: $('#fd-jahr').val() || '2026',
		start_liquiditaet: parseFloat($('#fd-liq').val()) || 0,
		angebotsumwandlung: parseFloat($('#fd-umwandlung').val()) || 30,
		avg_aus_tag_manuell: parseFloat($('#fd-burnrate').val()) || 0
	};
}

function fmt(val, decimals) {
	if (val === null || val === undefined || isNaN(val)) return '—';
	decimals = decimals !== undefined ? decimals : 0;
	return new Intl.NumberFormat('de-DE', {
		style: 'currency', currency: 'EUR',
		minimumFractionDigits: decimals, maximumFractionDigits: decimals
	}).format(val);
}

function fmtN(val, decimals) {
	if (val === null || val === undefined || isNaN(val)) return '—';
	decimals = decimals !== undefined ? decimals : 1;
	return new Intl.NumberFormat('de-DE', {
		minimumFractionDigits: decimals, maximumFractionDigits: decimals
	}).format(val);
}

function loadAll() {
	loadReport();
	loadAngebote();
	loadOutstanding();
}

function loadReport() {
	var filters = getFilters();
	frappe.call({
		method: 'frappe.desk.query_report.run',
		args: {
			report_name: 'Finanz Dashboard',
			filters: filters,
			ignore_prepared_report: true
		},
		callback: function (r) {
			if (!r.message) return;
			processReport(r.message.columns, r.message.result, filters.jahr);
		}
	});
}

function processReport(columns, rows, jahr) {
	var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'Mai', 'Jun', 'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez'];
	var monthlyRows = [];
	var prognoseMap = {};

	(rows || []).forEach(function (row) {
		var monat = row.monat !== undefined ? row.monat : row[0];
		var yearVal = row.jahr !== undefined ? row.jahr : row[1];
		if (String(yearVal) === String(jahr) && MONTHS.indexOf(monat) !== -1) {
			monthlyRows.push(row);
		} else if (!yearVal && monat && monat !== '---') {
			prognoseMap[monat] = row;
		}
	});

	function peur(label) {
		var found = null;
		Object.keys(prognoseMap).forEach(function (k) {
			if (k.indexOf(label) !== -1) { found = prognoseMap[k]; }
		});
		return found ? (found.prognose_eur !== undefined ? found.prognose_eur : (found[2] || 0)) : 0;
	}

	function pzahl(label) {
		var found = null;
		Object.keys(prognoseMap).forEach(function (k) {
			if (k.indexOf(label) !== -1) { found = prognoseMap[k]; }
		});
		return found ? (found.prognose_zahl !== undefined ? found.prognose_zahl : (found[3] || 0)) : 0;
	}

	var ist = peur('Umsatz Ist');
	var soll = peur('Umsatz Soll');
	var vorrLuecke = peur('Vorraussichtliche');
	var liqNetto = peur('Liquiditaet aktuell (Netto');
	var burnTag = peur('Burnrate/Tag verwendet');
	var burnM = burnTag * 30;
	var tage = pzahl('Tage ohne');
	var monate = pzahl('Monate ohne');

	// ── LEFT: Umsatz ──
	var lueckeClass = vorrLuecke > 0 ? 'fd-color-red' : 'fd-color-green';
	$('#fd-umsatz-rows').html(
		row('Umsatz Ist (YTD)', fmt(ist), 'fd-color-green') +
		row('Umsatz Soll', fmt(soll), 'fd-color-purple') +
		rowTotal('Vorr. Umsatzlücke', fmt(vorrLuecke), lueckeClass)
	);

	// ── RIGHT: Liquidität & Runway ──
	$('#fd-liq-rows').html(
		row('Liquidität aktuell (Netto)', fmt(liqNetto), 'fd-color-blue') +
		row('Tage ohne Zahlung', fmtN(tage, 0) + ' Tage / ' + fmtN(monate, 1) + ' Monate', 'fd-color-amber') +
		row('Burnrate / Tag (Netto)', fmt(burnTag, 2), 'fd-color-purple') +
		rowTotal('Burnrate / Monat (Netto)', fmt(burnM), 'fd-color-purple')
	);

	// ── CHART DATA ──
	var activeMonths = monthlyRows.filter(function (r) {
		var ein = r.einnahmen_brutto !== undefined ? r.einnahmen_brutto : (r[4] || 0);
		var aus = r.ausgaben_brutto !== undefined ? r.ausgaben_brutto : (r[5] || 0);
		return ein > 0 || aus > 0;
	});

	var labels = activeMonths.map(function (r) { return r.monat !== undefined ? r.monat : r[0]; });
	var einnahmen = activeMonths.map(function (r) { return r.einnahmen_brutto !== undefined ? r.einnahmen_brutto : (r[4] || 0); });
	var ausgaben = activeMonths.map(function (r) { return r.ausgaben_brutto !== undefined ? r.ausgaben_brutto : (r[5] || 0); });
	var liquiditaet = activeMonths.map(function (r) { return r.liquiditaet_netto !== undefined ? r.liquiditaet_netto : (r[8] || 0); });
	var burnrate = activeMonths.map(function (r) { return r.burnrate_m !== undefined ? r.burnrate_m : (r[12] || 0); });

	window.fd_chart_data = { labels: labels, einnahmen: einnahmen, ausgaben: ausgaben, liquiditaet: liquiditaet, burnrate: burnrate };

	if (window.fd_chart_js_loaded) {
		buildGVChart(labels, einnahmen, ausgaben, liquiditaet);
		buildBurnChart(labels, burnrate);
	}
}

function row(label, val, valClass) {
	return '<div class="fd-row">' +
		'<span class="fd-row-label">' + label + '</span>' +
		'<span class="fd-row-val ' + (valClass || '') + '">' + val + '</span>' +
		'</div>';
}

function rowTotal(label, val, valClass) {
	return '<div class="fd-row fd-row-total">' +
		'<span class="fd-row-label">' + label + '</span>' +
		'<span class="fd-row-val ' + (valClass || '') + '">' + val + '</span>' +
		'</div>';
}

function buildGVChart(labels, einnahmen, ausgaben, liquiditaet) {
	if (window.fd_charts && window.fd_charts.gv) { window.fd_charts.gv.destroy(); }
	var ctx = document.getElementById('fd-chart-gv');
	if (!ctx) return;
	$('#fd-legend-gv').html(
		'<span><span class="fd-dot" style="background:#639922"></span>Einnahmen</span>' +
		'<span><span class="fd-dot" style="background:#E24B4A"></span>Ausgaben</span>' +
		'<span><span class="fd-dot" style="background:#378ADD"></span>Liquidität Netto</span>'
	);
	window.fd_charts.gv = new Chart(ctx, {
		type: 'line',
		data: {
			labels: labels,
			datasets: [
				{ label: 'Einnahmen', data: einnahmen, borderColor: '#639922', borderWidth: 2, pointRadius: 4, tension: 0.3, fill: false },
				{ label: 'Ausgaben', data: ausgaben, borderColor: '#E24B4A', borderWidth: 2, pointRadius: 4, tension: 0.3, fill: false, borderDash: [4, 3] },
				{ label: 'Liquidität Netto', data: liquiditaet, borderColor: '#378ADD', borderWidth: 2.5, pointRadius: 4, tension: 0.3, fill: false, borderDash: [8, 3] }
			]
		},
		options: chartOptions()
	});
}

function buildBurnChart(labels, burnrate) {
	if (window.fd_charts && window.fd_charts.burn) { window.fd_charts.burn.destroy(); }
	var ctx = document.getElementById('fd-chart-burn');
	if (!ctx) return;
	$('#fd-legend-burn').html('<span><span class="fd-dot" style="background:#534AB7"></span>Burnrate/M Netto</span>');
	window.fd_charts.burn = new Chart(ctx, {
		type: 'line',
		data: {
			labels: labels,
			datasets: [{ label: 'Burnrate/M', data: burnrate, borderColor: '#534AB7', backgroundColor: 'rgba(83,74,183,0.08)', borderWidth: 2.5, pointRadius: 4, tension: 0.3, fill: true }]
		},
		options: chartOptions()
	});
}

function chartOptions() {
	return {
		responsive: true, maintainAspectRatio: false,
		plugins: {
			legend: { display: false },
			tooltip: {
				callbacks: {
					label: function (ctx) {
						return ctx.dataset.label + ': ' + new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 }).format(ctx.raw);
					}
				}
			}
		},
		scales: {
			x: { ticks: { color: '#888', font: { size: 11 } }, grid: { color: 'rgba(128,128,128,0.15)' } },
			y: {
				ticks: {
					color: '#888', font: { size: 11 }, callback: function (v) {
						return new Intl.NumberFormat('de-DE', { notation: 'compact', maximumFractionDigits: 0 }).format(v);
					}
				}, grid: { color: 'rgba(128,128,128,0.15)' }
			}
		}
	};
}

function loadAngebote() {
	frappe.call({
		method: 'frappe.client.get_list',
		args: {
			doctype: 'Quotation',
			fields: ['company', 'net_total'],
			filters: [
				['status', 'not in', ['Ordered', 'Partially Ordered', 'Cancelled', 'Lost']],
				['docstatus', '=', 1]
			],
			limit: 500
		},
		callback: function (r) {
			if (!r.message) return;
			var byCompany = {};
			var total = 0;
			var totalCount = 0;
			r.message.forEach(function (q) {
				var co = q.company || 'Unbekannt';
				if (!byCompany[co]) { byCompany[co] = { count: 0, total: 0 }; }
				byCompany[co].count++;
				byCompany[co].total += q.net_total || 0;
				total += q.net_total || 0;
				totalCount++;
			});
			var html = '';
			Object.keys(byCompany).forEach(function (co) {
				var d = byCompany[co];
				html += '<div class="fd-row"><span class="fd-row-label">' + co + '<span class="fd-badge">' + d.count + '</span></span><span class="fd-row-val fd-color-blue">' + fmt(d.total) + '</span></div>';
			});
			html += '<div class="fd-row fd-row-total"><span class="fd-row-label">Total <span class="fd-badge">' + totalCount + '</span></span><span class="fd-row-val fd-color-green">' + fmt(total) + '</span></div>';
			$('#fd-angebote-rows').html(html);
		}
	});
}

function loadOutstanding() {
	frappe.call({
		method: 'frappe.desk.query_report.run',
		args: { report_name: 'Outstanding Report', filters: {}, ignore_prepared_report: true },
		callback: function (r) {
			if (!r.message || !r.message.result) {
				$('#fd-outstanding-rows').html('<div class="fd-loading">Keine Daten</div>');
				return;
			}
			var rows = r.message.result;
			var unbilled = 0;
			var invoicedNotPaid = 0;
			rows.forEach(function (row) {
				var type = row.type !== undefined ? row.type : row[10];
				var unbilledAmt = row.unbilled_netto !== undefined ? row.unbilled_netto : (row[7] || 0);
				var invoicedAmt = row.invoice_outstanding_netto !== undefined ? row.invoice_outstanding_netto : (row[8] || 0);
				if (type === 'Not Yet Invoiced' || type === 'Partially Invoiced') { unbilled += unbilledAmt; }
				else if (type === 'Invoiced Not Paid') { invoicedNotPaid += invoicedAmt; }
			});
			var total = unbilled + invoicedNotPaid;
			var html =
				'<div class="fd-row"><span class="fd-row-label">Unbilled (nicht fakturiert)</span><span class="fd-row-val fd-color-blue">' + fmt(unbilled) + '</span></div>' +
				'<div class="fd-row"><span class="fd-row-label">Invoiced not paid</span><span class="fd-row-val fd-color-amber">' + fmt(invoicedNotPaid) + '</span></div>' +
				'<div class="fd-row fd-row-total"><span class="fd-row-label">Total Expected (Netto)</span><span class="fd-row-val fd-color-green">' + fmt(total) + '</span></div>';
			$('#fd-outstanding-rows').html(html);
		}
	});
}