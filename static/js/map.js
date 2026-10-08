/* CRMap: thin Leaflet wrapper. analysis.js talks only to these methods. */
(function () {
  const BASES = {
    normal: ['https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '© OpenStreetMap contributors' }],
    satellite: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', { maxZoom: 19, attribution: 'Imagery © Esri' }]
  };
  class CRMap {
    constructor(id) {
      const touch = L.Browser.mobile || ('ontouchstart' in window);
      // Wheel zoom is OFF so the page scrolls normally over the map; Ctrl/Cmd + wheel zooms.
      // On touch screens one finger scrolls the page, two fingers move/zoom the map.
      this.map = L.map(id, { zoomControl: true, minZoom: 5, scrollWheelZoom: false, dragging: !touch, tap: false, touchZoom: true });
      this.hint = document.createElement('div'); this.hint.className = 'map-hint';
      this.map.getContainer().parentNode.appendChild(this.hint);
      let ht;
      const flash = text => { this.hint.textContent = text; this.hint.classList.add('on'); clearTimeout(ht); ht = setTimeout(() => this.hint.classList.remove('on'), 1200); };
      const cont = this.map.getContainer();
      cont.addEventListener('wheel', e => {
        if (e.ctrlKey || e.metaKey) {
          e.preventDefault();
          const z = this.map.getZoom() + (e.deltaY < 0 ? 0.5 : -0.5);
          this.map.setZoomAround(this.map.mouseEventToContainerPoint(e), Math.min(19, Math.max(5, z)));
        } else flash('Use Ctrl + scroll to zoom the map');
      }, { passive: false });
      if (touch) {
        cont.addEventListener('touchstart', e => {
          if (e.touches.length === 1) flash('Use two fingers to move the map');
          else this.map.dragging.enable();
        }, { passive: true });
        cont.addEventListener('touchend', e => { if (e.touches.length < 2) this.map.dragging.disable(); }, { passive: true });
      }
      this.map.createPane('analytic').style.zIndex = 350;
      this.base = null; this.layer = null; this.aoi = null; this.pins = {}; this.opacity = 1; this.bounds = null;
      const self = this, Reset = L.Control.extend({
        options: { position: 'topleft' },
        onAdd() {
          const d = L.DomUtil.create('div', 'leaflet-bar');
          const a = L.DomUtil.create('a', '', d); a.href = '#'; a.title = 'Reset view'; a.innerHTML = '⟲'; a.style.fontSize = '18px';
          L.DomEvent.on(a, 'click', e => { L.DomEvent.stop(e); self.reset(); });
          return d;
        }
      });
      this.map.addControl(new Reset());
      this.setBase('normal');
    }
    setBase(name) {
      if (this.base) { this.map.removeLayer(this.base); this.base = null; }
      if (BASES[name]) { this.base = L.tileLayer(BASES[name][0], BASES[name][1]).addTo(this.map); this.base.setZIndex(1); }
    }
    showAOI(geojson, b) {
      if (this.aoi) this.map.removeLayer(this.aoi);
      this.aoi = L.geoJSON(geojson, { style: { color: '#17201A', weight: 2, fill: false }, interactive: false }).addTo(this.map);
      this.bounds = L.latLngBounds([b[1], b[0]], [b[3], b[2]]);
      this.map.invalidateSize(); this.reset();
    }
    reset() { if (this.bounds) this.map.fitBounds(this.bounds, { padding: [20, 20] }); }
    setLayer(url, boost) {
      this.clearLayer();
      this.layer = L.tileLayer(url, { pane: 'analytic', opacity: this.opacity, maxZoom: 19, className: boost ? 'boost' : '' }).addTo(this.map);
      return this.layer;
    }
    setOverlay(url, bounds) {
      this.clearLayer();
      this.layer = L.imageOverlay(url, bounds, { pane: 'analytic', opacity: this.opacity, interactive: false }).addTo(this.map);
      this.layer.getElement().classList.add('crisp');
      return this.layer;
    }
    clearLayer() { if (this.layer) { this.map.removeLayer(this.layer); this.layer = null; } }
    setOpacity(o) { this.opacity = o; if (this.layer) this.layer.setOpacity(o); }
    onClick(cb) { this.map.on('click', e => cb(e.latlng)); }
    popup(latlng, html) { return L.popup({ maxWidth: 300 }).setLatLng(latlng).setContent(html).openOn(this.map); }
    setPins(recs, colors, onClick) {
      Object.values(this.pins).forEach(m => this.map.removeLayer(m)); this.pins = {};
      recs.forEach(r => {
        const icon = L.divIcon({ className: '', iconSize: [30, 30], iconAnchor: [15, 30],
          html: `<div class="cr-pin" style="background:${colors[r.hazard]}"><span>${String(r.n).padStart(2, '0')}</span></div>` });
        const m = L.marker([r.lat, r.lng], { icon, title: `${r.hazard_label}: ${r.place}` }).addTo(this.map);
        m.on('click', () => onClick(r.id)); this.pins[r.id] = m;
      });
    }
    highlight(id) {
      Object.entries(this.pins).forEach(([k, m]) => { const el = m.getElement(); if (el) el.firstChild.classList.toggle('on', String(k) === String(id)); });
    }
    focusPin(id, html) {
      const m = this.pins[id]; if (!m) return;
      this.map.flyTo(m.getLatLng(), Math.max(this.map.getZoom(), 14), { duration: 0.8 });
      this.highlight(id);
      m.unbindPopup().bindPopup(html, { maxWidth: 300 }); setTimeout(() => m.openPopup(), 850);
    }
    resize() { this.map.invalidateSize(); }
  }
  window.CRMap = CRMap;
})();
