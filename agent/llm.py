import httpx
import json
from datetime import datetime


class LLMClient:
    def __init__(self, config):
        self.backend = config.get("llm_backend", "local")
        self.url = config.get("llm_url", "http://localhost:8082")
        self.api_key = config.get("llm_api_key", "")
        self.model = config.get("llm_model", "")
        self.debug_logs = []
        self.max_logs = 50

    async def chat(self, messages, temperature=0.7, max_tokens=2048):
        log_entry = {
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "backend": self.backend,
            "request": messages,
            "response": None,
            "raw_response": None,
            "error": None
        }

        try:
            if self.backend == "local":
                result, raw = await self._call_llama_server(messages, temperature, max_tokens)
            elif self.backend == "ollama":
                result, raw = await self._call_ollama(messages, temperature, max_tokens)
            elif self.backend == "openai":
                result, raw = await self._call_openai(messages, temperature, max_tokens)
            else:
                result, raw = "未配置 LLM 后端", {}

            log_entry["response"] = result
            log_entry["raw_response"] = raw
        except Exception as e:
            log_entry["error"] = str(e)
            result = f"调用失败: {e}"

        self.debug_logs.append(log_entry)
        if len(self.debug_logs) > self.max_logs:
            self.debug_logs.pop(0)

        return result

    def _headers(self):
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _payload(self, messages, temperature, max_tokens):
        payload = {"messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        if self.model:
            payload["model"] = self.model
        return payload

    async def _post(self, url, payload):
        """发起请求，出错时抛出带状态码与响应体的异常，便于诊断"""
        async with httpx.AsyncClient(timeout=120.0, headers=self._headers()) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code >= 400:
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:500]}")
            return resp.json()

    def _extract_content(self, raw):
        """兼容 content 为字符串或数组（多段文本/推理模型）两种情况"""
        try:
            msg = raw["choices"][0]["message"]
        except Exception as e:
            raise RuntimeError(f"返回格式异常: {e}，响应={str(raw)[:500]}")
        content = msg.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict):
                    text = part.get("text")
                    if text:
                        parts.append(str(text))
                elif part:
                    parts.append(str(part))
            if parts:
                return "\n".join(parts)
        raise RuntimeError(f"未找到可用内容: {str(content)[:300]}")

    async def _call_llama_server(self, messages, temperature, max_tokens):
        raw = await self._post(f"{self.url}/v1/chat/completions", self._payload(messages, temperature, max_tokens))
        return self._extract_content(raw), raw

    async def _call_ollama(self, messages, temperature, max_tokens):
        payload = self._payload(messages, temperature, max_tokens)
        payload["stream"] = False
        payload["options"] = {"temperature": temperature, "num_predict": max_tokens}
        raw = await self._post(f"{self.url}/api/chat", payload)
        content = raw["message"]["content"]
        return content, raw

    async def _call_openai(self, messages, temperature, max_tokens):
        raw = await self._post(f"{self.url}/chat/completions", self._payload(messages, temperature, max_tokens))
        return self._extract_content(raw), raw

    async def list_models(self, url=None, api_key=None, backend=None):
        """拉取服务商可用的模型列表"""
        b = backend or self.backend
        u = url or self.url
        key = self.api_key if api_key is None else api_key
        headers = {}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        try:
            async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
                if b == "ollama":
                    resp = await client.get(f"{u}/api/tags")
                    data = resp.json()
                    return {"models": [m.get("name") for m in data.get("models", [])], "error": None}
                elif b == "local":
                    resp = await client.get(f"{u}/v1/models")
                    data = resp.json()
                    return {"models": [m.get("id") for m in data.get("data", [])], "error": None}
                else:
                    resp = await client.get(f"{u}/models")
                    data = resp.json()
                    return {"models": [m.get("id") for m in data.get("data", [])], "error": None}
        except Exception as e:
            return {"models": [], "error": str(e)}

    def get_logs(self):
        return self.debug_logs

    def clear_logs(self):
        self.debug_logs = []
