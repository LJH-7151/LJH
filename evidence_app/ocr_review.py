"""Image OCR stays in a draft until a human explicitly confirms the text."""
import json
import os
import subprocess
from pathlib import Path

from .common import ValidationError, digest, now, uid


class OcrReview:
    def __init__(self, workspace):
        self.workspace=workspace
        with workspace.store.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS ocr_drafts (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, sha256 TEXT NOT NULL,
                recognized TEXT NOT NULL, language TEXT NOT NULL, state TEXT NOT NULL,
                document_id TEXT, created_at TEXT NOT NULL
            )''')

    def recognize(self, name, content):
        if os.name!='nt': raise ValidationError('图片 OCR 需要 Windows OCR')
        if not isinstance(name,str) or not name.lower().endswith(('.png','.jpg','.jpeg','.bmp','.tif','.tiff','.pdf')) or '/' in name or '\\' in name or len(name)>160:
            raise ValidationError('图片或 PDF 文件名无效')
        if not isinstance(content,bytes) or not content or len(content)>24*1024*1024:
            raise ValidationError('图片为空或超过24 MiB')
        checksum=digest(content)
        path=self.workspace.store.blob(checksum)
        if not path.exists():
            try:
                with path.open('xb') as stream: stream.write(content)
            except FileExistsError: pass
        if digest(path.read_bytes()) != checksum: raise RuntimeError('图片完整性校验失败')
        script=Path(__file__).with_name('ocr_pdf.ps1' if name.lower().endswith('.pdf') else 'ocr_image.ps1')
        executable=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
        try:
            output=subprocess.run([str(executable),'-NoProfile','-NonInteractive','-File',str(script),'-Path',str(path)],
                                  capture_output=True,timeout=600 if name.lower().endswith('.pdf') else 120,check=True,creationflags=subprocess.CREATE_NO_WINDOW)
            result=json.loads(output.stdout.decode('utf-8-sig'))
            text=result['text']; language=result['language']
            if not isinstance(text,str) or not text.strip() or len(text)>500000:
                raise ValueError('No usable OCR text')
        except (OSError,ValueError,KeyError,subprocess.SubprocessError):
            raise ValidationError('OCR 不可用或未识别文字，请检查语言包和图片') from None
        item={'id':uid('ocr'),'name':name,'sha256':checksum,'recognized':text,'language':language,'state':'pending','document_id':None,'created_at':now()}
        with self.workspace.store.connect() as db:
            db.execute('INSERT INTO ocr_drafts VALUES (?,?,?,?,?,?,?,?)',tuple(item[k] for k in ('id','name','sha256','recognized','language','state','document_id','created_at')))
        return item

    def list(self):
        with self.workspace.store.connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM ocr_drafts ORDER BY rowid DESC LIMIT 100')]

    def get(self, identifier):
        with self.workspace.store.connect() as db:
            row=db.execute('SELECT * FROM ocr_drafts WHERE id=?',(identifier,)).fetchone()
        if not row: raise LookupError('OCR 草稿不存在')
        return dict(row)

    def confirm(self, identifier, text):
        draft=self.get(identifier)
        if draft['state']!='pending': raise ValidationError('OCR 草稿已经确认')
        if not isinstance(text,str) or not text.strip() or len(text.encode('utf-8'))>2*1024*1024:
            raise ValidationError('请填写有效的复核文字')
        result=self.workspace.upload('OCR-'+identifier+'.txt',text.encode('utf-8'))
        document_id=result['document']['id']
        if not result['duplicate']:
            self.workspace.catalog.update(document_id,{'source':'OCR 已人工复核；原件 SHA-256 '+draft['sha256']})
        with self.workspace.store.connect() as db:
            db.execute("UPDATE ocr_drafts SET state='confirmed',document_id=? WHERE id=? AND state='pending'",(document_id,identifier))
        return self.get(identifier)
