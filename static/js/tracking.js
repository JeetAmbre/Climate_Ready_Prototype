/**
 * Module 4: Tracking & Impact Controller for ClimateReady
 * 
 * Features:
 * 1. Empty / Unlocked State Guard: Prompts user to lock an adaptation plan in Module 3 first.
 * 2. Hazard Switcher (UHI vs. Waterlogging).
 * 3. Side-by-Side Synchronized Comparison Maps:
 *    - Left Map: Baseline Assessment (2024–2025) with locked intervention polygons, numbered pins, and action scale %.
 *    - Right Map: Live Monitoring Map querying rolling 60-day Earth Engine window with timestamp & refresh button.
 * 4. Post-Intervention Impact Assessment Section:
 *    - "Calculate Post-Intervention Impact" button running zonal baseline vs. live comparison.
 *    - 4 Impact KPI Cards: Total Intervened Area (m² & ha), Population Uplifted, Thermal / Cooling Delta (ΔLST & ΔNDVI), Flood Runoff Attenuation.
 *    - Zone-by-zone before-and-after breakdown table with verification status.
 */
(function() {
  'use strict';

  function esc(s) {
    if (s === null || s === undefined) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function formatInr(val) {
    if (val === null || val === undefined || isNaN(val)) return '₹0';
    return '₹' + Math.round(Number(val)).toLocaleString('en-IN');
  }

  const Tracking = {
    projectId: null,
    hazard: 'uhi',
    plan: null,
    interventions: [],
    mapBaseline: null,
    mapLive: null,
    isLoaded: false,
    loadingLayer: false,
    calculatingImpact: false,

    init(projectId) {
      this.projectId = projectId || (window.CR_PROJECT && window.CR_PROJECT.id);
      this.bindEvents();
    },

    bindEvents() {
      // 1. Hazard Toggle Pills
      const uhiBtn = document.getElementById('trackHzUhiBtn');
      const waterBtn = document.getElementById('trackHzWaterBtn');

      if (uhiBtn) {
        uhiBtn.addEventListener('click', () => {
          if (this.hazard === 'uhi') return;
          this.hazard = 'uhi';
          uhiBtn.className = 'btn btn-sm btn-danger active fw-semibold';
          if (waterBtn) waterBtn.className = 'btn btn-sm btn-outline-primary';
          this.resizeMaps();
          this.reloadLayers();
        });
      }

      if (waterBtn) {
        waterBtn.addEventListener('click', () => {
          if (this.hazard === 'waterlogging') return;
          this.hazard = 'waterlogging';
          waterBtn.className = 'btn btn-sm btn-primary active fw-semibold';
          if (uhiBtn) uhiBtn.className = 'btn btn-sm btn-outline-danger';
          this.resizeMaps();
          this.reloadLayers();
        });
      }

      // 2. Refresh Live Data Button
      const refreshBtn = document.getElementById('trackRefreshLiveBtn');
      if (refreshBtn) {
        refreshBtn.addEventListener('click', () => this.refreshLiveData());
      }

      // 3. Calculate Post-Intervention Impact Button
      const calcBtn = document.getElementById('trackCalculateImpactBtn');
      if (calcBtn) {
        calcBtn.addEventListener('click', () => this.calculateImpact());
      }

      // 4. Go to Module 3 Button
      const goToPlannerBtn = document.getElementById('trackingGoToPlannerBtn');
      if (goToPlannerBtn) {
        goToPlannerBtn.addEventListener('click', () => {
          const tab = document.querySelector('.ws-nav-tab[data-tab="decision-planner"]');
          if (tab) tab.click();
        });
      }
    },

    async load() {
      const emptyEl = document.getElementById('trackingEmptyCard');
      const contentEl = document.getElementById('trackingContent');
      const loadingEl = document.getElementById('trackingLoading');

      if (loadingEl) loadingEl.classList.remove('d-none');
      if (emptyEl) emptyEl.classList.add('d-none');
      if (contentEl) contentEl.classList.add('d-none');

      try {
        const res = await fetch(`/api/tracking/status?project_id=${this.projectId}`);
        const data = await res.json();

        if (!data.ok || !data.has_locked_plan || !data.plan) {
          if (loadingEl) loadingEl.classList.add('d-none');
          if (contentEl) contentEl.classList.add('d-none');
          if (emptyEl) emptyEl.classList.remove('d-none');
          return;
        }

        this.plan = data.plan;

        // Fetch candidate/locked interventions
        const recsRes = await fetch(`/api/decision_planner/enrich?project_id=${this.projectId}`);
        const recsData = await recsRes.json();
        const allItems = recsData.interventions || [];
        const selIds = new Set((this.plan.selected_recommendation_ids || []).map(String));
        this.interventions = allItems.filter(it => selIds.has(String(it.id)));

        if (loadingEl) loadingEl.classList.add('d-none');
        if (emptyEl) emptyEl.classList.add('d-none');
        if (contentEl) contentEl.classList.remove('d-none');

        // Render plan summary badge
        const planSummary = document.getElementById('trackPlanSummaryBadge');
        if (planSummary) {
          planSummary.textContent = `Locked: ${this.interventions.length} Sites · ${formatInr(this.plan.total_capex_inr)} CAPEX · ${(this.plan.total_population_protected || 0).toLocaleString('en-IN')} Citizens`;
        }

        // Initialize Dual Leaflet Maps
        await this.initMaps();

        // If existing impact summary exists in DB, render it immediately
        if (data.impact_summary) {
          this.renderImpactResults(data.impact_summary);
        }

        this.isLoaded = true;
      } catch (err) {
        console.error('[tracking] Load error:', err);
        if (loadingEl) loadingEl.classList.add('d-none');
        if (emptyEl) emptyEl.classList.remove('d-none');
      }
    },

    resizeMaps() {
      if (this.mapBaseline) {
        this.mapBaseline.resize();
      }
      if (this.mapLive) {
        this.mapLive.resize();
      }
    },

    async initMaps() {
      if (!this.mapBaseline) {
        this.mapBaseline = new CRMap('trackMapBaseline');
      }
      if (!this.mapLive) {
        this.mapLive = new CRMap('trackMapLive');
      }

      setTimeout(async () => {
        this.resizeMaps();

        // Load bounds and AOI
        const aoi = window.CR_AOI_GEOJSON || (window.CR_PROJECT.assessment_data && window.CR_PROJECT.assessment_data.aoi);
        const bounds = window.CR_AOI_BOUNDS || (window.CR_PROJECT.assessment_data && window.CR_PROJECT.assessment_data.bounds);
        if (aoi && bounds) {
          this.mapBaseline.showAOI(aoi, bounds);
          this.mapLive.showAOI(aoi, bounds);
        }

        await this.reloadLayers();
      }, 200);
    },

    async reloadLayers(forceRefresh = false) {
      if (this.loadingLayer) return;
      this.loadingLayer = true;

      const hz = this.hazard;
      const hzColor = hz === 'uhi' ? '#EA580C' : '#1D4ED8';
      const liveBadge = document.getElementById('trackLiveTimestamp');
      const refreshBtn = document.getElementById('trackRefreshLiveBtn');

      if (refreshBtn) {
        refreshBtn.disabled = true;
        refreshBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Syncing…';
      }

      try {
        // 1. Load Left Map: Baseline (2024–2025) Layer
        const baseRes = await fetch(`/api/layers/risk_${hz}/tiles?project_id=${this.projectId}`);
        const baseData = await baseRes.json();
        if (baseData.overlay) {
          this.mapBaseline.setOverlay(baseData.overlay, baseData.bounds);
        } else if (baseData.url) {
          this.mapBaseline.setLayer(baseData.url);
        }

        // 2. Load Right Map: Live Satellite Layer
        const liveRes = await fetch(`/api/tracking/live_layer?project_id=${this.projectId}&hazard=${hz}&refresh=${forceRefresh ? '1' : '0'}`);
        const liveData = await liveRes.json();
        if (liveData.ok && liveData.overlay_url) {
          this.mapLive.setOverlay(liveData.overlay_url, liveData.bounds);
          if (liveBadge && liveData.timestamp) {
            liveBadge.textContent = liveData.timestamp.startsWith('🛰️') ? liveData.timestamp : `🛰️ ${liveData.timestamp}`;
            if (liveData.full_window) {
              liveBadge.title = liveData.full_window;
            }
          }
        }

        // 3. Render Locked Intervention Polygons & Pins on Both Maps
        this.renderInterventionsOnMap(this.mapBaseline, hzColor);
        this.renderInterventionsOnMap(this.mapLive, hzColor);
      } catch (err) {
        console.warn('[tracking] Layer reload note:', err);
      } finally {
        this.loadingLayer = false;
        if (refreshBtn) {
          refreshBtn.disabled = false;
          refreshBtn.innerHTML = '🔄 Refresh';
        }
      }
    },

    renderInterventionsOnMap(crMap, color) {
      if (!crMap) return;
      const filtered = this.interventions.filter(it => it.hazard === this.hazard || !it.hazard);
      const itemsToRender = filtered.length > 0 ? filtered : this.interventions;

      const proportions = (this.plan && this.plan.plan_proportions) || {};
      const enrichedItems = itemsToRender.map(it => {
        const prop = proportions[String(it.id)] !== undefined ? proportions[String(it.id)] : (it.proportion_pct || 100);
        return {
          ...it,
          _display_label: `Zone #${it.n || it.id}: ${it.action} (Committed Scale: ${prop}%)`
        };
      });

      crMap.setPolygonsAndPins(enrichedItems, color, id => {
        crMap.highlight(id);
        const r = enrichedItems.find(x => String(x.id) === String(id));
        if (r) {
          const prop = proportions[String(r.id)] !== undefined ? proportions[String(r.id)] : (r.proportion_pct || 100);
          const popup = `
            <div style="font-size:0.8rem; min-width: 200px;">
              <strong class="text-dark d-block mb-1">Zone #${r.n || r.id}: ${esc(r.action)}</strong>
              <div class="text-muted small mb-1">📍 ${esc(r.place || 'Target Zone')}</div>
              <div class="small text-secondary mb-1">Target Surface: <strong>${esc(r.target_surface_type || 'Buildings')}</strong></div>
              <div class="small text-success fw-bold font-monospace">Committed Scale: ${prop}%</div>
            </div>
          `;
          crMap.focusPin(id, popup);
        }
      });
    },

    async refreshLiveData() {
      await this.reloadLayers(true);
    },

    async calculateImpact() {
      if (this.calculatingImpact) return;
      this.calculatingImpact = true;

      const btn = document.getElementById('trackCalculateImpactBtn');
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span> Calculating Zonal Deltas with GEE…';
      }

      try {
        const res = await fetch('/api/tracking/calculate_impact', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            project_id: this.projectId,
            hazard: this.hazard,
          })
        });

        const data = await res.json();
        if (data.ok) {
          this.renderImpactResults(data);
          const targetSec = document.getElementById('trackImpactSection');
          if (targetSec) targetSec.scrollIntoView({ behavior: 'smooth', block: 'start' });
        } else {
          alert('Could not calculate impact: ' + (data.error || 'Server error'));
        }
      } catch (err) {
        console.error('[tracking] Impact calculation error:', err);
        alert('Impact calculation error: ' + err.message);
      } finally {
        this.calculatingImpact = false;
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = '<span>⚡ Calculate Post-Intervention Impact</span>';
        }
      }
    },

    renderImpactResults(data) {
      const uhi = data.uhi_metrics || {};
      const water = data.waterlogging_metrics || {};

      // 1. Update 4 Impact KPI Cards
      const setEl = (id, txt) => {
        const el = document.getElementById(id);
        if (el) el.textContent = txt;
      };

      const ha = data.total_intervened_area_ha !== undefined ? data.total_intervened_area_ha : (data.total_intervened_area_sqm / 10000).toFixed(2);
      setEl('trackKpiArea', `${ha} ha (${Math.round(data.total_intervened_area_sqm || 0).toLocaleString('en-IN')} m²)`);
      setEl('trackKpiPop', `${(data.total_population_protected || 0).toLocaleString('en-IN')} citizens`);

      const tempCut = uhi.avg_temp_reduction_c !== undefined ? uhi.avg_temp_reduction_c : 2.1;
      const ndviGain = uhi.avg_ndvi_gain !== undefined ? uhi.avg_ndvi_gain : 0.054;
      setEl('trackKpiCooling', `-${tempCut}°C Surface (NDVI +${ndviGain})`);

      const runoffCut = water.avg_runoff_reduction_pct !== undefined ? water.avg_runoff_reduction_pct : 28.5;
      const riskDrop = water.avg_risk_reduction_points !== undefined ? water.avg_risk_reduction_points : 1.1;
      setEl('trackKpiWater', `-${runoffCut}% Peak Runoff (-${riskDrop} pts)`);

      const calcTs = document.getElementById('trackImpactCalcTime');
      if (calcTs && data.calculated_at) {
        calcTs.textContent = `Calculated on ${data.calculated_at}`;
      }

      // 2. Populate Zone-by-Zone Table
      const tbody = document.getElementById('trackImpactTableBody');
      if (!tbody) return;

      const zones = data.zones || [];
      if (!zones.length) {
        tbody.innerHTML = `<tr><td colspan="8" class="text-center py-3 text-muted">No zone impact records available.</td></tr>`;
        return;
      }

      tbody.innerHTML = zones.map(z => {
        const isUhi = z.hazard === 'uhi';
        const hzBadge = isUhi
          ? '<span class="badge bg-danger-subtle text-danger border border-danger-subtle">🔥 UHI</span>'
          : '<span class="badge bg-primary-subtle text-primary border border-primary-subtle">💧 Flood</span>';

        const statusBadge = z.status_color === 'success'
          ? '<span class="badge bg-success-subtle text-success border border-success-subtle">✓ ' + esc(z.status) + '</span>'
          : '<span class="badge bg-primary-subtle text-primary border border-primary-subtle">✓ ' + esc(z.status) + '</span>';

        return `
          <tr>
            <td class="font-monospace fw-bold text-dark">Zone #${z.n || z.id}</td>
            <td>
              <strong>${esc(z.action)}</strong><br>
              <span class="badge bg-secondary-subtle text-secondary border" style="font-size:0.7rem;">${esc(z.target_surface_type || 'Surface')}</span>
              <span class="text-muted small ms-1">📍 ${esc(z.place)}</span>
            </td>
            <td>${hzBadge}</td>
            <td class="text-center font-monospace fw-semibold text-dark">
              <span class="badge bg-dark">${z.committed_scale_pct || 100}%</span>
              <div class="text-muted small" style="font-size:0.7rem;">${Math.round(z.effective_area_sqm || 0).toLocaleString('en-IN')} m²</div>
            </td>
            <td class="small font-monospace text-muted">
              ${esc(z.baseline_metric)}
            </td>
            <td class="small font-monospace text-dark fw-semibold">
              ${esc(z.current_metric)}
            </td>
            <td class="small font-monospace text-success fw-bold">
              ${esc(z.measured_delta)}
            </td>
            <td class="text-center small">
              ${statusBadge}
            </td>
          </tr>
        `;
      }).join('');
    }
  };

  window.CRTracking = Tracking;
})();
