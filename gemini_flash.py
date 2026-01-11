import json, http.client, ssl, os, logging, base64
from flask import Response, request
from searx.plugins import Plugin, PluginInfo
from searx.result_types import EngineResults
from flask_babel import gettext
from markupsafe import Markup

logger = logging.getLogger(__name__)

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
        self.api_key = os.getenv('GEMINI_API_KEY')
        self.model = os.getenv('GEMINI_MODEL', 'gemini-3-flash-preview')
        self.max_tokens = int(os.getenv('GEMINI_MAX_TOKENS', 500))
        self.temperature = float(os.getenv('GEMINI_TEMPERATURE', 0.2))

    def init(self, app):
        @app.route('/gemini-stream', methods=['POST'])
        def g_stream():
            data = request.json or {}
            context_text = data.get('context', '')
            q = data.get('q', '')

            if not self.api_key or not q:
                return Response("Error: Missing Key or Query", status=400)

            def generate():
                host = "generativelanguage.googleapis.com"
                path = f"/v1beta/models/{self.model}:streamGenerateContent?key={self.api_key}"
                try:
                    conn = http.client.HTTPSConnection(host, context=ssl.create_default_context())
                    prompt = (
                        f"SYSTEM: Answer USER QUERY by integrating SEARCH RESULTS with expert knowledge.\n"
                        f"HIERARCHY: Use RESULTS for facts/data. Use KNOWLEDGE for context/synthesis.\n"
                        f"CONSTRAINTS: <4 sentences | Dense information | Complete thoughts.\n"
                        f"FALLBACK: If results are empty, answer from knowledge but note the lack of sources.\n\n"
                        f"SEARCH RESULTS:\n{context_text}\n\n"
                        f"USER QUERY: {q}\n\n"
                        f"ANSWER:"
                    )
                    payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"maxOutputTokens": self.max_tokens, "temperature": self.temperature}}
                    conn.request("POST", path, body=json.dumps(payload), headers={"Content-Type": "application/json"})
                    res = conn.getresponse()
                    
                    buffer = ""
                    for chunk in res:
                        if not chunk: continue
                        buffer += chunk.decode('utf-8')
                        while True:
                            start = buffer.find('{')
                            if start == -1: break
                            brace_count, end = 0, -1
                            for i in range(start, len(buffer)):
                                if buffer[i] == '{': brace_count += 1
                                elif buffer[i] == '}': brace_count -= 1
                                if brace_count == 0:
                                    end = i + 1
                                    break
                            if end == -1: break
                            try:
                                data = json.loads(buffer[start:end])
                                candidates = data.get('candidates', [])
                                if candidates:
                                    text = candidates[0]['content']['parts'][0]['text']
                                    if text: yield text
                            except: pass
                            buffer = buffer[end:]
                    conn.close()
                except Exception as e:
                    yield f" [Error: {str(e)}]"

            return Response(generate(), mimetype='text/plain', headers={'X-Accel-Buffering': 'no'})
        return True

    def post_search(self, request, search) -> EngineResults:
        results = EngineResults()
        if not self.active or not self.api_key or search.search_query.pageno > 1:
            return results

        raw_results = search.result_container.get_ordered_results()
        context_list = [f"[{i+1}] {r.get('title')}: {r.get('content')}" for i, r in enumerate(raw_results[:6])]
        context_str = "\n".join(context_list)

        # Base64 Encode to ensure HTML safety
        b64_context = base64.b64encode(context_str.encode('utf-8')).decode('utf-8')
        js_q = json.dumps(search.search_query.query)

        html_payload = f'''
        <div id="ai-shell" style="display:none; margin-bottom: 2rem; padding: 1.2rem; border-bottom: 1px solid var(--color-result-border);">
            <div id="ai-out" style="line-height: 1.7; white-space: pre-wrap; color: var(--color-result-description); font-size: 0.95rem;">Thinking...</div>
        </div>
        <script>
        (async () => {{
            const q = {js_q};
            const b64 = "{b64_context}";
            const shell = document.getElementById('ai-shell');
            const out = document.getElementById('ai-out');
            
            const container = document.getElementById('urls') || document.getElementById('main_results');
            if (container && shell) {{ container.prepend(shell); shell.style.display = 'block'; }}

            try {{
                // Decode context client-side
                const ctx = new TextDecoder().decode(Uint8Array.from(atob(b64), c => c.charCodeAt(0)));
                
                const res = await fetch('/gemini-stream', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ q: q, context: ctx }})
                }});
                
                const reader = res.body.getReader();
                const decoder = new TextDecoder();
                out.innerText = "";
                
                while (true) {{
                    const {{done, value}} = await reader.read();
                    if (done) break;
                    out.innerText += decoder.decode(value);
                }}
            }} catch (e) {{ console.error(e); out.innerText += " [Error]"; }}
        }})();
        </script>
        '''
        results.add(results.types.Answer(answer=Markup(html_payload)))
        return results
