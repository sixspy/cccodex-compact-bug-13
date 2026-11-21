import { api } from '../api.js';

function chipTag(chip) {
  const bad = chip !== '绿灯';
  return `<span class="tag ${bad ? 'bad' : 'ok'}">${chip}</span>`;
}

export async function renderSettings(view, setMsg) {
  const [j, cross] = await Promise.all([
    api('/api/settings'),
    api('/api/reconcile/cross-chip'),
  ]);
  const missing = cross.missing_tables || [];
  view.innerHTML = `
    <section class="card">
      <h2>台参数</h2>
      <p class="muted">压实阈值与对账模式；保存后立即写库。</p>
      <div class="wall">
        ${(j.items || []).map(s => `<article class="card">
          <h3>${s.label}</h3>
          <p class="muted">${s.key}</p>
          <input data-key="${s.key}" value="${s.value}" />
          <button data-save="${s.key}" class="primary" type="button">保存</button>
        </article>`).join('')}
      </div>
    </section>
    <section class="card" style="margin-top:1rem">
      <h3>跨表汇总快照（独立快照表单轨）</h3>
      <div class="row">${chipTag(cross.chip)}
        <button id="build_snapshot" class="primary" type="button">生成汇总补洞</button>
      </div>
      <p class="muted">快照号 ${cross.has_snapshot ? cross.snapshot_id : '—'} · 汇总 ${cross.total_bytes ?? 0} 字节</p>
      <p class="muted">纳入表清单：${(cross.included || []).join('、') || '（空）'}</p>
      ${missing.length ? `<p class="err">未纳入表：${missing.join('、')}，漏表不得亮绿</p>`
        : (cross.has_snapshot ? '<p class="muted">纳入表清单齐全，字节对齐</p>' : '<p class="err">尚无快照，禁止只刷绿灯</p>')}
    </section>`;
  view.querySelectorAll('[data-save]').forEach(btn => {
    btn.onclick = async () => {
      try {
        const key = btn.dataset.save;
        const input = view.querySelector('input[data-key="'+key+'"]');
        await api('/api/settings', { method:'POST', body: JSON.stringify({ key, value: input.value }) });
        setMsg('已保存 ' + key);
        await renderSettings(view, setMsg);
      } catch (e) { setMsg(e.message, true); }
    };
  });
  document.getElementById('build_snapshot').onclick = async () => {
    try {
      const r = await api('/api/reconcile/cross-summary', { method:'POST', body:'{}' });
      const s = r.snapshot;
      setMsg('汇总补洞完成 · ' + s.chip +
        (s.missing_tables.length ? '（未纳入：' + s.missing_tables.join('、') + '）' : ''));
      await renderSettings(view, setMsg);
    } catch (e) { setMsg(e.message, true); }
  };
}
