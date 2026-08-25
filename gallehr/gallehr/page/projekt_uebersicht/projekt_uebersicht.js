frappe.pages['projekt-uebersicht'].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Projekt Übersicht',
		single_column: true
	});

	$(frappe.render_template('projekt_uebersicht', {})).appendTo(page.body);

	bindEvents();
	loadCompanies();
	loadReport();
};

// Nur Unternehmen, die tatsaechlich an mindestens einem Project haengen --
// nicht jeden registrierten Company-Datensatz (es gibt lokal wie live auch
// unbenutzte/Alt-Eintraege, die hier nur verwirren wuerden, siehe Rueckmeldung
// vom 25.08.2026: lokal 3 Company-Records, aber nur 2 tatsaechlich in Benutzung).
function loadCompanies() {
	frappe.call({
		method: 'frappe.client.get_list',
		args: {
			doctype: 'Project', fields: ['company'], group_by: 'company',
			order_by: 'company', limit_page_length: 0
		},
		callback: function (r) {
			(r.message || []).forEach(function (c) {
				if (!c.company) return;
				$('#po-unternehmen').append('<option value="' + frappe.utils.escape_html(c.company) + '">' + frappe.utils.escape_html(c.company) + '</option>');
			});
		}
	});
}

function isoDate(d) {
	return d.toISOString().slice(0, 10);
}

// Zeitraum-Presets werden hier clientseitig in ein konkretes von/bis-Paar
// aufgeloest -- der Report sieht immer nur ein fertiges Datumspaar, ein
// Code-Pfad (gleiches Muster wie resolveBurnrateRange() im Finanz Dashboard).
function resolvePeriodRange() {
	var periode = $('#po-periode').val();
	var today = new Date();

	if (periode === 'custom') {
		return { von: $('#po-von').val() || '', bis: $('#po-bis').val() || '' };
	}
	if (periode === 'letztes_jahr') {
		var y = today.getFullYear() - 1;
		return { von: y + '-01-01', bis: y + '-12-31' };
	}
	if (periode === '3m') {
		var von3 = new Date(today);
		von3.setMonth(von3.getMonth() - 3);
		return { von: isoDate(von3), bis: isoDate(today) };
	}
	// jahresbeginn (Default)
	return { von: today.getFullYear() + '-01-01', bis: isoDate(today) };
}

function getFilters() {
	var range = resolvePeriodRange();
	return {
		von: range.von,
		bis: range.bis,
		status: $('#po-status').val() || 'Alle',
		unternehmen: $('#po-unternehmen').val() || 'Alle'
	};
}

function bindEvents() {
	$(document).on('click', '.po-apply-btn, .po-refresh-btn', function () {
		loadReport();
	});
	$(document).on('change', '#po-periode', function () {
		var isCustom = $(this).val() === 'custom';
		$('#po-custom-von, #po-custom-bis').toggle(isCustom);
	});
	$(document).on('keydown', '#po-von, #po-bis', function (e) {
		if (e.key === 'Enter') { e.preventDefault(); loadReport(); }
	});
}

function fmt(val) {
	if (val === null || val === undefined || isNaN(val)) return '—';
	return new Intl.NumberFormat('de-DE', {
		style: 'currency', currency: 'EUR', maximumFractionDigits: 0
	}).format(val);
}

