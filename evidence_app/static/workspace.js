(() => {
  'use strict';
  const main = document.querySelector('main');
  const nav = document.querySelector('.workspace-nav');
  const definitions = [
    ['overview','经营概览'], ['analysis','问题分析'], ['data','数据探索'],
    ['search','联合查询'], ['library','资料库'], ['history','分析档案'], ['settings','服务设置']
  ];
  nav.replaceChildren();
  const views = {};
  for (const [id, label] of definitions) {
    const link = document.createElement('a');
    link.href = '#' + id; link.textContent = label; link.dataset.view = id;
    nav.append(link);
    const view = document.createElement('div'); view.className = 'workspace-view'; view.dataset.view = id;
    view.hidden = true; main.append(view); views[id] = view;
  }
  const move = (id, selector) => { const node = document.querySelector(selector); if (node) views[id].append(node); };
  move('settings', '.intro');
  move('library', '.upload-panel');
  move('library', '.workspace');
  move('library', '[aria-labelledby="catalog-title"]');
  move('library', '[aria-labelledby="ocr-title"]');
  move('analysis', '[aria-labelledby="analysis-title"]');
  move('data', '[aria-labelledby="table-title"]');
  move('data', '[aria-labelledby="ledger-title"]');
  move('search', '[aria-labelledby="search-title"]');
  move('search', '[aria-labelledby="semantic-title"]');
  views.overview.innerHTML = `<div class="page-intro"><div><p class="eyebrow">ENTERPRISE INTELLIGENCE / 企业经营分析</p><h1>经营全景</h1><p>从企业资料与统计结果出发，探索经营变化。</p></div><a class="button button-primary" href="#analysis">＋ 发起分析</a></div>
    <div class="overview-metrics"><a href="#library"><span>资料版本</span><strong id="overview-docs">—</strong><small>已导入资料</small></a><a href="#data"><span>数据表</span><strong id="overview-tables">—</strong><small>可用于统计</small></a><a href="#data"><span>统计结果</span><strong id="overview-results">—</strong><small>已保存计算</small></a><a href="#history"><span>分析档案</span><strong id="overview-analyses">—</strong><small>已保存分析</small></a></div>
    <div class="overview-grid"><section class="panel overview-chart"><div class="panel-heading"><div><h2>统计结果概览</h2><p>选择已保存的统计，查看分组构成</p></div><a href="#data">探索数据 →</a></div><label class="overview-select">统计结果<select id="overview-result"></select></label><div id="overview-visual" class="overview-visual"></div><p id="overview-chart-status" class="overview-hint"></p></section><section class="panel overview-side"><p class="eyebrow">WORKSPACE / 工作空间</p><h2>从问题开始分析</h2><p>关联资料与统计结果，形成可追溯的经营分析。</p><a class="button button-primary" href="#analysis">提出问题 →</a><div class="quick-links"><a href="#search">检索原文 <span>→</span></a><a href="#library">管理企业资料 <span>→</span></a><a href="#history">查看分析档案 <span>→</span></a></div></section></div>`;
  views.history.innerHTML = '<div class="page-intro"><div><p class="eyebrow">ENTERPRISE INTELLIGENCE / 企业经营分析</p><h1>分析档案</h1><p>查看已保存的分析与核对记录。</p></div><a class="button button-primary" href="#analysis">发起分析 →</a></div><section class="panel"><h2>历史分析</h2><div id="overview-history" class="history-list"></div></section>';
  const titles = {analysis:['问题分析','提出经营问题，结合资料和统计结果进行分析。'],data:['数据探索','导入数据，按条件筛选、分组并追溯来源。'],search:['联合查询','检索企业资料并查看原文依据。'],library:['资料库','管理企业原件、版本和识别复核。'],settings:['服务与工作空间','查看本地服务状态并管理工作空间。']};
  for (const [id, [title, desc]] of Object.entries(titles)) {
    const intro = document.createElement('div'); intro.className = 'page-intro';
    const content = document.createElement('div'); const eyebrow = document.createElement('p'); eyebrow.className='eyebrow'; eyebrow.textContent='ENTERPRISE INTELLIGENCE / 企业经营分析';
    const h = document.createElement('h1'); h.textContent=title; const p = document.createElement('p'); p.textContent=desc; content.append(eyebrow,h,p); intro.append(content); views[id].prepend(intro);
  }
  async function request(path) { const response=await fetch(path); if(!response.ok) throw Error('工作空间数据读取失败'); return response.json(); }
  let results = [];
  function chart() {
    const box=document.querySelector('#overview-visual'), message=document.querySelector('#overview-chart-status'); box.replaceChildren();
    const item=results.find(x=>x.id===document.querySelector('#overview-result').value);
    if(!item) { message.textContent='暂无统计结果，请先在数据探索中创建统计。'; return; }
    const groups=(item.groups||[]).filter(g=>Number.isFinite(Number(g.value))).slice(0,12);
    if(!groups.length){message.textContent='该统计暂无可展示的分组数据。';return;}
    message.textContent=`${item.measure || '记录数'} · ${item.operation || '统计'} · 展示前 ${groups.length} 组`;
    const ns='http://www.w3.org/2000/svg', svg=document.createElementNS(ns,'svg'); svg.setAttribute('viewBox',`0 0 800 ${Math.max(180,groups.length*42+20)}`); svg.setAttribute('role','img'); svg.setAttribute('aria-label','统计分组图');
    const max=Math.max(...groups.map(g=>Math.abs(Number(g.value))),1);
    groups.forEach((g,i)=>{const y=30+i*42; const label=document.createElementNS(ns,'text');label.setAttribute('x','0');label.setAttribute('y',String(y));label.textContent=String(g.group).slice(0,16);svg.append(label); const bar=document.createElementNS(ns,'rect');bar.setAttribute('x','145');bar.setAttribute('y',String(y-15));bar.setAttribute('width',String(Math.max(2,500*Math.abs(Number(g.value))/max)));bar.setAttribute('height','15');bar.setAttribute('rx','6');bar.setAttribute('class','chart-bar');svg.append(bar);const val=document.createElementNS(ns,'text');val.setAttribute('x','655');val.setAttribute('y',String(y));val.textContent=Number(g.value).toLocaleString('zh-CN',{maximumFractionDigits:2});svg.append(val);}); box.append(svg);
  }
  async function refreshOverview() {
    try {
      const [docs,tables,stats,analyses]=await Promise.all(['/api/documents','/api/tables','/api/table-results','/api/analyses'].map(request));
      document.querySelector('#overview-docs').textContent=docs.documents.length; document.querySelector('#overview-tables').textContent=tables.tables.length;
      results=stats.results; document.querySelector('#overview-results').textContent=results.length; document.querySelector('#overview-analyses').textContent=analyses.analyses.length;
      const select=document.querySelector('#overview-result'), old=select.value; select.replaceChildren();
      for(const item of results){const option=document.createElement('option'); option.value=item.id; option.textContent=`${item.measure||'记录数'} · ${item.operation||'统计'} · ${item.created_at||''}`;select.append(option);}
      if(results.some(x=>x.id===old)) select.value=old;
      if(select.value) { const detail=await request('/api/table-result?id='+encodeURIComponent(select.value)); results=results.map(x=>x.id===detail.id?detail:x); }
      chart();
      const history=document.querySelector('#overview-history'); history.replaceChildren();
      if(!analyses.analyses.length) history.textContent='暂无分析档案。';
      for(const item of analyses.analyses){const row=document.createElement('button');row.type='button';row.className='history-row'; const name=document.createElement('strong');name.textContent=item.question||'分析档案'; const date=document.createElement('span');date.textContent=item.created_at||'';row.append(name,date);row.addEventListener('click',()=>{location.hash='analysis';const select=document.querySelector('#analysis-history'); select.value=item.id;select.dispatchEvent(new Event('change'));});history.append(row);}
    } catch(error) {document.querySelector('#overview-chart-status').textContent=error.message;}
  }
  document.querySelector('#overview-result').addEventListener('change',async e=>{try{const detail=await request('/api/table-result?id='+encodeURIComponent(e.target.value));results=results.map(x=>x.id===detail.id?detail:x);chart();}catch(error){document.querySelector('#overview-chart-status').textContent=error.message;}});
  function show() {const id=location.hash.slice(1);const current=views[id]?id:'overview';for(const [key,view] of Object.entries(views))view.hidden=key!==current;for(const link of nav.querySelectorAll('a')){link.classList.toggle('current',link.dataset.view===current);if(link.dataset.view===current)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');}if(current==='overview'||current==='history')refreshOverview();window.scrollTo(0,0);}
  addEventListener('hashchange',show);
  document.querySelector('#search-results').addEventListener('click',event=>{if(event.target.closest('button')){location.hash='library';show();}},true);
  for(const event of ['evidence:open-calculation','evidence:open-table-source']) window.addEventListener(event,()=>{location.hash='data';show();},true);
  window.addEventListener('evidence:open-source',()=>{location.hash='library';show();},true);
  show();
})();
