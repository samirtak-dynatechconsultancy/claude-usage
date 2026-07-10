// ==UserScript==
// @name         Claude Usage Tracker
// @namespace    claude-usage-analyzer
// @version      1.0
// @description  Show live Claude subscription usage (5h + 7d) and log a daily history you can export to CSV.
// @match        https://claude.ai/*
// @grant        GM_setValue
// @grant        GM_getValue
// @grant        GM_registerMenuCommand
// @run-at       document-idle
// ==/UserScript==

(function () {
  'use strict';

  // ---- config ---------------------------------------------------------------
  const POLL_MINUTES = 15;                 // how often to refresh while a tab is open
  const LOG_KEY = 'cu_daily_log';          // persisted history {date: {...}}

  // Resolved once per page load (never hardcoded, never persisted -> always current).
  let RESOLVED_ORG = null;

  // ---- fetch usage for one org ---------------------------------------------
  async function usageFor(org) {
    const r = await fetch(`/api/organizations/${org}/usage`, {
      headers: { accept: 'application/json' },
    });
    if (!r.ok) throw new Error(`usage ${r.status}`);
    return r.json();
  }

  // Which org is the UI currently using? The site stores the active org id in
  // a cookie (e.g. lastActiveOrg). We don't rely on the exact name: we just
  // look for whichever known org id appears in document.cookie.
  function activeOrgFromCookie(ids) {
    const jar = document.cookie || '';
    return ids.find((id) => jar.includes(id)) || null;
  }

  function hasUsage(data) {
    return data && data.five_hour && typeof data.five_hour.utilization === 'number';
  }

  // ---- fully dynamic org discovery -----------------------------------------
  // 1) list every org this account belongs to
  // 2) prefer the org the UI is actively using (from cookie)
  // 3) among candidates, pick the first whose /usage returns real numbers
  //    (an org without a subscription returns nulls) -> always the right one.
  async function resolveOrg() {
    const r = await fetch('/api/organizations', { headers: { accept: 'application/json' } });
    if (!r.ok) throw new Error(`organizations ${r.status}`);
    const orgs = await r.json();
    // The /usage endpoint requires the UUID, not the numeric `id`. Prefer uuid;
    // only accept an `id` if it actually looks like a UUID.
    const isUuid = (v) => typeof v === 'string' && /^[0-9a-f-]{32,}$/i.test(v);
    const ids = (Array.isArray(orgs) ? orgs : [])
      .map((o) => (isUuid(o.uuid) ? o.uuid : (isUuid(o.id) ? o.id : null)))
      .filter(Boolean);
    if (!ids.length) throw new Error('no organizations found for this account');
    if (ids.length === 1) return { org: ids[0], data: null };

    // Try the active org first, then the rest.
    const active = activeOrgFromCookie(ids);
    const order = active ? [active, ...ids.filter((i) => i !== active)] : ids;

    let firstOk = null;
    for (const id of order) {
      try {
        const data = await usageFor(id);
        if (hasUsage(data)) return { org: id, data };   // real subscription data
        if (!firstOk) firstOk = { org: id, data };       // remember any valid response
      } catch (e) { /* try next org */ }
    }
    // no org had numeric utilization; use active/first that at least responded
    return firstOk || { org: order[0], data: null };
  }

  // ---- fetch usage (resolves org on demand, re-resolves on failure) ---------
  async function fetchUsage() {
    if (!RESOLVED_ORG) {
      const { org, data } = await resolveOrg();
      RESOLVED_ORG = org;
      if (data) return data; // discovery already fetched it — reuse
    }
    try {
      return await usageFor(RESOLVED_ORG);
    } catch (e) {
      // org may have changed (workspace switch); re-resolve once and retry.
      RESOLVED_ORG = null;
      const { org, data } = await resolveOrg();
      RESOLVED_ORG = org;
      return data || usageFor(org);
    }
  }

  // ---- persistence: keep the MAX utilization seen per day -------------------
  async function record(data) {
    const s = data?.five_hour?.utilization ?? null;
    const w = data?.seven_day?.utilization ?? null;
    const now = new Date();
    const date = now.toISOString().slice(0, 10);
    const log = await GM_getValue(LOG_KEY, {});
    const prev = log[date] || { session_max: 0, weekly_max: 0 };
    log[date] = {
      session_max: Math.max(prev.session_max || 0, s ?? 0),
      weekly_max: Math.max(prev.weekly_max || 0, w ?? 0),
      session_last: s,
      weekly_last: w,
      updated: now.toISOString(),
    };
    await GM_setValue(LOG_KEY, log);
    return { s, w, resets: data?.five_hour?.resets_at, sev: sev(data) };
  }

  function sev(data) {
    const lim = (data?.limits || []).find((l) => l.kind === 'session');
    return lim?.severity || 'normal';
  }

  // ---- CSV export -----------------------------------------------------------
  async function exportCsv() {
    const log = await GM_getValue(LOG_KEY, {});
    const rows = [['date', 'session_max_pct', 'weekly_max_pct', 'session_last_pct', 'weekly_last_pct', 'updated']];
    Object.keys(log).sort().forEach((d) => {
      const e = log[d];
      rows.push([d, e.session_max, e.weekly_max, e.session_last, e.weekly_last, e.updated]);
    });
    const csv = rows.map((r) => r.join(',')).join('\n');
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
    a.download = 'claude_usage.csv';
    a.click();
    URL.revokeObjectURL(a.href);
  }

  // ---- badge UI -------------------------------------------------------------
  const COLORS = { normal: '#2e7d32', warning: '#ed6c02', critical: '#d32f2f' };

  function makeBadge() {
    let el = document.getElementById('cu-badge');
    if (el) return el;
    el = document.createElement('div');
    el.id = 'cu-badge';
    Object.assign(el.style, {
      position: 'fixed', bottom: '14px', right: '14px', zIndex: 999999,
      font: '12px/1.3 system-ui, sans-serif', color: '#fff',
      background: '#2e7d32', padding: '6px 10px', borderRadius: '8px',
      boxShadow: '0 2px 8px rgba(0,0,0,.25)', cursor: 'pointer',
      userSelect: 'none', opacity: '0.92',
    });
    el.title = 'Click to refresh • double-click to export CSV';
    el.addEventListener('click', refresh);
    el.addEventListener('dblclick', (e) => { e.preventDefault(); exportCsv(); });
    document.body.appendChild(el);
    return el;
  }

  function render(state) {
    const el = makeBadge();
    if (state.error) {
      el.style.background = '#616161';
      el.textContent = `usage: ${state.error}`;
      return;
    }
    el.style.background = COLORS[state.sev] || COLORS.normal;
    const reset = state.resets ? new Date(state.resets).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '?';
    el.textContent = `5h ${state.s}%  •  7d ${state.w}%  (resets ${reset})`;
  }

  // ---- main loop ------------------------------------------------------------
  async function refresh() {
    try {
      const data = await fetchUsage();
      render(await record(data));
    } catch (e) {
      render({ error: String(e.message || e) });
    }
  }

  GM_registerMenuCommand('Claude Usage: export CSV', exportCsv);
  GM_registerMenuCommand('Claude Usage: refresh now', refresh);

  refresh();
  setInterval(refresh, POLL_MINUTES * 60 * 1000);
})();