function fmtPct(val) {
	if (val === null || val === undefined || isNaN(val)) return '—';
	return new Intl.NumberFormat('de-DE', { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(val) + ' %';
}

// Deep-Link in den Projekt-Uebersicht-Report mit denselben Filterwerten, die
// die Zahlen auf dem Screen erzeugt haben -- eine Quelle der Wahrheit,
// gleiches Prinzip wie buildReportLink() im Finanz Dashboard.
function buildReportLink(filters) {
	var params = [
		'von=' + encodeURIComponent(filters.von),
		'bis=' + encodeURIComponent(filters.bis),
		'status=' + encodeURIComponent(filters.status)
	];
	if (filters.unternehmen && filters.unternehmen !== 'Alle') {
		params.push('unternehmen=' + encodeURIComponent(filters.unternehmen));
	}
	return '/app/query-report/Projekt%20%C3%9Cbersicht?' + params.join('&');
}

function loadReport() {
	var filters = getFilters();
	if (!filters.von || !filters.bis) return;

	$('#po-typ-rows, #po-proj-rows, #po-kunde-rows, #po-pm-rows').html('<div class="po-loading">Laden...</div>');

	frappe.call({
		method: 'frappe.desk.query_report.run',
		args: { report_name: 'Projekt Übersicht', filters: filters, ignore_prepared_report: true },
		callback: function (r) {
			if (!r.message) return;
			processReport(r.message.result || [], filters);
		}
	});

	loadUnassignedProjects(filters.unternehmen);
}

// Projekte ohne PM-Zuweisung -- unabhaengig vom Zeitraum-/Status-Filter des
// Reports (operative To-Do-Liste, keine Umsatzkennzahl), aber respektiert die
// Unternehmen-Auswahl. Nutzt den generischen Frappe-Filteroperator
// ["is","not set"], der fuer _assign zuverlaessig funktioniert (getestet
// gegen die echte List View -- die "Assigned To"-Sidebar selbst hat dafuer
// keinen brauchbaren Schnellfilter).
function loadUnassignedProjects(unternehmen) {
	var listFilters = { '_assign': ['is', 'not set'] };
	if (unternehmen && unternehmen !== 'Alle') listFilters.company = unternehmen;

	frappe.call({
		method: 'frappe.client.get_count',
		args: { doctype: 'Project', filters: listFilters },
		callback: function (r) {
			var count = r.message || 0;
			if (!count) { $('#po-unassigned').hide(); return; }
			$('#po-unassigned-text').text(
				count + (count === 1 ? ' Projekt ohne PM zugewiesen' : ' Projekte ohne PM zugewiesen')
			);
			var params = ['_assign=' + encodeURIComponent(JSON.stringify(['is', 'not set']))];
			if (unternehmen && unternehmen !== 'Alle') params.push('company=' + encodeURIComponent(unternehmen));
			$('#po-unassigned-link').attr('href', '/app/project?' + params.join('&'));
			$('#po-unassigned').show();
		}
	});
}

function processReport(rows, filters) {
	var byView = { typ: [], projekt: [], kunde: [], pm: [] };

	rows.forEach(function (row) {
		var view = row.view !== undefined ? row.view : row[0];
		if (byView[view]) byView[view].push(row);
	});

	// Alle 4 Views summieren sich auf denselben Gesamtumsatz (nur unter-
	// schiedliche Gruppierungen derselben gefilterten Auftraege) -- daher hier
	// nur EINE View (typ) aufsummieren, nicht ueber alle rows hinweg (das
	// wuerde den Gesamtumsatz je nach Zeilenzahl vervielfachen).
	var gesamt = byView.typ.reduce(function (sum, row) {
		return sum + ((row.umsatz !== undefined ? row.umsatz : row[2]) || 0);
	}, 0);

	var reportLink = buildReportLink(filters);
	$('#po-hero-total').text(fmt(gesamt));
	$('#po-hero-meta').text(rows.length ? 'Zeitraum ' + filters.von + ' bis ' + filters.bis : '');

	renderView('typ', byView.typ, '#BA7517', reportLink);
	renderView('proj', byView.projekt, '#378ADD', reportLink);
	renderView('kunde', byView.kunde, '#639922', reportLink);
	renderView('pm', byView.pm, '#534AB7', reportLink);
}

function renderView(prefix, rowsForView, color, reportLink) {
	$('#po-' + prefix + '-link').attr('href', reportLink);
	$('#po-' + prefix + '-count').text(rowsForView.length + (rowsForView.length === 1 ? ' Eintrag' : ' Einträge'));

	var container = $('#po-' + prefix + '-rows');
	if (!rowsForView.length) {
		container.html('<div class="po-empty">Keine Daten im gewählten Zeitraum</div>');
		return;
	}

	// Report liefert bereits absteigend sortiert -- hier nur defensiv erneut
	// sortiert, falls sich das je aendert.
	var sorted = rowsForView.slice().sort(function (a, b) {
		var au = a.umsatz !== undefined ? a.umsatz : a[2];
		var bu = b.umsatz !== undefined ? b.umsatz : b[2];
		return bu - au;
	});

	var html = '';
	sorted.forEach(function (row, i) {
		var label = row.label !== undefined ? row.label : row[1];
		var umsatz = row.umsatz !== undefined ? row.umsatz : row[2];
		var anteil = row.anteil !== undefined ? row.anteil : row[3];
		var pctWidth = Math.max(Math.min(anteil, 100), 0);
		html +=
			'<div class="po-row">' +
			'<span class="po-rank">' + (i + 1) + '</span>' +
			'<span class="po-name" title="' + frappe.utils.escape_html(label) + '">' + frappe.utils.escape_html(label) + '</span>' +
			'<span class="po-amt">' + fmt(umsatz) + '</span>' +
			'<span class="po-pct">' + fmtPct(anteil) + '</span>' +
			'<span class="po-bar-track"><span class="po-bar-fill" style="width:' + pctWidth + '%; background:' + color + '"></span></span>' +
			'</div>';
	});
	container.html(html);
}
