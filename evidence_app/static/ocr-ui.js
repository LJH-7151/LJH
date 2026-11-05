(() => {
  'use strict';
  const $=id=>document.getElementById(id), token=document.querySelector('meta[name="local-token"]').content;
  let drafts=[];
  async function request(path,data) {
    const response=await fetch(path,data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Local-Token':token},body:JSON.stringify(data)});
    const payload=await response.json(); if(!response.ok) throw new Error(payload.error || '操作失败'); return payload;
  }
  function select() {
    const draft=drafts.find(d=>d.id===$('ocr-select').value); $('ocr-text').value=draft?.recognized || '';
    $('ocr-original').hidden=!draft; $('ocr-confirm').disabled=!draft || draft.state!=='pending';
    if(draft) $('ocr-original').href='/api/ocr-original?id='+encodeURIComponent(draft.id);
  }
  async function refresh(id) {
    drafts=(await request('/api/ocr')).drafts; $('ocr-select').replaceChildren();
    for(const draft of drafts) { const option=document.createElement('option'); option.value=draft.id; option.textContent=`${draft.name} · ${draft.state==='pending'?'待复核':'已确认'}`; $('ocr-select').append(option); }
    if(id) $('ocr-select').value=id; select();
  }
  function base64(buffer) {
    const bytes=new Uint8Array(buffer); let text='';
    for(let i=0;i<bytes.length;i+=8192) text+=String.fromCharCode(...bytes.subarray(i,i+8192));
    return btoa(text);
  }
  $('ocr-select').addEventListener('change',select);
  $('ocr-upload').addEventListener('submit',async event=>{
    event.preventDefault(); const file=$('ocr-file').files[0], button=event.submitter; button.disabled=true; $('ocr-message').textContent='正在识别…';
    try { if(!file || file.size>24*1024*1024) throw new Error('请选择不超过24 MiB的图片');
      const result=await request('/api/ocr',{name:file.name,content:base64(await file.arrayBuffer())});
      await refresh(result.id); $('ocr-message').textContent='请对照原图核对并修正。';
    } catch(error) { $('ocr-message').textContent=error.message; } finally { button.disabled=false; }
  });
  $('ocr-confirm').addEventListener('click',async event=>{
    event.target.disabled=true;
    try { const result=await request('/api/ocr-confirm',{id:$('ocr-select').value,text:$('ocr-text').value});
      await refresh(result.id); window.dispatchEvent(new Event('evidence:documents-changed')); $('ocr-message').textContent='已确认并加入资料库，请点击资料库刷新。';
    } catch(error) { $('ocr-message').textContent=error.message; event.target.disabled=false; }
  });
  refresh().catch(error=>$('ocr-message').textContent=error.message);
})();
