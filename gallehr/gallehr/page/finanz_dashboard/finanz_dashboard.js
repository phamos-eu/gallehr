frappe.pages['finanz-dashboard'].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Finanz Dashboard',
		single_column: true
	});

	$(frappe.render_template('finanz_dashboard', {})).appendTo(page.body);

	var script = document.createElement('script');
	script.src = 'https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js';
	script.onload = function () {
		window.fd_charts = {};
		bindEvents();
		loadAll();
	};
	document.head.appendChild(script);
};

function bindEvents() {
	$('.fd-apply-btn, .fd-refresh-btn').on('click', function () {
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

	var liq = peur('Liquiditaet aktuell');
	var tage = pzahl('Tage ohne');
	var monate = pzahl('Monate ohne');
	var soll = peur('Umsatz Soll');
	var realLuecke = peur('Reale Umsatz');
	var vorrLuecke = peur('Vorraussichtliche');

	var kpiHtml = [
		kpiCard('Liquidität aktuell', fmt(liq), 'Netto', 'blue', ''),
		kpiCard('Tage ohne Zahlung', fmtN(tage, 0) + ' Tage', fmtN(monate, 1) + ' Monate', 'amber', 'amber'),
		kpiCard('Umsatz Soll', fmt(soll), 'Netto / Jahr', 'purple', ''),
		kpiCard('Reale Umsatzlücke', fmt(realLuecke), 'Soll − Ist − Outstanding', 'red', realLuecke > 0 ? 'red' : 'green'),
		kpiCard('Vorr. Umsatzlücke', fmt(vorrLuecke), 'nach Angebotsumwandlung', vorrLuecke > 0 ? 'red' : 'green', vorrLuecke > 0 ? 'red' : 'green')
	].join('');
	$('#fd-kpi-row').html(kpiHtml);

	var activeMonths = monthlyRows.filter(function (r) {
		var ein = r.einnahmen_brutto !== undefined ? r.einnahmen_brutto : (r[4] || 0);
		var aus = r.ausgaben_brutto !== undefined ? r.ausgaben_brutto : (r[5] || 0);
		return ein > 0 || aus > 0;
	});

	var labels = activeMonths.map(function (r) { return r.monat !== undefined ? r.monat : r[0]; });
	var einnahmen = activeMonths.map(function (r) { return r.einnahmen_brutto !== undefined ? r.einnahmen_brutto : (r[4] || 0); });
	var ausgaben = activeMonths.map(function (r) { return r.ausgaben_brutto !== undefined ? r.ausgaben_brutto : (r[5] || 0); });
	var liquiditaet = activeMonths.map(function (r) { return r.liq_brutto !== undefined ? r.liq_brutto : (r[7] || 0); });
	var burnrate = activeMonths.map(function (r) { return r.burnrate_m !== undefined ? r.burnrate_m : (r[11] || 0); });

	buildGVChart(labels, einnahmen, ausgaben, liquiditaet);
	buildBurnChart(labels, burnrate);
}

function kpiCard(label, value, sub, borderColor, valueColor) {
	return '<div class="fd-kpi-card fd-border-' + borderColor + '">' +
		'<div class="fd-kpi-label">' + label + '</div>' +
		'<div class="fd-kpi-val' + (valueColor ? ' fd-color-' + valueColor : '') + '">' + value + '</div>' +
		'<div class="fd-kpi-sub">' + sub + '</div>' +
		'</div>';
}

function buildGVChart(labels, einnahmen, ausgaben, liquiditaet) {
	if (window.fd_charts && window.fd_charts.gv) { window.fd_charts.gv.destroy(); }
	var ctx = document.getElementById('fd-chart-gv');
	if (!ctx) return;

	$('#fd-legend-gv').html(
		'<span><span class="fd-dot" style="background:#639922"></span>Einnahmen</span>' +
		'<span><span class="fd-dot" style="background:#E24B4A"></span>Ausgaben</span>' +
		'<span><span class="fd-dot" style="background:#378ADD"></span>Liquidität</span>'
	);

	window.fd_charts.gv = new Chart(ctx, {
		type: 'line',
		data: {
			labels: labels,
			datasets: [
				{ label: 'Einnahmen', data: einnahmen, borderColor: '#639922', borderWidth: 2, pointRadius: 4, tension: 0.3, fill: false, borderDash: [] },
				{ label: 'Ausgaben', data: ausgaben, borderColor: '#E24B4A', borderWidth: 2, pointRadius: 4, tension: 0.3, fill: false, borderDash: [4, 3] },
				{ label: 'Liquidität', data: liquiditaet, borderColor: '#378ADD', borderWidth: 2.5, pointRadius: 4, tension: 0.3, fill: false, borderDash: [8, 3] }
			]
		},
		options: chartOptions()
	});
}

function buildBurnChart(labels, burnrate) {
	if (window.fd_charts && window.fd_charts.burn) { window.fd_charts.burn.destroy(); }
	var ctx = document.getElementById('fd-chart-burn');
	if (!ctx) return;

	$('#fd-legend-burn').html(
		'<span><span class="fd-dot" style="background:#534AB7"></span>Burnrate/M</span>'
	);

	window.fd_charts.burn = new Chart(ctx, {
		type: 'line',
		data: {
			labels: labels,
			datasets: [
				{ label: 'Burnrate/M', data: burnrate, borderColor: '#534AB7', backgroundColor: 'rgba(83,74,183,0.08)', borderWidth: 2.5, pointRadius: 4, tension: 0.3, fill: true }
			]
		},
		options: chartOptions()
	});
}

function chartOptions() {
	return {
		responsive: true,
		maintainAspectRatio: false,
		plugins: {
			legend: { display: false },
			tooltip: {
				callbacks: {
					label: function (ctx) {
						return ctx.dataset.label + ': ' + new Intl.NumberFormat('de-DE', {
							style: 'currency', currency: 'EUR', maximumFractionDigits: 0
						}).format(ctx.raw);
					}
				}
			}
		},
		scales: {
			x: {
				ticks: { color: '#888', font: { size: 11 } },
				grid: { color: 'rgba(128,128,128,0.15)' }
			},
			y: {
				ticks: {
					color: '#888', font: { size: 11 },
					callback: function (v) {
						return new Intl.NumberFormat('de-DE', { notation: 'compact', maximumFractionDigits: 0 }).format(v);
					}
				},
				grid: { color: 'rgba(128,128,128,0.15)' }
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
				html += '<div class="fd-row">' +
					'<span class="fd-row-label">' + co + '<span class="fd-badge">' + d.count + '</span></span>' +
					'<span class="fd-row-val fd-color-blue">' + fmt(d.total) + '</span>' +
					'</div>';
			});
			html += '<div class="fd-row fd-row-total">' +
				'<span class="fd-row-label">Total <span class="fd-badge">' + totalCount + '</span></span>' +
				'<span class="fd-row-val fd-color-green">' + fmt(total) + '</span>' +
				'</div>';

			$('#fd-angebote-rows').html(html);
		}
	});
}

