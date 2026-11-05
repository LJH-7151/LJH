"""Opt-in, local-only semantic index for document chunks."""
import json
import math
import socket
from urllib.error import URLError, HTTPError
from urllib.request import Request, build_opener, ProxyHandler

from .analysis_service import NoRedirect
from .common import ValidationError

MODEL='bge-small-zh-v1.5'


class SemanticIndex:
    def __init__(self,workspace):
        self.workspace=workspace
        with workspace.store.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS semantic_vectors (
                chunk_id TEXT NOT NULL REFERENCES chunks(id), model TEXT NOT NULL,
                content_sha256 TEXT NOT NULL, vector TEXT NOT NULL, PRIMARY KEY(chunk_id,model)
            )''')

    def _embed(self,texts):
        request=Request('http://127.0.0.1:18771/v1/embeddings',
            data=json.dumps({'model':MODEL,'input':texts,'encoding_format':'float'},ensure_ascii=False).encode('utf-8'),
            headers={'Content-Type':'application/json'},method='POST')
        try:
            with build_opener(ProxyHandler({}),NoRedirect()).open(request,timeout=120) as response:
                raw=response.read(8*1024*1024+1)
            if len(raw)>8*1024*1024: raise ValueError('response too large')
            data=json.loads(raw)['data']
            if not isinstance(data,list) or len(data)!=len(texts): raise ValueError('invalid count')
            if {item['index'] for item in data} != set(range(len(texts))): raise ValueError('invalid indices')
            vectors=[]; dimension=None
            for item in sorted(data,key=lambda item:item['index']):
                vector=item['embedding']
                if not isinstance(vector,list) or not 1<=len(vector)<=16384: raise ValueError('invalid dimension')
                if dimension is not None and len(vector)!=dimension: raise ValueError('inconsistent dimension')
                if any(type(value) not in (int,float) or not math.isfinite(value) for value in vector): raise ValueError('invalid vector')
                norm=math.sqrt(sum(value*value for value in vector))
                if not math.isfinite(norm) or norm==0: raise ValueError('invalid norm')
                vectors.append([value/norm for value in vector]); dimension=len(vector)
            return vectors
        except (HTTPError,URLError,socket.timeout,ValueError,KeyError,TypeError,OverflowError):
            raise ValidationError('本地 Embedding 服务不可用或返回无效向量') from None

    def build(self):
        from .common import digest
        with self.workspace.store.connect() as db:
            chunks=db.execute('''SELECT c.id,c.content FROM chunks c
                LEFT JOIN enterprise_metadata m ON m.document_id=c.document_id WHERE COALESCE(m.archived,0)=0 ORDER BY c.rowid''').fetchall()
        processed=0
        for offset in range(0,len(chunks),32):
            batch=chunks[offset:offset+32]
            texts=[row['content'][:12000] for row in batch]
            vectors=self._embed(texts)
            with self.workspace.store.connect() as db:
                db.executemany('INSERT OR REPLACE INTO semantic_vectors VALUES (?,?,?,?)',
                    [(row['id'],MODEL,digest(text.encode('utf-8')),json.dumps(vector)) for row,text,vector in zip(batch,texts,vectors)])
            processed+=len(batch)
        return {'indexed':processed,'model':MODEL}

    def search(self,question,limit=20):
        if not isinstance(question,str) or not question.strip() or len(question)>2000:
            raise ValidationError('请输入1至2000字符的查询')
        if type(limit) is not int or not 1<=limit<=50: raise ValidationError('返回数量无效')
        vector=self._embed([question])[0]
        with self.workspace.store.connect() as db:
            rows=db.execute('''SELECT v.vector,c.id,c.document_id,c.content,c.start_line,c.end_line,
                 l.location AS explicit_location,d.title,u.sha256,m.payload AS metadata_json FROM semantic_vectors v
                 JOIN chunks c ON c.id=v.chunk_id JOIN documents d ON d.id=c.document_id
                 JOIN uploads u ON u.id=d.upload_id LEFT JOIN chunk_locations l ON l.chunk_id=c.id
                 LEFT JOIN enterprise_metadata m ON m.document_id=d.id
                 WHERE v.model=? AND COALESCE(m.archived,0)=0''',(MODEL,)).fetchall()
        scored=[]
        for row in rows:
            candidate=json.loads(row['vector'])
            if len(candidate)!=len(vector): continue
            score=sum(a*b for a,b in zip(vector,candidate))
            start,end=row['start_line'],row['end_line']
            location=row['explicit_location'] or (f'第{start}行' if start==end else f'第{start}–{end}行')
            scored.append({'id':row['id'],'document_id':row['document_id'],'title':row['title'],
                           'sha256':row['sha256'],'location':location,'content':row['content'],'score':score,
                           'metadata':json.loads(row['metadata_json']) if row['metadata_json'] else {}})
        return sorted(scored,key=lambda item:item['score'],reverse=True)[:limit]
