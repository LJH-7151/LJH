(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const token = document.querySelector('meta[name="local-token"]').content;
  let tables = [];
  const message = (text) => { $('table-message').textContent = text; };
  async function request(path, data) {
    const options = data === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json','X-Local-Token':token}, body:JSON.stringify(data)};
    const response = await fetch(path, options);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || '操作失败');
    return payload;
  }
  function option(value, label) {
    const item = document.createElement('option'); item.value = value; item.textContent = label; return item;
  }
  function columns() {
    const selected = tables.find((item) => item.id === $('table-select').value);
    $('table-original').hidden=!selected;
    if(selected) $('table-original').href='/api/table-original?id='+encodeURIComponent(selected.id);
    $('table-measure').replaceChildren(); $('table-group').replaceChildren(option('', '不分组'));
    $('table-filter-column').replaceChildren(option('', '不筛选'));
    $('table-extra-filters').replaceChildren();
    for (const column of selected?.columns || []) {
      $('table-measure').append(option(column, column)); $('table-group').append(option(column, column));
      $('table-filter-column').append(option(column, column));
    }
  }
  async function refresh() {
    const current = $('table-select').value;
    tables = (await request('/api/tables')).tables.filter(item=>!item.metadata.archived);
    $('table-select').replaceChildren(...tables.map((item) => option(item.id, `${item.name}（${item.row_count}行）`)));
    if (tables.some((item) => item.id === current)) $('table-select').value = current;
    columns();
  }
  function base64(buffer) {
    const bytes = new Uint8Array(buffer); let result = '';
    for (let i=0; i<bytes.length; i+=8192) result += String.fromCharCode(...bytes.subarray(i,i+8192));
    return btoa(result);
  }
  async function history(id) {
    const items=(await request('/api/table-results')).results;
    $('table-history').replaceChildren(option('','选择统计记录'),...items.map(item=>option(item.id,`${item.created_at} · ${item.measure || '行数'} · ${item.operation}`)));
    if(id) $('table-history').value=id;
  }
  function render(result) {
    const container = $('table-results'); container.replaceChildren();
    for (const group of result.groups) {
      const line = document.createElement('p');
      line.textContent = `${group.group}：${group.value}（${group.count} 行；来源：${group.source_locations.slice(0, 20).join('、')}${group.source_locations.length > 20 ? '等' : ''}）`;
      container.append(line);
    }
    if(result.groups.length && result.groups.length<=30) {
      const chart=document.createElement('div'); chart.setAttribute('aria-label','分组统计图');
      const maximum=Math.max(...result.groups.map(group=>Math.abs(Number(group.value))),1);
      for(const group of result.groups) {
        const row=document.createElement('div'), label=document.createElement('span'), bar=document.createElement('span');
        label.textContent=`${group.group} ${group.value} `; bar.textContent=' '; bar.style.display='inline-block';
        bar.style.height='0.7em'; bar.style.width=`${Math.min(100,Math.abs(Number(group.value))/maximum*100)}%`;
        bar.style.maxWidth='240px'; bar.style.background=Number(group.value)<0?'#b05239':'#2b6d61';
        row.append(label,bar); chart.append(row);
      }
      container.append(chart);
    }
    const download=document.createElement('a'); download.textContent='下载 Excel 统计及来源位置';
    download.href='/api/table-export?id='+encodeURIComponent(result.id); container.append(download);
    message(`筛选 ${result.selected} 行；空值 ${result.missing}，无效值 ${result.invalid}。结果按原列单位计算。`);
  }
  $('table-history').addEventListener('change',async event=>{
    if(!event.target.value) return;
    try { render(await request('/api/table-result?id='+encodeURIComponent(event.target.value))); }
    catch(error) { message(error.message); }
  });
  window.addEventListener('evidence:open-table-source',async event=>{
    const source=event.detail;
    try {
      const row=await request('/api/table-source?id='+encodeURIComponent(source.tableId)+'&location='+encodeURIComponent(source.location));
      const box=$('table-preview'); box.replaceChildren(); const line=document.createElement('p');
      line.textContent=`${row.name} · ${row.location}：`+Object.entries(row.values).map(([key,value])=>`${key}=${value}`).join('；');
      box.append(line); box.scrollIntoView({block:'center'}); message('已定位来源行，原件哈希：'+row.sha256);
    } catch(error) { message(error.message); }
  });
  window.addEventListener('evidence:open-calculation',async event=>{
    try { render(await request('/api/table-result?id='+encodeURIComponent(event.detail.id))); $('table-results').scrollIntoView({block:'center'}); }
    catch(error) { message(error.message); }
  });
  $('table-select').addEventListener('change', columns);
  $('table-preview-button').addEventListener('click',async event=>{
    event.target.disabled=true;
    try {
      const table=await request('/api/table?id='+encodeURIComponent($('table-select').value));
      const box=$('table-preview'); box.replaceChildren();
      for(const [name,stats] of Object.entries(table.profile)) {
        const p=document.createElement('p'); p.textContent=`${name}：${stats.type==='number'?'数值列':'文本或编号列'}，非空 ${stats.present}，空值 ${stats.missing}，可识别数值 ${stats.numeric}`; box.append(p);
      }
      for(const row of table.rows) { const p=document.createElement('p');
        p.textContent=`${row.location}：`+Object.entries(row.values).map(([key,value])=>`${key}=${String(value).slice(0,200)}`).join('；'); box.append(p); }
      message(`共 ${table.row_count} 行，预览前 ${table.rows.length} 行。`);
    } catch(error) { message(error.message); } finally { event.target.disabled=false; }
  });
  $('table-add-filter').addEventListener('click',()=>{
    const container=$('table-extra-filters');
    if(container.children.length>=7) { message('最多使用8个筛选条件。'); return; }
    const row=document.createElement('div'); const column=$('table-filter-column').cloneNode(true);
    column.removeAttribute('id'); column.setAttribute('aria-label','筛选列');
    const operation=$('table-filter-op').cloneNode(true); operation.removeAttribute('id'); operation.setAttribute('aria-label','筛选方式');
    const value=document.createElement('input'); value.maxLength=300; value.setAttribute('aria-label','筛选值');
    const remove=document.createElement('button'); remove.type='button'; remove.textContent='删除条件'; remove.addEventListener('click',()=>row.remove());
    row.append(column,operation,value,remove); container.append(row);
  });
  $('table-upload').addEventListener('submit', async (event) => {
    event.preventDefault(); const file = $('table-file').files[0];
    if (!file || file.size > 24*1024*1024) { message('请选择不超过24 MiB的表格。'); return; }
    const button = event.submitter; button.disabled = true; message('正在导入…');
    try {
      const result = await request('/api/tables', {name:file.name, content:base64(await file.arrayBuffer()),
        header_row:Number($('table-header').value), sheet_name:$('table-sheet').value || null});
      await refresh(); $('table-select').value = result.id; columns(); window.dispatchEvent(new Event('evidence:tables-changed')); message(`导入成功，共 ${result.row_count} 行。`);
    } catch (error) { message(error.message); } finally { button.disabled = false; }
  });
  $('table-query').addEventListener('submit', async (event) => {
    event.preventDefault(); const button = event.submitter; button.disabled = true; message('正在计算…');
    try {
      const operation = $('table-operation').value;
      const filter=$('table-filter-column').value;
      const filters=filter ? [{column:filter,operator:$('table-filter-op').value,value:$('table-filter-value').value}] : [];
      for(const row of $('table-extra-filters').children) {
        const [column,operator,value]=row.children;
        if(column.value) filters.push({column:column.value,operator:operator.value,value:value.value});
      }
      const result = await request('/api/table-calculate', {table_id:$('table-select').value, operation,
        measure:operation === 'count' ? null : $('table-measure').value, group_by:$('table-group').value || null,
        filters});
      render(result); await history(result.id);
      window.dispatchEvent(new Event('evidence:tables-changed'));
    } catch (error) { message(error.message); } finally { button.disabled = false; }
  });
  refresh().catch((error) => message(error.message));
  history().catch((error) => message(error.message));
})();
