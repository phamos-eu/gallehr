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

function applyFilters() {
	var aktuell = parseFloat($('#fd-aktuell').val());
	var save = $('#fd-aktuell-save').is(':checked');
	if (aktuell > 0 && save) {
		saveSnapshot(aktuell, function () { loadSnapshots(); loadAll(); });
	} else {
		loadAll();
	}
}

function bindEvents() {
	$(document).on('click', '.fd-apply-btn, .fd-refresh-btn', function () {
		applyFilters();
	});

	// Enter key on any filter input triggers Anwenden
	$(document).on('keydown', '#fd-jahr, #fd-aktuell, #fd-liq, #fd-umwandlung, #fd-burnrate-von, #fd-burnrate-bis', function (e) {
		if (e.key === 'Enter') {
			e.preventDefault();
			applyFilters();
		}
	});

	// Burnrate-Zeitraum: show/hide the custom von/bis fields
	$(document).on('change', '#fd-burnrate-periode', function () {
		var isCustom = $(this).val() === 'custom';
		$('#fd-burnrate-custom-von, #fd-burnrate-custom-bis').toggle(isCustom);
	});

	// Mutual exclusion: Aktuell clears Start, Start clears Aktuell
	$(document).on('input', '#fd-aktuell', function () {
		if ($(this).val()) {
			$('#fd-liq').val('');
		}
	});
	$(document).on('input', '#fd-liq', function () {
		if ($(this).val()) {
			$('#fd-aktuell').val('');
			$('#fd-aktuell-save').prop('checked', false);
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

function parseDE(val) {
	// Normalize German decimal comma to dot for parseFloat
	return parseFloat((val || '').replace(',', '.'));
}

function isoDate(d) {
	return d.toISOString().slice(0, 10);
}

function resolveBurnrateRange() {
	var periode = $('#fd-burnrate-periode').val();
	if (!periode) return { von: '', bis: '' };
	if (periode === 'custom') {
		return { von: $('#fd-burnrate-von').val() || '', bis: $('#fd-burnrate-bis').val() || '' };
	}
	// Preset: last N calendar months up to today, resolved here so the
	// backend only ever sees a concrete date range -- one code path.
	var months = parseInt(periode, 10);
	var bis = new Date();
	var von = new Date();
	von.setMonth(von.getMonth() - months);
	return { von: isoDate(von), bis: isoDate(bis) };
}

function getFilters() {
	var burnrate = resolveBurnrateRange();
	return {
		jahr: $('#fd-jahr').val() || '2026',
		aktuell_liquiditaet: parseDE($('#fd-aktuell').val()) || 0,
		start_liquiditaet: parseDE($('#fd-liq').val()) || 0,
		angebotsumwandlung: parseDE($('#fd-umwandlung').val()) || 30,
		burnrate_von: burnrate.von,
		burnrate_bis: burnrate.bis
	};
}

// Deep-link into the Finanz Dashboard query-report using the same filter values
// that produced the numbers on screen -- built from getFilters() so there is
// exactly one source of truth. Empty/zero values are omitted: the report script
// treats 0 as "not set" (it checks `> 0`), so forcing them into the URL would
// change the result. Only declared report filters can be passed this way.
function buildReportLink() {
	var f = getFilters();
	var params = ['jahr=' + encodeURIComponent(f.jahr)];
	if (f.aktuell_liquiditaet > 0) params.push('aktuell_liquiditaet=' + f.aktuell_liquiditaet);
	if (f.start_liquiditaet > 0) params.push('start_liquiditaet=' + f.start_liquiditaet);
	if (f.angebotsumwandlung) params.push('angebotsumwandlung=' + f.angebotsumwandlung);
	if (f.burnrate_von) params.push('burnrate_von=' + encodeURIComponent(f.burnrate_von));
	if (f.burnrate_bis) params.push('burnrate_bis=' + encodeURIComponent(f.burnrate_bis));
	return '/app/query-report/Finanz%20Dashboard?' + params.join('&');
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
	var snapLiq = peur('Snapshot Kontostand');
	var liqDelta = (liqBrutto && snapLiq) ? liqBrutto - snapLiq : null;
	var realLuecke = peur('Reale Umsatz');
	var burnTag = peur('Burnrate/Tag verwendet');
	// Read the report's own Burnrate/Monat instead of recomputing burnTag * 30 here:
	// the report uses the echten Monatsdurchschnitt (Excel J5 = AVERAGEIF) when no
	// Burnrate-Zeitraum is set, which is NOT the same as Tagessatz * 30. Recomputing
	// it here made the tile disagree with the report it links to (1.827,34 EUR apart).
	var burnM = peur('Burnrate/Monat');
	var tage = pzahl('Tage ohne');
	var monate = pzahl('Monate ohne');

	// SPEC 1: positive = surplus (gedeckt) = grün, negative = Lücke = rot
	// Sign is now flipped in Python (absehbar - soll, not soll - absehbar),
	// so here: >= 0 means covered/green, < 0 means gap/red
	var realClass = realLuecke >= 0 ? 'fd-color-green' : 'fd-color-red';
	var vorrClass = vorrLuecke >= 0 ? 'fd-color-green' : 'fd-color-red';

	// Umsatz box: 4 rows
	// Every value links into the Finanz Dashboard report carrying the *current*
	// filter values, so the report reproduces exactly the number shown here.
	// Verifying against a doctype list view is not possible: a list view can
	// only show stored fields (Brutto) and would need the report's WHERE clause
	// reimplemented as URL params -- two sources of truth that drift apart.
	var rpLink = buildReportLink();
	$('#fd-umsatz-rows').html(
		fdRow('Umsatz Ist (YTD Netto)', fmt(ist), 'fd-color-green', rpLink) +
		fdRow('Umsatz Soll (Netto/Jahr)', fmt(soll), 'fd-color-purple', rpLink) +
		fdRow('Reale Umsatzlücke', fmt(realLuecke), realClass, rpLink) +
		fdRowTotal('Vorr. Umsatzlücke', fmt(vorrLuecke), vorrClass, rpLink)
	);

	// Liquidität box — Burnrate in Brutto like Excel
	var deltaClass = liqDelta === null ? '' : (liqDelta >= 0 ? 'fd-color-green' : 'fd-color-red');
	var deltaStr = liqDelta === null ? '—' : (liqDelta >= 0 ? '+' : '') + fmt(liqDelta);
	// Only the snapshot actually used by the report (als_standard = 1)
	var snapLink = '/app/liquiditaet-snapshot?als_standard=1';
	$('#fd-liq-rows').html(
		fdRow('Liquidität aktuell (Bank/berechnet)', fmt(liqBrutto), 'fd-color-blue', rpLink) +
		fdRow('Snapshot (Standard)', fmt(snapLiq), 'fd-color-blue', snapLink) +
		fdRow('Differenz (Bank − Snapshot)', deltaStr, deltaClass) +
		fdRow('Tage ohne Zahlung', fmtN(tage, 0) + ' Tage / ' + fmtN(monate, 1) + ' Monate', 'fd-color-amber') +
		fdRow('Burnrate / Tag (Brutto)', fmt(burnTag, 2), 'fd-color-purple', rpLink) +
		fdRowTotal('Burnrate / Monat (Brutto)', fmt(burnM), 'fd-color-purple', rpLink)
	);

	// G&V chart: all months with data including current (partial) month
	var gvMonths = monthlyRows.filter(function (r) {
		var ein = r.einnahmen_brutto !== undefined ? r.einnahmen_brutto : (r[4] || 0);
		var aus = r.ausgaben_brutto !== undefined ? r.ausgaben_brutto : (r[5] || 0);
		return ein > 0 || aus > 0;
	});

	// Burnrate chart: exclude current month — incomplete month creates misleading nosedive
	var burnMonths = monthlyRows.filter(function (r) {
		var monat = r.monat !== undefined ? r.monat : r[0];
		var ein = r.einnahmen_brutto !== undefined ? r.einnahmen_brutto : (r[4] || 0);
		var aus = r.ausgaben_brutto !== undefined ? r.ausgaben_brutto : (r[5] || 0);
		if (monat === currentMonthName) return false;
		return ein > 0 || aus > 0;
	});

	var gvLabels = gvMonths.map(function (r) { return r.monat !== undefined ? r.monat : r[0]; });
	var einnahmen = gvMonths.map(function (r) { return r.einnahmen_brutto !== undefined ? r.einnahmen_brutto : (r[4] || 0); });
	var ausgaben = gvMonths.map(function (r) { return r.ausgaben_brutto !== undefined ? r.ausgaben_brutto : (r[5] || 0); });
	var liquiditaet = gvMonths.map(function (r) { return r.liq_brutto !== undefined ? r.liq_brutto : (r[7] || 0); });

	var burnLabels = burnMonths.map(function (r) { return r.monat !== undefined ? r.monat : r[0]; });
	var burnrate = burnMonths.map(function (r) { return r.burnrate_m !== undefined ? r.burnrate_m : (r[12] || 0); });

	window.fd_chart_data = { labels: gvLabels, einnahmen: einnahmen, ausgaben: ausgaben, liquiditaet: liquiditaet, burnrate: burnrate };
	if (window.fd_chart_js_loaded) {
		buildGVChart(gvLabels, einnahmen, ausgaben, liquiditaet);
		buildBurnChart(burnLabels, burnrate);
	}
}

function fdRow(label, val, valClass, link) {
	var valHtml = link
		? '<a href="' + link + '" target="_blank" class="fd-row-val fd-link-val ' + (valClass || '') + '">' + val + '</a>'
		: '<span class="fd-row-val ' + (valClass || '') + '">' + val + '</span>';
	return '<div class="fd-row"><span class="fd-row-label">' + label + '</span>' + valHtml + '</div>';
}
function fdRowTotal(label, val, valClass, link) {
	var valHtml = link
		? '<a href="' + link + '" target="_blank" class="fd-row-val fd-link-val ' + (valClass || '') + '">' + val + '</a>'
		: '<span class="fd-row-val ' + (valClass || '') + '">' + val + '</span>';
	return '<div class="fd-row fd-row-total"><span class="fd-row-label">' + label + '</span>' + valHtml + '</div>';
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
				var coLink = '/app/quotation?company=' + encodeURIComponent(co) + '&docstatus=1&status=%5B%22not+in%22%2C%5B%22Ordered%22%2C%22Partially+Ordered%22%2C%22Cancelled%22%2C%22Lost%22%5D%5D&view=Report';
				html += '<div class="fd-row"><span class="fd-row-label">' + co + '<span class="fd-badge">' + d.count + '</span></span><a href="' + coLink + '" target="_blank" class="fd-row-val fd-link-val fd-color-blue">' + fmt(d.total) + '</a></div>';
			});
			var totalLink = '/app/quotation?docstatus=1&status=%5B%22not+in%22%2C%5B%22Ordered%22%2C%22Partially+Ordered%22%2C%22Cancelled%22%2C%22Lost%22%5D%5D&view=Report';
			html += '<div class="fd-row fd-row-total"><span class="fd-row-label">Total <span class="fd-badge">' + totalCount + '</span></span><a href="' + totalLink + '" target="_blank" class="fd-row-val fd-link-val fd-color-green">' + fmt(total) + '</a></div>';
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
			// All three link into Outstanding Report -- the report these numbers are
			// summed from, one row per document, with the Netto columns visible and a
			// Type column separating the two buckets. The previous links pointed at
			// filtered Sales Order / Sales Invoice list views whose filters did not
			// match the report's WHERE clause (e.g. status "To Deliver and Bill" was
			// excluded, and list views show Brutto, not the Netto shown here).
			var outLink = '/app/query-report/Outstanding%20Report';
			$('#fd-outstanding-rows').html(
				'<div class="fd-row"><span class="fd-row-label">Unbilled (nicht fakturiert)</span><a href="' + outLink + '" target="_blank" class="fd-row-val fd-link-val fd-color-blue">' + fmt(unbilled) + '</a></div>' +
				'<div class="fd-row"><span class="fd-row-label">Invoiced not paid</span><a href="' + outLink + '" target="_blank" class="fd-row-val fd-link-val fd-color-amber">' + fmt(invoicedNotPaid) + '</a></div>' +
				'<div class="fd-row fd-row-total"><span class="fd-row-label">Total Expected (Netto)</span><a href="' + outLink + '" target="_blank" class="fd-row-val fd-link-val fd-color-green">' + fmt(total) + '</a></div>'
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
					// Standard-Snapshot wird direkt im Python-Report aus der DB gelesen.
					// Filterfeld bleibt leer — nur bei manuellem Override befuellen.
					var def = null;
					snaps.forEach(function (s) { if (s.als_standard) def = s; });
					if (def) {
						showNotice('Standard-Snapshot vom ' + fmtDt(def.datum) + ' aktiv (' + fmt(def.kontostand_brutto) + ')', 'info');
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