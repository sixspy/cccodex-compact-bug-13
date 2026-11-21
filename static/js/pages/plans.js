import { api } from '../api.js';

function chipTag(chip) {
  const bad = chip !== '绿灯';
  return `<span class="tag ${bad ? 'bad' : 'ok'}">${chip}</span>`;
}

export async function renderPlans(view, setMsg) {
  const [j, cross] = await Promise.all([
    api('/api/plans'),
    api('/api/reconcile/cross-chip'),
  ]);
  const missing = cross.missing_tables || [];
  view.innerHTML = `
    <section class="card">
      <h2>压实计划</h2>
      <div class="row">
        <label>编号<input id="code" value="CP-NEW-1" /></label>
        <label>标题<input id="title" value="新压实计划" /></label>
        <label>目标表<input id="table" value="dw_payments" /></label>
        <button class="primary" id="create" type="button">创建计划</button>
        ${chipTag(cross.chip)}
        <span class="muted">已纳入表号 ${cross.has_snapshot ? (cross.included || []).length : 0} 张</span>
      </div>
      ${missing.length ? `<p class="err">未纳入表：${missing.join('、')}，汇总不得亮绿</p>` : ''}
    </section>
    <section class="wall" style="margin-top:1rem">
      ${(j.items || []).map(p => `<article class="card">
        <h3>${p.plan_code}</h3>
        <span class="tag">${p.status}</span>
        ${chipTag(cross.chip)}
        <p>${p.title}</p>
        <p class="muted">${p.target_table} · ${p.item_count} 文件 · ${p.plan_bytes} 字节</p>
        <div class="row">
          <button data-attach="${p.id}" type="button">挂入碎文件</button>
          <button data-pub="${p.id}" class="primary" type="button">发布</button>
          <button data-detail="${p.id}" type="button">详情</button>
        </div>
        <pre class="muted" id="d${p.id}"></pre>
      </article>`).join('') || '<p class="muted">暂无计划</p>'}
    </section>`;
  document.getElementById('create').onclick = async () => {
    try {
      await api('/api/plans', { method:'POST', body: JSON.stringify({
        plan_code: document.getElementById('code').value,
        title: document.getElementById('title').value,
        target_table: document.getElementById('table').value,
      })});
      setMsg('计划已创建');
      await renderPlans(view, setMsg);
    } catch (e) { setMsg(e.message, true); }
  };
  view.querySelectorAll('[data-attach]').forEach(btn => {
    btn.onclick = async () => {
      try {
        const r = await api('/api/plans/' + btn.dataset.attach + '/attach', { method:'POST', body:'{}' });
        setMsg('挂入 ' + r.attached + ' 个碎文件');
        await renderPlans(view, setMsg);
      } catch (e) { setMsg(e.message, true); }
    };
  });
  view.querySelectorAll('[data-pub]').forEach(btn => {
    btn.onclick = async () => {
      try {
        await api('/api/plans/' + btn.dataset.pub + '/publish', { method:'POST', body:'{}' });
        setMsg('已发布');
        await renderPlans(view, setMsg);
      } catch (e) { setMsg(e.message, true); }
    };
  });
  view.querySelectorAll('[data-detail]').forEach(btn => {
    btn.onclick = async () => {
      try {
        const r = await api('/api/plans/' + btn.dataset.detail);
        document.getElementById('d' + btn.dataset.detail).textContent = JSON.stringify(r.items, null, 2);
      } catch (e) { setMsg(e.message, true); }
    };
  });
}
