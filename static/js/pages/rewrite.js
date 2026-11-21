import { api } from '../api.js';

function chipTag(chip) {
  const bad = chip !== '绿灯';
  return `<span class="tag ${bad ? 'bad' : 'ok'}">${chip}</span>`;
}

export async function renderRewrite(view, setMsg) {
  const [plans, jobs, cross] = await Promise.all([
    api('/api/plans'),
    api('/api/rewrite/jobs'),
    api('/api/reconcile/cross-chip'),
  ]);
  const options = (plans.items || []).map(p => `<option value="${p.id}">${p.plan_code} · ${p.status}</option>`).join('');
  const missing = cross.missing_tables || [];
  view.innerHTML = `
    <section class="card">
      <h2>重写合并</h2>
      <p class="muted">对已发布计划启动合并；成功后碎文件变为已合并。</p>
      <div class="row">
        <label>计划<select id="pid">${options}</select></label>
        <button class="primary" id="go" type="button">启动合并</button>
        ${chipTag(cross.chip)}
      </div>
      ${missing.length ? `<p class="err">未纳入表：${missing.join('、')}，合并入队已被挡，请先在对账页生成汇总补洞</p>`
        : (cross.has_snapshot ? '<p class="muted">汇总快照已对齐，可入队</p>' : '<p class="err">尚无汇总快照，当前不得亮绿</p>')}
    </section>
    <section class="wall" style="margin-top:1rem">
      ${(jobs.items || []).map(j => `<article class="card">
        <h3>${j.plan_code || ('计划#'+j.plan_id)}</h3>
        <span class="tag">${j.status}</span>
        <p class="muted">${j.message}</p>
        <p>合并字节 ${j.merged_bytes}</p>
      </article>`).join('') || '<p class="muted">尚无合并任务</p>'}
    </section>`;
  document.getElementById('go').onclick = async () => {
    try {
      const pid = document.getElementById('pid').value;
      const r = await api('/api/rewrite/plans/' + pid + '/start', { method:'POST', body:'{}' });
      setMsg('合并完成 · ' + r.job.status);
      await renderRewrite(view, setMsg);
    } catch (e) { setMsg(e.message, true); }
  };
}
