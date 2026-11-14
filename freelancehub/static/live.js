// UI effects + near-real-time updates via short polling (no WebSocket dependency).
(function () {
  const csrf = (document.querySelector('meta[name=csrf]') || {}).content;
  const INTERVAL = 3000;

  /* ---------- scroll reveal + count-up numbers ---------- */
  const io = 'IntersectionObserver' in window
    ? new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); } }), { threshold: .08 })
    : null;
  document.querySelectorAll('.reveal').forEach((el, i) => {
    el.style.transitionDelay = Math.min(i, 8) * 60 + 'ms';
    io ? io.observe(el) : el.classList.add('in');
  });
  document.querySelectorAll('[data-count]').forEach(el => {
    const end = +el.dataset.count, t0 = performance.now();
    (function step(t) {
      const k = Math.min(1, (t - t0) / 900);
      el.textContent = Math.round(end * (1 - Math.pow(1 - k, 3)));
      if (k < 1) requestAnimationFrame(step);
    })(t0);
  });

  /* ---------- confirm modal (works on live-refreshed content too) ---------- */
  const modal = document.getElementById('modal');
  const mTitle = document.getElementById('m-title'), mText = document.getElementById('m-text');
  const mReason = document.getElementById('m-reason'), mOk = document.getElementById('m-ok');
  let pending = null;
  function closeModal() { modal.hidden = true; pending = null; }
  document.addEventListener('submit', e => {
    const f = e.target;
    if (!f.classList.contains('confirm-form')) return;
    e.preventDefault();
    pending = { action: f.action, token: (f.querySelector('[name=csrf_token]') || {}).value };
    mTitle.textContent = f.dataset.title || 'Are you sure?';
    mText.textContent = f.dataset.text || '';
    mReason.hidden = !f.dataset.reason; mReason.value = '';
    mOk.className = 'btn ' + (f.dataset.danger ? 'danger' : '');
    mOk.textContent = f.dataset.ok || 'Confirm';
    modal.hidden = false;
    (f.dataset.reason ? mReason : mOk).focus();
  });
  document.getElementById('m-cancel').onclick = closeModal;
  modal.addEventListener('click', e => { if (e.target === modal) closeModal(); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && !modal.hidden) closeModal(); });
  mOk.onclick = () => {
    if (!pending) return;
    // build a fresh form so it still works if the live panel re-rendered meanwhile
    const f = document.createElement('form'); f.method = 'post'; f.action = pending.action;
    const add = (n, v) => { const i = document.createElement('input'); i.type = 'hidden'; i.name = n; i.value = v; f.appendChild(i); };
    add('csrf_token', pending.token || csrf);
    if (!mReason.hidden) add('reason', mReason.value);
    document.body.appendChild(f); f.submit();
  };

  /* ---------- notifications: bell + toasts ---------- */
  if (document.body.dataset.auth === '1') {
    const bell = document.getElementById('bell-count'), box = document.getElementById('toasts');
    let lastSeen = null;
    const toast = n => {
      const d = document.createElement('div'); d.className = 'toast';
      if (n.link) { const a = document.createElement('a'); a.href = n.link; a.textContent = n.message; d.appendChild(a); }
      else d.textContent = n.message;
      box.appendChild(d); setTimeout(() => d.remove(), 7000);
    };
    const poll = async () => {
      try {
        const r = await fetch('/api/notifications', { headers: { 'X-CSRF-Token': csrf } });
        if (!r.ok) return;
        const d = await r.json();
        bell.textContent = d.unread; bell.hidden = d.unread === 0;
        if (lastSeen === null) lastSeen = d.latest_id;            // don't toast old items on page load
        else { d.items.filter(n => n.id > lastSeen).reverse().forEach(toast); lastSeen = Math.max(lastSeen, d.latest_id); }
      } catch (e) {}
    };
    poll(); setInterval(poll, INTERVAL);
  }

  /* ---------- live bid list (client's project page) ---------- */
  const live = document.getElementById('bids-live');
  if (live) {
    const ids = () => new Set([...live.querySelectorAll('.bid-card')].map(c => c.dataset.id));
    let known = ids(), last = live.innerHTML;
    setInterval(async () => {
      try {
        const r = await fetch(live.dataset.url);
        if (!r.ok) return;
        const { html } = await r.json();
        const dot = '<span class="livedot" title="Updating live"></span>';
        if (html !== last) {
          last = html; live.innerHTML = dot + html;
          live.querySelectorAll('.bid-card').forEach(c => { if (!known.has(c.dataset.id)) c.classList.add('fresh'); });
          known = ids();
        }
      } catch (e) {}
    }, INTERVAL);
  }
})();
