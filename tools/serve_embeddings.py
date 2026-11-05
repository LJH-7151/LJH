"""Serve a local BGE ONNX encoder on loopback; model weights are not included."""
import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

MODEL='bge-small-zh-v1.5'


class Encoder:
    def __init__(self,path):
        self.tokenizer=Tokenizer.from_file(str(path/'tokenizer.json'))
        self.tokenizer.enable_truncation(max_length=512)
        self.tokenizer.enable_padding(pad_id=0,pad_token='[PAD]')
        self.session=ort.InferenceSession(str(path/'model_quantized.onnx'),providers=['CPUExecutionProvider'])
        self.lock=threading.Lock()

    def encode(self,texts):
        with self.lock:
            encoded=self.tokenizer.encode_batch(texts)
            feeds={'input_ids':np.asarray([x.ids for x in encoded],dtype=np.int64),
                   'attention_mask':np.asarray([x.attention_mask for x in encoded],dtype=np.int64),
                   'token_type_ids':np.asarray([x.type_ids for x in encoded],dtype=np.int64)}
            vectors=self.session.run(None,feeds)[0][:,0,:]
        norms=np.linalg.norm(vectors,axis=1,keepdims=True)
        if not np.all(np.isfinite(vectors)) or np.any(norms==0): raise ValueError('invalid vectors')
        return (vectors/norms).tolist()


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def reply(self,status,data):
        body=json.dumps(data,ensure_ascii=False).encode('utf-8')
        self.send_response(status); self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(body))); self.send_header('Cache-Control','no-store')
        self.end_headers(); self.wfile.write(body)
    def allowed(self):
        hosts={f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}
        return self.headers.get('Host') in hosts and not self.headers.get('Origin') and self.headers.get('Sec-Fetch-Site')!='cross-site'
    def do_GET(self):
        if not self.allowed(): self.reply(403,{'error':'本地访问受限'}); return
        if self.path=='/health': self.reply(200,{'model':MODEL,'status':'ok'})
        else: self.reply(404,{'error':'接口不存在'})
    def do_POST(self):
        if not self.allowed(): self.reply(403,{'error':'本地访问受限'}); return
        if self.path!='/v1/embeddings': self.reply(404,{'error':'接口不存在'}); return
        try:
            length=int(self.headers.get('Content-Length','0'))
            if self.headers.get('Transfer-Encoding') or not 0<length<=512*1024: raise ValueError('invalid length')
            data=json.loads(self.rfile.read(length))
            texts=data.get('input'); texts=[texts] if isinstance(texts,str) else texts
            if data.get('model')!=MODEL or data.get('encoding_format','float')!='float' or not isinstance(texts,list) or not 1<=len(texts)<=32 or any(not isinstance(text,str) or not text.strip() or len(text)>12000 for text in texts): raise ValueError('invalid input')
            vectors=self.server.encoder.encode(texts)
            self.reply(200,{'object':'list','model':MODEL,'data':[{'object':'embedding','index':i,'embedding':v} for i,v in enumerate(vectors)]})
        except (ValueError,TypeError,KeyError): self.reply(400,{'error':'输入或模型无效'})
        except Exception: self.reply(500,{'error':'本地向量计算失败'})


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-dir',type=Path,required=True)
    parser.add_argument('--port',type=int,default=18771)
    args=parser.parse_args()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    server.encoder=Encoder(args.model_dir)
    print(f'Local embedding ready: http://127.0.0.1:{args.port}',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()


if __name__=='__main__': main()
