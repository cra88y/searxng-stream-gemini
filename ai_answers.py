import json, http.client, ssl, os, logging, base64, time, hashlib
from urllib.parse import urlparse
from flask import Response, request, abort
from searx.plugins import Plugin, PluginInfo
from searx.result_types import EngineResults
from flask_babel import gettext
from markupsafe import Markup

logger = logging.getLogger(__name__)

TOKEN_EXPIRY_SEC = 86400
CONNECTION_TIMEOUT_SEC = 30

PROVIDER_PRESETS = {
    'openai':     {'url': 'https://api.openai.com/v1/chat/completions',       'model': 'gpt-4o-mini'},
    'openrouter': {'url': 'https://openrouter.ai/api/v1/chat/completions',    'model': 'google/gemma-3-27b-it:free'},
    'ollama':     {'url': 'http://localhost:11434/v1/chat/completions',       'model': 'llama3.2'},
    'localai':    {'url': 'http://localhost:8080/v1/chat/completions',        'model': 'gpt-4'},
    'lmstudio':   {'url': 'http://localhost:1234/v1/chat/completions',        'model': 'local-model'},
    'gemini':     {'url': 'https://generativelanguage.googleapis.com',        'model': 'gemma-3-27b-it'},
    'azure':      {'url': None,                                               'model': 'azure-deployment'},
    'huggingface': {'url': 'https://api-inference.huggingface.co/models/{model}/v1/chat/completions', 'model': 'meta-llama/Meta-Llama-3-8B-Instruct'}
}

import typing
if typing.TYPE_CHECKING:
    from searx.search import SearchWithPlugins
    from searx.extended_types import SXNG_Request
    from . import PluginCfg

