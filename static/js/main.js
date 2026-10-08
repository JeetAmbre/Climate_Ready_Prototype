/* Shared site behaviour: sticky nav shadow, hero visual, highlight slider, contact form. */
(function () {
  const nav = document.querySelector('.cr-nav');
  const onScroll = () => nav && nav.classList.toggle('scrolled', window.scrollY > 8);
  onScroll(); window.addEventListener('scroll', onScroll, { passive: true });
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // ---- Hero: three stacked mock map layers (purely decorative) ----
  const stack = document.getElementById('heroStack');
  if (stack) {
    const NS = 'http://www.w3.org/2000/svg', N = 10;
    const ramps = {
      'Urban heat': ['#FFF3B0', '#FDCB6E', '#F59E0B', '#EA580C', '#B91C1C'],
      'Waterlogging': ['#DBEAFE', '#93C5FD', '#3B82F6', '#1D4ED8', '#1E3A8A'],
      'Air pollution': ['#EDE9FE', '#C4B5FD', '#A78BFA', '#7C3AED', '#4C1D95']
    };
    let seed = 0;
    Object.entries(ramps).forEach(([name, ramp]) => {
      seed += 2.1;
      const wrap = document.createElement('div'); wrap.className = 'hl-layer';
      let s = `<svg viewBox="0 0 ${N} ${N}" preserveAspectRatio="none">`;
      for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
        const v = 0.5 + 0.5 * (Math.sin(x * 0.7 + seed) * Math.cos(y * 0.6 + seed * 1.6) * 0.6 + Math.sin((x + y) * 0.4 + seed) * 0.4);
        s += `<rect x="${x}" y="${y}" width="1" height="1" fill="${ramp[Math.min(4, Math.floor(v * 5))]}" stroke="#fff" stroke-opacity=".5" stroke-width=".04"/>`;
      }
      wrap.innerHTML = s + '</svg>'; stack.appendChild(wrap);
    });
    Object.keys(ramps).forEach(n => { const t = document.createElement('span'); t.className = 'hl-tag'; t.textContent = n; stack.appendChild(t); });
  }

  // ---- Highlight slider ----
  const track = document.getElementById('hlTrack');
  if (track) {
    const slides = track.children, dots = document.getElementById('hlDots'); let i = 0, timer;
    [...slides].forEach((_, n) => { const b = document.createElement('button'); b.type = 'button'; b.setAttribute('aria-label', 'Show highlight ' + (n + 1)); b.onclick = () => { go(n); restart(); }; dots.appendChild(b); });
    const go = n => { i = (n + slides.length) % slides.length; track.style.transform = `translateX(-${i * 100}%)`; [...dots.children].forEach((d, k) => d.classList.toggle('on', k === i)); };
    const restart = () => { clearInterval(timer); if (!reduce) timer = setInterval(() => go(i + 1), 6000); };
    track.parentElement.addEventListener('mouseenter', () => clearInterval(timer));
    track.parentElement.addEventListener('mouseleave', restart);
    go(0); restart();
  }

  // ---- Contact form (front-end only; POST to /api/contact when backend exists) ----
  const form = document.getElementById('contactForm');
  if (form) form.addEventListener('submit', e => {
    e.preventDefault();
    let ok = true;
    form.querySelectorAll('[required]').forEach(f => { const v = f.checkValidity() && f.value.trim(); f.classList.toggle('is-invalid', !v); if (!v) ok = false; });
    if (ok) { document.getElementById('contactOk').classList.remove('d-none'); form.reset(); }
  });
})();
