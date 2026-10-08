/* ClimateReady analysis page. All science is done by the Flask backend; this file only shows results. */
(function () {
  const CFG = window.CR_CFG, $ = id => document.getElementById(id), esc = Recs.esc;
  const HZ_COLOR = { uhi: '#EA580C', waterlogging: '#1D4ED8', air_pollution: '#7C3AED' };
  const LV_COLOR = { 'Very High': '#B91C1C', High: '#EA580C', Moderate: '#B7791F', Low: '#64748B', 'Very Low': '#94A3B8' };
  const GROUPS = [['uhi', 'Urban Heat Island'], ['waterlogging', 'Waterlogging'], ['air_pollution', 'Air Pollution'], ['socio', 'Socio-economic']];
  const S = { level: 'district', picked: [], pending: null, custom: null, layers: [], active: null, recs: null, state: 'idle', poll: null, timer: null };
  let map;
  const TOUCH = window.matchMedia('(pointer: coarse)').matches || 'ontouchstart' in window;

  // Phones dim/lock the screen and freeze the page while we wait. Ask the browser to keep the screen on.
  let wakeLock = null;
  async function keepAwake(on) {
    try {
      if (on && 'wakeLock' in navigator && !wakeLock) {
        wakeLock = await navigator.wakeLock.request('screen');
        wakeLock.addEventListener('release', () => { wakeLock = null; });
      } else if (!on && wakeLock) { await wakeLock.release(); wakeLock = null; }
    } catch (e) { /* not supported or refused: ignore */ }
  }
  const working = () => S.state === 'queued' || S.state === 'processing' || S.reporting || S.recBusy;
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState !== 'visible') return;
    if (working()) keepAwake(true);
    if (S.poll) poll();                                   // catch up immediately when the user comes back
  });

  /* ---------- helpers ---------- */
  async function api(url, opt) {
    let r;
    try { r = await fetch(url, opt); }
    catch (e) { const er = new Error('Connection problem. Please check your internet connection and try again.'); er.status = 0; throw er; }
    let d = {}; try { d = await r.json(); } catch (e) { /* ignore */ }
    if (!r.ok) {
      const er = new Error(d.error || (r.status >= 500 ? 'The server is busy or restarting. Please try again in a moment.' : 'Request failed'));
      er.status = r.status; er.data = d; throw er;
    }
    return d;
  }
  const post = (u, b) => api(u, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) });
  const show = id => $(id).classList.remove('d-none'), hide = id => $(id).classList.add('d-none');
  const fmt = (v, d = 1) => v == null ? '–' : Number(v).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d });
  const fmtPop = v => v >= 1e6 ? (v / 1e6).toFixed(2) + ' million' : Math.round(v).toLocaleString();
  function msg(text, kind = 'warning') { const m = $('locMsg'); m.className = `alert alert-${kind} py-2 mb-0`; m.textContent = text; }
  function clearMsg() { $('locMsg').classList.add('d-none'); }
  const hasAssessment = () => ['queued', 'processing', 'done'].includes(S.state);

  /* ---------- location selection ---------- */
  function renderChips() {
    const box = $('chips'); box.innerHTML = '';
    const items = S.custom ? [{ id: 'custom', name: 'Custom area: ' + S.custom.name }] : S.picked;
    items.forEach(p => {
      const c = document.createElement('span'); c.className = 'chip';
      c.innerHTML = `${esc(p.name)}<button type="button" aria-label="Remove ${esc(p.name)}">×</button>`;
      c.querySelector('button').onclick = () => { if (p.id === 'custom') S.custom = null; else S.picked = S.picked.filter(x => x.id !== p.id); renderChips(); };
      box.appendChild(c);
    });
    $('chipLabel').textContent = items.length ? 'Selected:' : 'No area selected';
  }
  let searchT;
  $('locInput').addEventListener('input', () => {
    S.pending = null; clearTimeout(searchT);
    const q = $('locInput').value.trim(); if (!q) { hide('locResults'); return; }
    searchT = setTimeout(async () => {
      try {
        const { results } = await post('/api/location/search', { level: S.level, q });
        const box = $('locResults'); box.innerHTML = '';
        if (!results.length) {
          const why = CFG.errors[S.level] || 'No matching location found.'; box.innerHTML = `<div class="list-group-item small text-muted-cr">${esc(why)}</div>`;
        }
        results.forEach(r => {
          const b = document.createElement('button'); b.type = 'button'; b.className = 'list-group-item list-group-item-action';
          b.innerHTML = `${esc(r.name)} <small>${r.level === 'district' ? 'District' : 'Subdistrict'}${r.parent ? ' · ' + esc(r.parent) : ''}</small>`;
          b.onclick = () => { S.pending = r; $('locInput').value = r.name; hide('locResults'); };
          box.appendChild(b);
        });
        show('locResults');
      } catch (e) { /* ignore */ }
    }, 200);
  });
  document.addEventListener('click', e => { if (!e.target.closest('#locResults, #locInput')) hide('locResults'); });
  $('levelSel').addEventListener('change', e => {
    S.level = e.target.value; S.pending = null; $('locInput').value = ''; hide('locResults'); clearMsg();
    if (S.picked.length && S.picked[0].level !== S.level) { S.picked = []; renderChips(); }
  });
  $('addBtn').addEventListener('click', async () => {
    clearMsg();
    if (S.custom) return msg('Remove the custom area first to select districts or subdistricts.');
    if (!S.pending) return msg('Type a name and choose a location from the list first.');
    try {
      const { location } = await post('/api/location/select', { level: S.level, id: S.pending.id, current: S.picked.map(p => p.id) });
      S.picked.push(location); S.pending = null; $('locInput').value = ''; renderChips();
    } catch (e) { msg(e.message); }
  });
  $('uploadBtn').addEventListener('click', () => $('uploadFile').click());
  $('uploadFile').addEventListener('change', async e => {
    const f = e.target.files[0]; if (!f) return; clearMsg();
    if (f.size > CFG.maxUploadMb * 1048576) { e.target.value = ''; return msg(`The file is larger than ${CFG.maxUploadMb} MB.`); }
    const fd = new FormData(); fd.append('file', f);
    try {
      const d = await api('/api/upload-aoi', { method: 'POST', body: fd });
      S.custom = { upload_id: d.upload_id, name: d.name }; S.picked = []; renderChips();
      msg(`Custom area loaded (${d.area_km2.toFixed(1)} km²).`, 'success');
    } catch (er) { msg(er.message); }
    e.target.value = '';
  });

  /* ---------- start / queue / progress ---------- */
  function setBusy(b) { $('startBtn').disabled = b; $('recBtn').disabled = b || S.state !== 'done'; $('recBtn2').disabled = $('recBtn').disabled; }
  $('startBtn').addEventListener('click', async () => {
    clearMsg();
    if (S.state === 'queued' || S.state === 'processing') return msg('Assessment already in progress.');
    const payload = S.custom ? { mode: 'custom', upload_id: S.custom.upload_id } : { mode: S.level, ids: S.picked.map(p => p.id) };
    if (!S.custom && !S.picked.length) return msg('Add at least one location first.');
    if (S.state === 'done' && !confirm('Your current assessment will be lost. Do you want to leave?')) return;
    try {
      await post('/api/assessment/start', payload);
    } catch (e) { return msg(e.message, e.status === 503 ? 'danger' : 'warning'); }
    resetResults(); S.state = 'queued'; setBusy(true);
    ['stateEmpty', 'stateError', 'workspace'].forEach(hide); show('stateLoading');
    renderSteps([]); $('stateLoading').scrollIntoView({ behavior: 'smooth' });
    S.t0 = Date.now(); clearInterval(S.tick); S.tick = setInterval(() => {
      const t = Math.floor((Date.now() - S.t0) / 1000);
      $('loadElapsed').textContent = `Elapsed ${Math.floor(t / 60)}:${String(t % 60).padStart(2, '0')}`;
    }, 1000);
    keepAwake(true);
    clearInterval(S.poll); S.poll = setInterval(poll, 2000); poll();
  });
  function renderSteps(steps) {
    $('loadSteps').innerHTML = steps.map(s => `<li class="${s.status === 'done' ? 'done' : s.status === 'active' ? 'active' : ''}">${esc(s.label)}</li>`).join('');
    const done = steps.filter(s => s.status === 'done').length + 0.5 * steps.filter(s => s.status === 'active').length;
    $('loadBar').style.width = steps.length ? Math.min(100, 100 * done / steps.length) + '%' : '0';
  }
  async function poll() {
    let st; try { st = await api('/api/assessment/status'); } catch (e) { return; }
    if (st.state === 'NONE' && (S.state === 'queued' || S.state === 'processing')) {
      clearInterval(S.poll); clearInterval(S.tick); S.state = 'idle'; setBusy(false); keepAwake(false);
      hide('stateQueue'); hide('stateLoading');
      $('errMsg').textContent = 'The assessment was stopped (the server restarted, or the page was inactive for too long). Please start it again.';
      show('stateError'); return;
    }
    if (st.state === 'QUEUED') {
      S.state = 'queued'; hide('stateLoading'); show('stateQueue');
      $('queuePos').textContent = st.queue_position ? `You are currently #${st.queue_position} in the queue.` : '';
    } else if (st.state === 'PROCESSING') {
      S.state = 'processing'; hide('stateQueue'); show('stateLoading'); renderSteps(st.steps);
    } else if (st.state === 'COMPLETED') {
      clearInterval(S.poll); clearInterval(S.tick); keepAwake(false); hide('stateQueue'); renderSteps(st.steps); await loadResults();
    } else if (st.state === 'FAILED') {
      clearInterval(S.poll); clearInterval(S.tick); keepAwake(false); S.state = 'idle'; setBusy(false); hide('stateQueue'); hide('stateLoading');
      $('errMsg').textContent = st.error || 'Please try again.'; show('stateError');
    }
  }
  $('retryBtn').onclick = () => { hide('stateError'); show('stateEmpty'); window.scrollTo({ top: 0, behavior: 'smooth' }); };

  /* ---------- results ---------- */
  function resetResults() {
    S.layers = []; S.active = null; S.recs = null;
    if (map) { map.clearLayer(); map.setPins([], HZ_COLOR, () => {}); }
    ['workspace', 'statsSection', 'recsSection', 'recModal'].forEach(hide);
    $('mapActions').innerHTML = '<button class="btn btn-primary" id="recBtn2" type="button">Generate Recommendations</button>';
    $('recBtn2').onclick = generateRecs;
  }
  async function loadResults() {
    const [L, stats] = await Promise.all([api('/api/layers'), api('/api/statistics')]);
    S.layers = L.layers; S.label = L.label; S.state = 'done'; setBusy(false);
    hide('stateLoading'); show('workspace'); show('statsSection');
    $('wsAreas').textContent = L.label;
    const w = $('dataWarn');
    if (L.warnings && L.warnings.length) {
      w.innerHTML = '<b>Some data was not available for this area:</b> ' + L.warnings.map(esc).join('; ') +
        '. A neutral score (3 on the 1-5 scale) was used for missing indicators when calculating hazards.';
      w.classList.remove('d-none');
    } else w.classList.add('d-none');
    if (!map) { map = new CRMap('map'); map.onClick(inspect); }
    buildPanel(); map.resize(); map.showAOI(L.aoi, L.bounds);
    renderStats(stats); selectLayer('risk_uhi');
    $('recBtn').disabled = $('recBtn2').disabled = false;
    $('workspace').scrollIntoView({ behavior: 'smooth' });
    setTimeout(() => map.resize(), 400);
  }

  /* ---------- layer panel ---------- */
  function buildPanel() {
    const radio = (l, sw) => `<label class="opt${l.available === false ? ' nodata' : ''}"><input type="radio" name="layer" value="${l.id}">${sw ? `<span class="sw" style="background:${sw}"></span>` : ''}<span>${esc(l.label)}</span>${l.available === false ? '<small>no data</small>' : ''}</label>`;
    const sw = l => (l.legend.items ? l.legend.items[4].color : l.legend.palette[l.legend.palette.length - 1]);
    $('riskLayers').innerHTML = ['risk_uhi', 'risk_waterlogging', 'risk_air_pollution'].map(id => S.layers.find(l => l.id === id)).map(l => radio(l, sw(l))).join('');
    $('indGroups').innerHTML = GROUPS.map(([k, name]) => {
      const items = S.layers.filter(l => l.hazard === k && l.group !== 'risk');
      return `<button class="grp collapsed" data-bs-toggle="collapse" data-bs-target="#g_${k}" aria-expanded="false">${name}</button>
        <div class="collapse" id="g_${k}">${items.map(l => radio(l)).join('')}</div>`;
    }).join('');
    document.querySelectorAll('input[name=layer]').forEach(i => i.onchange = () => selectLayer(i.value));
  }
  async function selectLayer(id) {
    S.active = id; const lyr = S.layers.find(l => l.id === id);
    document.querySelectorAll('input[name=layer]').forEach(i => i.checked = i.value === id);
    map.clearLayer(); hide('mapNotice');
    if (lyr.available === false) {
      hide('mapBusy'); $('legend').innerHTML = '';
      $('mapNotice').innerHTML = `<b>Data not available</b>${esc(lyr.label)} could not be generated for this area because no data exists for it here.`;
      show('mapNotice'); return;
    }
    renderLegend(lyr.legend); show('mapBusy');
    try {
      const d = await api(`/api/layers/${id}/tiles`);
      if (d.unavailable) { hide('mapBusy'); $('mapNotice').innerHTML = `<b>Data not available</b>${esc(d.message)}`; show('mapNotice'); return; }
      if (S.active !== id) return;
      const fail = () => { if (S.active !== id) return; hide('mapBusy');
        $('mapNotice').innerHTML = '<b>This layer could not be rendered</b>Earth Engine did not return it for this area (it may be too heavy or timed out). Try again, or choose a smaller area.'; show('mapNotice'); };
      if (d.overlay) {
        const o = map.setOverlay(d.overlay, d.bounds); o.on('load', () => hide('mapBusy')); o.on('error', fail);
      } else {
        const t = map.setLayer(d.url); let bad = 0;
        t.on('tileerror', () => { bad++; }); t.on('load', () => { hide('mapBusy'); if (bad > 3) fail(); });
      }
    } catch (e) { $('mapNotice').innerHTML = `<b>Layer could not be loaded</b>${esc(e.message)}`; show('mapNotice'); hide('mapBusy'); }
    clearTimeout(S.busyT); S.busyT = setTimeout(() => hide('mapBusy'), 180000);   // safety only
  }
  function renderLegend(lg) {
    let h = `<b>${esc(lg.title)}</b>`;
    if (lg.type === 'classes') h += lg.items.map(i => `<div class="lg-item"><i style="background:${i.color}"></i>${esc(i.label)} ${i.range ? `<small>${i.range}</small>` : ''}</div>`).join('');
    else {
      const u = lg.unit && !lg.unit.startsWith('score') ? ' ' + lg.unit : '';
      h += `<div class="lg-ramp">${lg.palette.map(c => `<i style="background:${c}"></i>`).join('')}</div><div class="lg-ends"><span>${lg.min}${esc(u)}</span><span>${lg.max}${esc(u)}</span></div>`;
    }
    $('legend').innerHTML = h;
  }
  document.querySelectorAll('input[name=base]').forEach(i => i.onchange = () => map.setBase(i.value));
  $('opacity').oninput = e => { $('opacityVal').textContent = e.target.value + '%'; map && map.setOpacity(e.target.value / 100); };

  /* ---------- click inspection ---------- */
  async function inspect(ll) {
    if (!S.active) return;
    map.popup(ll, '<div class="pp">Reading location…</div>');
    try {
      const d = await post('/api/map/point-info', { lat: ll.lat, lng: ll.lng, layer: S.active });
      if (d.outside) return map.popup(ll, '<div class="pp">No data here (outside the study area).</div>');
      const badge = l => l ? `<span class="lv" style="background:${LV_COLOR[l]}">${l}</span>` : '–';
      let h = `<div class="pp"><h4>${ll.lat.toFixed(4)}° N, ${ll.lng.toFixed(4)}° E</h4><table>` +
        d.risks.map(r => `<tr><td class="k">${esc(r.name)} risk</td><td>${badge(r.level)}</td></tr>`).join('') + '</table>';
      if (d.indicators.length) h += `<hr class="my-2"><b class="small">${esc(d.focus)} indicators</b><table>` +
        d.indicators.map(i => `<tr><td class="k">${esc(i.label)}</td><td>${i.value == null ? '–' : fmt(i.value, Math.abs(i.value) < 10 ? 3 : 1)} ${esc(i.unit.startsWith('score') ? '' : i.unit)}</td></tr>`).join('') + '</table>';
      map.popup(ll, h + '</div>');
    } catch (e) { map.popup(ll, `<div class="pp">${esc(e.message)}</div>`); }
  }

  /* ---------- statistics ---------- */
  function renderStats(st) {
    const o = st.overview;
    $('overview').innerHTML = [['Total Area', fmt(o.area_km2) + ' km²'], ['Population (WorldPop 2020)', fmtPop(o.population)],
      ['Assessment Location', esc(o.location)], ['Approx. coordinates', `${o.lat.toFixed(4)}° N, ${o.lng.toFixed(4)}° E`]]
      .map(([k, v]) => `<div class="col-6 col-lg-3"><div class="ov-card"><span>${k}</span><b>${v}</b></div></div>`).join('');
    $('hazardStats').innerHTML = ['uhi', 'waterlogging', 'air_pollution'].map(hz => {
      const h = st.hazards[hz], pal = S.layers.find(l => l.id === 'risk_' + hz).legend.items.map(i => i.color);
      const row = (r, kind) => {
        const pct = kind === 'area' ? r.area_pct : r.population_pct, val = kind === 'area' ? fmt(r.area_km2, 2) + ' km²' : Math.round(r.population).toLocaleString();
        return `<div class="srow"><span>${r.level}</span><div class="sbar"><i style="width:${pct}%;background:${pal[r.class - 1]}"></i></div><div class="sval">${pct.toFixed(1)}%<small>${val}</small></div></div>`;
      };
      return `<div class="hz" style="border-top-color:${HZ_COLOR[hz]}"><h3>${esc(h.name)} Risk</h3><div class="row g-4">
        <div class="col-lg-6"><h4>Percentage of AREA in each risk class</h4>${h.rows.map(r => row(r, 'area')).join('')}</div>
        <div class="col-lg-6"><h4>Percentage of POPULATION in each risk class</h4>${[...h.rows].reverse().map(r => row(r, 'pop')).join('')}</div></div></div>`;
    }).join('') + '<p class="small text-muted-cr">Area and population percentages are separate measures. Statistics use the final risk maps (hazard × socio-economic vulnerability ÷ 5).</p>';
  }

  /* ---------- recommendations ---------- */
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  // Buttons that fill with colour while a server job runs (same look for recommendations and the report).
  function fillButtons(ids) {
    const btns = ids.map($).filter(Boolean), old = btns.map(b => b.textContent);
    btns.forEach(b => { b.disabled = true; b.classList.add('btn-progress'); });
    return {
      set: (p, text) => btns.forEach(b => { b.style.setProperty('--p', p + '%'); b.textContent = text; }),
      end: () => btns.forEach((b, i) => { b.classList.remove('btn-progress'); b.style.removeProperty('--p'); b.textContent = old[i]; b.disabled = false; })
    };
  }
  // Polls a background job. Short connection drops (common on phones) are retried instead of failing.
  async function waitFor(url, onProgress) {
    let fails = 0;
    for (;;) {
      await sleep(1200);
      let st;
      try { st = await api(url); fails = 0; }
      catch (e) {
        if (e.status === 404 || e.status === 409) throw new Error('This assessment is no longer available on the server. Please run it again.');
        if (++fails > 60) throw new Error('Connection lost. Please check your internet connection and try again.');
        continue;
      }
      if (st.state === 'failed') throw new Error(st.error || 'The task failed.');
      onProgress(st.progress);
      if (st.state === 'done') return st;
    }
  }
  async function generateRecs() {
    if (S.state !== 'done' || S.recBusy) return;
    if (S.recs) { show('recModal'); return; }
    S.recBusy = true; keepAwake(true);
    const f = fillButtons(['recBtn', 'recBtn2']); f.set(0, 'Starting… 0%');
    let ok = false, notes = [];
    try {
      await post('/api/recommendations', {});
      await waitFor('/api/recommendations/status', p => f.set(p, `Generating recommendations… ${p}%`));
      f.set(100, 'Done');
      const res = await api('/api/recommendations/result');
      S.recs = res.recommendations; notes = res.notes || []; ok = true;
    } catch (e) { msg(e.message, 'danger'); }
    f.end(); S.recBusy = false; keepAwake(false);
    if (!ok) return;
    Recs.render($('recList'), S.recs, locate); show('recsSection');
    if (notes.length) $('recList').insertAdjacentHTML('afterbegin', `<div class="col-12"><div class="alert alert-warning small mb-0">${notes.map(esc).join('<br>')}</div></div>`);
    map.setPins(S.recs, HZ_COLOR, id => { map.highlight(id); Recs.flash(id); map.focusPin(id, Recs.popupHtml(S.recs.find(r => r.id === id))); });
    $('mapActions').innerHTML = '<button class="btn btn-primary" id="seeBtn">See Recommendations</button><button class="btn btn-outline-primary bg-white" id="dlBtn">Download Report</button>';
    $('seeBtn').onclick = seeRecs; $('dlBtn').onclick = downloadReport;
    show('recModal');
  }
  const seeRecs = () => { hide('recModal'); $('recsSection').scrollIntoView({ behavior: 'smooth' }); };
  function locate(id) {
    $('workspace').scrollIntoView({ behavior: 'smooth' });
    setTimeout(() => map.focusPin(id, Recs.popupHtml(S.recs.find(r => r.id === id))), 500);
  }
  // The PDF is fetched with a normal download link (not loaded into memory by JavaScript), which is what
  // mobile browsers handle reliably. On phones the final step is a tap, because browsers only allow
  // downloads that start from a real tap.
  function triggerDownload() {
    const a = document.createElement('a');
    a.href = '/api/report/download';
    const loc = (S.label || '').replace(/[\\/*?:"<>|]/g, '').trim();
    a.download = loc ? `ClimateReady Resilience Report - ${loc}.pdf` : 'ClimateReady Resilience Report.pdf';
    a.rel = 'noopener';
    document.body.appendChild(a); a.click(); a.remove();
  }
  async function downloadReport() {
    if (S.reporting) return;
    S.reporting = true; keepAwake(true);
    const ids = ['reportBtn', 'dlBtn', 'mDlBtn'];
    const f = fillButtons(ids); f.set(0, 'Starting report… 0%');
    try {
      await post('/api/report/start', {});
      await waitFor('/api/report/status', p => f.set(p, `Generating report… ${p}%`));
      keepAwake(false);
      if (TOUCH) {
        f.set(100, '✓ Report ready – tap to download');
        const btns = ids.map($).filter(Boolean);
        btns.forEach(b => { b.disabled = false; });
        await new Promise(res => btns.forEach(b => { b.onclick = () => { triggerDownload(); res(); }; }));
        ids.map($).filter(Boolean).forEach(b => { b.onclick = downloadReport; });
      } else triggerDownload();
    } catch (e) { alert(e.message || 'The report could not be generated.'); }
    f.end(); S.reporting = false; keepAwake(false);
  }

  $('recBtn').onclick = generateRecs; $('recBtn2').onclick = generateRecs;
  $('mViewBtn').onclick = seeRecs; $('mDlBtn').onclick = downloadReport; $('reportBtn').onclick = downloadReport;
  $('mCloseBtn').onclick = () => hide('recModal');

  /* ---------- leaving the page ---------- */
  window.addEventListener('beforeunload', e => { if (hasAssessment()) { e.preventDefault(); e.returnValue = ''; } });
  document.addEventListener('click', e => {
    const a = e.target.closest('a[href]');
    if (!a || !hasAssessment() || a.target === '_blank' || a.getAttribute('href').startsWith('#') || a.hasAttribute('data-bs-toggle') || a.hasAttribute('download')) return;
    if (!confirm('Your current assessment will be lost. Do you want to leave?')) e.preventDefault();
  }, true);

  /* ---------- init ---------- */
  setBusy(false); $('recBtn').disabled = $('recBtn2').disabled = true; renderChips();
  if (!CFG.loaded.district && !CFG.loaded.subdistrict) msg('No shapefiles were found in data/districts or data/subdistricts. See README.md.', 'danger');
  // Leaving the page cancels the job on the server (the browser warning was already shown).
  // (Phones fire page events when you merely switch apps, so there the server relies on its inactivity timeout instead.)
  window.addEventListener('pagehide', () => { if (hasAssessment() && !TOUCH) navigator.sendBeacon('/api/assessment/cancel'); });
  // Back/forward cache would bring back a dead page; reload so it starts clean.
  window.addEventListener('pageshow', e => { if (e.persisted) location.reload(); });
})();
