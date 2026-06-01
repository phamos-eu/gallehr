frappe.pages['finanz-dashboard'].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Finanz Dashboard',
		single_column: true
	});

	$(frappe.render_template('finanz_dashboard', {})).appendTo(page.body);

	window.fd_charts = {};
	window.fd_chart_js_loaded = false;

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

	bindEvents();
	loadSnapshots(function () { loadAll(); });
};

function bindEvents() {
	$(document).on('click', '.fd-apply-btn, .fd-refresh-btn', function () {
		var aktuell = parseFloat($('#fd-aktuell').val());
		var save = $('#fd-aktuell-save').is(':checked');
		if (aktuell > 0 && save) {
			saveSnapshot(aktuell, function () { loadSnapshots(); loadAll(); });
		} else {
			loadAll();
		}
	});
	$(document).on('click', '.fd-snap-del-btn', function () {
		var name = $(this).data('name');
		frappe.confirm('Snapshot löschen?', function () {
			frappe.call({
				method: 'frappe.client.delete',
				args: { doctype: 'Liquiditaet Snapshot', name: name },
				callback: function () { loadSnapshots(function () { loadAll(); }); }
			});
		});
	});
	$(document).on('click', '.fd-snap-set-btn', function () {
		var name = $(this).data('name');
		var val = parseFloat($(this).data('val'));
		setDefaultSnapshot(name, val);
	});
}

function getFilters() {
	return {
		jahr: $('#fd-jahr').val() || '2026',
		aktuell_liquiditaet: parseFloat($('#fd-aktuell').val()) || 0,
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

function fmtDt(dt) {
	if (!dt) return '—';
	return frappe.datetime.str_to_user(dt.substring(0, 16));
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
		args: { report_name: 'Finanz Dashboard', filters: filters, ignore_prepared_report: true },
		callback: function (r) {
			if (!r.message) return;
			processReport(r.message.result, filters.jahr);
		}
	});
}

