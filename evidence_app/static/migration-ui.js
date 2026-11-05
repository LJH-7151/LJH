(() => {
  'use strict';
  fetch('/api/migration').then(response=>response.json()).then(data=>{
    if(!data.report) return;
    const notice=document.getElementById('migration-notice');
    notice.textContent=`旧版资料迁移：${data.report.documents_imported} 份文档、${data.report.tables_imported} 张表、${data.report.analyses_imported || 0} 份分析档案、${data.report.queries_imported || 0} 份统计记录；待复核 ${data.report.skipped.length} 项，未转换统计 ${(data.report.queries_skipped || []).length} 项。原始数据库快照仍保留。`;
    notice.hidden=false; document.getElementById('migration-download').hidden=false;
  }).catch(()=>{});
})();