class SXNGPlugin(Plugin):
    """
    AI Answers Plugin for SearXNG.
    Injects a real-time streaming answer box synthesized from search results using LLM providers.
    Supports OpenAI, OpenRouter, Gemini, Ollama, LocalAI, Azure, and Hugging Face.
    """
    id = "ai_answers"

    def __init__(self, plg_cfg: "PluginCfg"):
        super().__init__(plg_cfg)
        self.info = PluginInfo(
            id=self.id,
            name=gettext("AI Answers Plugin"),
            description=gettext("Live AI search answers using LLM providers."),
            preference_section="general",
        )
        self._load_config()

        if self.api_key:
            self.secret = os.getenv('SXNG_LLM_SECRET') or hashlib.sha256(self.api_key.encode()).hexdigest()
        else:
            self.secret = os.getenv('SXNG_LLM_SECRET', '')
            logger.warning("AI Answers: No API key configured, plugin inactive")

    def _load_config(self):
        self.style = os.getenv('LLM_STYLE', 'interactive')
        raw_provider = os.getenv('LLM_PROVIDER', '').lower().strip()
        
        raw_url = os.getenv('LLM_URL', '').strip()
        if not raw_provider and raw_url:
            url_lower = raw_url.lower()
            if 'openai.com' in url_lower:
                raw_provider = 'openai'
            elif 'openrouter.ai' in url_lower:
                raw_provider = 'openrouter'
            elif ':11434' in url_lower:
                raw_provider = 'ollama'
            elif 'generativelanguage.googleapis.com' in url_lower:
                raw_provider = 'gemini'
        
        if not raw_provider:
            logger.debug("AI Answers: No provider configured, plugin inactive")
            self.provider = ''
            self.model = ''
            self.is_gemini = False
            self.api_key = ''
            return
        
        self.provider = raw_provider if raw_provider in PROVIDER_PRESETS else 'openai'
        self.is_gemini = (self.provider == 'gemini')
        preset = PROVIDER_PRESETS[self.provider]

        self.api_key = os.getenv('LLM_KEY', '')
        if not self.api_key and self.provider in ('ollama', 'localai', 'lmstudio'):
            self.api_key = 'none'
        self.api_key = self.api_key.strip()

        self.model = os.getenv('LLM_MODEL', preset['model']).strip()

        try:
            self.max_tokens = int(os.getenv('LLM_MAX_TOKENS', 500))
        except ValueError:
            self.max_tokens = 500
        try:
            self.temperature = float(os.getenv('LLM_TEMPERATURE', 0.2))
        except ValueError:
            self.temperature = 0.2
        try:
            self.context_count = max(0, int(os.getenv('LLM_CONTEXT_COUNT', 5)))
        except ValueError:
            self.context_count = 5

        self.allowed_tabs = set(t.strip() for t in os.getenv('LLM_TABS', 'general,science,it,news').split(','))

        preset_url = preset['url']
        if preset_url and '{model}' in preset_url:
            preset_url = preset_url.format(model=self.model)
        self._parse_url(preset_url)

        logger.info(f"AI Answers: {self.provider} @ {self.endpoint_host}")

    def _parse_url(self, default_url):
        raw_url = os.getenv('LLM_URL', '').strip() or default_url
        if not raw_url.startswith(('http://', 'https://')):
            raw_url = f"https://{raw_url}"
        
        parsed = urlparse(raw_url)
        self.endpoint_url = raw_url
        self.endpoint_host = parsed.hostname or 'localhost'
        self.endpoint_port = parsed.port
        self.endpoint_path = parsed.path or '/v1/chat/completions'
        if parsed.query:
            self.endpoint_path += f"?{parsed.query}"
        self.endpoint_ssl = (parsed.scheme == 'https')

        if self.is_gemini:
            return

        is_local = self.endpoint_host in ('localhost', '127.0.0.1') or self.endpoint_host.startswith('127.')
        if not self.endpoint_ssl and not is_local:
            logger.warning(f"AI Answers: HTTP on non-localhost ({self.endpoint_host}). Credentials may be exposed.")

    def _get_connection(self):
        proxy_url = os.getenv('HTTPS_PROXY' if self.endpoint_ssl else 'HTTP_PROXY') or os.getenv('https_proxy' if self.endpoint_ssl else 'http_proxy')
        
        target_host = self.endpoint_host
        target_port = self.endpoint_port
        target_str = f"{target_host}:{target_port}" if target_port else target_host

        if proxy_url:
            p = urlparse(proxy_url)
            p_host = p.hostname
            p_port = p.port or 8080

            if p.scheme == 'https':
                conn = http.client.HTTPSConnection(p_host, p_port, timeout=CONNECTION_TIMEOUT_SEC, context=ssl.create_default_context())
            else:
                conn = http.client.HTTPConnection(p_host, p_port, timeout=CONNECTION_TIMEOUT_SEC)
            
            conn.set_tunnel(target_host, target_port)
            return conn

        # Direct Connection
        if self.endpoint_ssl:
            return http.client.HTTPSConnection(target_str, timeout=CONNECTION_TIMEOUT_SEC, context=ssl.create_default_context())
        return http.client.HTTPConnection(target_str, timeout=CONNECTION_TIMEOUT_SEC)

    def init(self, app):
        @app.route('/ai-stream', methods=['POST'])
        def handle_ai_stream():
            data = request.json or {}
            token = data.get('tk', '')
            q = data.get('q', '')
            lang = data.get('lang', 'all')
            
            try:
                ts, sig = token.split('.', 1)
                expected = hashlib.sha256(f"{ts}{self.secret}".encode()).hexdigest()
                if sig != expected or (time.time() - float(ts)) > TOKEN_EXPIRY_SEC:
                    abort(403)
            except (ValueError, KeyError, AttributeError):
                abort(403)

            context_text = data.get('context', '')
            prev_answer = (data.get('prev_answer') or '')[-4000:]
            
            if not self.api_key:
                logger.warning(f"AI Answers: request rejected. Key loaded: {bool(self.api_key)}, Query: {bool(q)}")
                return Response("Missing API key or query", status=400)
            
            today = time.strftime("%Y-%m-%d")
            target_words = int(self.max_tokens * 0.2)
            lang_instruction = f" Respond in {lang}." if lang not in ('all', 'auto') else ""

            SYSTEM = f"You are a search synthesis engine. Direct, grounded, citation-accurate. Today is {today}.{lang_instruction}"

            CORE_RULES = [
                "DENSITY 4/5: Expert-briefing level. No filler, no transitions. Every sentence = new information.",
                f"BREVITY: {target_words} words max. Complete, not verbose.",
                "CITATIONS: Cite [n] only for specific facts from sources. Max 3 total. Sentence-end only. Never cite common knowledge.",
                "NO HEDGE: State answers confidently. Note uncertainty only if critical.",
            ]

            if q == "Continue":
                task = "CONTINUE: Pick up exactly where previous answer stopped. No repetition. Seamless flow."
            elif prev_answer:
                task = "FOLLOW-UP: Address the new question using prior context. Prioritize the new query."
            else:
                task = "ANSWER FIRST: Lead with the direct answer. No preamble, no context-setting."

            grounding = "GROUNDING: Trust sources for current events. Use knowledge for fundamentals." if context_text else "GROUNDING: No sources available. Use knowledge and note 'based on general knowledge'."
            history_rule = "HISTORY: Refer to prior exchange for context. Do not repeat." if prev_answer else None

            instructions = [task] + CORE_RULES + [grounding]
            if history_rule:
                instructions.append(history_rule)

            numbered_instructions = "\n".join(f"{i+1}. {r}" for i, r in enumerate(instructions))
            prompt = f"""<system>{SYSTEM}</system>

<sources>
{context_text or 'None.'}
</sources>

<history>
{prev_answer or 'None.'}
</history>

<query>{q}</query>

<instructions>
{numbered_instructions}
</instructions>

<answer>"""

            def stream_gemini():
                path = f"/v1/models/{self.model}:streamGenerateContent"
                conn = None
                try:
                    conn = self._get_connection()
                        
                    payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"maxOutputTokens": self.max_tokens, "temperature": self.temperature, "stopSequences": ["</answer>"]}}
                    headers = {"Content-Type": "application/json", "x-goog-api-key": self.api_key}
                    conn.request("POST", path, body=json.dumps(payload), headers=headers)
                    res = conn.getresponse()
                    if res.status != 200:
                        logger.error(f"Gemini API {res.status}: {res.read().decode('utf-8')}")
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
                except Exception as e:
                    logger.error(f"Gemini stream error: {e}")
                finally:
                    if conn: conn.close()

            def stream_openai_compatible():
                conn = None
                try:
                    conn = self._get_connection()
                    
                    payload = {
                        "model": self.model,
                        "messages": [{"role": "user", "content": prompt}],
                        "stream": True,
                        "max_tokens": self.max_tokens,
                        "temperature": self.temperature,
                        "stop": ["</answer>"]
                    }
                    headers = {
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://github.com/searxng/searxng",
                        "X-Title": "SearXNG"
                    }
                    if self.provider == 'azure':
                        headers['api-key'] = self.api_key
                    else:
                        headers['Authorization'] = f"Bearer {self.api_key}"
                    
                    conn.request("POST", self.endpoint_path, body=json.dumps(payload), headers=headers)
                    res = conn.getresponse()
                    if res.status != 200:
                        logger.error(f"{self.provider} API {res.status}: {res.read().decode('utf-8')}")
                        return

                    decoder = json.JSONDecoder()
                    buffer = b""
                    while True:
                        chunk = res.read(128)
                        if not chunk: break
                        buffer += chunk
                        while b"\n" in buffer:
                            line_bytes, buffer = buffer.split(b"\n", 1)
                            line = line_bytes.decode('utf-8', errors='replace')
                            if line.startswith("data: "):
                                data_str = line[6:].strip()
                                if data_str == "[DONE]": return
                                try:
                                    obj, _ = decoder.raw_decode(data_str)
                                    content = obj.get("choices", [{}])[0].get("delta", {}).get("content", "")
                                    if content: yield content
                                except json.JSONDecodeError:
                                    pass
                except Exception as e:
                    logger.error(f"{self.provider} stream error: {e}")
                finally:
                    if conn: conn.close()

            generator = stream_gemini if self.is_gemini else stream_openai_compatible
            return Response(generator(), mimetype='text/event-stream', headers={
                'X-Accel-Buffering': 'no',
                'Cache-Control': 'no-cache, no-store',
                'Connection': 'keep-alive',
                'Content-Encoding': 'identity'
            })
        return True

    def post_search(self, request: "SXNG_Request", search: "SearchWithPlugins") -> EngineResults:
        results = EngineResults()
        try:
            current_tabs = set(search.search_query.categories)
            if not current_tabs: current_tabs = {'general'}

            if not self.active or not self.api_key or search.search_query.pageno > 1 or not self.allowed_tabs.intersection(current_tabs):
                return results

            raw_results = search.result_container.get_ordered_results()
            context_list = []
            for i, r in enumerate(raw_results[:self.context_count]):
                domain = urlparse(r.get('url', '')).netloc
                date = r.get('publishedDate')
                date_str = f" ({date})" if date else ""
                title = r.get('title') or ""
                context_list.append(f"[{i+1}] {domain}{date_str}: {title}: {str(r.get('content', ''))[:500]}")
            
            context_str = "\n".join(context_list)


            ts = str(int(time.time()))
            q_clean = search.search_query.query.strip()
            lang = search.search_query.lang
            sig = hashlib.sha256(f"{ts}{self.secret}".encode()).hexdigest()
            tk = f"{ts}.{sig}"
            
            b64_context = base64.b64encode(context_str.encode('utf-8')).decode('utf-8')
            js_q = json.dumps(q_clean)
            js_lang = json.dumps(lang)
            js_urls = json.dumps([r.get('url') for r in raw_results[:self.context_count]])

            is_interactive = (self.style == 'interactive')
            
            # Conditional CSS for interactive mode
            interactive_css = '''
                        @keyframes sxng-fade-in-up {
                            0% { opacity: 0; transform: translateY(10px); }
                            100% { opacity: 1; transform: translateY(0); }
                        }
                        .sxng-footer {
                            display: flex;
                            align-items: center;
                            gap: 0.5rem;
                            margin-top: 0.5rem;
                            opacity: 0;
                            animation: sxng-fade-in-up 0.5s ease-out forwards;
                        }
                        .sxng-btn {
                            display: inline-flex;
                            align-items: center;
                            justify-content: center;
                            width: 32px;
                            height: 32px;
                            padding: 0;
                            border: 1px solid transparent;
                            border-radius: 6px;
                            background: transparent;
                            color: var(--color-base-font, #333);
                            cursor: pointer;
                            transition: all 0.2s ease;
                            opacity: 0.6;
                        }
                        .sxng-btn:hover {
                            background: var(--color-base-background-hover, rgba(0,0,0,0.05));
                            color: var(--color-result-link, #5e81ac);
                            opacity: 1;
                            transform: translateY(-1px);
                        }
                        .sxng-btn svg { width: 18px; height: 18px; fill: currentColor; }
                        .sxng-input-wrapper {
                            flex-grow: 1;
                            display: flex;
                            align-items: center;
                            margin: 0 0.5rem;
                            position: relative;
                        }
                        .sxng-input {
                            width: 100%;
                            background: transparent;
                            border: none;
                            color: var(--color-base-font, #333);
                            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                            font-size: 16px;
                            padding: 0.5rem 2.5rem 0.5rem 0;
                            opacity: 0.8;
                            transition: opacity 0.2s;
                        }
                        .sxng-input:focus { outline: none; opacity: 1; }
                        .sxng-input::placeholder { color: var(--color-base-font, #333); opacity: 0.35; }
                        .sxng-input-line {
                            position: absolute;
                            bottom: 0;
                            left: 0;
                            width: 0;
                            height: 1px;
                            background: var(--color-result-link, #5e81ac);
                            transition: width 0.3s ease;
                        }
                        .sxng-input:focus + .sxng-input-line { width: 100%; }
                        .sxng-user-msg {
                            display: block;
                            width: fit-content;
                            max-width: 80%;
                            margin: 1rem 0 1rem auto;
                            padding: 0.5rem 0.8rem;
                            background: var(--color-base-background-hover, rgba(0,0,0,0.05));
                            border-radius: 12px 12px 0 12px;
                            color: var(--color-base-font, #333);
                            font-size: 0.9rem;
                            line-height: 1.5;
                            animation: sxng-fade-in-up 0.3s ease-out forwards;
                            border: 1px solid var(--color-base-border, rgba(0,0,0,0.1));
                        }
                        .sxng-input-submit {
                            position: absolute;
                            right: 0;
                            top: 50%;
                            transform: translateY(-50%);
                            background: none;
                            border: none;
                            padding: 8px;
                            color: var(--color-base-font, #333);
                            cursor: pointer;
                            opacity: 0.3;
                            transition: all 0.2s ease;
                        }
                        .sxng-input-wrapper:focus-within .sxng-input-submit,
                        .sxng-input-submit:hover { opacity: 1; color: var(--color-result-link, #5e81ac); }
                        .sxng-input-submit svg { width: 18px; height: 18px; fill: currentColor; }
''' if is_interactive else ''

            # Conditional HTML for interactive footer
            interactive_html = '''
                    <div id="sxng-footer" class="sxng-footer" style="display:none;">
                        <button class="sxng-btn" id="btn-copy" title="Copy to clipboard">
                            <svg viewBox="0 0 24 24"><path d="M16 1H4C2.9 1 2 1.9 2 3V17H4V3H16V1M19 5H8C6.9 5 6 5.9 6 7V21C6 22.1 6.9 23 8 23H19C20.1 23 21 22.1 21 21V7C21 5.9 20.1 5 19 5M19 21H8V7H19V21Z"/></svg>
                        </button>
                        <button class="sxng-btn" id="btn-regen" title="Regenerate answer">
                            <svg viewBox="0 0 24 24"><path d="M17.65 6.35C16.2 4.9 14.21 4 12 4C7.58 4 4.01 7.58 4.01 12C4.01 16.42 7.58 20 12 20C15.73 20 18.84 17.45 19.73 14H17.65C16.83 16.33 14.61 18 12 18C8.69 18 6 15.31 6 12C6 8.69 8.69 6 12 6C13.66 6 15.14 6.69 16.22 7.78L13 11H20V4L17.65 6.35Z"/></svg>
                        </button>
                        <form id="sxng-action-form" class="sxng-input-wrapper" onsubmit="event.preventDefault();">
                            <input type="text" id="sxng-action-input" class="sxng-input" placeholder="Ask..." aria-label="Ask follow-up" autocomplete="off">
                            <div class="sxng-input-line"></div>
                            <button type="submit" id="btn-action" class="sxng-input-submit" title="Send / Continue">
                                <svg viewBox="0 0 24 24"><path d="M19,7V11H5.83L9.41,7.41L8,6L2,12L8,18L9.41,16.59L5.83,13H21V7H19Z"/></svg>
                            </button>
                        </form>
                    </div>
''' if is_interactive else ''

            # Conditional JS for interactive handlers
            interactive_js_init = '''
                        const footer = document.getElementById('sxng-footer');
                        const input = document.getElementById('sxng-action-input');

                        document.getElementById('btn-copy').onclick = async (e) => {
                            const btn = e.currentTarget;
                            const originalContent = btn.innerHTML;
                            const text = Array.from(data.childNodes)
                                .filter(n => n.nodeType === 3 || n.tagName === 'SPAN')
                                .map(n => n.textContent)
                                .join('');
                            await navigator.clipboard.writeText(text);
                            btn.innerHTML = '<svg viewBox="0 0 24 24" style="color:#a3be8c;"><path d="M9 16.17L4.83 12L3.41 13.41L9 19L21 7L19.59 5.59L9 16.17Z"/></svg>';
                            setTimeout(() => btn.innerHTML = originalContent, 2000);
                        };

                        document.getElementById('btn-regen').onclick = () => {
                            data.innerHTML = '<span class="sxng-cursor"></span>';
                            footer.style.display = 'none';
                            startStream();
                        };

                        const handleAction = (e) => {
                            if (e) e.preventDefault();
                            const val = input.value.trim();
                            const currentText = Array.from(data.childNodes)
                                .filter(n => n.nodeType === 3 || n.tagName === 'SPAN')
                                .map(n => {
                                    if (n.classList && n.classList.contains('sxng-user-msg')) {
                                        return '\\n\\nQ: ' + n.textContent + '\\nA: ';
                                    }
                                    return n.textContent;
                                })
                                .join('');
                            input.value = '';
                            input.blur();
                            footer.style.display = 'none';

                            if (val) {
                                const cursor = data.querySelector('.sxng-cursor');
                                if (cursor) cursor.remove();
                                const userMsg = document.createElement('span');
                                userMsg.className = 'sxng-user-msg';
                                userMsg.textContent = val;
                                data.appendChild(userMsg);
                                const newCursor = document.createElement('span');
                                newCursor.className = 'sxng-cursor';
                                data.appendChild(newCursor);
                                startStream(val, currentText);
                            } else {
                                const cursor = data.querySelector('.sxng-cursor');
                                if (cursor) cursor.remove();
                                data.appendChild(document.createElement('br'));
                                data.appendChild(document.createElement('br'));
                                const newCursor = document.createElement('span');
                                newCursor.className = 'sxng-cursor';
                                data.appendChild(newCursor);
                                startStream("Continue", currentText);
                            }
                        };

                        document.getElementById('sxng-action-form').onsubmit = handleAction;
                        input.onfocus = () => {
                            setTimeout(() => {
                                input.scrollIntoView({behavior: 'smooth', block: 'center'});
                            }, 300);
                        };
''' if is_interactive else ''

            interactive_js_complete = "footer.style.display = 'flex';" if is_interactive else ''
            
            # Streaming function signature differs between modes
            stream_fn_sig = 'async function startStream(overrideQ = null, prevAnswer = null)' if is_interactive else 'async function startStream()'
            stream_q = 'overrideQ || q_init' if is_interactive else 'q_init'
            stream_body = f'''prev_answer: prevAnswer''' if is_interactive else ''

            html_payload = f'''
                <article id="sxng-stream-box" class="answer" style="display:none; margin: 1rem 0;">
                    <style>
                        @keyframes sxng-fade-pulse {{
                            0%, 100% {{ opacity: 0.3; }}
                            50% {{ opacity: 1; }}
                        }}
                        @keyframes sxng-fade-in {{
                            0% {{ opacity: 0; filter: blur(3px); transform: translateY(2px); }}
                            100% {{ opacity: 1; filter: blur(0); transform: translateY(0); }}
                        }}
                        #sxng-stream-data {{
                            position: relative;
                            margin: 0;
                            min-height: 1.5em;
                        }}
                        .sxng-cursor {{
                            display: inline-block;
                            width: 0.6em;
                            height: 1.2em;
                            background: var(--color-result-link, #5e81ac);
                            vertical-align: text-bottom;
                            animation: sxng-fade-pulse 1s ease-in-out infinite;
                            margin-right: 0.2rem;
                            border-radius: 2px;
                        }}
                        .sxng-chunk {{
                            opacity: 0;
                            animation: sxng-fade-in 0.4s cubic-bezier(0.2, 0.9, 0.1, 1.0) forwards;
                            will-change: opacity, filter, transform;
                        }}
                        {interactive_css}
                    </style>
                    <p id="sxng-stream-data" style="white-space: pre-wrap; color: var(--color-result-description); font-size: 0.95rem; margin:0;"><span class="sxng-cursor"></span></p>
                    {interactive_html}
                    <script>
                    (async () => {{
                        const q_init = {js_q};
                        const lang_init = {js_lang};
                        const urls = {js_urls};
                        const b64_init = "{b64_context}";
                        const tk_init = "{tk}";
                        const box = document.getElementById('sxng-stream-box');
                        const data = document.getElementById('sxng-stream-data');
                        const wrapper = box.closest('.answer');
                        if (wrapper) wrapper.style.display = 'none';

                        {interactive_js_init}

                        {stream_fn_sig} {{
                            try {{
                                const ctx = new TextDecoder().decode(Uint8Array.from(atob(b64_init), c => c.charCodeAt(0)));
                                if (wrapper) wrapper.style.display = '';
                                box.style.display = 'block';

                                const controller = new AbortController();
                                const timeoutId = setTimeout(() => controller.abort(), 60000);
                                const finalQ = {stream_q};
                                
                                const bodyObj = {{ q: finalQ, lang: lang_init, context: ctx, tk: tk_init{', ' + stream_body if stream_body else ''} }};
                                const res = await fetch('/ai-stream', {{
                                    method: 'POST',
                                    headers: {{ 'Content-Type': 'application/json' }},
                                    body: JSON.stringify(bodyObj),
                                    signal: controller.signal
                                }});

                                clearTimeout(timeoutId);
                                if (!res.ok) {{
                                    const errSpan = document.createElement('span');
                                    errSpan.style.color = '#bf616a';
                                    errSpan.textContent = "Error: " + res.statusText;
                                    data.appendChild(errSpan);
                                    return;
                                }}

                                const reader = res.body.getReader();
                                const decoder = new TextDecoder();
                                let cursor = data.querySelector('.sxng-cursor');
                                if (!cursor) {{
                                    cursor = document.createElement('span');
                                    cursor.className = 'sxng-cursor';
                                    data.appendChild(cursor);
                                }}

                                let started = false;
                                let pendingSpace = '';

                                while (true) {{
                                    const {{done, value}} = await reader.read();
                                    if (done) break;

                                    const chunk = decoder.decode(value, {{stream: true}});
                                    if (chunk) {{
                                        let text = chunk;
                                        if (!started) {{
                                            text = text.replace(/^[\\s.,;:!?]+/, '');
                                            if (!text) continue;
                                            if (cursor && !cursor.isConnected) data.appendChild(cursor);
                                            started = true;
                                        }}

                                        if (text.trim().length === 0) {{
                                            pendingSpace += text;
                                            continue;
                                        }}

                                        if (pendingSpace) {{
                                            const s = document.createElement('span');
                                            s.className = 'sxng-chunk';
                                            s.textContent = pendingSpace;
                                            cursor.before(s);
                                            pendingSpace = '';
                                        }}

                                        const span = document.createElement('span');
                                        span.className = 'sxng-chunk';
                                        span.textContent = text;
                                        cursor.before(span);

                                        if (text.includes(']')) {{
                                            processLastCitation();
                                        }}
                                    }}
                                }}
                                if (cursor) cursor.remove();

                                let last = data.lastChild;
                                while (last) {{
                                    if (last.textContent && last.textContent.trim().length === 0) {{
                                        const prev = last.previousSibling;
                                        last.remove();
                                        last = prev;
                                    }} else {{
                                        if (last.textContent) last.textContent = last.textContent.trimEnd();
                                        break;
                                    }}
                                }}

                                if (!started) {{
                                    if (box.parentElement) box.parentElement.remove();
                                    else box.remove();
                                    return;
                                }}

                                {interactive_js_complete}

                                function processLastCitation() {{
                                    let node = cursor ? cursor.previousSibling : data.lastChild;
                                    let nodesRaw = [];
                                    let buffer = '';

                                    while (node && nodesRaw.length < 20) {{
                                        if (node.tagName === 'SPAN' && node.className === 'sxng-chunk') {{
                                            const content = node.textContent;
                                            buffer = content + buffer;
                                            nodesRaw.unshift(node);
                                            if (content.includes('[')) break;
                                        }} else {{
                                            break;
                                        }}
                                        node = node.previousSibling;
                                    }}

                                    const re = /(?:\\\\)?\\[\\s*(\\d{{1,2}}(?:\\s*,\\s*\\d{{1,2}})*)\\s*(?:\\\\)?\\]/g;
                                    let match, lastMatch;
                                    while ((match = re.exec(buffer)) !== null) {{
                                        lastMatch = match;
                                    }}

                                    if (lastMatch) {{
                                        const before = buffer.substring(0, lastMatch.index);
                                        const citationBody = lastMatch[1];
                                        const after = buffer.substring(lastMatch.index + lastMatch[0].length);
                                        nodesRaw.forEach(n => n.remove());
                                        const fragment = document.createDocumentFragment();

                                        if (before) {{
                                            const s = document.createElement('span');
                                            s.className = 'sxng-chunk';
                                            s.textContent = before;
                                            fragment.appendChild(s);
                                        }}

                                        citationBody.split(/\\s*,\\s*/).forEach(n => {{
                                            const url = urls[parseInt(n)-1];
                                            if (url) {{
                                                const a = document.createElement('a');
                                                a.href = url;
                                                a.target = '_blank';
                                                a.style.cssText = 'text-decoration:none;color:var(--color-result-link);font-weight:bold;';
                                                a.textContent = `[${{n}}]`;
                                                a.className = 'sxng-chunk';
                                                fragment.appendChild(a);
                                            }} else {{
                                                const s = document.createElement('span');
                                                s.className = 'sxng-chunk';
                                                s.textContent = `[${{n}}]`;
                                                fragment.appendChild(s);
                                            }}
                                        }});

                                        if (after) {{
                                            const s = document.createElement('span');
                                            s.className = 'sxng-chunk';
                                            s.textContent = after;
                                            fragment.appendChild(s);
                                        }}

                                        if (cursor) cursor.before(fragment);
                                        else data.appendChild(fragment);
                                    }}
                                }}
                            }} catch (e) {{
                                console.error(e);
                                if (box.parentElement) box.parentElement.remove();
                                else box.remove();
                            }}
                        }}

                        startStream();
                    }})();
                    </script>
                </article>
            '''
            search.result_container.answers.add(results.types.Answer(answer=Markup(html_payload)))
        except Exception as e:
            logger.error(f"AI Answers: {e}")
        return results