function processReport(rows, jahr) {
	var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'Mai', 'Jun', 'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez'];
	var monthlyRows = [];
	var prognoseMap = {};

	// Current calendar month name — used to exclude incomplete month from charts
	var now = new Date();
	var currentMonthName = MONTHS[now.getMonth()];

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
		Object.keys(prognoseMap).forEach(function (k) { if (k.indexOf(label) !== -1) found = prognoseMap[k]; });
		return found ? (found.prognose_eur !== undefined ? found.prognose_eur : (found[2] || 0)) : 0;
	}
	function pzahl(label) {
		var found = null;
		Object.keys(prognoseMap).forEach(function (k) { if (k.indexOf(label) !== -1) found = prognoseMap[k]; });
		return found ? (found.prognose_zahl !== undefined ? found.prognose_zahl : (found[3] || 0)) : 0;
	}

	var ist = peur('Umsatz Ist');
	var soll = peur('Umsatz Soll');
	var vorrLuecke = peur('Vorraussichtliche');
	var liqBrutto = peur('Liquiditaet aktuell');
	var realLuecke = peur('Reale Umsatz');
	var burnTag = peur('Burnrate/Tag verwendet');
	var burnM = burnTag * 30;
	var tage = pzahl('Tage ohne');
	var monate = pzahl('Monate ohne');

	// SPEC 1: positive = surplus (gedeckt) = grün, negative = Lücke = rot
	// Sign is now flipped in Python (absehbar - soll, not soll - absehbar),
	// so here: >= 0 means covered/green, < 0 means gap/red
	var realClass = realLuecke >= 0 ? 'fd-color-green' : 'fd-color-red';
	var vorrClass = vorrLuecke >= 0 ? 'fd-color-green' : 'fd-color-red';

	// Umsatz box: 4 rows
	$('#fd-umsatz-rows').html(
		fdRow('Umsatz Ist (YTD Netto)', fmt(ist), 'fd-color-green') +
		fdRow('Umsatz Soll (Netto/Jahr)', fmt(soll), 'fd-color-purple') +
		fdRow('Reale Umsatzlücke', fmt(realLuecke), realClass) +
		fdRowTotal('Vorr. Umsatzlücke', fmt(vorrLuecke), vorrClass)
	);

	// Liquidität box — Burnrate in Brutto like Excel
	$('#fd-liq-rows').html(
		fdRow('Liquidität aktuell (Brutto/Kontostand)', fmt(liqBrutto), 'fd-color-blue') +
		fdRow('Tage ohne Zahlung', fmtN(tage, 0) + ' Tage / ' + fmtN(monate, 1) + ' Monate', 'fd-color-amber') +
		fdRow('Burnrate / Tag (Brutto)', fmt(burnTag, 2), 'fd-color-purple') +
		fdRowTotal('Burnrate / Monat (Brutto)', fmt(burnM), 'fd-color-purple')
	);

	// SPEC 2: Exclude the current calendar month from charts if it has no data yet.
	// This prevents a misleading nosedive at the end of the chart on day 1 of a new month.
	var activeMonths = monthlyRows.filter(function (r) {
		var monat = r.monat !== undefined ? r.monat : r[0];
		var ein = r.einnahmen_brutto !== undefined ? r.einnahmen_brutto : (r[4] || 0);
		var aus = r.ausgaben_brutto !== undefined ? r.ausgaben_brutto : (r[5] || 0);
		var hasData = ein > 0 || aus > 0;
		// Drop current month only when it carries no data yet
		if (monat === currentMonthName && !hasData) return false;
		return hasData;
	});

	var labels = activeMonths.map(function (r) { return r.monat !== undefined ? r.monat : r[0]; });
	var einnahmen = activeMonths.map(function (r) { return r.einnahmen_brutto !== undefined ? r.einnahmen_brutto : (r[4] || 0); });
	var ausgaben = activeMonths.map(function (r) { return r.ausgaben_brutto !== undefined ? r.ausgaben_brutto : (r[5] || 0); });
	var liquiditaet = activeMonths.map(function (r) { return r.liq_brutto !== undefined ? r.liq_brutto : (r[7] || 0); });
	var burnrate = activeMonths.map(function (r) { return r.burnrate_m !== undefined ? r.burnrate_m : (r[12] || 0); });

	window.fd_chart_data = { labels: labels, einnahmen: einnahmen, ausgaben: ausgaben, liquiditaet: liquiditaet, burnrate: burnrate };
	if (window.fd_chart_js_loaded) {
		buildGVChart(labels, einnahmen, ausgaben, liquiditaet);
		buildBurnChart(labels, burnrate);
	}
}

function fdRow(label, val, valClass) {
	return '<div class="fd-row"><span class="fd-row-label">' + label + '</span><span class="fd-row-val ' + (valClass || '') + '">' + val + '</span></div>';
}
function fdRowTotal(label, val, valClass) {
	return '<div class="fd-row fd-row-total"><span class="fd-row-label">' + label + '</span><span class="fd-row-val ' + (valClass || '') + '">' + val + '</span></div>';
}

function buildGVChart(labels, einnahmen, ausgaben, liquiditaet) {
	if (window.fd_charts && window.fd_charts.gv) { window.fd_charts.gv.destroy(); }
	var ctx = document.getElementById('fd-chart-gv');
	if (!ctx) return;
	$('#fd-legend-gv').html(
		'<span><span class="fd-dot" style="background:#639922"></span>Einnahmen (Brutto)</span>' +
		'<span><span class="fd-dot" style="background:#E24B4A"></span>Ausgaben (Brutto)</span>' +
		'<span><span class="fd-dot" style="background:#378ADD"></span>Liquidität (Brutto)</span>'
	);
	window.fd_charts.gv = new Chart(ctx, {
		type: 'line',
		data: {
			labels: labels, datasets: [
				{ label: 'Einnahmen (Brutto)', data: einnahmen, borderColor: '#639922', borderWidth: 2, pointRadius: 4, tension: 0.3, fill: false },
				{ label: 'Ausgaben (Brutto)', data: ausgaben, borderColor: '#E24B4A', borderWidth: 2, pointRadius: 4, tension: 0.3, fill: false, borderDash: [4, 3] },
				{ label: 'Liquidität (Brutto)', data: liquiditaet, borderColor: '#378ADD', borderWidth: 2.5, pointRadius: 4, tension: 0.3, fill: false, borderDash: [8, 3] }
			]
		},
		options: chartOptions()
	});
}

