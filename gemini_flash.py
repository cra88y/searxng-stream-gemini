import json, http.client, ssl, os, logging, base64, time, hashlib
from flask import Response, request, abort
from searx.plugins import Plugin, PluginInfo
from searx.result_types import EngineResults
from flask_babel import gettext
from markupsafe import Markup

logger = logging.getLogger(__name__)

# Constants
TOKEN_EXPIRY_SEC = 60
CONNECTION_TIMEOUT_SEC = 30

class SXNGPlugin(Plugin):
    id = "gemini_flash"

    def __init__(self, plg_cfg):
        super().__init__(plg_cfg)
        self.info = PluginInfo(
            id=self.id,
            name=gettext("Gemini Flash Streaming"),
            description=gettext("Live AI search answers using Google Gemini Flash"),
            preference_section="general", 
        )
        self.provider = os.getenv('LLM_PROVIDER', 'openrouter').lower()
        self.api_key = os.getenv('OPENROUTER_API_KEY') if self.provider == 'openrouter' else os.getenv('GEMINI_API_KEY')
        self.model = os.getenv('GEMINI_MODEL', 'gemma-3-27b-it') if self.provider == 'gemini' else os.getenv('OPENROUTER_MODEL', 'google/gemma-3-27b-it:free')
        try:
            self.max_tokens = int(os.getenv('GEMINI_MAX_TOKENS', 500))
        except ValueError:
            self.max_tokens = 500
        try:
            self.temperature = float(os.getenv('GEMINI_TEMPERATURE', 0.2))
        except ValueError:
            self.temperature = 0.2
        self.base_url = os.getenv('OPENROUTER_BASE_URL', 'openrouter.ai')
        # Stable secret for multi-worker environments
        if self.api_key:
            self.secret = os.getenv('SXNG_LLM_SECRET') or hashlib.sha256(self.api_key.encode()).hexdigest()
        else:
            self.secret = os.getenv('SXNG_LLM_SECRET', '')
            logger.warning("Gemini Flash plugin: No API key configured, plugin will be inactive")

    def init(self, app):
        @app.route('/gemini-stream', methods=['POST'])
        def g_stream():
            data = request.json or {}
            token = data.get('tk', '')
            q = data.get('q', '')
            
            try:
                ts, sig = token.split('.', 1)
                query_clean = q.strip()
                expected = hashlib.sha256(f"{ts}{query_clean}{self.secret}".encode()).hexdigest()
                if sig != expected or (time.time() - float(ts)) > TOKEN_EXPIRY_SEC:
                    abort(403)
            except (ValueError, KeyError, AttributeError):
                abort(403)

            context_text = data.get('context', '')
            if not self.api_key or not q:
                return Response("Error: Missing Key", status=400)

            prompt = (
                f"SYSTEM: Answer USER QUERY by integrating SEARCH RESULTS with expert knowledge.\n"
                f"HIERARCHY: Use RESULTS for facts/data. Use KNOWLEDGE for context/synthesis.\n"
                f"CONSTRAINTS: <4 sentences | Dense information | Complete thoughts.\n"
                f"FALLBACK: If results are empty, answer from knowledge but note the lack of sources.\n\n"
                f"SEARCH RESULTS:\n{context_text}\n\n"
                f"USER QUERY: {q}\n\n"
                f"ANSWER:"
            )

            def generate_gemini():
                host = "generativelanguage.googleapis.com"
                path = f"/v1/models/{self.model}:streamGenerateContent?key={self.api_key}"
                try:
                    conn = http.client.HTTPSConnection(host, timeout=CONNECTION_TIMEOUT_SEC, context=ssl.create_default_context())
                    payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"maxOutputTokens": self.max_tokens, "temperature": self.temperature}}
                    conn.request("POST", path, body=json.dumps(payload), headers={"Content-Type": "application/json"})
                    res = conn.getresponse()
                    if res.status != 200:
                        logger.error(f"Gemini API Error {res.status}: {res.read().decode('utf-8')}")
                        return

                    decoder = json.JSONDecoder()
                    buffer = ""
                    while True:
                        chunk = res.read(128)
                        if not chunk: break
                        buffer += chunk.decode('utf-8')
                        while buffer:
                            buffer = buffer.lstrip()
                            if not buffer: break
                            try:
                                obj, idx = decoder.raw_decode(buffer)
                                candidates = obj.get('candidates', [])
                                if candidates:
                                    content = candidates[0].get('content', {})
                                    parts = content.get('parts', [])
                                    if parts:
                                        text = parts[0].get('text', '')
                                        if text: yield text
                                buffer = buffer[idx:]
                            except json.JSONDecodeError: break
                    conn.close()
                except Exception as e: logger.error(f"Gemini Stream Exception: {e}")

            def generate_openrouter():
                try:
                    conn = http.client.HTTPSConnection(self.base_url, timeout=CONNECTION_TIMEOUT_SEC, context=ssl.create_default_context())
                    payload = {
                        "model": self.model,
                        "messages": [{"role": "user", "content": prompt}],
                        "stream": True,
                        "max_tokens": self.max_tokens,
                        "temperature": self.temperature
                    }
                    headers = {
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://github.com/searxng/searxng",
                        "X-Title": "SearXNG LLM Plugin"
                    }
                    conn.request("POST", "/api/v1/chat/completions", body=json.dumps(payload), headers=headers)
                    res = conn.getresponse()
                    if res.status != 200:
                        logger.error(f"OpenRouter API Error {res.status}: {res.read().decode('utf-8')}")
                        return

                    decoder = json.JSONDecoder()
                    buffer = ""
                    while True:
                        chunk = res.read(128)
                        if not chunk: break
                        buffer += chunk.decode('utf-8')
                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            if line.startswith("data: "):
                                data_str = line[6:].strip()
                                if data_str == "[DONE]": return
                                try:
                                    obj, _ = decoder.raw_decode(data_str)
                                    content = obj.get("choices", [{}])[0].get("delta", {}).get("content", "")
                                    if content: yield content
                                except json.JSONDecodeError:
                                    pass
                    conn.close()
                except Exception as e: logger.error(f"OpenRouter Stream Exception: {e}")

            generator = generate_openrouter if self.provider == 'openrouter' else generate_gemini
            return Response(generator(), mimetype='text/plain', headers={'X-Accel-Buffering': 'no'})
        return True

    def post_search(self, request, search) -> EngineResults:
        results = EngineResults()
        try:
            if not self.active or not self.api_key or search.search_query.pageno > 1:
                return results

            raw_results = search.result_container.get_ordered_results()
            context_list = [f"[{i+1}] {r.get('title')}: {r.get('content')}" for i, r in enumerate(raw_results[:6])]
            context_str = "\n".join(context_list)

            # Stateless Handshake
            ts = str(int(time.time()))
            q_clean = search.search_query.query.strip()
            sig = hashlib.sha256(f"{ts}{q_clean}{self.secret}".encode()).hexdigest()
            tk = f"{ts}.{sig}"

            b64_context = base64.b64encode(context_str.encode('utf-8')).decode('utf-8')
            js_q = json.dumps(q_clean)

            html_payload = f'''
            <article id="sxng-stream-box" class="answer" style="display:none; margin-bottom: 1rem;">
                <style>
                    @keyframes sxng-blink {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0; }} }}
                    .sxng-cursor {{ 
                        display: inline-block; width: 0.5rem; height: 1rem; 
                        background: var(--color-result-description); 
                        margin-left: 2px; vertical-align: middle;
                        animation: sxng-blink 1s step-end infinite;
                    }}
                </style>
                <p id="sxng-stream-data" style="white-space: pre-wrap; color: var(--color-result-description); font-size: 0.95rem;"></p>
                <script>
                (async () => {{
                    const q = {js_q};
                    const b64 = "{b64_context}";
                    const tk = "{tk}";
                    const box = document.getElementById('sxng-stream-box');
                    const data = document.getElementById('sxng-stream-data');
                    
                    try {{
                        const ctx = new TextDecoder().decode(Uint8Array.from(atob(b64), c => c.charCodeAt(0)));
                        const res = await fetch('/gemini-stream', {{
                            method: 'POST',
                            headers: {{ 'Content-Type': 'application/json' }},
                            body: JSON.stringify({{ q: q, context: ctx, tk: tk }})
                        }});
                        
                        if (!res.ok) {{ box.remove(); return; }}

                        const reader = res.body.getReader();
                        const decoder = new TextDecoder();
                        const cursor = document.createElement('span');
                        cursor.className = 'sxng-cursor';
                        
                        let started = false;
                        while (true) {{
                            const {{done, value}} = await reader.read();
                            if (done) break;
                            
                            const chunk = decoder.decode(value);
                            if (chunk) {{
                                let text = chunk;
                                if (!started) {{
                                    text = text.replace(/^[\\s.,;:!?]+/, '');
                                    if (!text) continue;
                                    data.appendChild(cursor);
                                    box.style.display = 'block';
                                    started = true; 
                                }}
                                cursor.before(text);
                            }}
                        }}
                        cursor.remove();
                        if (!started) box.remove();
                    }} catch (e) {{ console.error(e); box.remove(); }}
                }})();
                </script>
            </article>
            '''
            search.result_container.answers.add(results.types.Answer(answer=Markup(html_payload)))
        except Exception as e:
            logger.error(f"Gemini Flash plugin error: {e}")
        return results
