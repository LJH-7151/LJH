(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const token = document.querySelector('meta[name="local-token"]').content;
  let currentId=null;
  const tell = value => { $('analysis-message').textContent = value; };
  async function request(path, data) {
    const options = data === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json','X-Local-Token':token}, body:JSON.stringify(data)};
    const response = await fetch(path,options); const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || '分析失败');
    return payload;
  }
  function display(analysis) {
    currentId=analysis.id;
    const box = $('analysis-result'); box.replaceChildren();
    const title=document.createElement('h3'); title.textContent=analysis.question; box.append(title);
    if (!analysis.conclusions.length) {
      const empty=document.createElement('p'); empty.textContent='本次未找到直接材料，请调整关键词。'; box.append(empty);
    }
    for (const item of analysis.conclusions) {
      const section=document.createElement('section'); const text=document.createElement('p'); text.textContent=item.text; section.append(text);
      for (const citation of item.citations) {
        const source=analysis.sources.find(s => s.id === citation.id); const quote=document.createElement('blockquote');
        quote.textContent=`${source?.title || '来源'} · ${source?.location || ''}：${citation.quote}`; section.append(quote);
        if(source && analysis.mode!=='migrated') {
          const open=document.createElement('button'); open.type='button'; open.className='button button-quiet';
          if(source.metadata?.category==='计算证据') {
            open.textContent='查看统计'; open.addEventListener('click',()=>window.dispatchEvent(new CustomEvent('evidence:open-calculation',{detail:{id:source.id}})));
          } else if(source.id.startsWith('table_')) {
            open.textContent='查看来源行'; open.addEventListener('click',()=>window.dispatchEvent(new CustomEvent('evidence:open-table-source',{detail:{tableId:source.document_id,location:source.location}})));
          } else {
            open.textContent='查看原文'; open.addEventListener('click',()=>window.dispatchEvent(new CustomEvent('evidence:open-source',{detail:{documentId:source.document_id,chunkId:source.id}})));
          }
          section.append(open);
        }
      }
      box.append(section);
    }
    for (const item of analysis.conflicts || []) {
      const line=document.createElement('p'); line.textContent=`${item.state}：${item.metric}，${item.left.display} / ${item.right.display}。请核对来源与口径。`; box.append(line);
    }
    for (const item of analysis.legacy_conflicts || []) {
      const line=document.createElement('p'); line.textContent=`${item.state || '待核对'}：${item.metric || '来源差异'}。${item.note || ''}`; box.append(line);
    }
    for (const item of analysis.gaps || []) { const line=document.createElement('p'); line.textContent=`材料缺口：${item.title || item.material || ''} ${item.reason || ''}`; box.append(line); }
    for (const item of analysis.actions || []) { const line=document.createElement('p'); line.textContent=`建议：${item.text || ''}`; box.append(line); }
    const issues=$('analysis-issue'); issues.replaceChildren();
    for(const item of [...(analysis.conflicts || []),...(analysis.legacy_conflicts || []),...(analysis.gaps || [])]) {
      if(!item.id) continue; const option=document.createElement('option'); option.value=item.id; option.textContent=item.metric || item.title || '待核对事项'; issues.append(option);
    }
    for (const text of analysis.limitations) { const note=document.createElement('p'); note.textContent=text; box.append(note); }
    const download=document.createElement('a'); download.textContent='下载 Word 分析档案';
    download.href='/api/analysis-export?id='+encodeURIComponent(analysis.id); box.append(download);
    tell(`已保存，检索到 ${analysis.sources.length} 条原文。`);
    showReviews().catch(error=>tell(error.message));
  }
  async function showReviews() {
    const result=await request('/api/analysis-reviews?id='+encodeURIComponent(currentId)); const box=$('analysis-reviews'); box.replaceChildren();
    for(const review of result.reviews) { const line=document.createElement('p'); line.textContent=`${review.created_at} · ${review.status} · ${review.note}`; box.append(line); }
  }
  async function history() {
    const entries=(await request('/api/analyses')).analyses; const select=$('analysis-history');
    select.replaceChildren(); const blank=document.createElement('option'); blank.value=''; blank.textContent='选择档案'; select.append(blank);
    for (const entry of entries) { const item=document.createElement('option'); item.value=entry.id; item.textContent=`${entry.created_at} ${entry.question}`; select.append(item); }
  }
  async function scope() {
    const [docs,tables,calculations]=await Promise.all([request('/api/catalog/list'),request('/api/tables'),request('/api/table-results')]);
    const select=$('analysis-scope'); select.replaceChildren();
    for(const item of docs.documents.filter(doc=>!doc.metadata.archived)) { const option=document.createElement('option'); option.value=item.id; option.textContent='文档 · '+item.title; select.append(option); }
    for(const item of tables.tables.filter(table=>!table.metadata.archived)) { const option=document.createElement('option'); option.value=item.id; option.textContent='数据表 · '+item.name; select.append(option); }
    const calc=$('analysis-calculations'); calc.replaceChildren();
    for(const item of calculations.results) { const option=document.createElement('option'); option.value=item.id; option.textContent=`${item.created_at} · ${item.measure || '行数'} · ${item.operation}`; calc.append(option); }
  }
  $('analysis-refresh-scope').addEventListener('click',()=>scope().catch(error=>tell(error.message)));
  window.addEventListener('evidence:documents-changed',()=>scope().catch(()=>{}));
  window.addEventListener('evidence:tables-changed',()=>scope().catch(()=>{}));
  $('analysis-form').addEventListener('submit',async event => {
    event.preventDefault(); const button=event.submitter; button.disabled=true; tell('正在分析，本地模型可能需要较长时间…');
    try { const selected=$('analysis-use-scope').checked ? [...$('analysis-scope').selectedOptions].map(item=>item.value) : null;
      const calculations=[...$('analysis-calculations').selectedOptions].map(item=>item.value);
      const tasks=$('analysis-tasks').value.split('\n').map(value=>value.trim()).filter(Boolean);
      const result=await request('/api/analyze',{question:$('analysis-question').value,mode:$('analysis-mode').value,lens:$('analysis-lens').value,selected_ids:selected,calculation_ids:calculations,tasks:tasks.length?tasks:null}); display(result); await history(); $('analysis-history').value=result.id; }
    catch(error) { tell(error.message); } finally { button.disabled=false; }
  });
  $('analysis-history').addEventListener('change',async event => {
    if (!event.target.value) return;
    try { display(await request('/api/analysis?id='+encodeURIComponent(event.target.value))); } catch(error) { tell(error.message); }
  });
  $('analysis-review').addEventListener('submit',async event=>{
    event.preventDefault(); if(!currentId || !$('analysis-issue').value) { tell('请先选择有待核对事项的档案。'); return; }
    const button=event.submitter; button.disabled=true;
    try { await request('/api/analysis-review',{id:currentId,issue_id:$('analysis-issue').value,status:$('analysis-review-status').value,note:$('analysis-review-note').value});
      await showReviews(); tell('核对记录已保存。'); }
    catch(error) { tell(error.message); } finally { button.disabled=false; }
  });
  history().catch(error => tell(error.message));
  scope().catch(error => tell(error.message));
})();
