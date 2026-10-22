"""Bounded provider-compatible JSON response; no tools, remote code, document or key logging."""
import json
import httpx
from pydantic import ValidationError
from app.extraction_model import ExtractionError
from app.storage import sha256


def request_json(config,secret,system,content,schema,validator,request_key):
    response_format={"type":"json_object"}
    if config["output_mode"]=="json_schema":
        response_format={"type":"json_schema","json_schema":{"name":"grounded_review","strict":True,"schema":schema}}
    body={"model":config["model"],"messages":[{"role":"system","content":system},
        {"role":"user","content":json.dumps(content,ensure_ascii=False)}],"response_format":response_format,
        "store":False,config["token_parameter"]:config["max_output_tokens"]}
    try:
        with httpx.Client(timeout=config["timeout_seconds"],trust_env=False,follow_redirects=False) as client:
            with client.stream("POST",config["base_url"]+"/chat/completions",json=body,
                headers={"Authorization":"Bearer "+secret.get_secret_value(),"Idempotency-Key":request_key}) as response:
                if response.status_code==429 or response.status_code>=500:
                    raise ExtractionError("MODEL_TRANSIENT","模型暂不可用，将有限重试。",True)
                if response.status_code!=200:raise ExtractionError("MODEL_HTTP_ERROR","模型拒绝请求，请检查配置和结构化输出支持。")
                data=bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data)>1024*1024:raise ExtractionError("MODEL_OUTPUT_LIMIT","模型响应过大，已拒绝处理。")
        envelope=json.loads(data);choice=envelope["choices"][0]
        if choice.get("finish_reason")!="stop" or choice["message"].get("refusal"):
            raise ExtractionError("MODEL_INCOMPLETE","模型未完整返回可用结果，请人工处理或缩小输入。")
        output=validator.model_validate_json(choice["message"]["content"])
        usage={k:v for k,v in (envelope.get("usage") or {}).items()
            if k in {"prompt_tokens","completion_tokens","total_tokens"} and type(v) is int and v>=0}
        return {"output":output.model_dump(),"usage":usage,"response_hash":sha256(bytes(data))}
    except ExtractionError:raise
    except (httpx.TimeoutException,httpx.NetworkError):
        raise ExtractionError("MODEL_TRANSIENT","模型连接超时或中断，将有限重试。",True) from None
    except (httpx.HTTPError,ValueError,TypeError,KeyError,IndexError,ValidationError):
        raise ExtractionError("MODEL_OUTPUT_INVALID","模型返回格式或引用约定不符合要求，未发布结果。") from None
