(() => {
  'use strict';
  const $=id=>document.getElementById(id),token=document.querySelector('meta[name="local-token"]').content;
  async function post(path,data) {
    const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Local-Token':token},body:JSON.stringify(data)});
    const payload=await response.json(); if(!response.ok) throw new Error(payload.error || '操作失败'); return payload;
  }
  async function history(id) {
    const response=await fetch('/api/ledger/history'); const payload=await response.json();
    const select=$('ledger-history'); select.replaceChildren();
    const blank=document.createElement('option'); blank.value=''; blank.textContent='选择快照'; select.append(blank);
    for(const item of payload.snapshots) { const option=document.createElement('option'); option.value=item.id; option.textContent=`${item.start} 至 ${item.end}：${item.net} 元`; select.append(option); }
    if(id) select.value=id;
  }
  $('ledger-history').addEventListener('change',async event=>{
    if(!event.target.value) return;
    try { const response=await fetch('/api/ledger/sources?id='+encodeURIComponent(event.target.value)); const payload=await response.json();
      if(!response.ok) throw new Error(payload.error || '来源读取失败');
      const container=$('ledger-sources'); container.replaceChildren();
      for(const row of payload.records.slice(0,100)) { const item=document.createElement('p');
        item.textContent=`${row.kind} ${JSON.stringify(row.values)}；来源 ${row.origins.map(o=>o.location).join('、')} `;
        for(const origin of row.origins.filter(o=>o.source_sha256)) { const link=document.createElement('a'); link.href='/api/ledger/original?id='+encodeURIComponent(origin.id); link.textContent='下载批次原件 '; item.append(link); }
        container.append(item); }
      $('ledger-message').textContent=`关联 ${payload.records.length} 条版本记录，页面最多显示100条。`;
      $('ledger-export').href='/api/ledger/export?id='+encodeURIComponent(event.target.value); $('ledger-export').hidden=false;
    } catch(error) { $('ledger-message').textContent=error.message; }
  });
  $('ledger-recompute').addEventListener('click',async()=>{
    const id=$('ledger-history').value; if(!id) { $('ledger-message').textContent='请先选择快照。'; return; }
    try { const response=await fetch('/api/ledger/recompute?id='+encodeURIComponent(id)); const result=await response.json();
      if(!response.ok) throw new Error(result.error || '复算失败');
      $('ledger-message').textContent=`复算${result.matches?'一致':'不一致'}：支付 ${result.paid}，退款 ${result.refunds}，净额 ${result.net} 元。`;
    } catch(error) { $('ledger-message').textContent=error.message; }
  });
  function encode(buffer) { const bytes=new Uint8Array(buffer); let text=''; for(let i=0;i<bytes.length;i+=8192) text+=String.fromCharCode(...bytes.subarray(i,i+8192)); return btoa(text); }
  $('ledger-import').addEventListener('submit',async event=>{
    event.preventDefault(); const button=event.submitter; button.disabled=true;
    try { const file=$('ledger-file').files[0]; if(!file || file.size>24*1024*1024) throw new Error('请选择不超过24 MiB的表格');
      const result=await post('/api/ledger/import',{kind:$('ledger-kind').value,namespace:$('ledger-namespace').value,
        content:encode(await file.arrayBuffer()),name:file.name,header_row:Number($('ledger-header').value),
        sheet_name:$('ledger-sheet').value || null,allow_update:$('ledger-update').checked});
      $('ledger-message').textContent=`新增 ${result.added}，重复 ${result.duplicate}，更新 ${result.updated}。`;
    } catch(error) { $('ledger-message').textContent=error.message; } finally { button.disabled=false; }
  });
  $('ledger-calculate').addEventListener('submit',async event=>{
    event.preventDefault(); const button=event.submitter; button.disabled=true;
    try { const result=await post('/api/ledger/calculate',{start:$('ledger-start').value,end:$('ledger-end').value,refund_cutoff:$('ledger-cutoff').value,
      refund_mode:$('ledger-refund-mode').value,namespace:$('ledger-filter-namespace').value,skus:$('ledger-skus').value.split(',').map(x=>x.trim()).filter(Boolean),
      baseline_start:$('ledger-baseline-start').value || null,baseline_end:$('ledger-baseline-end').value || null});
      $('ledger-message').textContent=`支付 ${result.paid} 元，退款 ${result.refunds} 元，净额 ${result.net} 元；订单 ${result.order_count} 笔，客单价 ${result.average_order_value ?? '不可计算'}，较基准变化 ${result.growth_percent ?? '不可计算'}%。快照 ${result.id}。`;
      await history(result.id);
    } catch(error) { $('ledger-message').textContent=error.message; } finally { button.disabled=false; }
  });
  history().catch(error=>{ $('ledger-message').textContent=error.message; });
})();
