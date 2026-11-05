"""Read-only health checks for the two fixed loopback model services."""
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, ProxyHandler
from .analysis_service import NoRedirect


def status():
    checks=[('llm','http://127.0.0.1:18770/v1/models'),('embedding','http://127.0.0.1:18771/health')]
    result={}
    for name,url in checks:
        try:
            with build_opener(ProxyHandler({}),NoRedirect()).open(Request(url),timeout=2) as response:
                data=json.loads(response.read(1024*1024))
            ok=any(item.get('id')=='qwen2.5-1.5b-instruct' for item in data.get('data',[])) if name=='llm' else data.get('model')=='bge-small-zh-v1.5'
            result[name]={'available':bool(ok)}
        except (HTTPError,URLError,TimeoutError,ValueError,TypeError,AttributeError):
            result[name]={'available':False}
    return result