function buildBurnChart(labels, burnrate) {
	if (window.fd_charts && window.fd_charts.burn) { window.fd_charts.burn.destroy(); }
	var ctx = document.getElementById('fd-chart-burn');
	if (!ctx) return;
	$('#fd-legend-burn').html('<span><span class="fd-dot" style="background:#534AB7"></span>Burnrate/M (Brutto)</span>');
	window.fd_charts.burn = new Chart(ctx, {
		type: 'line',
		data: {
			labels: labels, datasets: [
				{ label: 'Burnrate/M (Brutto)', data: burnrate, borderColor: '#534AB7', backgroundColor: 'rgba(83,74,183,0.08)', borderWidth: 2.5, pointRadius: 4, tension: 0.3, fill: true }
			]
		},
		options: chartOptions()
	});
}

function chartOptions() {
	return {
		responsive: true, maintainAspectRatio: false,
		plugins: {
			legend: { display: false }, tooltip: {
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
			doctype: 'Quotation', fields: ['company', 'net_total'],
			filters: [['status', 'not in', ['Ordered', 'Partially Ordered', 'Cancelled', 'Lost']], ['docstatus', '=', 1]], limit: 500
		},
		callback: function (r) {
			if (!r.message) return;
			var byCompany = {}, total = 0, totalCount = 0;
			r.message.forEach(function (q) {
				var co = q.company || 'Unbekannt';
				if (!byCompany[co]) byCompany[co] = { count: 0, total: 0 };
				byCompany[co].count++; byCompany[co].total += q.net_total || 0;
				total += q.net_total || 0; totalCount++;
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
			if (!r.message || !r.message.result) { $('#fd-outstanding-rows').html('<div class="fd-loading">Keine Daten</div>'); return; }
			var rows = r.message.result, unbilled = 0, invoicedNotPaid = 0;
			rows.forEach(function (row) {
				var type = row.type !== undefined ? row.type : row[10];
				var uAmt = row.unbilled_netto !== undefined ? row.unbilled_netto : (row[7] || 0);
				var iAmt = row.invoice_outstanding_netto !== undefined ? row.invoice_outstanding_netto : (row[8] || 0);
				if (type === 'Not Yet Invoiced' || type === 'Partially Invoiced') unbilled += uAmt;
				else if (type === 'Invoiced Not Paid') invoicedNotPaid += iAmt;
			});
			var total = unbilled + invoicedNotPaid;
			$('#fd-outstanding-rows').html(
				'<div class="fd-row"><span class="fd-row-label">Unbilled (nicht fakturiert)</span><span class="fd-row-val fd-color-blue">' + fmt(unbilled) + '</span></div>' +
				'<div class="fd-row"><span class="fd-row-label">Invoiced not paid</span><span class="fd-row-val fd-color-amber">' + fmt(invoicedNotPaid) + '</span></div>' +
				'<div class="fd-row fd-row-total"><span class="fd-row-label">Total Expected (Netto)</span><span class="fd-row-val fd-color-green">' + fmt(total) + '</span></div>'
			);
		}
	});
}

// ── Snapshots ────────────────────────────────────────────────────────────────

function loadSnapshots(cb) {
	frappe.call({
		method: 'frappe.client.get_value',
		args: { doctype: 'DocType', filters: { name: 'Liquiditaet Snapshot' }, fieldname: 'name' },
		callback: function (r) {
			if (!r.message || !r.message.name) {
				$('#fd-snap-rows').html('<div class="fd-loading">Snapshots nicht verfügbar</div>');
				if (cb) cb();
				return;
			}
			frappe.call({
				method: 'frappe.client.get_list',
				args: {
					doctype: 'Liquiditaet Snapshot',
					fields: ['name', 'kontostand_brutto', 'datum', 'als_standard', 'notiz'],
					order_by: 'datum desc', limit: 50
				},
				callback: function (r) {
					var snaps = r.message || [];
					renderSnapshotTable(snaps);
					var aktuellField = $('#fd-aktuell');
					if (!aktuellField.val()) {
						var def = null;
						snaps.forEach(function (s) { if (s.als_standard) def = s; });
						if (def) {
							aktuellField.val(def.kontostand_brutto);
							$('#fd-liq').val('');
							showNotice('Standard-Snapshot vom ' + fmtDt(def.datum) + ' geladen (' + fmt(def.kontostand_brutto) + ')', 'info');
						}
					}
					if (cb) cb();
				}
			});
		},
		error: function () { if (cb) cb(); }
	});
}

function saveSnapshot(val, cb) {
	frappe.call({
		method: 'frappe.client.get_list',
		args: { doctype: 'Liquiditaet Snapshot', filters: { als_standard: 1 }, fields: ['name'], limit: 50 },
		callback: function (r) {
			var prev = r.message || [];
			var chain = prev.length;
			function createNew() {
				frappe.call({
					method: 'frappe.client.insert',
					args: {
						doc: {
							doctype: 'Liquiditaet Snapshot', kontostand_brutto: val,
							datum: frappe.datetime.now_datetime(), als_standard: 1
						}
					},
					callback: function () {
						showNotice('Snapshot gespeichert: ' + fmt(val), 'saved');
						$('#fd-aktuell-save').prop('checked', false);
						if (cb) cb();
					}
				});
			}
			if (chain === 0) { createNew(); return; }
			var done = 0;
			prev.forEach(function (p) {
				frappe.call({
					method: 'frappe.client.set_value',
					args: { doctype: 'Liquiditaet Snapshot', name: p.name, fieldname: 'als_standard', value: 0 },
					callback: function () { done++; if (done === chain) createNew(); }
				});
			});
		}
	});
}

function setDefaultSnapshot(name, val) {
	frappe.call({
		method: 'frappe.client.get_list',
		args: { doctype: 'Liquiditaet Snapshot', filters: { als_standard: 1 }, fields: ['name'], limit: 50 },
		callback: function (r) {
			var prev = r.message || [];
			var done = 0; var total = prev.length;
			function finish() {
				frappe.call({
					method: 'frappe.client.set_value',
					args: { doctype: 'Liquiditaet Snapshot', name: name, fieldname: 'als_standard', value: 1 },
					callback: function () {
						$('#fd-aktuell').val(val);
						showNotice('Standard gesetzt: ' + fmt(val), 'saved');
						loadSnapshots(function () { loadAll(); });
					}
				});
			}
			if (total === 0) { finish(); return; }
			prev.forEach(function (p) {
				frappe.call({
					method: 'frappe.client.set_value',
					args: { doctype: 'Liquiditaet Snapshot', name: p.name, fieldname: 'als_standard', value: 0 },
					callback: function () { done++; if (done === total) finish(); }
				});
			});
		}
	});
}

function renderSnapshotTable(snaps) {
	if (!snaps.length) { $('#fd-snap-rows').html('<div class="fd-loading">Keine Snapshots gespeichert</div>'); return; }
	var html = '<table class="fd-snap-table"><thead><tr><th>Datum</th><th>Kontostand Brutto</th><th>Standard</th><th style="text-align:right">Aktionen</th></tr></thead><tbody>';
	snaps.forEach(function (s) {
		var stdBadge = s.als_standard
			? '<span class="fd-snap-std-badge">Standard</span>'
			: '<button class="fd-snap-set-btn" data-name="' + s.name + '" data-val="' + s.kontostand_brutto + '">Als Standard</button>';
		html += '<tr><td>' + fmtDt(s.datum) + '</td><td class="val">' + fmt(s.kontostand_brutto) + '</td><td class="std">' + stdBadge + '</td><td class="act"><button class="fd-snap-del-btn" data-name="' + s.name + '" title="Löschen">&#x2715;</button></td></tr>';
	});
	html += '</tbody></table>';
	$('#fd-snap-rows').html(html);
}

function showNotice(msg, type) {
	$('#fd-snap-notice').removeClass('info saved').addClass(type).text(msg).show();
	setTimeout(function () { $('#fd-snap-notice').fadeOut(400); }, 4000);
}