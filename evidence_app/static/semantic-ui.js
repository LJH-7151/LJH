(() => {
  'use strict';
  const $=id=>document.getElementById(id),token=document.querySelector('meta[name="local-token"]').content;
  async function post(path,data) {
    const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Local-Token':token},body:JSON.stringify(data)});
    const payload=await response.json(); if(!response.ok) throw new Error(payload.error || '操作失败'); return payload;
  }
  $('semantic-build').addEventListener('click',async event=>{
    event.target.disabled=true; $('semantic-message').textContent='正在构建本地索引…';
    try { const result=await post('/api/semantic/build',{}); $('semantic-message').textContent=`已索引 ${result.indexed} 个资料片段。`; }
    catch(error) { $('semantic-message').textContent=error.message; } finally { event.target.disabled=false; }
  });
  $('semantic-search').addEventListener('submit',async event=>{
    event.preventDefault(); const button=event.submitter; button.disabled=true;
    try { const result=await post('/api/semantic/search',{query:$('semantic-query').value});
      const box=$('semantic-results'); box.replaceChildren();
      for(const source of result.sources) { const p=document.createElement('p');
        p.textContent=`${source.title} · ${source.location}（相似度 ${source.score.toFixed(3)}）：${source.content}`; box.append(p); }
      $('semantic-message').textContent=`返回 ${result.sources.length} 条，请核对原文。`;
    } catch(error) { $('semantic-message').textContent=error.message; } finally { button.disabled=false; }
  });
})();
