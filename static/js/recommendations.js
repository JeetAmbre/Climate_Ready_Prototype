/* Recommendation cards linked to AI-driven spatial-visual discovery engine.
   Unified grouping: similar recommendations across multiple locations are grouped into one clean card.
*/
window.Recs = {
  esc(s) { 
    return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); 
  },

  group(recs) {
    if (!Array.isArray(recs)) return [];
    const groups = new Map();

    recs.forEach(r => {
      // Normalize action title for clean matching
      const normKey = (r.action || '').trim().toLowerCase().replace(/[\s\-_]+/g, ' ');
      if (!groups.has(normKey)) {
        groups.set(normKey, {
          key: normKey,
          id: r.id,
          hazard: r.hazard,
          hazard_label: r.hazard_label || (r.hazard === 'uhi' ? 'Urban Heat Island' : 'Waterlogging'),
          level: r.level || 'High',
          priority: r.priority || 'HIGH PRIORITY',
          action: r.action,
          short_description: r.short_description || r.why || '',
          why: r.why,
          indicator: r.indicator,
          site_context_summary: r.site_context_summary || r.observed_typology || '',
          expected_impact: r.expected_impact || {},
          source_citation: r.source_citation || (r.source_citations && r.source_citations[0]) || '',
          locations: [],
          ids: [],
          total_area_sqm: 0,
          primaryItem: r
        });
      }
      const g = groups.get(normKey);
      g.locations.push({
        id: r.id,
        n: r.n || r.id,
        place: r.place || 'Study Sector',
        lat: r.lat,
        lng: r.lng,
        area_sqm: r.area_sqm || 50000,
        risk_score: r.risk_score || 4.0,
      });
      g.ids.push(r.id);
      g.total_area_sqm += (r.area_sqm || 50000);
    });

    return Array.from(groups.values());
  },

  card(g) {
    const e = Recs.esc;
    const impact = g.expected_impact || {};
    
    // Impact highlights
    const impacts = [];
    if (impact.surface_temp_reduction_c && impact.surface_temp_reduction_c !== '0') {
      impacts.push(`<span>🌡️ <strong>Surface Cooling:</strong> ${e(impact.surface_temp_reduction_c)}°C</span>`);
    }
    if (impact.indoor_or_ambient_temp_reduction_c && impact.indoor_or_ambient_temp_reduction_c !== '0') {
      impacts.push(`<span>🏠 <strong>Ambient / Indoor Drop:</strong> ${e(impact.indoor_or_ambient_temp_reduction_c)}°C</span>`);
    }
    if (impact.runoff_reduction_pct && impact.runoff_reduction_pct !== '0') {
      impacts.push(`<span>🌊 <strong>Runoff Reduction:</strong> ${e(impact.runoff_reduction_pct)}%</span>`);
    }
    if (!impacts.length && impact.summary) {
      impacts.push(`<span>⚡ ${e(impact.summary)}</span>`);
    }

    const citation = g.source_citation || 'NDMA Urban Resilience Guidelines / NIUA Climate Centre';
    const idsAttr = g.ids.join(',');

    // Locations breakdown
    const locationsHtml = g.locations.map(loc => {
      let cleanPlace = (loc.place || 'Study Area').replace(/^Zone\s*#?\d+\s*[,:\-–—]?\s*/i, '').trim();
      if (!cleanPlace) cleanPlace = loc.place || 'Study Area';
      return `
      <div class="d-flex justify-content-between align-items-center py-1 border-bottom border-light-subtle">
        <span class="text-dark fw-medium text-truncate me-2" style="max-width: 60%;">
          📍 <strong>Zone #${loc.n}:</strong> ${e(cleanPlace)}
        </span>
        <span class="badge bg-white text-secondary border font-monospace" style="font-size: 0.75rem;">
          ${loc.lat.toFixed(4)}° N, ${loc.lng.toFixed(4)}° E
        </span>
      </div>
    `;
    }).join('');

    // Site context wrapped cleanly inside card with word-break
    const contextHtml = g.site_context_summary ? `
      <div class="p-2 mb-2 bg-light rounded border small text-secondary" style="white-space: normal; word-break: break-word; overflow-wrap: break-word; line-height: 1.35;">
        <span class="fw-semibold text-dark">🏗️ Site Context:</span> ${e(g.site_context_summary)}
      </div>
    ` : '';

    return `<div class="col-md-6 col-xl-4"><article class="rec h-100 d-flex flex-column justify-content-between shadow-sm" id="rec-group-${g.id}" data-group-ids="${idsAttr}">
      <div>
        <div class="d-flex justify-content-between align-items-center mb-2">
          <span class="tag mb-0">${e(g.hazard_label).toUpperCase()}</span>
          <span class="badge ${g.level === 'Very High' || g.level === 'High' ? 'bg-danger' : 'bg-warning text-dark'}">
            ${g.locations.length > 1 ? `${g.locations.length} TARGET ZONES` : e(g.priority)}
          </span>
        </div>

        <h4 class="h6 fw-bold text-success mb-1" style="line-height: 1.35;">${e(g.action)}</h4>
        ${g.short_description ? `<p class="small text-muted mb-2" style="line-height: 1.35; white-space: normal; word-break: break-word;">${e(g.short_description)}</p>` : ''}

        ${contextHtml}

        <div class="p-2 bg-light rounded border mb-2 small">
          <div class="d-flex justify-content-between align-items-center mb-1 text-secondary fw-semibold">
            <span>Targeted Hotspot Locations (${g.locations.length}):</span>
            <span class="text-muted small">${(g.total_area_sqm / 10000).toFixed(1)} ha total</span>
          </div>
          <div class="d-flex flex-column" style="max-height: 130px; overflow-y: auto;">
            ${locationsHtml}
          </div>
        </div>

        <dl class="mb-2">
          <div>
            <dt>Expected Quantified Impact</dt>
            <dd class="p-2 bg-light rounded border my-1 small d-flex flex-column gap-1">
              ${impacts.length ? impacts.join('') : '<span>Localized microclimate buffering & runoff detention</span>'}
            </dd>
          </div>
        </dl>
      </div>

      <div>
        <!-- Source / Citation at bottom of card -->
        <div class="mt-2 pt-2 border-top small text-muted" style="white-space: normal; word-break: break-word;">
          <span class="fw-semibold text-secondary">📚 Source:</span>
          <span class="fst-italic text-dark">${e(citation)}</span>
        </div>
        <button class="btn btn-outline-primary btn-sm w-100 mt-2 fw-semibold" data-locate-group="${idsAttr}">
          🗺️ Locate All ${g.locations.length} Zone${g.locations.length > 1 ? 's' : ''} on Map
        </button>
      </div>
    </article></div>`;
  },

  render(container, recs, onLocate) {
    if (!recs || !recs.length) {
      container.innerHTML = '<div class="col-12"><p class="empty-note">No priority areas were identified in this study area.</p></div>';
      return;
    }

    const grouped = Recs.group(recs);
    container.innerHTML = grouped.map(Recs.card).join('');

    // Locate button click handlers
    container.querySelectorAll('[data-locate-group]').forEach(b => {
      b.onclick = (e) => {
        e.stopPropagation();
        const ids = b.dataset.locateGroup.split(',').map(Number);
        const firstId = ids[0];
        const primaryRec = recs.find(x => x.id === firstId) || recs[0];
        onLocate(ids, primaryRec);
      };
    });

    // Clicking card background triggers locate as well
    container.querySelectorAll('article.rec').forEach(art => {
      art.onclick = (e) => {
        if (e.target.tagName !== 'BUTTON') {
          const idsStr = art.dataset.groupIds;
          if (idsStr) {
            const ids = idsStr.split(',').map(Number);
            const firstId = ids[0];
            const primaryRec = recs.find(x => x.id === firstId) || recs[0];
            onLocate(ids, primaryRec);
          }
        }
      };
    });
  },

  popupHtml(r) {
    const e = Recs.esc;
    const impact = r.expected_impact || {};
    let impactText = '';
    if (impact.surface_temp_reduction_c && impact.surface_temp_reduction_c !== '0') impactText += `${impact.surface_temp_reduction_c}°C cooling; `;
    if (impact.runoff_reduction_pct && impact.runoff_reduction_pct !== '0') impactText += `${impact.runoff_reduction_pct}% runoff cut`;
    const citation = r.source_citation || (r.source_citations && r.source_citations[0]) || '';
    let cleanPlace = (r.place || 'Study Area').replace(/^Zone\s*#?\d+\s*[,:\-–—]?\s*/i, '').trim();
    if (!cleanPlace) cleanPlace = r.place || 'Study Area';

    return `<div class="pp">
      <h4>${e(r.hazard_label)} · ${e(r.priority || 'PRIORITY')}</h4>
      <div class="mb-1 text-muted small">Zone #${r.n || r.id}: ${e(cleanPlace)}</div>
      <table>
        <tr><td class="k">Intervention</td><td><strong>${e(r.action)}</strong></td></tr>
        ${(r.site_context_summary || r.observed_typology) ? `<tr><td class="k">Site Context</td><td>${e(r.site_context_summary || r.observed_typology)}</td></tr>` : ''}
        ${impactText ? `<tr><td class="k">Expected Impact</td><td>${e(impactText)}</td></tr>` : ''}
        ${r.why ? `<tr><td class="k">Rationale</td><td>${e(r.why)}</td></tr>` : ''}
        ${citation ? `<tr><td class="k">Source</td><td><span class="small fst-italic">${e(citation)}</span></td></tr>` : ''}
      </table>
    </div>`;
  },

  flash(id) { 
    const c = document.getElementById('rec-group-' + id); 
    if (c) { 
      c.classList.add('flash'); 
      c.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      setTimeout(() => c.classList.remove('flash'), 1800); 
    } 
  }
};
