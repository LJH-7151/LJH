"""Run user-supplied local model files; never downloads models or credentials."""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--llama-server',type=Path,required=True)
    parser.add_argument('--llm',type=Path,required=True)
    parser.add_argument('--embedding-dir',type=Path,required=True)
    args=parser.parse_args()
    for path in (args.llama_server,args.llm,args.embedding_dir/'model_quantized.onnx',args.embedding_dir/'tokenizer.json'):
        if not path.is_file(): parser.error('Required model or executable is missing: '+str(path))
    flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    commands=[
        [str(args.llama_server),'--model',str(args.llm),'--alias','qwen2.5-1.5b-instruct',
         '--host','127.0.0.1','--port','18770','--ctx-size','8192','--parallel','1',
         '--threads','2','--threads-batch','2','--batch-size','32','--ubatch-size','16',
         '--n-predict','1200','--no-webui','--no-warmup','--no-repack','--cache-ram','0','--log-disable'],
        [sys.executable,str(Path(__file__).with_name('serve_embeddings.py')),'--model-dir',str(args.embedding_dir)],
    ]
    children=[]
    try:
        for command in commands:
            children.append(subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                                             stderr=subprocess.DEVNULL,creationflags=flags))
        print('本地模型进程已启动；按 Ctrl+C 停止本次启动的进程。',flush=True)
        while True:
            for child in children:
                if child.poll() is not None: raise RuntimeError(f'本地模型进程退出，代码 {child.returncode}；请检查文件与端口。')
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for child in children:
            if child.poll() is None: child.terminate()
        for child in children:
            try: child.wait(timeout=10)
            except subprocess.TimeoutExpired: child.kill(); child.wait()


if __name__=='__main__': main()
