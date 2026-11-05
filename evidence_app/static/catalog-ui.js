(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  const fields=['entity','category','department','period','scope','source','tags','version','published_at','effective_start','effective_end'];
  const token=document.querySelector('meta[name="local-token"]').content;
  let entries=[];
  async function request(url,data) {
    const response=await fetch(url,data===undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json','X-Local-Token':token},body:JSON.stringify(data)});
    const result=await response.json(); if(!response.ok) throw new Error(result.error || '操作失败'); return result;
  }
  function option(value,label) { const item=document.createElement('option'); item.value=value; item.textContent=label; return item; }
  async function load() {
    const id=$('catalog-document').value; if(!id) return;
    const entry=entries.find(item=>item.id===id); if(!entry) return;
    $('catalog-supersedes').replaceChildren(option('','无'),...entries.filter(item=>item.kind===entry.kind && item.id!==id).map(item=>option(item.id,item.title)));
    const data=await request((entry.kind==='table'?'/api/table-metadata?id=':'/api/catalog?id=')+encodeURIComponent(id));
    for(const field of fields) $('catalog-'+field).value=data[field] || '';
    $('catalog-supersedes').value=data.supersedes || ''; $('catalog-archived').checked=data.archived;
  }
  async function list() {
    const [docs,tables]=await Promise.all([request('/api/catalog/list'),request('/api/tables')]); const current=$('catalog-document').value;
    entries=[...docs.documents.map(doc=>({...doc,kind:'document'})),...tables.tables.map(table=>({...table,title:table.name,kind:'table'}))];
    $('catalog-document').replaceChildren(...entries.map(item=>option(item.id,(item.kind==='table'?'数据表 · ':'文档 · ')+item.title+(item.metadata.archived?'（已归档）':''))));
    if(entries.some(item=>item.id===current)) $('catalog-document').value=current;
    await load();
  }
  $('catalog-document').addEventListener('change',()=>load().catch(e=>$('catalog-message').textContent=e.message));
  $('catalog-form').addEventListener('submit',async event=>{
    event.preventDefault(); const button=event.submitter; button.disabled=true;
    try {
      const metadata=Object.fromEntries(fields.map(field=>[field,$('catalog-'+field).value]));
      metadata.supersedes=$('catalog-supersedes').value; metadata.archived=$('catalog-archived').checked;
      const id=$('catalog-document').value, entry=entries.find(item=>item.id===id);
      await request(entry?.kind==='table'?'/api/table-metadata':'/api/catalog',{id,metadata});
      window.dispatchEvent(new Event('evidence:documents-changed'));
      window.dispatchEvent(new Event('evidence:tables-changed'));
      $('catalog-message').textContent='已保存。历史分析继续保留当时的证据。';
    } catch(error) { $('catalog-message').textContent=error.message; } finally { button.disabled=false; }
  });
  document.getElementById('refresh-button').addEventListener('click',()=>list().catch(e=>$('catalog-message').textContent=e.message));
  window.addEventListener('evidence:documents-changed',()=>list().catch(()=>{}));
  window.addEventListener('evidence:tables-changed',()=>list().catch(()=>{}));
  list().catch(e=>$('catalog-message').textContent=e.message);
})();
