import { api } from '../api.js';

export async function renderReconcile(view, setMsg) {
  const plans = await api('/api/plans');
  const reports = await api('/api/reconcile/reports');
  const options = (plans.items || []).map(p => `<option value="${p.id}">${p.plan_code}</option>`).join('');
  view.innerHTML = `
    <section class="card">
      <h2>体积对账</h2>
      <div class="row">
        <label>计划<select id="pid">${options}</select></label>
        <button class="primary" id="go" type="button">跑对账</button><button id="cross" type="button">跨表汇总</button><span class="tag">绿灯</span>
      </div>
    </section>
    <section class="wall" style="margin-top:1rem">
      ${(reports.items || []).map(r => `<article class="card">
        <h3>${r.plan_code || ('计划#'+r.plan_id)}</h3>
        <p>${r.summary}</p>
        <p class="muted">前 ${r.before_bytes} / 后 ${r.after_bytes}</p>
      </article>`).join('') || '<p class="muted">暂无对账报告</p>'}
    </section>`;
  document.getElementById('cross').onclick = async () => {
    try {
      const r = await api('/api/reconcile/cross-summary');
      setMsg('跨表汇总 ' + r.total_bytes + ' · ' + r.chip);
    } catch (e) { setMsg(e.message, true); }
  };
  document.getElementById('go').onclick = async () => {
    try {
      const r = await api('/api/reconcile/reports', {
        method:'POST',
        body: JSON.stringify({ plan_id: Number(document.getElementById('pid').value) }),
      });
      setMsg(r.report.summary);
      await renderReconcile(view, setMsg);
    } catch (e) { setMsg(e.message, true); }
  };
}
