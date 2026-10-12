/** Overnight planner — compact plan + last-run table (AP-2). */
(function () {
  const HUB_PREFIX = (location.pathname.match(/^(\/hub-form)(?=\/|$)/) || [])[1] || '';

  const STEP_CATALOG = [
    { type: 'machine_wake', label: 'Wake machine', defaults: { target: 'tnas', timeout_min: 5 } },
    { type: 'machine_sleep', label: 'Sleep machine', defaults: { target: 'ubuntu', timeout_min: 3 } },
    { type: 'mount_check', label: 'Check drives', defaults: { timeout_min: 3 } },
    { type: 'llm_start', label: 'Start vLLM', defaults: { timeout_min: 8 } },
    { type: 'llm_stop', label: 'Stop vLLM', defaults: { timeout_min: 3 } },
    { type: 'dsh_research', label: 'DeepSeek research', defaults: { timeout_min: 45 } },
    { type: 'dsh_log_review', label: 'DeepSeek log review', defaults: { timeout_min: 15 } },
    { type: 'sync_job', label: 'Seedvault sync', defaults: { timeout_min: 30 } },
    { type: 'queue_drain', label: 'Download queue', defaults: { timeout_min: 20 } },
    { type: 'storage_scan', label: 'Storage scan', defaults: { timeout_min: 20 } },
  ];

  let schedule = {
    timezone: 'Australia/Brisbane',
    window: { start: '22:00', end: '06:00' },
    advance_mode: 'complete_or_timeout',
    steps: [],
  };
  let savedJson = '';
  let sortable = null;
  let statusPoll = null;

  function api(path, opts = {}) {
    return fetch(`${HUB_PREFIX}/api${path}`, {
      headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
      ...opts,
    }).then(async (r) => {
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.detail || r.statusText);
      return j;
    });
  }

  function uid() {
    return Math.random().toString(36).slice(2, 10);
  }

  function stepTimeout(step) {
    return Number(step.timeout_min ?? step.duration_min) || 5;
  }

  function parseHm(hm) {
    const [h, m] = String(hm || '0:0').split(':').map(Number);
    return h * 60 + m;
  }

  function enabledSteps() {
    return (schedule.steps || []).filter((s) => s.enabled);
  }

  function disabledSteps() {
    return (schedule.steps || []).filter((s) => !s.enabled);
  }

  function windowSpanMins() {
    const start = parseHm(schedule.window?.start || '22:00');
    const end = parseHm(schedule.window?.end || '06:00');
    let w = end - start;
    if (w <= 0) w += 24 * 60;
    return w;
  }

  function budgetTotalMins() {
    return enabledSteps().reduce((a, s) => a + stepTimeout(s), 0);
  }

  function normaliseSchedule() {
    schedule.advance_mode = schedule.advance_mode || 'complete_or_timeout';
    schedule.window = schedule.window || { start: '22:00', end: '06:00' };
    schedule.steps = schedule.steps || [];
  }

  function scheduleJson() {
    return JSON.stringify(schedule);
  }

  function setDirty() {
    const btn = document.getElementById('btnSave');
    if (!btn) return;
    const dirty = scheduleJson() !== savedJson;
    btn.hidden = !dirty;
    btn.textContent = 'Save changes';
  }

  function renderStrip() {
    const total = budgetTotalMins();
    const span = windowSpanMins();
    const strip = document.getElementById('budgetStrip');
    const line = document.getElementById('limitsLine');
    const wl = document.getElementById('windowLabel');
    if (wl) {
      wl.textContent = `${schedule.window?.start || '22:00'} → ${schedule.window?.end || '06:00'} Brisbane`;
    }
    if (line) {
      line.textContent = `Limits total ${total} min of a ${span} min window`;
    }
    if (!strip) return;
    const steps = enabledSteps();
    if (!steps.length) {
      strip.innerHTML = '';
      return;
    }
    strip.innerHTML = steps
      .map((s) => {
        const pct = Math.max(1, (stepTimeout(s) / total) * 100);
        const title = s.label || s.type;
        return `<div class="strip-seg" style="flex:${stepTimeout(s)} 0 ${pct}%" title="${title}"></div>`;
      })
      .join('');
  }

  function stepRowHtml(step, removable) {
    const label = step.label || step.type;
    const to = stepTimeout(step);
    return `<div class="step-row${step.enabled ? '' : ' disabled'}" data-id="${step.id}">
      <strong>${label}</strong>
      <div class="meta">
        <label><input type="checkbox" class="step-enabled" ${step.enabled ? 'checked' : ''} /> enabled</label>
        <span>limit <input type="number" min="1" max="240" class="step-to" value="${to}" /> min</span>
        <span>${step.type}${step.target ? ' · ' + step.target : ''}</span>
        ${removable ? '<button type="button" class="btn step-remove" style="padding:0.1rem 0.35rem;font-size:0.72rem;margin-left:auto">Remove</button>' : ''}
      </div>
    </div>`;
  }

  function bindStepEvents(container) {
    container.querySelectorAll('.step-row').forEach((row) => {
      const id = row.dataset.id;
      row.querySelector('.step-enabled')?.addEventListener('change', (e) => {
        const s = schedule.steps.find((x) => x.id === id);
        if (s) s.enabled = e.target.checked;
        renderPlan();
        setDirty();
      });
      row.querySelector('.step-to')?.addEventListener('change', (e) => {
        const s = schedule.steps.find((x) => x.id === id);
        if (s) {
          s.timeout_min = Number(e.target.value) || 5;
          delete s.duration_min;
        }
        renderStrip();
        setDirty();
      });
      row.querySelector('.step-remove')?.addEventListener('click', () => {
        schedule.steps = schedule.steps.filter((x) => x.id !== id);
        renderPlan();
        renderStrip();
        setDirty();
      });
    });
  }

  function renderPlan() {
    const enabledEl = document.getElementById('enabledSteps');
    const disabledEl = document.getElementById('disabledSteps');
    const wrap = document.getElementById('disabledWrap');
    const summary = document.getElementById('notScheduledSummary');
    const enabled = enabledSteps();
    const disabled = disabledSteps();
    enabledEl.innerHTML = enabled.length
      ? enabled.map((s) => stepRowHtml(s, true)).join('')
      : '<p class="hint">No enabled steps. Enable steps below or add from the palette.</p>';
    bindStepEvents(enabledEl);
    if (sortable) sortable.destroy();
    sortable = null;
    if (enabled.length) {
      sortable = Sortable.create(enabledEl, {
        animation: 140,
        ghostClass: 'sortable-ghost',
        draggable: '.step-row',
        onEnd(evt) {
          const en = enabledSteps();
          const movedId = en[evt.oldIndex]?.id;
          if (!movedId) return;
          const order = en.map((s) => s.id);
          order.splice(evt.oldIndex, 1);
          order.splice(evt.newIndex, 0, movedId);
          const byId = new Map(schedule.steps.map((s) => [s.id, s]));
          const dis = disabledSteps();
          schedule.steps = order.map((id) => byId.get(id)).concat(dis);
          renderPlan();
          setDirty();
        },
      });
    }
    disabledEl.innerHTML = disabled.map((s) => stepRowHtml(s, true)).join('');
    bindStepEvents(disabledEl);
    if (wrap && summary) {
      wrap.hidden = disabled.length === 0;
      summary.textContent = `Not scheduled (${disabled.length})`;
    }
    renderStrip();
    validate();
  }

  function validate() {
    const banner = document.getElementById('warnBanner');
    const total = budgetTotalMins();
    const span = windowSpanMins();
    const msgs = [];
    if (total > span) {
      msgs.push(
        `Time limits total ${total} min exceed the ${span} min night window — some steps may not run unless they finish early.`
      );
    }
    const types = enabledSteps().map((s) => s.type);
    const ls = types.indexOf('llm_start');
    const lr = types.findIndex((t) => t === 'dsh_research' || t === 'research_synthesis');
    if (lr >= 0 && ls >= 0 && ls > lr) msgs.push('Start vLLM should come before DeepSeek research.');
    if (msgs.length) {
      banner.textContent = msgs.join(' ');
      banner.classList.add('show');
    } else {
      banner.classList.remove('show');
    }
  }

  function renderPalette() {
    const el = document.getElementById('palette');
    el.innerHTML = STEP_CATALOG.map(
      (c) => `<div class="palette-item" data-type="${c.type}">${c.label}</div>`
    ).join('');
    el.querySelectorAll('.palette-item').forEach((node) => {
      node.addEventListener('click', () => addStep(node.dataset.type));
    });
  }

  function addStep(type) {
    const cat = STEP_CATALOG.find((c) => c.type === type);
    if (!cat) return;
    schedule.steps.push({
      id: `${type}-${uid()}`,
      type,
      label: cat.label,
      enabled: true,
      critical: false,
      timeout_min: cat.defaults.timeout_min,
      ...cat.defaults,
    });
    renderPlan();
    setDirty();
  }

  function fmtTook(s) {
    const n = s.took_s != null ? s.took_s : s.duration_s;
    if (n == null) return '—';
    return `${Math.round(Number(n))}s`;
  }

  async function loadLastRun() {
    const meta = document.getElementById('lastRunMeta');
    const body = document.getElementById('lastRunBody');
    try {
      const d = await api('/overnight/last-night');
      if (!d.run_id) {
        meta.textContent = d.message || 'No run recorded last night';
        body.innerHTML = '<tr><td colspan="4" class="hint">No steps yet.</td></tr>';
        return;
      }
      meta.textContent = `Run ${d.run_id} · outcome ${d.outcome || 'ok'}`;
      const steps = d.steps || [];
      if (!steps.length) {
        body.innerHTML = '<tr><td colspan="4" class="hint">No steps in this run.</td></tr>';
        return;
      }
      body.innerHTML = steps
        .map((s) => {
          const cls = s.ok ? 'result-ok' : 'result-fail';
          const res = s.result_text || (s.ok ? 'OK' : 'Failed');
          return `<tr>
            <td>${s.started_at || '—'}</td>
            <td>${s.label || '?'}</td>
            <td class="${cls}">${res}</td>
            <td>${fmtTook(s)}</td>
          </tr>`;
        })
        .join('');
    } catch (e) {
      meta.textContent = 'Could not load last run';
      body.innerHTML = '';
    }
  }

  async function pollRunStatus() {
    try {
      const st = await api('/overnight/status');
      const el = document.getElementById('runStatus');
      if (!st.status || st.status === 'idle') {
        el.classList.remove('show');
        if (statusPoll) {
          clearInterval(statusPoll);
          statusPoll = null;
        }
        return;
      }
      el.classList.add('show');
      el.classList.remove('running', 'done');
      if (st.status === 'running') {
        el.classList.add('running');
        el.textContent = `Running: ${st.current_label || st.current_step || '…'} (${st.steps_done}/${st.steps_total})`;
      } else if (st.status === 'done') {
        el.classList.add('done');
        el.textContent = `Last run finished — ${st.steps_done}/${st.steps_total} steps`;
        clearInterval(statusPoll);
        statusPoll = null;
        loadLastRun();
      } else if (st.status === 'failed') {
        el.textContent = `Run failed: ${st.error || 'unknown'}`;
        clearInterval(statusPoll);
        statusPoll = null;
        loadLastRun();
      }
    } catch (_) {
      /* ignore */
    }
  }

  async function load() {
    const data = await api('/overnight/schedule');
    schedule = data.schedule || schedule;
    normaliseSchedule();
    savedJson = scheduleJson();
    renderPlan();
    setDirty();
    await loadLastRun();
    pollRunStatus();
    if (!statusPoll) statusPoll = setInterval(pollRunStatus, 4000);
  }

  async function save() {
    const btn = document.getElementById('btnSave');
    btn.disabled = true;
    try {
      await api('/overnight/schedule', { method: 'PUT', body: JSON.stringify({ schedule }) });
      savedJson = scheduleJson();
      btn.textContent = 'Saved';
      setTimeout(() => {
        btn.textContent = 'Save changes';
        setDirty();
      }, 1200);
    } finally {
      btn.disabled = false;
    }
  }

  async function runNow() {
    const btn = document.getElementById('btnRun');
    btn.disabled = true;
    try {
      await api('/overnight/run', { method: 'POST', body: JSON.stringify({ dry_run: false }) });
      pollRunStatus();
      if (!statusPoll) statusPoll = setInterval(pollRunStatus, 3000);
    } catch (e) {
      alert(e.message || String(e));
    } finally {
      btn.disabled = false;
    }
  }

  function init() {
    renderPalette();
    document.getElementById('btnSave')?.addEventListener('click', save);
    document.getElementById('btnRun')?.addEventListener('click', runNow);
    load().catch((e) => {
      const b = document.getElementById('warnBanner');
      b.textContent = 'Load failed: ' + e.message;
      b.classList.add('show');
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
