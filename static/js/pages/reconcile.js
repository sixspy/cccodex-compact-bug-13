import { api } from '../api.js';

function chipTag(chip) {
  const bad = chip !== '绿灯';
  return `<span class="tag ${bad ? 'bad' : 'ok'}">${chip}</span>`;
}

export async function renderReconcile(view, setMsg) {
  const [plans, reports, cross] = await Promise.all([
    api('/api/plans'),
    api('/api/reconcile/reports'),
    api('/api/reconcile/cross-chip'),
  ]);
  const options = (plans.items || []).map(p => `<option value="${p.id}">${p.plan_code}</option>`).join('');
  const missing = (cross.missing_tables || []);
  const missingLine = missing.length
    ? `<p class="err">未纳入表：${missing.join('、')}</p>`
    : (cross.has_snapshot ? '<p class="muted">纳入表清单已全部对齐</p>' : '<p class="err">尚无汇总快照，当前不得亮绿</p>');
  view.innerHTML = `
    <section class="card">
      <h2>体积对账</h2>
      <div class="row">
        <label>计划<select id="pid">${options}</select></label>
        <button class="primary" id="go" type="button">跑对账</button>
        <button id="cross" type="button">生成汇总补洞</button>
        ${chipTag(cross.chip)}
      </div>
      ${missingLine}
      <p class="muted">纳入 ${(cross.included || []).join('、') || '—'} · 汇总 ${cross.total_bytes ?? 0} 字节</p>
    </section>
    <section class="wall" style="margin-top:1rem">
      ${(reports.items || []).map(r => `<article class="card">
        <h3>${r.plan_code || ('计划#'+r.plan_id)} ${chipTag(r.cross_chip || '漏表汇总')}</h3>
        <p>${r.summary}</p>
        <p class="muted">前 ${r.before_bytes} / 后 ${r.after_bytes}</p>
        ${(r.cross_missing_tables || []).length ? `<p class="err">未纳入表：${r.cross_missing_tables.join('、')}</p>` : ''}
      </article>`).join('') || '<p class="muted">暂无对账报告</p>'}
    </section>`;
  document.getElementById('cross').onclick = async () => {
    try {
      const r = await api('/api/reconcile/cross-summary', { method:'POST', body:'{}' });
      const s = r.snapshot;
      setMsg('汇总补洞完成 ' + s.total_bytes + ' 字节 · ' + s.chip +
        (s.missing_tables.length ? '（未纳入：' + s.missing_tables.join('、') + '）' : ''));
      await renderReconcile(view, setMsg);
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
