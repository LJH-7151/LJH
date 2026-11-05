(() => {
  'use strict';
  const button=document.getElementById('check-services'), message=document.getElementById('services-status');
  button.addEventListener('click',async()=>{
    button.disabled=true; message.textContent='正在检查…';
    try { const response=await fetch('/api/services'); if(!response.ok) throw new Error('检查失败'); const result=await response.json();
      message.textContent=`千问：${result.llm.available?'在线':'未连接'}；Embedding：${result.embedding.available?'在线':'未连接'}。在线状态不代表生成质量已验收。`;
    } catch(error) { message.textContent=error.message; } finally { button.disabled=false; }
  });
})();
