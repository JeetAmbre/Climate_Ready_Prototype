/* CRMap: thin Leaflet wrapper. analysis.js talks only to these methods. */
(function () {
  if (typeof document !== 'undefined' && !document.getElementById('cr-pin-blink-style')) {
    const st = document.createElement('style');
    st.id = 'cr-pin-blink-style';
    st.textContent = `
      @keyframes cr-pin-blink {
        0%, 100% { transform: scale(1); filter: brightness(1); }
        50% { transform: scale(1.4); filter: brightness(1.4) drop-shadow(0 0 10px rgba(0,0,0,0.85)); }
      }
      .cr-pin.blink { animation: cr-pin-blink 0.45s ease-in-out 6 !important; z-index: 9999 !important; }
    `;
    document.head.appendChild(st);
  }
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
      this.map.createPane('polygonsPane').style.zIndex = 550;
      this.map.createPane('markersPane').style.zIndex = 650;
      this.base = null; this.layer = null; this.aoi = null; this.pins = {}; this.polygons = {}; this.opacity = 1; this.bounds = null;
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
    reset() { 
      if (this.bounds) {
        this.map.invalidateSize();
        this.map.fitBounds(this.bounds, { padding: [25, 25], maxZoom: 13 }); 
      } 
    }
    setLayer(url, boost) {
      this.clearLayer();
      this.layer = L.tileLayer(url, { pane: 'analytic', opacity: this.opacity, maxZoom: 19, className: boost ? 'boost' : '' }).addTo(this.map);
      return this.layer;
    }
    setOverlay(url, bounds) {
      this.clearLayer();
      this.layer = L.imageOverlay(url, bounds, { pane: 'analytic', opacity: this.opacity, interactive: false }).addTo(this.map);
      const el = this.layer.getElement();
      if (el) el.classList.add('crisp');
      else this.layer.on('load', () => { const e = this.layer.getElement(); if (e) e.classList.add('crisp'); });
      return this.layer;
    }
    clearLayer() { if (this.layer) { this.map.removeLayer(this.layer); this.layer = null; } }
    setOpacity(o) { this.opacity = o; if (this.layer) this.layer.setOpacity(o); }
    onClick(cb) { this.map.on('click', e => cb(e.latlng)); }
    popup(latlng, html) { return L.popup({ maxWidth: 300 }).setLatLng(latlng).setContent(html).openOn(this.map); }
    setPins(recs, colors, onClick) {
      this.setPolygonsAndPins(recs, colors, onClick);
    }
    setPolygonsAndPins(recs, colors, onClick) {
      Object.values(this.pins).forEach(m => this.map.removeLayer(m)); this.pins = {};
      Object.values(this.polygons || {}).forEach(p => this.map.removeLayer(p)); this.polygons = {};
      
      const defaultColors = { uhi: '#EA580C', waterlogging: '#1D4ED8' };
      recs.forEach(r => {
        const pinColor = (typeof colors === 'string') ? colors : (colors && colors[r.hazard]) || defaultColors[r.hazard] || '#16A34A';
        
        // 1. Draw polygon boundary in bold black as requested
        if (r.polygon && Array.isArray(r.polygon) && r.polygon.length >= 3) {
          const poly = L.polygon(r.polygon, {
            pane: 'polygonsPane',
            color: '#000000',
            weight: 2.5,
            dashArray: '5, 4',
            fillColor: '#000000',
            fillOpacity: 0.16,
            interactive: true
          }).addTo(this.map);
          poly.on('click', () => onClick(r.id));
          this.polygons[r.id] = poly;
        }

        // 2. Center pin marker
        const icon = L.divIcon({ className: '', iconSize: [30, 30], iconAnchor: [15, 30],
          html: `<div class="cr-pin" style="background:${pinColor}"><span>${String(r.n).padStart(2, '0')}</span></div>` });
        const m = L.marker([r.lat, r.lng], { 
          pane: 'markersPane',
          icon, 
          title: `${r.hazard_label}: ${r.place}` 
        }).addTo(this.map);
        m.on('click', () => onClick(r.id)); this.pins[r.id] = m;
      });
    }
    highlight(id) {
      Object.entries(this.pins).forEach(([k, m]) => { 
        const el = m.getElement(); 
        if (el) el.firstChild.classList.toggle('on', String(k) === String(id)); 
      });
      Object.entries(this.polygons || {}).forEach(([k, poly]) => {
        const isTarget = String(k) === String(id);
        poly.setStyle({
          color: '#000000',
          weight: isTarget ? 4 : 2.5,
          dashArray: isTarget ? null : '5, 4',
          fillOpacity: isTarget ? 0.35 : 0.14
        });
        if (isTarget) poly.bringToFront();
      });
    }
    focusPin(id, html) {
      this.focusMultiplePins([id], html);
    }
    focusMultiplePins(ids, html) {
      const targetIds = Array.isArray(ids) ? ids.map(String) : [String(ids)];
      const bounds = L.latLngBounds([]);
      let firstMarker = null;

      targetIds.forEach(id => {
        const m = this.pins[id];
        const p = (this.polygons || {})[id];
        if (m) {
          bounds.extend(m.getLatLng());
          if (!firstMarker) firstMarker = m;
          const el = m.getElement();
          if (el && el.firstChild) {
            el.firstChild.classList.add('blink', 'on');
            setTimeout(() => { if (el && el.firstChild) el.firstChild.classList.remove('blink'); }, 2800);
          }
        }
        if (p) bounds.extend(p.getBounds());
      });

      if (bounds.isValid()) {
        this.map.flyToBounds(bounds, { padding: [55, 55], maxZoom: 15, duration: 0.8 });
      }

      // Highlight all target polygons with black stroke
      Object.entries(this.polygons || {}).forEach(([k, poly]) => {
        const isTarget = targetIds.includes(String(k));
        poly.setStyle({
          color: '#000000',
          weight: isTarget ? 4 : 2.5,
          dashArray: isTarget ? null : '5, 4',
          fillOpacity: isTarget ? 0.35 : 0.14
        });
        if (isTarget) poly.bringToFront();
      });

      if (targetIds.length > 2) {
        this.map.closePopup();
      } else if (firstMarker && html) {
        firstMarker.unbindPopup().bindPopup(html, { maxWidth: 320 });
        setTimeout(() => firstMarker.openPopup(), 850);
      }
    }
    resize() { this.map.invalidateSize(); }
  }
  window.CRMap = CRMap;
})();