function loadOutstanding() {
	frappe.call({
		method: 'frappe.desk.query_report.run',
		args: {
			report_name: 'Outstanding Report',
			filters: {},
			ignore_prepared_report: true
		},
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
				var unbilledAmt = row.unbilled_amount !== undefined ? row.unbilled_amount : (row[7] || 0);
				var invoicedAmt = row.invoice_outstanding !== undefined ? row.invoice_outstanding : (row[8] || 0);
				if (type === 'Not Yet Invoiced' || type === 'Partially Invoiced') {
					unbilled += unbilledAmt;
				} else if (type === 'Invoiced Not Paid') {
					invoicedNotPaid += invoicedAmt;
				}
			});

			var total = unbilled + invoicedNotPaid;
			var html = '<div class="fd-row">' +
				'<span class="fd-row-label">Unbilled (nicht fakturiert)</span>' +
				'<span class="fd-row-val fd-color-blue">' + fmt(unbilled) + '</span>' +
				'</div>' +
				'<div class="fd-row">' +
				'<span class="fd-row-label">Invoiced not paid</span>' +
				'<span class="fd-row-val fd-color-amber">' + fmt(invoicedNotPaid) + '</span>' +
				'</div>' +
				'<div class="fd-row fd-row-total">' +
				'<span class="fd-row-label">Total Expected (Netto)</span>' +
				'<span class="fd-row-val fd-color-green">' + fmt(total) + '</span>' +
				'</div>';

			$('#fd-outstanding-rows').html(html);
		}
	});
}