import httpx
import json
from collections import deque
from datetime import datetime


class _StreamRawCollector:
    """流式响应原始分块收集器（调试日志用）。

    流式回复一上来就是几百个小 JSON 分块，全存会撑爆调试日志；
    这里只保留前 80 块 + 后 20 块（开头看系统词回显，结尾看 usage 统计），
    中间用占位标记省略。
    """

    def __init__(self, head=80, tail=20):
        self._head = []
        self._tail = deque(maxlen=tail)
        self._head_limit = head
        self._total = 0
        self.error = None

    def add(self, chunk):
        self._total += 1
        if len(self._head) < self._head_limit:
            self._head.append(chunk)
        else:
            self._tail.append(chunk)

    def fail(self, message):
        self.error = message

    def value(self):
        chunks = list(self._head)
        omitted = self._total - len(self._head) - len(self._tail)
        if omitted > 0:
            chunks.append({"省略": f"中间 {omitted} 块"})
        chunks.extend(self._tail)
        out = {"stream": True, "chunks_total": self._total, "chunks": chunks}
        if self.error:
            out["stream_error"] = self.error
        return out


class LLMClient:
    def __init__(self, config):
        self.backend = config.get("llm_backend", "local")
        # 用 127.0.0.1 而非 localhost：Windows 上 localhost 先解析为 IPv6 ::1，
        # llama-server 只监听 IPv4 时每次连接会白等 ~2 秒超时才回落
        self.url = config.get("llm_url", "http://127.0.0.1:8082")
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

    async def chat_stream(self, messages, temperature=0.7, max_tokens=2048):
        """流式对话：逐段 yield 文本增量。

        llama-server / openai 兼容后端走 SSE（data: {...}，[DONE] 结束）；
        ollama 走 NDJSON（每行一个 JSON，done=true 结束）。
        原始分块同步收集进调试日志（与 chat() 的 raw_response 对应）。
        """
        log_entry = {
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "backend": self.backend,
            "request": messages,
            "response": None,
            "raw_response": None,
            "error": None
        }
        raw = _StreamRawCollector()
        parts = []
        try:
            if self.backend == "ollama":
                gen = self._stream_ollama(messages, temperature, max_tokens, raw)
            elif self.backend in ("local", "openai"):
                gen = self._stream_openai_compat(messages, temperature, max_tokens, raw)
            else:
                async def _unconfigured():
                    yield "未配置 LLM 后端"
                gen = _unconfigured()
            async for delta in gen:
                parts.append(delta)
                yield delta
        except Exception as e:
            log_entry["error"] = str(e)
            raw.fail(str(e))
            raise
        finally:
            log_entry["response"] = "".join(parts)
            log_entry["raw_response"] = raw.value()
            self.debug_logs.append(log_entry)
            if len(self.debug_logs) > self.max_logs:
                self.debug_logs.pop(0)

    async def _stream_openai_compat(self, messages, temperature, max_tokens,
                                    raw=None):
        payload = self._payload(messages, temperature, max_tokens)
        payload["stream"] = True
        url = f"{self.url}/v1/chat/completions" if self.backend == "local" \
            else f"{self.url}/chat/completions"
        async with httpx.AsyncClient(timeout=120.0, headers=self._headers()) as client:
            async with client.stream("POST", url, json=payload) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode("utf-8", "replace")
                    raise RuntimeError(f"HTTP {resp.status_code}: {body[:500]}")
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        if raw is not None:
                            raw.add({"done": True})
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    if raw is not None:
                        raw.add(chunk)
                    choices = chunk.get("choices") or []
                    delta = (choices[0].get("delta") or {}).get("content") if choices else None
                    if delta:
                        yield delta

    async def _stream_ollama(self, messages, temperature, max_tokens, raw=None):
        payload = self._payload(messages, temperature, max_tokens)
        payload["stream"] = True
        payload["options"] = {"temperature": temperature, "num_predict": max_tokens}
        async with httpx.AsyncClient(timeout=120.0, headers=self._headers()) as client:
            async with client.stream("POST", f"{self.url}/api/chat", json=payload) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode("utf-8", "replace")
                    raise RuntimeError(f"HTTP {resp.status_code}: {body[:500]}")
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if raw is not None:
                        raw.add(chunk)
                    if chunk.get("error"):
                        raise RuntimeError(str(chunk["error"]))
                    content = (chunk.get("message") or {}).get("content") or ""
                    if content:
                        yield content
                    if chunk.get("done"):
                        break

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
