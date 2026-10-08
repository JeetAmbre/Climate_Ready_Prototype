/* Recommendation cards. Data comes from POST /api/recommendations (library lookup in Python). */
window.Recs = {
  esc(s) { return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); },
  card(r) {
    const e = Recs.esc;
    return `<div class="col-md-6 col-xl-4"><article class="rec" id="rec-${r.id}">
      <div class="tag">${e(r.hazard_label).toUpperCase()}</div><div class="pr">${e(r.priority)}</div>
      <dl>
        <div><dt>Location</dt><dd>${e(r.place)}<br><small class="text-muted-cr">Approx. ${r.lat.toFixed(4)}° N, ${r.lng.toFixed(4)}° E</small></dd></div>
        <div><dt>Primary indicator</dt><dd><span class="ind-chip">${e(r.indicator)}</span>${r.also ? `<small class="text-muted-cr"> · also: ${e(r.also)}</small>` : ''}</dd></div>
        <div><dt>Recommended action</dt><dd>${e(r.action)}</dd></div>
        <div><dt>Addresses</dt><dd>${e(r.addresses)}</dd></div>
        <div><dt>Why this matters</dt><dd>${e(r.why)}</dd></div>
      </dl><button class="btn btn-outline-primary w-100" data-locate="${r.id}">Locate on Map</button></article></div>`;
  },
  render(container, recs, onLocate) {
    container.innerHTML = recs.length ? recs.map(Recs.card).join('')
      : '<div class="col-12"><p class="empty-note">No priority areas (Moderate or above) were identified in this study area.</p></div>';
    container.querySelectorAll('[data-locate]').forEach(b => b.onclick = () => onLocate(+b.dataset.locate));
  },
  popupHtml(r) {
    const e = Recs.esc;
    return `<div class="pp"><h4>${e(r.hazard_label)} · ${e(r.priority)}</h4><table>
      <tr><td class="k">Where</td><td>${e(r.place)}</td></tr><tr><td class="k">Indicator</td><td>${e(r.indicator)}</td></tr>
      <tr><td class="k">Action</td><td>${e(r.action)}</td></tr><tr><td class="k">Why</td><td>${e(r.why)}</td></tr></table></div>`;
  },
  flash(id) { const c = document.getElementById('rec-' + id); if (c) { c.classList.add('flash'); setTimeout(() => c.classList.remove('flash'), 1600); } }
};
