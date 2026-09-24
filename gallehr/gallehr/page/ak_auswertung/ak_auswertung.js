frappe.pages['ak-auswertung'].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'AK Auswertung',
		single_column: true
	});
	$(frappe.render_template('ak_auswertung', {})).appendTo(page.body);

	var API = 'gallehr.gallehr.page.ak_auswertung.ak_auswertung.';
	var root = $(wrapper).find('.ak-auswertung')[0];
	var el = function (id) { return root.querySelector('#ak-' + id); };

	// Zustand der Seite. Alles, was die Zahlen beeinflusst, geht als "filters" ans Backend (eine Quelle der Wahrheit
	// fuer Kopfsumme, Karten, Tabelle und Excel); nur "open" (aufgeklappte Konten) ist rein clientseitig.
	var S = {
		zeit: 'jahr', von: '', bis: '', unternehmen: '', kostenstelle: '', bank: '', kennzahl: 'netto', konzern: true,
		gruppen: {}, tag: '', konto: '', spalten: {}, sort: {k: 'betrag', richtung: -1, abs: true},
		limit: 25, open: {}, kontoMax: 12
	};
	var COLS = [
		{k: 'datum', label: 'Datum', ph: '2026-03 / >2026-05', tip: 'Teil des Datums (2026-03) oder Vergleich: >2026-05-01, <=2026-06.'},
		{k: 'beleg', label: 'Beleg', ph: 'Beleg'},
		{k: 'lieferant', label: 'Lieferant', ph: 'Lieferant'},
		{k: 'konto', label: 'Konto', ph: 'Nr. oder Name'},
		{k: 'item', label: 'Item', ph: 'Item'},
		{k: 'kostenstelle', label: 'Kostenstelle', type: 'kst'},
		{k: 'betrag', label: 'Betrag', num: true, ph: '200 / >1000',
			tip: 'Zahl = enthält die Ziffern (200 findet 200, 1.200, 2.005). Mit Vergleich: >1000, <=500, =200. Bereich: 100-500.'},
		{k: 'bank', label: 'Bank', type: 'bank'},
		{k: 'tags', label: 'Tags', ph: 'Tag'}
	];
	var opt = {gruppen: []};
	var reqId = 0, timer = null, last = null;

	function esc(s) {
		return String(s).replace(/[&<>"]/g, function (c) { return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]; });
	}
	function eur(v) {
		return new Intl.NumberFormat('de-DE', {style: 'currency', currency: 'EUR', maximumFractionDigits: 0}).format(v || 0);
	}
	function pct(v) {
		return new Intl.NumberFormat('de-DE', {maximumFractionDigits: 0}).format(v) + ' %';
	}

	function range() {
		var today = frappe.datetime.get_today();
		var y = parseInt(today.slice(0, 4), 10);
		if (S.zeit === 'jahr') return [y + '-01-01', today];
		if (S.zeit === '3m') return [frappe.datetime.add_months(today, -3), today];
		if (S.zeit === '12m') return [frappe.datetime.add_months(today, -12), today];
		if (S.zeit === 'vorjahr') return [(y - 1) + '-01-01', (y - 1) + '-12-31'];
		if (S.zeit === 'ab2025') return ['2025-01-01', today];
		if (S.zeit === 'custom') return [S.von || '2000-01-01', S.bis || '2099-12-31'];
		return ['2000-01-01', '2099-12-31'];
	}

	function filters(zeit) {
		var r = zeit ? zeit : range();
		return {
			von: r[0], bis: r[1], unternehmen: S.unternehmen, kostenstelle: S.kostenstelle, bank: S.bank,
			kennzahl: S.kennzahl, konzern_ausblenden: S.konzern ? 1 : 0,
			gruppen: Object.keys(S.gruppen).filter(function (k) { return S.gruppen[k]; }),
			tag: S.tag, konto: S.konto, spalten: S.spalten, sortierung: S.sort
		};
	}

	function load() {
		var id = ++reqId;
		root.classList.add('ak-loading');
		frappe.call({
			method: API + 'get_data',
			args: {filters: JSON.stringify(filters()), limit: S.limit, offset: 0},
			callback: function (r) {
				if (id !== reqId || !r.message) return;
				last = r.message;
				render(r.message);
			},
			always: function () { if (id === reqId) root.classList.remove('ak-loading'); }
		});
	}
	function loadSoon() {
		clearTimeout(timer);
		timer = setTimeout(load, 160);
	}

	function rows(list, total, sel, attr, sub) {
		var max = list.length ? Math.abs(list[0].v) : 1;
		return list.map(function (e) {
			return '<div class="ak-row ' + (sel === e.k ? 'sel' : '') + '" ' + attr + '="' + esc(e.k) + '"><div class="ak-nm"><span>' + esc(e.label || e.k) +
				'</span><div class="ak-bar" style="width:' + Math.max(2, Math.abs(e.v) / (max || 1) * 100) + '%"></div></div><div class="ak-am">' + eur(e.v) +
				'</div><div class="ak-pc">' + (total ? pct(e.v / total * 100) : '') + '</div></div>' + (sub ? sub(e) : '');
		}).join('');
	}
	function summe(list) {
		return list.reduce(function (s, e) { return s + e.v; }, 0);
	}

	function render(d) {
		el('h-val').textContent = eur(d.summe);
		el('h-lbl').textContent = (d.kennzahl === 'brutto' ? 'Brutto-Kosten (wie in der Bank)' : 'Netto-Kosten') + ' im Zeitraum';
		var bis = d.bis > frappe.datetime.get_today() ? frappe.datetime.get_today() : d.bis;
		el('h-meta').textContent = d.belege.toLocaleString('de-DE') + ' Rechnungen · ' + d.zeilen_anzahl.toLocaleString('de-DE') + ' Zeilen · ' +
			(d.von <= '2000-01-01' ? 'ab Beginn' : d.von) + ' bis ' + (bis >= '2099-12-31' ? 'heute' : bis);

		var bt = (d.bank.bank + d.bank.ohne) || 1;
		var parts = [['bank', 'Bank bestätigt', 'var(--ak-good)'], ['ohne', 'Ohne Bank-Bestätigung', 'var(--ak-off)']];
		el('h-stack').innerHTML = parts.map(function (p) { return '<i style="width:' + Math.max(0, d.bank[p[0]] / bt * 100) + '%;background:' + p[2] + '"></i>'; }).join('');
		el('h-legend').innerHTML = parts.map(function (p) {
			return '<span><span class="ak-dot" style="background:' + p[2] + '"></span>' + p[1] + ': <b>' + eur(d.bank[p[0]]) + '</b> (' + pct(d.bank[p[0]] / bt * 100) + ')</span>';
		}).join('');

		el('c-kst').innerHTML = rows(d.kostenstellen, summe(d.kostenstellen), S.kostenstelle, 'data-kst') || '<div class="ak-empty">Keine Daten</div>';
		el('c-kst-n').textContent = d.kostenstellen.length + ' Einträge';

		var kt = summe(d.konten), shown = d.konten.slice(0, S.kontoMax);
		el('c-konto').innerHTML = rows(shown, kt, S.konto, 'data-konto', function (e) {
			if (!S.open[e.k]) return '';
			return e.items.map(function (i) {
				return '<div class="ak-row ak-subrow"><div class="ak-nm"><span>↳ ' + esc(i.k) + '</span></div><div class="ak-am">' + eur(i.v) +
					'</div><div class="ak-pc">' + (kt ? pct(i.v / kt * 100) : '') + '</div></div>';
			}).join('');
		}) + (d.konten.length > shown.length ? '<div class="ak-more" id="ak-konto-mehr">+ ' + (d.konten.length - shown.length) + ' weitere Konten</div>' : '');
		if (!d.konten.length) el('c-konto').innerHTML = '<div class="ak-empty">Keine Daten</div>';
		el('c-konto-n').textContent = d.konten.length + ' Konten';

		el('c-tag').innerHTML = d.tags.map(function (e) {
			return '<div class="ak-row ' + (S.tag === e.k ? 'sel' : '') + '" data-tag="' + esc(e.k) + '"><div class="ak-nm"><span>' +
				(e.familie ? '<span class="ak-pill">' + esc(e.familie) + '</span>' : '') + esc(e.k) + '</span></div><div class="ak-am">' + eur(e.v) +
				'</div><div class="ak-pc">' + e.n + '</div></div>';
		}).join('') || '<div class="ak-empty">Keine Daten</div>';

		var mx = Math.max.apply(null, [1].concat(d.monate.map(function (m) { return Math.abs(m.v); })));
		el('c-mon').innerHTML = d.monate.map(function (m) {
			return '<div style="height:' + Math.max(2, Math.abs(m.v) / mx * 100) + '%" title="' + m.k + ': ' + eur(m.v) + '">' +
				(d.monate.length <= 16 ? '<span class="ak-v">' + eur(m.v) + '</span>' : '') + '</div>';
		}).join('');
		el('c-mon-lab').innerHTML = d.monate.map(function (m, i) {
			return '<span>' + (d.monate.length <= 18 || i % 3 === 0 ? m.k.slice(5) + '/' + m.k.slice(2, 4) : '') + '</span>';
		}).join('');
		el('c-mon-sub').textContent = d.monate.length ? 'Ø ' + eur(d.summe / d.monate.length) + ' pro Monat (' + d.monate.length + ' Monate)' : '';

		renderTabelle(d);
		renderChips();
		el('f-kst').value = S.kostenstelle;
		el('f-bank').value = S.bank;
		if (el('col-kostenstelle')) { el('col-kostenstelle').value = S.kostenstelle; el('col-bank').value = S.bank; }
		markSort();
	}

	function renderTabelle(d) {
		el('t-n').textContent = d.zeilen_anzahl.toLocaleString('de-DE') + ' Zeilen · Summe ' + eur(d.summe);
		el('t-body').innerHTML = d.zeilen.map(function (z) {
			var bt = z.bt ? '<a href="/app/bank-transaction/' + encodeURIComponent(z.bt) + '" target="_blank" class="ak-pill good">' + esc(z.bt) + '</a>' :
				'<span class="ak-pill off">ohne Bank</span>';
			return '<tr><td>' + z.datum + '</td><td><a href="/app/purchase-invoice/' + encodeURIComponent(z.beleg) + '" target="_blank">' + esc(z.beleg) + '</a></td>' +
				'<td class="ak-trunc" title="' + esc(z.lieferant) + '">' + esc(z.lieferant) + '</td>' +
				'<td class="ak-trunc" title="' + esc(z.konto_nr + ' ' + z.konto_name) + '">' + esc(z.konto_nr + ' ' + z.konto_name) + '</td>' +
				'<td class="ak-trunc" title="' + esc(z.item) + '">' + esc(z.item) + '</td>' +
				'<td>' + esc(z.kostenstelle) + (z.kostenstelle_quelle === 'Tag' ? ' <span class="ak-pill">per Tag</span>' : '') + '</td>' +
				'<td class="ak-num">' + eur(z.betrag) + '</td><td>' + bt + '</td>' +
				'<td>' + z.tags.map(function (t) { return '<span class="ak-pill">' + esc(t) + '</span>'; }).join('') + '</td></tr>';
		}).join('') || '<tr><td colspan="9" class="ak-empty" id="ak-leer">Keine Zeilen im Ausschnitt</td></tr>';
		el('t-more').textContent = d.zeilen_anzahl > d.zeilen.length ? 'Weitere ' + (d.zeilen_anzahl - d.zeilen.length) + ' Zeilen anzeigen' : '';
		if (!d.zeilen.length) leerHinweis();
	}

	// Leeres Ergebnis: erklaeren, ob nur der Zeitraum schuld ist (haeufigste Verwirrung), mit einem Klick zum Aufheben.
	function leerHinweis() {
		var leer = el('leer');
		if (S.zeit === 'alle') {
			leer.textContent = 'Keine Zeilen für diese Filter. Filter lockern oder mit „Filter zurücksetzen“ neu beginnen.';
			return;
		}
		var id = reqId;
		frappe.call({
			method: API + 'get_data',
			args: {filters: JSON.stringify(filters(['2000-01-01', '2099-12-31'])), limit: 1, offset: 0},
			callback: function (r) {
				if (id !== reqId || !el('leer')) return;
				var n = r.message ? r.message.zeilen_anzahl : 0;
				el('leer').innerHTML = n ?
					'Keine Zeilen im gewählten Zeitraum. Ohne Zeitraum-Filter wären es <b>' + n + '</b> Zeilen. <a href="#" id="ak-hint-all">Zeitraum auf „Alle Jahre“ stellen</a>' :
					'Keine Zeilen für diese Filter. Filter lockern oder mit „Filter zurücksetzen“ neu beginnen.';
			}
		});
	}

	function renderChips() {
		var act = [];
		if (S.kostenstelle) act.push(['kostenstelle', 'Kostenstelle: ' + S.kostenstelle]);
		if (S.konto) act.push(['konto', 'Konto: ' + S.konto]);
		if (S.tag) act.push(['tag', 'Tag: ' + S.tag]);
		Object.keys(S.gruppen).filter(function (g) { return S.gruppen[g]; }).forEach(function (g) { act.push(['gruppe:' + g, 'Tag-Gruppe: ' + g]); });
		if (S.bank) act.push(['bank', 'Bank-Status: ' + (S.bank === 'bank' ? 'bestätigt' : 'ohne')]);
		COLS.forEach(function (c) { if (S.spalten[c.k]) act.push(['spalte:' + c.k, c.label + ': ' + S.spalten[c.k]]); });
		el('active').innerHTML = act.map(function (a) { return '<span class="ak-chip" data-x="' + esc(a[0]) + '">' + esc(a[1]) + ' ✕</span>'; }).join('');
		el('tagrow').innerHTML = '<span class="ak-lbl">Tag-Gruppe (Kontext): <span class="ak-info" tabindex="0" data-tip="' + esc(TIP_TAG) + '">i</span></span>' +
			opt.gruppen.map(function (g) { return '<span class="ak-chip ' + (S.gruppen[g] ? 'on' : '') + '" data-gruppe="' + esc(g) + '">' + esc(g) + '</span>'; }).join('');
	}
	var TIP_TAG = 'Tags sind nur Kontext (z. B. Zahlungsart, Weiterbelastung). Mehrere Gruppen lassen sich kombinieren: dann muss eine Rechnung aus jeder gewählten Gruppe mindestens einen Tag tragen. Tags filtern nur, sie ändern nie die Summe der Kosten.';

	function buildHead() {
		var h1 = COLS.map(function (c) {
			return '<th class="ak-sortable ' + (c.num ? 'ak-num' : '') + '" data-sort="' + c.k + '">' + c.label + '<span class="ak-arr" id="ak-arr-' + c.k + '"></span></th>';
		}).join('');
		var h2 = COLS.map(function (c) {
			var inp;
			if (c.type === 'kst') inp = '<select id="ak-col-kostenstelle"><option value="">Alle</option></select>';
			else if (c.type === 'bank') inp = '<select id="ak-col-bank"><option value="">Alle</option><option value="bank">Bank bestätigt</option><option value="ohne">Ohne Bank</option></select>';
			else inp = '<input type="text" data-col="' + c.k + '" placeholder="' + esc(c.ph || 'Filter') + '" title="' + esc(c.tip || 'enthält (Groß-/Kleinschreibung egal)') + '">';
			return '<th class="' + (c.num ? 'ak-num' : '') + '">' + inp + '</th>';
		}).join('');
		el('t-head').innerHTML = '<tr>' + h1 + '</tr><tr class="ak-fr">' + h2 + '</tr>';
	}
	function markSort() {
		COLS.forEach(function (c) {
			var a = el('arr-' + c.k);
			if (a) a.textContent = S.sort.k === c.k ? (S.sort.richtung > 0 ? ' ▲' : ' ▼') : '';
		});
	}
	function syncSpalten() {
		root.querySelectorAll('#ak-t-head [data-col]').forEach(function (i) { i.value = S.spalten[i.dataset.col] || ''; });
	}
	function resetAll() {
		Object.assign(S, {
			zeit: 'jahr', von: '', bis: '', unternehmen: '', kostenstelle: '', bank: '', kennzahl: 'netto', konzern: true,
			gruppen: {}, tag: '', konto: '', spalten: {}, sort: {k: 'betrag', richtung: -1, abs: true}, limit: 25, open: {}, kontoMax: 12
		});
		el('f-zeit').value = 'jahr'; el('f-firma').value = ''; el('f-konzern').checked = true;
		el('g-von').style.display = el('g-bis').style.display = 'none';
		root.querySelectorAll('#ak-f-kz button').forEach(function (b) { b.classList.toggle('on', b.dataset.k === 'netto'); });
		syncSpalten();
	}

	function bind() {
		el('f-zeit').onchange = function (e) {
			S.zeit = e.target.value; S.limit = 25;
			el('g-von').style.display = el('g-bis').style.display = S.zeit === 'custom' ? '' : 'none';
			load();
		};
		el('f-von').onchange = function (e) { S.von = e.target.value; load(); };
		el('f-bis').onchange = function (e) { S.bis = e.target.value; load(); };
		el('f-firma').onchange = function (e) { S.unternehmen = e.target.value; load(); };
		el('f-kst').onchange = function (e) { S.kostenstelle = e.target.value; load(); };
		el('f-bank').onchange = function (e) { S.bank = e.target.value; load(); };
		el('f-konzern').onchange = function (e) { S.konzern = e.target.checked; load(); };
		el('f-kz').onclick = function (e) {
			var k = e.target.dataset.k; if (!k) return;
			S.kennzahl = k;
			root.querySelectorAll('#ak-f-kz button').forEach(function (b) { b.classList.toggle('on', b.dataset.k === k); });
			load();
		};
		el('btn-reset').onclick = function () { resetAll(); load(); };
		el('btn-refresh').onclick = load;
		el('btn-export').onclick = function () {
			window.open('/api/method/' + API + 'export_excel?' + $.param({filters: JSON.stringify(filters())}));
		};
		el('t-more').onclick = function () { S.limit += 50; load(); };
		el('t-head').onclick = function (e) {
			var th = e.target.closest('[data-sort]'); if (!th) return;
			var k = th.dataset.sort;
			if (S.sort.k === k) S.sort.richtung = -S.sort.richtung;
			else S.sort = {k: k, richtung: (k === 'betrag' || k === 'datum') ? -1 : 1, abs: false};
			load();
		};
		var spaltenTimer;
		el('t-head').oninput = function (e) {
			var k = e.target.dataset.col; if (!k) return;
			clearTimeout(spaltenTimer);
			spaltenTimer = setTimeout(function () {
				var q = e.target.value.trim();
				if (q) S.spalten[k] = q; else delete S.spalten[k];
				S.limit = 25;
				load();
			}, 200);
		};
		el('t-head').onchange = function (e) {
			if (e.target.id === 'ak-col-kostenstelle') { S.kostenstelle = e.target.value; load(); }
			if (e.target.id === 'ak-col-bank') { S.bank = e.target.value; load(); }
		};
		root.addEventListener('click', function (e) {
			var t = e.target.closest('[data-kst],[data-konto],[data-tag],[data-gruppe],[data-x],#ak-konto-mehr,#ak-hint-all');
			if (!t) return;
			if (t.id === 'ak-hint-all') { e.preventDefault(); S.zeit = 'alle'; el('f-zeit').value = 'alle'; el('g-von').style.display = el('g-bis').style.display = 'none'; return load(); }
			if (t.id === 'ak-konto-mehr') { S.kontoMax = 999; return last && render(last); }
			if (t.dataset.kst !== undefined) S.kostenstelle = S.kostenstelle === t.dataset.kst ? '' : t.dataset.kst;
			else if (t.dataset.konto !== undefined) {
				var k = t.dataset.konto;
				if (!S.open[k]) { S.open[k] = true; return last && render(last); }
				S.konto = S.konto === k ? '' : k;
			}
			else if (t.dataset.tag !== undefined) S.tag = S.tag === t.dataset.tag ? '' : t.dataset.tag;
			else if (t.dataset.gruppe !== undefined) S.gruppen[t.dataset.gruppe] = !S.gruppen[t.dataset.gruppe];
			else if (t.dataset.x) {
				var x = t.dataset.x;
				if (x.indexOf('gruppe:') === 0) S.gruppen[x.slice(7)] = false;
				else if (x.indexOf('spalte:') === 0) { delete S.spalten[x.slice(7)]; syncSpalten(); }
				else S[x] = '';
			}
			S.limit = 25;
			load();
		});
	}

	function init() {
		var y = new Date().getFullYear();
		el('opt-vorjahr').textContent = 'Vorjahr (' + (y - 1) + ')';
		buildHead();
		bind();
		frappe.call({
			method: API + 'get_optionen',
			callback: function (r) {
				var o = r.message || {unternehmen: [], kostenstellen: [], gruppen: []};
				opt.gruppen = o.gruppen;
				o.unternehmen.forEach(function (u) { el('f-firma').insertAdjacentHTML('beforeend', '<option>' + esc(u) + '</option>'); });
				var ks = o.kostenstellen.map(function (k) { return '<option>' + esc(k) + '</option>'; }).join('');
				el('f-kst').insertAdjacentHTML('beforeend', ks);
				el('col-kostenstelle').insertAdjacentHTML('beforeend', ks);
				renderChips();
				load();
			}
		});
	}
	init();
};
