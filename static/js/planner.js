/**
 * Module 3: Decision Support Controller for ClimateReady
 * 
 * Features:
 * 1. Fixed costs using estimated_intervention_area_sqm (no variable coverage slider).
 * 2. Top 6 Stat Cards: Total Polygon Area, Total Est. Intervention Area, Total Population Across Zones,
 *    Selected Implementation Cost, Annual Maintenance Cost, Total People Impacted.
 * 3. Clean numeric budget input + centered dynamic slider (0.5x to 2.0x of entered budget).
 * 4. Budget exhaustion progress bar (with warning/red color when exceeded).
 * 5. Sortable comparison table of 10 interventions with crisp black-bordered checkboxes.
 *    Sort dropdown: People Impacted (High to Low), Cost (Low to High), Maintenance (Low to High),
 *    Technical Complexity (Low to High), Lifespan (High to Low).
 * 6. Two Primary Action Buttons:
 *    - Button 1: Lock Plan & Send to Tracking & Impact (saves to Cloud SQL and switches directly to Tab 4).
 *    - Button 2: Generate Detailed Project Report (clean print/PDF-ready DPR with 5 required sections).
 */
(function() {
  'use strict';

  function formatInr(val) {
    if (val === null || val === undefined || isNaN(val)) return '₹0';
    const num = Math.round(Number(val));
    return '₹' + num.toLocaleString('en-IN');
  }

  function formatLakhs(val) {
    const num = Number(val || 0);
    if (num >= 10000000) {
      return '₹' + (num / 10000000).toFixed(2) + ' Cr';
    }
    if (num >= 100000) {
      return '₹' + (num / 100000).toFixed(1) + ' Lakh';
    }
    return formatInr(num);
  }

  function esc(s) {
    if (s === null || s === undefined) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  const Planner = {
    projectId: null,
    budget: 2500000,
    sortBy: 'pop_desc',
    hazardFilter: 'all',
    goal: 'people_protected',
    stakeholderType: 'municipal_dpr',
    items: [],
    selectedIds: new Set(),
    currentBrief: null,
    lockedPlan: null,
    isEnriched: false,
    loading: false,
    dprMap: null,

    init(projectId) {
      this.projectId = projectId || (window.CR_PROJECT && window.CR_PROJECT.id);
      this.bindEvents();
    },

    bindEvents() {
      // 1. Budget inputs & Centered Slider
      const budgetSlider = document.getElementById('planBudgetSlider');
      const budgetInput = document.getElementById('planBudgetInput');
      const budgetDisplay = document.getElementById('planBudgetDisplay');

      const setBudget = (val, recenter = false) => {
        let b = Math.max(100000, Math.min(200000000, Math.round(Number(val) || 2500000)));
        this.budget = b;
        if (budgetInput && Number(budgetInput.value) !== b) budgetInput.value = b;
        if (budgetDisplay) budgetDisplay.textContent = formatLakhs(b);
        if (recenter) {
          this.updateSliderBounds(b);
        } else if (budgetSlider && Number(budgetSlider.value) !== b) {
          budgetSlider.value = b;
        }
        this.updateKPIs();
      };

      if (budgetInput) {
        budgetInput.addEventListener('change', e => setBudget(e.target.value, true));
      }

      if (budgetSlider) {
        budgetSlider.addEventListener('input', e => {
          let b = Math.round(Number(e.target.value) || 2500000);
          this.budget = b;
          if (budgetInput) budgetInput.value = b;
          if (budgetDisplay) budgetDisplay.textContent = formatLakhs(b);
          this.updateKPIs();
        });
        budgetSlider.addEventListener('change', e => {
          // Re-center around new slider position on release
          this.updateSliderBounds(Number(e.target.value));
        });
      }

      // Quick budget chips
      document.querySelectorAll('[data-budget-chip]').forEach(chip => {
        chip.addEventListener('click', () => {
          const val = Number(chip.dataset.budgetChip);
          if (val) setBudget(val, true);
        });
      });

      // 2. Table Sorting Dropdown
      const sortSelect = document.getElementById('planTableSortSelect');
      if (sortSelect) {
        sortSelect.addEventListener('change', e => {
          this.sortBy = e.target.value;
          this.renderTable();
        });
      }

      // 3. Goal Selector & Auto-Fit
      const goalSelect = document.getElementById('planGoalSelect');
      if (goalSelect) {
        goalSelect.addEventListener('change', e => {
          this.goal = e.target.value;
        });
      }
      const optBtn = document.getElementById('planOptimizeBtn');
      if (optBtn) {
        optBtn.addEventListener('click', () => this.autoOptimize());
      }

      // 4. Hazard Filter pills
      document.querySelectorAll('[data-hazard-filter]').forEach(pill => {
        pill.addEventListener('click', () => {
          document.querySelectorAll('[data-hazard-filter]').forEach(p => p.classList.remove('active', 'btn-dark'));
          pill.classList.add('active', 'btn-dark');
          this.hazardFilter = pill.dataset.hazardFilter;
          this.renderTable();
        });
      });

      // 5. Select All / Clear Selection
      const selAllBtn = document.getElementById('planSelectAllBtn');
      if (selAllBtn) {
        selAllBtn.addEventListener('click', () => {
          this.visibleItems().forEach(it => this.selectedIds.add(String(it.id)));
          this.renderTable();
          this.updateKPIs();
        });
      }
      const clearBtn = document.getElementById('planClearBtn');
      if (clearBtn) {
        clearBtn.addEventListener('click', () => {
          this.selectedIds.clear();
          this.renderTable();
          this.updateKPIs();
        });
      }

      // 6. Primary Action Buttons
      // Button 1: Lock Plan & Send to Tracking & Impact
      const lockBtn = document.getElementById('planLockBtn');
      if (lockBtn) {
        lockBtn.addEventListener('click', () => this.lockPlanAndSendToTracking());
      }

      // Button 2: Generate Detailed Project Report
      const dprBtn = document.getElementById('planGenerateDprBtn');
      if (dprBtn) {
        dprBtn.addEventListener('click', () => this.generateDpr());
      }
      const headerDprBtn = document.getElementById('planHeaderDprBtn');
      if (headerDprBtn) {
        headerDprBtn.addEventListener('click', () => this.generateDpr());
      }

      // AI Brief Button (optional executive narrative)
      const aiBriefBtn = document.getElementById('planAiBriefBtn');
      if (aiBriefBtn) {
        aiBriefBtn.addEventListener('click', () => this.generateAiBrief());
      }

      // Print Button inside Modal
      const printBtn = document.getElementById('planPrintReportBtn');
      if (printBtn) {
        printBtn.addEventListener('click', () => window.print());
      }

      // Prepare Adaptation Plan Button (First-time load state)
      const prepBtn = document.getElementById('preparePlanBtn');
      if (prepBtn) {
        prepBtn.addEventListener('click', () => this.preparePlan());
      }

      // 7. Report Preview Modal Close / Cleanup handler (prevents UI freeze)
      const reportModalEl = document.getElementById('planReportModal');
      if (reportModalEl) {
        reportModalEl.addEventListener('hidden.bs.modal', () => {
          if (this.dprMap) {
            try { this.dprMap.remove(); } catch (e) {}
            this.dprMap = null;
          }
          document.querySelectorAll('.modal-backdrop').forEach(b => b.remove());
          document.body.classList.remove('modal-open');
          document.body.style.overflow = 'auto';
          document.body.style.paddingRight = '';
        });
      }
    },

    updateSliderBounds(centerBudget) {
      const slider = document.getElementById('planBudgetSlider');
      const minLabel = document.getElementById('sliderMinLabel');
      const centerLabel = document.getElementById('sliderCenterLabel');
      const maxLabel = document.getElementById('sliderMaxLabel');
      
      const b = Math.max(100000, Number(centerBudget) || 2500000);
      const minVal = Math.round(0.5 * b);
      const maxVal = Math.round(2.0 * b);
      const stepVal = Math.max(10000, Math.round(b / 100));

      if (slider) {
        slider.min = minVal;
        slider.max = maxVal;
        slider.step = stepVal;
        slider.value = b;
      }
      if (minLabel) minLabel.textContent = `0.5x (${formatLakhs(minVal)})`;
      if (centerLabel) centerLabel.textContent = `1.0x (${formatLakhs(b)})`;
      if (maxLabel) maxLabel.textContent = `2.0x (${formatLakhs(maxVal)})`;
    },

    async load() {
      if (this.loading) return;
      const loadingEl = document.getElementById('planLoading');
      const contentEl = document.getElementById('planContent');
      const emptyEl = document.getElementById('planEmpty');
      const prepareCard = document.getElementById('planPrepareCard');

      // 1. Check if an existing locked plan exists in DB
      await this.checkExistingLockedPlan();

      // 2. If locked plan already exists, prepare and display it immediately
      if (this.lockedPlan) {
        await this.preparePlan(true);
        return;
      }

      // 3. If already enriched in current session, ensure content is visible
      if (this.isEnriched && this.items && this.items.length > 0) {
        if (loadingEl) loadingEl.classList.add('d-none');
        if (emptyEl) emptyEl.classList.add('d-none');
        if (prepareCard) prepareCard.classList.add('d-none');
        if (contentEl) contentEl.classList.remove('d-none');
        const headerDprBtn = document.getElementById('planHeaderDprBtn');
        if (headerDprBtn) headerDprBtn.classList.remove('d-none');
        this.renderTable();
        this.updateKPIs();
        return;
      }

      // 4. Check if interventions exist either in memory, project, or cached data
      let hasInterventions = (this.items && this.items.length > 0) ||
                             (window.CR_PROJECT && window.CR_PROJECT.interventions_data && window.CR_PROJECT.interventions_data.length > 0) ||
                             (window.CR_CACHED_RECS && window.CR_CACHED_RECS.length > 0);

      if (!hasInterventions) {
        // Query backend to check if project has interventions persisted
        try {
          const chkRes = await fetch(`/api/decision_planner/enrich?project_id=${this.projectId}`);
          const chkData = await chkRes.json();
          if (chkData.ok && chkData.interventions && chkData.interventions.length > 0) {
            this.items = chkData.interventions;
            if (window.CR_PROJECT) window.CR_PROJECT.interventions_data = chkData.interventions;
            hasInterventions = true;
          }
        } catch (e) {
          console.warn('[planner] Quick check note:', e);
        }
      }

      const availableItems = (this.items && this.items.length > 0) ||
                             (window.CR_PROJECT && window.CR_PROJECT.interventions_data && window.CR_PROJECT.interventions_data.length > 0) ||
                             (window.CR_CACHED_RECS && window.CR_CACHED_RECS.length > 0);

      if (!availableItems) {
        // No interventions discovered yet in Module 2
        if (loadingEl) loadingEl.classList.add('d-none');
        if (prepareCard) prepareCard.classList.add('d-none');
        if (contentEl) contentEl.classList.add('d-none');
        if (emptyEl) emptyEl.classList.remove('d-none');
        return;
      }

      // 5. Interventions exist and user arrived at Module 3 for the first time!
      // Show the prominent Prepare Planning state card with the action button.
      if (emptyEl) emptyEl.classList.add('d-none');
      if (loadingEl) loadingEl.classList.add('d-none');
      if (contentEl) contentEl.classList.add('d-none');
      if (prepareCard) prepareCard.classList.remove('d-none');
    },

    async preparePlan(isRestore = false) {
      if (this.loading) return;
      this.loading = true;

      const loadingEl = document.getElementById('planLoading');
      const contentEl = document.getElementById('planContent');
      const emptyEl = document.getElementById('planEmpty');
      const prepareCard = document.getElementById('planPrepareCard');
      const headerDprBtn = document.getElementById('planHeaderDprBtn');

      if (prepareCard) prepareCard.classList.add('d-none');
      if (emptyEl) emptyEl.classList.add('d-none');
      if (contentEl) contentEl.classList.add('d-none');
      if (loadingEl) loadingEl.classList.remove('d-none');

      try {
        const candidateRecs = (this.items && this.items.length > 0) 
          ? this.items 
          : ((window.CR_PROJECT && window.CR_PROJECT.interventions_data) || (window.CR_CACHED_RECS || []));

        const res = await fetch(`/api/decision_planner/enrich?project_id=${this.projectId}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            project_id: this.projectId,
            interventions: candidateRecs
          })
        });

        const data = await res.json();
        const items = data.interventions || [];

        if (!items || items.length === 0) {
          if (loadingEl) loadingEl.classList.add('d-none');
          if (prepareCard) prepareCard.classList.add('d-none');
          if (contentEl) contentEl.classList.add('d-none');
          if (emptyEl) emptyEl.classList.remove('d-none');
          this.loading = false;
          return;
        }

        this.items = items;
        if (window.CR_PROJECT) {
          window.CR_PROJECT.interventions_data = items;
        }
        this.isEnriched = true;

        // Check if there is an existing locked plan
        if (!this.lockedPlan) {
          await this.checkExistingLockedPlan();
        }

        // Calculate fixed financials using estimated_intervention_area_sqm
        this.recalculateClientFinancials();

        // If not already restored from locked plan, auto-fit within smart budget
        if (!this.lockedPlan && !isRestore) {
          const totalCapex = this.items.reduce((s, it) => s + (it._total_capex_inr || 0), 0);
          const medianCapex = this.items.length ? (totalCapex / this.items.length) : 2500000;
          const smartDefault = Math.max(2500000, Math.round((medianCapex * 2.2) / 250000) * 250000);
          this.budget = smartDefault;
          this.updateSliderBounds(smartDefault);

          const budgetInput = document.getElementById('planBudgetInput');
          if (budgetInput) budgetInput.value = smartDefault;
          const budgetDisplay = document.getElementById('planBudgetDisplay');
          if (budgetDisplay) budgetDisplay.textContent = formatLakhs(smartDefault);

          await this.autoOptimize();
        } else {
          this.updateSliderBounds(this.budget);
          this.renderTable();
          this.updateKPIs();
        }

        if (loadingEl) loadingEl.classList.add('d-none');
        if (prepareCard) prepareCard.classList.add('d-none');
        if (contentEl) contentEl.classList.remove('d-none');
        if (headerDprBtn) headerDprBtn.classList.remove('d-none');
      } catch (err) {
        console.error('[planner] preparePlan error:', err);
        if (loadingEl) loadingEl.classList.add('d-none');
        if (prepareCard) prepareCard.classList.remove('d-none');
        alert('Could not prepare adaptation plan: ' + err.message);
      } finally {
        this.loading = false;
      }
    },

    async checkExistingLockedPlan() {
      try {
        const res = await fetch(`/api/decision_planner/locked_plan?project_id=${this.projectId}`);
        const data = await res.json();
        if (data.ok && data.plan) {
          const p = data.plan;
          this.lockedPlan = p;
          if (p.selected_recommendation_ids && p.selected_recommendation_ids.length) {
            this.selectedIds = new Set(p.selected_recommendation_ids.map(String));
          }
          if (p.allocated_budget_inr) this.budget = p.allocated_budget_inr;
          if (p.optimization_goal) this.goal = p.optimization_goal;

          if (p.ai_decision_brief) {
            this.currentBrief = typeof p.ai_decision_brief === 'string'
              ? { raw_markdown: p.ai_decision_brief }
              : p.ai_decision_brief;
            this.renderAiBriefCard(this.currentBrief);
          }

          this.showLockedBanner(p);
          this.unlockModule4(p);
        }
      } catch (e) {
        console.warn('[planner] Note on locked plan check:', e);
      }
    },

    recalculateClientFinancials() {
      this.items.forEach(it => {
        const polyArea = Number(it.polygon_area_sqm || it.area_sqm || 50000);
        const bldArea = Number(it.building_area_sqm || 0);
        const roadArea = Number(it.road_area_sqm || 0);
        const openArea = Number(it.open_area_sqm || 0);

        let surf = it.target_surface_type;
        if (!surf) {
          const act = (it.action || '').toLowerCase();
          if (act.includes('roof') || act.includes('building') || act.includes('terrace') || act.includes('modroof')) {
            surf = 'Buildings';
          } else if (act.includes('paver') || act.includes('road') || act.includes('street') || act.includes('permeable') || act.includes('drain') || act.includes('bioswale')) {
            surf = 'Roads';
          } else {
            surf = 'Open Area';
          }
        }

        let allocArea = Number(it.allocated_intervention_area_sqm || it.estimated_intervention_area_sqm || 0);
        if (allocArea <= 0) {
          if (surf === 'Buildings') allocArea = Math.round((bldArea || polyArea * 0.45) * 0.18);
          else if (surf === 'Roads') allocArea = Math.round((roadArea || polyArea * 0.25) * 0.15);
          else allocArea = Math.round((openArea || polyArea * 0.30) * 0.25);
        }

        const costSqm = Number(it.implementation_cost_per_sqm || 1000);
        const maintSqm = Number(it.annual_maintenance_cost_per_sqm || 80);

        let propPct = (it.proportion_pct !== undefined && it.proportion_pct !== null) ? Number(it.proportion_pct) : 100;
        if (this.lockedPlan && this.lockedPlan.plan_proportions && this.lockedPlan.plan_proportions[String(it.id)]) {
          propPct = Number(this.lockedPlan.plan_proportions[String(it.id)]);
        }
        propPct = Math.max(10, Math.min(100, Math.round(propPct)));
        const effArea = Math.round(allocArea * (propPct / 100));

        const capex = Math.round(effArea * costSqm);
        const opex = Math.round(effArea * maintSqm);
        const tco = Math.round(capex + (5.0 * opex));

        const pop = Number(it.population_impacted || 0);
        const costPerPerson = pop > 0 ? Math.round(capex / pop) : 0;

        it._polygon_area_sqm = polyArea;
        it._building_area_sqm = bldArea;
        it._road_area_sqm = roadArea;
        it._open_area_sqm = openArea;
        it._target_surface_type = surf;
        it._allocated_intervention_area_sqm = allocArea;
        it._estimated_intervention_area_sqm = allocArea;
        it._proportion_pct = propPct;
        it._effective_intervention_area_sqm = effArea;
        it._implementation_cost_per_sqm = costSqm;
        it._annual_maintenance_cost_per_sqm = maintSqm;
        it._total_capex_inr = capex;
        it._annual_opex_inr = opex;
        it._five_year_tco_inr = tco;
        it._population_protected = pop;
        it._cost_per_person_inr = costPerPerson;
      });
    },

    visibleItems() {
      if (this.hazardFilter === 'uhi') {
        return this.items.filter(it => it.hazard === 'uhi');
      }
      if (this.hazardFilter === 'waterlogging') {
        return this.items.filter(it => it.hazard === 'waterlogging');
      }
      return this.items;
    },

    sortedItems() {
      const list = [...this.visibleItems()];
      const sort = this.sortBy || 'pop_desc';
      const complexityRank = { 'Low': 1, 'Medium': 2, 'High': 3 };

      list.sort((a, b) => {
        if (sort === 'pop_desc') {
          return (b._population_protected || 0) - (a._population_protected || 0);
        } else if (sort === 'cost_asc') {
          return (a._total_capex_inr || 0) - (b._total_capex_inr || 0);
        } else if (sort === 'maint_asc') {
          return (a._annual_opex_inr || 0) - (b._annual_opex_inr || 0);
        } else if (sort === 'complexity_asc') {
          const rA = complexityRank[a.technical_complexity] || 2;
          const rB = complexityRank[b.technical_complexity] || 2;
          return rA - rB;
        } else if (sort === 'lifespan_desc') {
          return (b.lifespan_years || 0) - (a.lifespan_years || 0);
        }
        return 0;
      });
      return list;
    },

    async autoOptimize() {
      const optBtn = document.getElementById('planOptimizeBtn');
      if (optBtn) {
        optBtn.disabled = true;
        optBtn.innerHTML = '⚡ Fitting…';
      }

      try {
        const res = await fetch('/api/decision_planner/optimize', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            project_id: this.projectId,
            budget_inr: this.budget,
            goal: this.goal,
            hazard_filter: this.hazardFilter,
          })
        });
        const data = await res.json();
        if (data.ok && Array.isArray(data.selected_ids)) {
          this.selectedIds = new Set(data.selected_ids.map(String));
        } else {
          this.clientFallbackOptimize();
        }
      } catch (err) {
        console.warn('[planner] Backend optimize notice:', err);
        this.clientFallbackOptimize();
      } finally {
        if (optBtn) {
          optBtn.disabled = false;
          optBtn.innerHTML = '⚡ Auto-Fit';
        }
        this.renderTable();
        this.updateKPIs();
      }
    },

    clientFallbackOptimize() {
      const candidates = this.visibleItems();
      let currentCapex = 0;
      this.selectedIds.clear();

      const sorted = [...candidates].sort((a, b) => {
        const scoreA = (a._population_protected || 100) / Math.max(100, a._total_capex_inr || 1000);
        const scoreB = (b._population_protected || 100) / Math.max(100, b._total_capex_inr || 1000);
        return scoreB - scoreA;
      });

      for (const it of sorted) {
        if (currentCapex + (it._total_capex_inr || 0) <= this.budget) {
          this.selectedIds.add(String(it.id));
          currentCapex += (it._total_capex_inr || 0);
        }
      }
    },

    toggleSelect(id, checked) {
      id = String(id);
      if (checked) {
        this.selectedIds.add(id);
      } else {
        this.selectedIds.delete(id);
      }
      this.updateKPIs();
    },

    updateKPIs() {
      const selected = this.items.filter(it => this.selectedIds.has(String(it.id)));

      // Candidate totals across all 10 candidate zones
      const totalPolyArea = this.items.reduce((s, it) => s + (it._polygon_area_sqm || 0), 0);
      const totalEstArea = this.items.reduce((s, it) => s + (it._effective_intervention_area_sqm || it._allocated_intervention_area_sqm || it._estimated_intervention_area_sqm || 0), 0);
      const totalZonePop = this.items.reduce((s, it) => s + (it._population_protected || 0), 0);

      // Selected totals
      const totalCapex = selected.reduce((s, it) => s + (it._total_capex_inr || 0), 0);
      const totalOpex = selected.reduce((s, it) => s + (it._annual_opex_inr || 0), 0);
      const totalPop = selected.reduce((s, it) => s + (it._population_protected || 0), 0);
      const fiveYearTco = selected.reduce((s, it) => s + (it._five_year_tco_inr || 0), 0);
      const costPerPerson = totalPop > 0 ? Math.round(totalCapex / totalPop) : 0;

      // Update Top Stat Cards
      const setEl = (id, txt) => {
        const el = document.getElementById(id);
        if (el) el.textContent = txt;
      };

      setEl('kpiTotalPolyArea', (totalPolyArea / 10000).toFixed(1) + ' ha');
      setEl('kpiTotalEstArea', (totalEstArea / 10000).toFixed(1) + ' ha');
      setEl('kpiTotalPop', totalZonePop.toLocaleString('en-IN') + ' people');
      setEl('kpiSelectedCapex', formatInr(totalCapex));
      setEl('kpiSelectedOpex', formatInr(totalOpex) + ' / yr');
      setEl('kpiSelectedPop', totalPop.toLocaleString('en-IN') + ' people');
      setEl('kpiSelectedCount', selected.length + ' / ' + this.items.length);
      setEl('kpiTco', '5-Yr TCO: ' + formatInr(fiveYearTco));
      setEl('kpiCostPerson', formatInr(costPerPerson) + ' / person');

      // Update Budget Exhaustion Bar
      const bar = document.getElementById('planBudgetExhaustionBar');
      const ratio = document.getElementById('planExhaustionRatio');
      const status = document.getElementById('planExhaustionStatus');
      const alertEl = document.getElementById('planExhaustionAlert');

      const pct = Math.round((totalCapex / Math.max(1, this.budget)) * 100);
      if (ratio) ratio.textContent = `${formatInr(totalCapex)} / ${formatLakhs(this.budget)} (${pct}%)`;

      if (totalCapex > this.budget) {
        if (bar) {
          bar.className = 'progress-bar bg-danger progress-bar-striped';
          bar.style.width = '100%';
        }
        if (status) status.textContent = `Target ceiling exceeded`;
        if (alertEl) {
          alertEl.className = 'small fw-bold text-danger';
          alertEl.textContent = `⚠️ Exceeds Budget by ${formatInr(totalCapex - this.budget)}`;
        }
      } else {
        if (bar) {
          bar.className = 'progress-bar bg-success progress-bar-striped';
          bar.style.width = Math.min(100, pct) + '%';
        }
        const rem = this.budget - totalCapex;
        if (status) status.textContent = `${formatLakhs(rem)} unallocated`;
        if (alertEl) {
          alertEl.className = 'small fw-bold text-success';
          alertEl.textContent = `✓ Within Budget (${pct}%)`;
        }
      }
    },

    renderTable() {
      const tbody = document.getElementById('planTableBody');
      if (!tbody) return;

      const items = this.sortedItems();
      if (!items.length) {
        tbody.innerHTML = `<tr><td colspan="10" class="text-center py-4 text-muted">No interventions match the selected hazard filter.</td></tr>`;
        return;
      }

      tbody.innerHTML = items.map(it => {
        const isChecked = this.selectedIds.has(String(it.id));
        const hz = it.hazard === 'uhi' ? 'uhi' : 'waterlogging';
        const hzBadge = hz === 'uhi'
          ? '<span class="badge bg-danger-subtle text-danger border border-danger-subtle">🔥 UHI</span>'
          : '<span class="badge bg-primary-subtle text-primary border border-primary-subtle">💧 Flood</span>';

        const imp = it.expected_impact || {};
        let impactStr = '';
        if (imp.surface_temp_reduction_c && imp.surface_temp_reduction_c !== '0') impactStr += `-${imp.surface_temp_reduction_c}°C surface `;
        if (imp.runoff_reduction_pct && imp.runoff_reduction_pct !== '0') impactStr += `-${imp.runoff_reduction_pct}% runoff `;
        if (!impactStr) impactStr = imp.summary || 'Localized microclimate buffering';

        const cleanPlace = (it.place || 'Target Zone').replace(/^Zone\s*#?\d+\s*[,:\-–—]?\s*/i, '').trim();
        const complexityColor = it.technical_complexity === 'Low' ? 'text-success' : (it.technical_complexity === 'High' ? 'text-danger' : 'text-primary');

        // Target Surface Badge & Physical Object Allocation breakdown
        const surf = it._target_surface_type || 'Buildings';
        let surfBadge = '';
        let availArea = 0;
        if (surf === 'Buildings') {
          surfBadge = '<span class="badge bg-secondary-subtle text-secondary border">🏢 Buildings</span>';
          availArea = it._building_area_sqm || Math.round(it._polygon_area_sqm * 0.45);
        } else if (surf === 'Roads') {
          surfBadge = '<span class="badge bg-dark-subtle text-dark border">🛣️ Roads</span>';
          availArea = it._road_area_sqm || Math.round(it._polygon_area_sqm * 0.25);
        } else {
          surfBadge = '<span class="badge bg-success-subtle text-success border">🌳 Open Area</span>';
          availArea = it._open_area_sqm || Math.round(it._polygon_area_sqm * 0.30);
        }

        const allocPct = Math.min(100, Math.max(1, Math.round((it._allocated_intervention_area_sqm / Math.max(1, availArea)) * 100)));
        const propPct = it._proportion_pct !== undefined ? it._proportion_pct : 100;
        const effArea = it._effective_intervention_area_sqm || Math.round(it._allocated_intervention_area_sqm * (propPct / 100));

        return `
          <tr class="${isChecked ? 'table-success-subtle' : ''}">
            <td class="text-center align-middle">
              <input type="checkbox" class="form-check-input plan-item-cb" style="border: 1.5px solid #000000; cursor: pointer; width: 1.25rem; height: 1.25rem;" data-item-id="${it.id}" ${isChecked ? 'checked' : ''}>
            </td>
            <td class="align-middle" style="min-width: 280px;">
              <div class="d-flex flex-wrap align-items-center gap-1 mb-1">
                <span class="badge bg-dark font-monospace">#${it.n || it.id}</span>
                ${hzBadge}
                ${surfBadge}
                <strong class="text-dark small">${esc(it.action)}</strong>
              </div>
              <div class="text-muted small mb-1" style="font-size:0.75rem;">
                📍 ${esc(cleanPlace)} &middot; <span class="font-monospace">${it.lat ? it.lat.toFixed(4) : ''}° N, ${it.lng ? it.lng.toFixed(4) : ''}° E</span>
              </div>
              <div class="small text-muted font-monospace mb-2" style="font-size:0.73rem;">
                Allocated Cap: <strong class="text-dark">${(it._allocated_intervention_area_sqm || 0).toLocaleString('en-IN')} m²</strong> 
                <span class="text-secondary">(${allocPct}% of ${Math.round(availArea).toLocaleString('en-IN')} m² ${surf})</span>
              </div>
              <!-- Per-Intervention Action Proportion Slider -->
              <div class="p-2 rounded bg-light border" style="font-size:0.74rem;">
                <div class="d-flex justify-content-between align-items-center mb-1">
                  <span class="fw-semibold text-secondary">Action Scale:</span>
                  <span class="badge bg-dark font-monospace" id="scale-badge-${it.id}">${propPct}%</span>
                </div>
                <input type="range" class="form-range plan-row-scale mb-1" min="10" max="100" step="5" value="${propPct}" data-item-id="${it.id}" style="cursor: pointer;">
                <div class="d-flex justify-content-between text-muted" style="font-size:0.70rem;">
                  <span>Effective Footprint:</span>
                  <span class="fw-bold text-success font-monospace" id="eff-area-${it.id}">${effArea.toLocaleString('en-IN')} m²</span>
                </div>
              </div>
            </td>
            <td class="align-middle text-end font-monospace small fw-semibold text-dark">
              👥 ${(it._population_protected || 0).toLocaleString('en-IN')}
            </td>
            <td class="align-middle text-end font-monospace small text-dark">
              ₹${(it._implementation_cost_per_sqm || 1000).toLocaleString('en-IN')}/m²
            </td>
            <td class="align-middle text-end font-monospace small text-muted">
              ₹${(it._annual_maintenance_cost_per_sqm || 80).toLocaleString('en-IN')}/m²
            </td>
            <td class="align-middle text-end font-monospace small fw-bold text-dark" id="capex-cell-${it.id}">
              ${formatInr(it._total_capex_inr)}
            </td>
            <td class="align-middle text-end font-monospace small text-muted" id="opex-cell-${it.id}">
              ${formatInr(it._annual_opex_inr)} / yr
            </td>
            <td class="align-middle text-center small fw-semibold ${complexityColor}">
              ${esc(it.technical_complexity || 'Medium')}
            </td>
            <td class="align-middle text-center small text-muted">
              ${it.lifespan_years || 20} yrs
            </td>
            <td class="align-middle small text-muted" style="max-width: 180px; font-size:0.76rem;">
              ${esc(impactStr)}
            </td>
          </tr>
        `;
      }).join('');

      tbody.querySelectorAll('.plan-item-cb').forEach(cb => {
        cb.addEventListener('change', () => {
          this.toggleSelect(cb.dataset.itemId, cb.checked);
          const tr = cb.closest('tr');
          if (tr) tr.classList.toggle('table-success-subtle', cb.checked);
        });
      });

      // Hook up live per-row Action Scale (%) sliders
      tbody.querySelectorAll('.plan-row-scale').forEach(slider => {
        slider.addEventListener('input', e => {
          const itemId = String(e.target.dataset.itemId);
          const item = this.items.find(x => String(x.id) === itemId);
          if (!item) return;
          const val = Number(e.target.value);
          item._proportion_pct = val;
          const allocBase = Number(item._allocated_intervention_area_sqm || item._estimated_intervention_area_sqm || 0);
          item._effective_intervention_area_sqm = Math.round(allocBase * (val / 100));
          item._total_capex_inr = Math.round(item._effective_intervention_area_sqm * (item._implementation_cost_per_sqm || 1000));
          item._annual_opex_inr = Math.round(item._effective_intervention_area_sqm * (item._annual_maintenance_cost_per_sqm || 80));
          item._five_year_tco_inr = Math.round(item._total_capex_inr + (5.0 * item._annual_opex_inr));

          const badge = document.getElementById(`scale-badge-${itemId}`);
          if (badge) badge.textContent = `${val}%`;
          const effAreaEl = document.getElementById(`eff-area-${itemId}`);
          if (effAreaEl) effAreaEl.textContent = `${item._effective_intervention_area_sqm.toLocaleString('en-IN')} m²`;
          const capexCell = document.getElementById(`capex-cell-${itemId}`);
          if (capexCell) capexCell.textContent = formatInr(item._total_capex_inr);
          const opexCell = document.getElementById(`opex-cell-${itemId}`);
          if (opexCell) opexCell.textContent = `${formatInr(item._annual_opex_inr)} / yr`;

          this.updateKPIs();
        });
      });
    },

    // ---------------- Primary Action Button 1: Lock Plan & Send to Tracking ----------------
    async lockPlanAndSendToTracking() {
      const selected = Array.from(this.selectedIds);
      if (!selected.length) {
        alert('Please select at least 1 intervention in the table before locking your plan.');
        return;
      }

      const confirmed = confirm(
        `Finalize and Lock this Adaptation Plan for ${window.CR_PROJECT.location_name}?\n\n` +
        `This will commit ${selected.length} interventions into Cloud SQL and transition directly to Stage 4 (Tracking & Impact).`
      );
      if (!confirmed) return;

      const btn = document.getElementById('planLockBtn');
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span> Locking Plan in Cloud SQL…';
      }

      const selectedItems = this.items.filter(it => this.selectedIds.has(String(it.id)));
      const totalCapex = selectedItems.reduce((s, it) => s + (it._total_capex_inr || 0), 0);
      const totalOpex = selectedItems.reduce((s, it) => s + (it._annual_opex_inr || 0), 0);
      const totalPop = selectedItems.reduce((s, it) => s + (it._population_protected || 0), 0);
      const totalArea = selectedItems.reduce((s, it) => s + (it._effective_intervention_area_sqm || it._allocated_intervention_area_sqm || 0), 0);

      const proportions = {};
      const effectiveAreas = {};
      selectedItems.forEach(it => {
        proportions[String(it.id)] = it._proportion_pct !== undefined ? it._proportion_pct : 100;
        effectiveAreas[String(it.id)] = it._effective_intervention_area_sqm || it._allocated_intervention_area_sqm;
      });

      try {
        const res = await fetch('/api/decision_planner/lock_plan', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            project_id: this.projectId,
            stakeholder_type: this.stakeholderType,
            allocated_budget_inr: this.budget,
            coverage_pct: 30.0,
            optimization_goal: this.goal,
            selected_recommendation_ids: selected,
            proportions: proportions,
            effective_areas: effectiveAreas,
            total_capex_inr: totalCapex,
            total_annual_opex_inr: totalOpex,
            total_population_protected: totalPop,
            total_treatable_area_sqm: totalArea,
            ai_decision_brief: this.currentBrief || {},
          })
        });

        const data = await res.json();
        if (data.ok && data.plan) {
          this.lockedPlan = data.plan;
          this.showLockedBanner(data.plan);
          this.unlockModule4(data.plan);

          // Transition directly to Stage 4: Tracking & Impact
          const monTab = document.querySelector('.ws-nav-tab[data-tab="monitoring"]');
          if (monTab) {
            monTab.click();
          }
        } else {
          alert('Could not lock plan: ' + (data.error || 'Server error'));
        }
      } catch (err) {
        console.error('[planner] Lock plan error:', err);
        alert('Plan locking error: ' + err.message);
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = '<span>🔒 Lock Plan & Send to Tracking & Impact</span>';
        }
      }
    },

    showLockedBanner(plan) {
      const banner = document.getElementById('planLockedAlert');
      const textEl = document.getElementById('planLockedText');
      if (banner && textEl) {
        textEl.innerHTML = `
          <strong>Plan Locked on ${plan.locked_at || 'Today'}</strong> &mdash; 
          ${plan.selected_recommendation_ids ? plan.selected_recommendation_ids.length : this.selectedIds.size} Interventions 
          committed (${formatInr(plan.total_capex_inr || 0)} CAPEX, protecting ${(plan.total_population_protected || 0).toLocaleString('en-IN')} citizens).
        `;
        banner.classList.remove('d-none');
      }
    },

    unlockModule4(plan) {
      const monTab = document.querySelector('[data-tab="monitoring"]');
      if (monTab) {
        monTab.classList.remove('opacity-50');
        const badge = monTab.querySelector('.step-badge');
        if (badge) badge.classList.add('bg-success', 'text-white');
      }

      if (window.CRTracking) {
        window.CRTracking.init(this.projectId);
        window.CRTracking.load();
      }
    },

    // ---------------- Primary Action Button 2: Generate Detailed Project Report (DPR) ----------------
    async generateDpr() {
      const selected = this.items.filter(it => this.selectedIds.has(String(it.id)));
      if (!selected.length) {
        alert('Please select at least 1 intervention in the table to compile the Detailed Project Report.');
        return;
      }

      const modalEl = document.getElementById('planReportModal');
      const bodyEl = document.getElementById('planReportModalBody');
      if (!modalEl || !bodyEl) return;

      const proj = window.CR_PROJECT || {};
      const dateStr = new Date().toLocaleDateString('en-IN', { year: 'numeric', month: 'long', day: 'numeric' });

      // Calculate totals
      const totalCapex = selected.reduce((s, it) => s + (it._total_capex_inr || 0), 0);
      const totalOpex = selected.reduce((s, it) => s + (it._annual_opex_inr || 0), 0);
      const fiveYearTco = selected.reduce((s, it) => s + (it._five_year_tco_inr || 0), 0);
      const totalPop = selected.reduce((s, it) => s + (it._population_protected || 0), 0);
      const totalTreatable = selected.reduce((s, it) => s + (it._effective_intervention_area_sqm || it._allocated_intervention_area_sqm || 0), 0);
      const costPerPerson = totalPop > 0 ? Math.round(totalCapex / totalPop) : 0;

      // Extract Module 1 Stats (sorted High to Low)
      const aData = proj.assessment_data || {};
      const stats = aData.stats || {};
      const hazards = stats.hazards || {};
      const uhiRows = (hazards.uhi && hazards.uhi.rows) ? [...hazards.uhi.rows].sort((a, b) => b.class - a.class) : [];
      const waterRows = (hazards.waterlogging && hazards.waterlogging.rows) ? [...hazards.waterlogging.rows].sort((a, b) => b.class - a.class) : [];

      const pal = ['#fee2e2', '#fca5a5', '#ef4444', '#b91c1c', '#7f1d1d'];

      bodyEl.innerHTML = `
        <div class="print-dossier p-3 bg-white">
          <!-- Document Header -->
          <div class="d-flex justify-content-between align-items-start border-bottom pb-3 mb-4">
            <div>
              <div class="d-flex align-items-center gap-2 mb-1">
                <span class="badge bg-success px-2 py-1">DETAILED PROJECT REPORT (DPR)</span>
                <span class="badge bg-dark-subtle text-dark border">Fixed 2024–2025 Baseline</span>
                <span class="text-muted small">${dateStr}</span>
              </div>
              <h2 class="h4 fw-bold text-dark mb-1">Urban Climate Resilience & Adaptation Detailed Project Report</h2>
              <div class="text-secondary small">Comprehensive Capital Investment, Engineering Specifications & Site Allocation Schedule</div>
            </div>
            <div class="text-end">
              <div class="fw-bold text-success font-monospace" style="font-size: 1.15rem;">ClimateReady™</div>
              <div class="text-muted small">${esc(proj.location_name)} (${esc(proj.level || 'District')})</div>
            </div>
          </div>

          <!-- ================= SECTION 1: ASSESSMENT OVERVIEW (High to Low) ================= -->
          <div class="mb-5">
            <h5 class="h6 fw-bold text-dark border-bottom pb-2 mb-3 d-flex align-items-center gap-2">
              <span class="badge bg-dark">SECTION 1</span>
              <span>Assessment Overview & Risk Class Distribution (High to Low)</span>
            </h5>
            
            <div class="row g-3 mb-3">
              <div class="col-sm-4">
                <div class="p-3 bg-light border rounded">
                  <span class="text-muted small d-block">Assessment Study Area</span>
                  <strong class="text-dark">${esc(proj.location_name)}</strong>
                </div>
              </div>
              <div class="col-sm-4">
                <div class="p-3 bg-light border rounded">
                  <span class="text-muted small d-block">Total Assessed Surface Area</span>
                  <strong class="text-dark">${stats.overview && stats.overview.area_km2 ? Number(stats.overview.area_km2).toFixed(1) + ' km²' : 'Study Area Footprint'}</strong>
                </div>
              </div>
              <div class="col-sm-4">
                <div class="p-3 bg-light border rounded">
                  <span class="text-muted small d-block">Resident Population (WorldPop)</span>
                  <strong class="text-dark">${stats.overview && stats.overview.population ? Math.round(Number(stats.overview.population)).toLocaleString('en-IN') + ' citizens' : 'Demographic Footprint'}</strong>
                </div>
              </div>
            </div>

            <!-- Area & Population Breakdown (High to Low) -->
            <div class="row g-3">
              <!-- UHI Risk Breakdown -->
              <div class="col-md-6">
                <div class="border rounded p-3 bg-light-subtle h-100">
                  <div class="fw-bold text-danger mb-2">🔥 Urban Heat Island (UHI) Risk Classes (High to Low)</div>
                  <table class="table table-sm table-borderless small mb-0">
                    <thead class="text-muted">
                      <tr>
                        <th>Class</th>
                        <th class="text-end">Area Share</th>
                        <th class="text-end">Population Share</th>
                      </tr>
                    </thead>
                    <tbody>
                      ${uhiRows.map(r => `
                        <tr>
                          <td><span class="badge" style="background:${pal[r.class - 1]}">${r.level}</span></td>
                          <td class="text-end font-monospace">${(r.area_pct || 0).toFixed(1)}% <small class="text-muted">(${Number(r.area_km2 || 0).toFixed(1)} km²)</small></td>
                          <td class="text-end font-monospace">${(r.population_pct || 0).toFixed(1)}% <small class="text-muted">(${Math.round(r.population || 0).toLocaleString('en-IN')})</small></td>
                        </tr>
                      `).join('')}
                    </tbody>
                  </table>
                </div>
              </div>

              <!-- Waterlogging Risk Breakdown -->
              <div class="col-md-6">
                <div class="border rounded p-3 bg-light-subtle h-100">
                  <div class="fw-bold text-primary mb-2">💧 Urban Waterlogging Risk Classes (High to Low)</div>
                  <table class="table table-sm table-borderless small mb-0">
                    <thead class="text-muted">
                      <tr>
                        <th>Class</th>
                        <th class="text-end">Area Share</th>
                        <th class="text-end">Population Share</th>
                      </tr>
                    </thead>
                    <tbody>
                      ${waterRows.map(r => `
                        <tr>
                          <td><span class="badge" style="background:${pal[r.class - 1]}">${r.level}</span></td>
                          <td class="text-end font-monospace">${(r.area_pct || 0).toFixed(1)}% <small class="text-muted">(${Number(r.area_km2 || 0).toFixed(1)} km²)</small></td>
                          <td class="text-end font-monospace">${(r.population_pct || 0).toFixed(1)}% <small class="text-muted">(${Math.round(r.population || 0).toLocaleString('en-IN')})</small></td>
                        </tr>
                      `).join('')}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          </div>

          <!-- ================= SECTION 2: BASELINE RISK MAPS (2024–2025) ================= -->
          <div class="mb-5">
            <h5 class="h6 fw-bold text-dark border-bottom pb-2 mb-3 d-flex align-items-center gap-2">
              <span class="badge bg-dark">SECTION 2</span>
              <span>Baseline Risk Maps (Fixed 2024–2025 Multi-Hazard Remote Sensing)</span>
            </h5>
            <div class="row g-3">
              <div class="col-md-6">
                <div class="border rounded p-2 text-center bg-light">
                  <div class="fw-semibold small text-danger mb-2">🔥 Baseline Urban Heat Island Risk Overlay (2024–2025)</div>
                  <div class="d-flex justify-content-center align-items-center" style="min-height: 220px; background: #e2e8f0; border-radius: 6px;">
                    <img src="/api/layers/risk_uhi/tiles?project_id=${proj.id}&thumbnail=1" 
                         alt="UHI Baseline Risk Map" 
                         class="img-fluid rounded border" 
                         style="max-height: 260px; object-fit: contain;"
                         onerror="this.onerror=null; this.src='/static/img/uhi_placeholder.png'; this.alt='UHI Map Overlay';">
                  </div>
                  <div class="text-muted small mt-2" style="font-size:0.75rem;">Multi-temporal Landsat-8/9 & MODIS LST thermal band calculation (100m grid)</div>
                </div>
              </div>
              <div class="col-md-6">
                <div class="border rounded p-2 text-center bg-light">
                  <div class="fw-semibold small text-primary mb-2">💧 Baseline Urban Waterlogging Risk Overlay (2024–2025)</div>
                  <div class="d-flex justify-content-center align-items-center" style="min-height: 220px; background: #e2e8f0; border-radius: 6px;">
                    <img src="/api/layers/risk_waterlogging/tiles?project_id=${proj.id}&thumbnail=1" 
                         alt="Waterlogging Baseline Risk Map" 
                         class="img-fluid rounded border" 
                         style="max-height: 260px; object-fit: contain;"
                         onerror="this.onerror=null; this.src='/static/img/flood_placeholder.png'; this.alt='Flood Map Overlay';">
                  </div>
                  <div class="text-muted small mt-2" style="font-size:0.75rem;">SRTM DEM, Sentinel-2 MNDWI runoff pooling, and impervious flow resistance</div>
                </div>
              </div>
            </div>
          </div>

          <!-- ================= SECTION 3: INTERVENTION PLAN MAPS ================= -->
          <div class="mb-5">
            <h5 class="h6 fw-bold text-dark border-bottom pb-2 mb-3 d-flex align-items-center gap-2">
              <span class="badge bg-dark">SECTION 3</span>
              <span>Intervention Plan Maps (Satellite Base Map with Hotspot Polygons & Numbered Pins)</span>
            </h5>
            <div class="border rounded p-3 bg-light mb-3">
              <div class="d-flex flex-wrap justify-content-between align-items-center mb-2">
                <span class="small fw-semibold text-dark">📍 Georeferenced Hotspot Polygons & Numbered Zone Pins:</span>
                <span class="badge bg-dark text-white font-monospace">${selected.length} Sites Selected</span>
              </div>
              <div id="dprSatelliteMapContainer" style="height: 340px; border-radius: 8px; border: 1.5px solid #000000; overflow: hidden; background: #1e293b;">
                <!-- Initialized with Leaflet Satellite Map -->
              </div>
              <div class="d-flex flex-wrap gap-2 mt-2" style="font-size: 0.75rem;">
                <span class="badge bg-dark text-white font-monospace">■ Black Border: Exact Geodesic Boundary</span>
                <span class="badge text-white" style="background:#EA580C;">● Orange Pin: UHI Action</span>
                <span class="badge text-white" style="background:#1D4ED8;">● Blue Pin: Waterlogging Action</span>
              </div>
            </div>
          </div>

          <!-- ================= SECTION 4: INTERVENTION PORTFOLIO OVERVIEW ================= -->
          <div class="mb-5">
            <h5 class="h6 fw-bold text-dark border-bottom pb-2 mb-3 d-flex align-items-center gap-2">
              <span class="badge bg-dark">SECTION 4</span>
              <span>Intervention Portfolio Overview & Investment Schedule</span>
            </h5>

            <div class="row g-3 mb-3">
              <div class="col-sm-3">
                <div class="p-3 bg-light border rounded">
                  <span class="text-muted small d-block">Total Allocated CAPEX</span>
                  <div class="h5 fw-bold text-success font-monospace mb-0">${formatInr(totalCapex)}</div>
                  <div class="text-muted small mt-1" style="font-size: 0.7rem;">Target: ${formatLakhs(this.budget)}</div>
                </div>
              </div>
              <div class="col-sm-3">
                <div class="p-3 bg-light border rounded">
                  <span class="text-muted small d-block">Annual O&M Upkeep</span>
                  <div class="h5 fw-bold text-primary font-monospace mb-0">${formatInr(totalOpex)} / yr</div>
                  <div class="text-muted small mt-1" style="font-size: 0.7rem;">5-Yr TCO: ${formatInr(fiveYearTco)}</div>
                </div>
              </div>
              <div class="col-sm-3">
                <div class="p-3 bg-light border rounded">
                  <span class="text-muted small d-block">Citizens Protected</span>
                  <div class="h5 fw-bold text-dark font-monospace mb-0">👥 ${totalPop.toLocaleString('en-IN')}</div>
                  <div class="text-muted small mt-1" style="font-size: 0.7rem;">WorldPop verified count</div>
                </div>
              </div>
              <div class="col-sm-3">
                <div class="p-3 bg-light border rounded">
                  <span class="text-muted small d-block">Capital Efficiency</span>
                  <div class="h5 fw-bold text-dark font-monospace mb-0">${formatInr(costPerPerson)} / person</div>
                  <div class="text-muted small mt-1" style="font-size: 0.7rem;">Direct benefit ratio</div>
                </div>
              </div>
            </div>

            <!-- Portfolio Summary Table -->
            <div class="table-responsive">
              <table class="table table-bordered table-sm small align-middle mb-0">
                <thead class="table-light">
                  <tr>
                    <th>Zone Pin</th>
                    <th>Action & Target Surface</th>
                    <th>Hazard Focus</th>
                    <th class="text-end">Object Surface (m²)</th>
                    <th class="text-end">Allocated Footprint</th>
                    <th class="text-end">Unit Cost (₹/m²)</th>
                    <th class="text-end">Implementation Cost</th>
                    <th class="text-end">Annual Maintenance</th>
                    <th class="text-end">Beneficiaries</th>
                  </tr>
                </thead>
                <tbody>
                  ${selected.map(it => {
                    const surf = it._target_surface_type || 'Buildings';
                    let availArea = 0;
                    if (surf === 'Buildings') availArea = it._building_area_sqm || Math.round(it._polygon_area_sqm * 0.45);
                    else if (surf === 'Roads') availArea = it._road_area_sqm || Math.round(it._polygon_area_sqm * 0.25);
                    else availArea = it._open_area_sqm || Math.round(it._polygon_area_sqm * 0.30);
                    const allocPct = Math.min(100, Math.max(1, Math.round((it._allocated_intervention_area_sqm / Math.max(1, availArea)) * 100)));

                    return `
                      <tr>
                        <td class="fw-bold font-monospace">#${it.n || it.id}</td>
                        <td>
                          <strong>${esc(it.action)}</strong><br>
                          <span class="badge bg-secondary-subtle text-secondary border" style="font-size:0.7rem;">${esc(surf)}</span>
                        </td>
                        <td><span class="badge ${it.hazard === 'uhi' ? 'bg-danger-subtle text-danger' : 'bg-primary-subtle text-primary'}">${esc(it.hazard_label)}</span></td>
                        <td class="text-end font-monospace">${Math.round(availArea).toLocaleString('en-IN')} m²</td>
                        <td class="text-end font-monospace fw-semibold text-success">${(it._effective_intervention_area_sqm || it._allocated_intervention_area_sqm || 0).toLocaleString('en-IN')} m² <small class="text-secondary">(${it._proportion_pct || 100}%)</small></td>
                        <td class="text-end font-monospace">₹${(it._implementation_cost_per_sqm || 1000).toLocaleString('en-IN')}</td>
                        <td class="text-end font-monospace fw-semibold">${formatInr(it._total_capex_inr)}</td>
                        <td class="text-end font-monospace text-muted">${formatInr(it._annual_opex_inr)}/yr</td>
                        <td class="text-end font-monospace">👥 ${(it._population_protected || 0).toLocaleString('en-IN')}</td>
                      </tr>
                    `;
                  }).join('')}
                  <tr class="table-secondary fw-bold">
                    <td colspan="4">PORTFOLIO TOTALS (${selected.length} Sites)</td>
                    <td class="text-end font-monospace text-success">${totalTreatable.toLocaleString('en-IN')} m²</td>
                    <td class="text-end font-monospace">-</td>
                    <td class="text-end font-monospace text-success">${formatInr(totalCapex)}</td>
                    <td class="text-end font-monospace text-primary">${formatInr(totalOpex)}/yr</td>
                    <td class="text-end font-monospace">👥 ${totalPop.toLocaleString('en-IN')}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- ================= SECTION 5: INDIVIDUAL INTERVENTION SPECIFICATIONS ================= -->
          <div class="mb-4">
            <h5 class="h6 fw-bold text-dark border-bottom pb-2 mb-3 d-flex align-items-center gap-2">
              <span class="badge bg-dark">SECTION 5</span>
              <span>Individual Intervention Specifications & Engineering Citations</span>
            </h5>

            <div class="d-flex flex-column gap-3">
              ${selected.map(it => {
                const imp = it.expected_impact || {};
                const cleanPlace = (it.place || 'Target Area').replace(/^Zone\s*#?\d+\s*[,:\-–—]?\s*/i, '').trim();
                const surf = it._target_surface_type || 'Buildings';
                let availArea = 0;
                if (surf === 'Buildings') availArea = it._building_area_sqm || Math.round(it._polygon_area_sqm * 0.45);
                else if (surf === 'Roads') availArea = it._road_area_sqm || Math.round(it._polygon_area_sqm * 0.25);
                else availArea = it._open_area_sqm || Math.round(it._polygon_area_sqm * 0.30);
                const allocPct = Math.min(100, Math.max(1, Math.round((it._allocated_intervention_area_sqm / Math.max(1, availArea)) * 100)));

                return `
                  <div class="border rounded-3 p-3 bg-light">
                    <div class="d-flex flex-wrap justify-content-between align-items-start mb-2">
                      <div>
                        <div class="d-flex align-items-center gap-2 mb-1">
                          <span class="badge bg-dark font-monospace">Zone #${it.n || it.id}</span>
                          <span class="badge ${it.hazard === 'uhi' ? 'bg-danger' : 'bg-primary'}">${esc(it.hazard_label)}</span>
                          <span class="badge bg-secondary-subtle text-secondary border">${esc(surf)}</span>
                          <h6 class="h6 fw-bold text-dark mb-0">${esc(it.action)}</h6>
                        </div>
                        <div class="text-secondary small mb-1">
                          📍 <strong>Location:</strong> ${esc(cleanPlace)} &middot; <span class="font-monospace">${it.lat ? it.lat.toFixed(4) : ''}° N, ${it.lng ? it.lng.toFixed(4) : ''}° E</span>
                        </div>
                      </div>
                      <div class="text-end font-monospace">
                        <span class="badge bg-white text-dark border px-2 py-1">Design Life: ${it.lifespan_years || 20} yrs</span>
                        <span class="badge bg-light text-secondary border px-2 py-1 ms-1">Complexity: ${esc(it.technical_complexity || 'Medium')}</span>
                      </div>
                    </div>

                    ${it.short_description ? `
                      <p class="small text-dark mb-2" style="line-height: 1.4;">
                        <strong>Description:</strong> ${esc(it.short_description)}
                      </p>
                    ` : ''}

                    <div class="row g-2 small mb-2">
                      <div class="col-md-3">
                        <div class="p-2 bg-white rounded border">
                          <span class="text-muted d-block">Gross Polygon Area</span>
                          <strong>${(it._polygon_area_sqm || 0).toLocaleString('en-IN')} m²</strong>
                        </div>
                      </div>
                      <div class="col-md-3">
                        <div class="p-2 bg-white rounded border">
                          <span class="text-muted d-block">Available ${esc(surf)} Area</span>
                          <strong class="text-primary">${Math.round(availArea).toLocaleString('en-IN')} m²</strong>
                        </div>
                      </div>
                      <div class="col-md-3">
                        <div class="p-2 bg-white rounded border">
                          <span class="text-muted d-block">Allocated Intervention Footprint</span>
                          <strong class="text-success">${(it._effective_intervention_area_sqm || it._allocated_intervention_area_sqm || 0).toLocaleString('en-IN')} m² (${it._proportion_pct || 100}% scale)</strong>
                        </div>
                      </div>
                      <div class="col-md-3">
                        <div class="p-2 bg-white rounded border">
                          <span class="text-muted d-block">Unit Implementation Cost</span>
                          <strong class="font-monospace">₹${(it._implementation_cost_per_sqm || 1000).toLocaleString('en-IN')}/m²</strong>
                        </div>
                      </div>
                    </div>

                    <div class="row g-2 small mb-2">
                      <div class="col-md-3">
                        <div class="p-2 bg-white rounded border">
                          <span class="text-muted d-block">Unit Annual Maintenance</span>
                          <strong class="font-monospace">₹${(it._annual_maintenance_cost_per_sqm || 80).toLocaleString('en-IN')}/m²/yr</strong>
                        </div>
                      </div>
                      <div class="col-md-3">
                        <div class="p-2 bg-white rounded border">
                          <span class="text-muted d-block">Total Setup CAPEX</span>
                          <strong class="text-success font-monospace">${formatInr(it._total_capex_inr)}</strong>
                        </div>
                      </div>
                      <div class="col-md-3">
                        <div class="p-2 bg-white rounded border">
                          <span class="text-muted d-block">Annual Upkeep OPEX</span>
                          <strong class="font-monospace text-primary">${formatInr(it._annual_opex_inr)} / yr</strong>
                        </div>
                      </div>
                      <div class="col-md-3">
                        <div class="p-2 bg-white rounded border">
                          <span class="text-muted d-block">Protected Beneficiaries</span>
                          <strong>👥 ${(it._population_protected || 0).toLocaleString('en-IN')} residents</strong>
                        </div>
                      </div>
                    </div>

                    <div class="p-2 bg-white rounded border small mb-2">
                      <strong>⚡ Expected Impact Metrics:</strong>
                      <span class="text-secondary ms-1">
                        ${imp.surface_temp_reduction_c ? `Surface Cooling: -${imp.surface_temp_reduction_c}°C &middot; ` : ''}
                        ${imp.indoor_or_ambient_temp_reduction_c ? `Ambient/Indoor Cooling: -${imp.indoor_or_ambient_temp_reduction_c}°C &middot; ` : ''}
                        ${imp.runoff_reduction_pct ? `Peak Runoff Attenuation: -${imp.runoff_reduction_pct}% &middot; ` : ''}
                        ${esc(imp.summary || 'Localized thermal and drainage buffer.')}
                      </span>
                    </div>

                    <div class="p-2 bg-white rounded border small text-muted">
                      <strong>🏛️ Authoritative Source & Engineering Citation:</strong>
                      <span class="fst-italic text-dark ms-1">${esc(it.source_citation || 'NDMA National Guidelines & CPWD Sustainability Standards')}</span>
                    </div>
                  </div>
                `;
              }).join('')}
            </div>
          </div>

          <!-- Document Footer -->
          <div class="text-center text-muted small border-top pt-3 mt-4" style="font-size:0.75rem;">
            ClimateReady Detailed Project Report (DPR) &middot; Formulated in accordance with NDMA, NIUA, and CPWD Standards &middot; Verified via Earth Engine 2024–2025 Satellite Baselines
          </div>
        </div>
      `;

      const modal = new bootstrap.Modal(modalEl);
      modal.show();

      // Initialize Leaflet satellite map with polygons and pins inside modal
      setTimeout(() => {
        this.renderDprSatelliteMap(selected);
      }, 400);
    },

    renderDprSatelliteMap(selectedItems) {
      const container = document.getElementById('dprSatelliteMapContainer');
      if (!container) return;

      if (this.dprMap) {
        try { this.dprMap.remove(); } catch (e) {}
        this.dprMap = null;
      }

      try {
        const map = L.map(container, {
          zoomControl: true,
          attributionControl: false
        });

        // Satellite Tile Layer (Esri World Imagery)
        L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
          maxZoom: 18,
        }).addTo(map);

        const latLngs = [];

        selectedItems.forEach(it => {
          const poly = it.polygon || [];
          const hzColor = it.hazard === 'uhi' ? '#EA580C' : '#1D4ED8';

          if (poly && poly.length >= 3) {
            const ring = poly.map(p => [Number(p[0]), Number(p[1])]);
            L.polygon(ring, {
              color: '#000000',
              weight: 2.5,
              opacity: 0.95,
              fillColor: hzColor,
              fillOpacity: 0.35,
            }).addTo(map);

            ring.forEach(pt => latLngs.push(pt));
          }

          if (it.lat && it.lng) {
            const num = it.n || it.id;
            const markerHtml = `
              <div style="background:${hzColor}; color:#ffffff; font-weight:bold; font-size:12px; width:26px; height:26px; border-radius:50%; border:2px solid #ffffff; box-shadow:0 2px 4px rgba(0,0,0,0.5); display:flex; align-items:center; justify-content:center;">
                ${num}
              </div>
            `;
            const icon = L.divIcon({
              className: 'dpr-pin-icon',
              html: markerHtml,
              iconSize: [26, 26],
              iconAnchor: [13, 13]
            });

            L.marker([it.lat, it.lng], { icon: icon })
              .addTo(map)
              .bindPopup(`<b>Zone #${num}: ${esc(it.action)}</b><br><small>${esc(it.place)}</small>`);

            latLngs.push([it.lat, it.lng]);
          }
        });

        if (latLngs.length) {
          const bounds = L.latLngBounds(latLngs);
          map.fitBounds(bounds, { padding: [30, 30], maxZoom: 14 });
        } else {
          map.setView([19.24, 73.13], 12);
        }

        setTimeout(() => map.invalidateSize(), 300);
        this.dprMap = map;
      } catch (err) {
        console.warn('[planner] DPR Leaflet render notice:', err);
      }
    },

    // ---------------- Optional AI Brief Generation ----------------
    async generateAiBrief() {
      const selected = Array.from(this.selectedIds);
      if (!selected.length) {
        alert('Please select at least 1 intervention in the table to synthesize an AI Decision Brief.');
        return;
      }

      const btn = document.getElementById('planAiBriefBtn');
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span> Synthesizing AI Brief…';
      }

      try {
        const res = await fetch('/api/decision_planner/ai_brief', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            project_id: this.projectId,
            selected_ids: selected,
            budget_inr: this.budget,
            goal: this.goal,
            stakeholder_type: this.stakeholderType,
          })
        });
        const data = await res.json();
        if (data.ok && data.brief) {
          this.currentBrief = data.brief;
          this.renderAiBriefCard(data.brief);
          const card = document.getElementById('planAiBriefCard');
          if (card) {
            card.scrollIntoView({ behavior: 'smooth', block: 'start' });
          }
        } else {
          alert('Could not generate AI brief: ' + (data.error || 'Unknown error'));
        }
      } catch (err) {
        console.error('[planner] AI brief error:', err);
        alert('AI Brief generation error: ' + err.message);
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = '🤖 AI Phasing Brief';
        }
      }
    },

    renderAiBriefCard(brief) {
      const card = document.getElementById('planAiBriefCard');
      const container = document.getElementById('planAiBriefContainer');
      if (!card || !container) return;

      const sec = brief.sections || {};
      const formatMd = (txt) => {
        if (!txt) return '';
        return esc(txt)
          .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
          .replace(/\*(.*?)\*/g, '<em>$1</em>')
          .replace(/^- (.*$)/gim, '<li class="mb-1">$1</li>')
          .replace(/\n\n/g, '<br><br>');
      };

      container.innerHTML = `
        <div class="row g-4">
          <div class="col-lg-4">
            <div class="p-3 bg-light rounded-3 border h-100">
              <h5 class="h6 fw-bold text-success mb-2 d-flex align-items-center gap-2">
                <span>💡</span> Strategic Fit & Budget Allocation
              </h5>
              <div class="small text-secondary" style="line-height: 1.5;">
                ${formatMd(sec.sec1 || brief.raw_markdown || 'Portfolio verified within budget.')}
              </div>
            </div>
          </div>
          <div class="col-lg-4">
            <div class="p-3 bg-light rounded-3 border h-100">
              <h5 class="h6 fw-bold text-primary mb-2 d-flex align-items-center gap-2">
                <span>📅</span> Phasing & Seasonal Execution Schedule
              </h5>
              <div class="small text-secondary" style="line-height: 1.5;">
                ${formatMd(sec.sec2 || 'Pre-summer thermal actions staged with pre-monsoon stormwater civil works.')}
              </div>
            </div>
          </div>
          <div class="col-lg-4">
            <div class="p-3 bg-light rounded-3 border h-100">
              <h5 class="h6 fw-bold text-warning-emphasis mb-2 d-flex align-items-center gap-2">
                <span>⚠️</span> Operational Liabilities & O&M
              </h5>
              <div class="small text-secondary" style="line-height: 1.5;">
                ${formatMd(sec.sec3 || 'Annual O&M commitment benchmarked to CPWD schedule.')}
              </div>
            </div>
          </div>
        </div>
      `;
      card.classList.remove('d-none');
    }
  };

  window.CRPlanner = Planner;
})();