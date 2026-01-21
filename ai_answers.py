import json, os, logging, base64, time, hashlib, codecs, re
from urllib.parse import urlparse
from searx import network
from flask import Response, request, abort, jsonify
from searx.plugins import Plugin, PluginInfo
from searx.result_types import EngineResults
from flask_babel import gettext
from markupsafe import Markup

logger = logging.getLogger(__name__)

TOKEN_EXPIRY_SEC = 3600



PLUGIN_NAME = "AI Answers"
DEFAULT_TABS = "general,science,it,news"

PROVIDER_PRESETS = {
    'openai':     {'url': 'https://api.openai.com/v1/chat/completions',       'model': 'gpt-4o-mini'},
    'openrouter': {'url': 'https://openrouter.ai/api/v1/chat/completions',    'model': 'google/gemma-3-27b-it:free'},
    'ollama':     {'url': 'http://localhost:11434/v1/chat/completions',       'model': 'llama3.2'},
    'localai':    {'url': 'http://localhost:8080/v1/chat/completions',        'model': 'gpt-4'},
    'lmstudio':   {'url': 'http://localhost:1234/v1/chat/completions',        'model': 'local-model'},
    'gemini':     {'url': 'https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent', 'model': 'gemma-3-27b-it'},
    'azure':      {'url': None,                                               'model': 'azure-deployment'},
    'huggingface': {'url': 'https://api-inference.huggingface.co/models/{model}/v1/chat/completions', 'model': 'meta-llama/Meta-Llama-3-8B-Instruct'}
}

# UI assets (inlined for single-file install)

INTERACTIVE_CSS = '''
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
                            margin: 0.75rem 0 0.75rem auto;
                            padding: 0.25rem 0.6rem 0.25rem 0;
                            border-right: 2px solid var(--color-result-link, #5e81ac);
                            text-align: right;
                            font-size: 0.85rem;
                            line-height: 1.4;
                            opacity: 0.55;
                            animation: sxng-fade-in-up 0.3s ease-out forwards;
                        }
                        .sxng-input-submit {
                            all: unset;
                            position: absolute;
                            right: 0;
                            top: 50%;
                            transform: translateY(-50%);
                            display: inline-flex;
                            align-items: center;
                            justify-content: center;
                            width: 32px;
                            height: 32px;
                            padding: 0;
                            background: transparent !important;
                            border: none !important;
                            border-radius: 6px;
                            color: var(--color-base-font, #333);
                            cursor: pointer;
                            opacity: 0.3;
                            transition: all 0.2s ease;
                        }
                        .sxng-input-wrapper:focus-within .sxng-input-submit,
                        .sxng-input-submit:hover { 
                            opacity: 1; 
                            color: var(--color-result-link, #5e81ac); 
                            background: var(--color-base-background-hover, rgba(0,0,0,0.05)) !important;
                        }
                        .sxng-input-submit svg { width: 18px; height: 18px; fill: currentColor; }
                        .sxng-input-submit svg { width: 18px; height: 18px; fill: currentColor; }
'''

INTERACTIVE_HTML = '''
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
'''

CITATION_HELPER_JS = '''
                        function renderCitations(text, urls) {
                            const fragment = document.createDocumentFragment();
                            const re = /\[(\d{1,2}(?:\s*,\s*\d{1,2})*)\]/g;
                            let lastIdx = 0;
                            const matches = [...text.matchAll(re)];
                            
                            matches.forEach(match => {
                                if (match.index > lastIdx) {
                                    const s = document.createElement('span');
                                    s.className = 'sxng-chunk';
                                    // Preserve whitespace by not trimming
                                    s.textContent = text.substring(lastIdx, match.index);
                                    fragment.appendChild(s);
                                }
                                match[1].split(/\s*,\s*/).forEach(n => {
                                    const idx = parseInt(n.trim());
                                    if (idx >= 1 && idx <= urls.length) {
                                        const url = urls[idx-1];
                                        if (url) {
                                            const a = document.createElement('a');
                                            a.href = url;
                                            a.target = '_blank';
                                            a.style.cssText = 'text-decoration:none;color:var(--color-result-link);font-weight:bold;';
                                            a.textContent = `[${n.trim()}]`;
                                            a.className = 'sxng-chunk';
                                            fragment.appendChild(a);
                                        } else {
                                            const s = document.createElement('span');
                                            s.className = 'sxng-chunk';
                                            s.textContent = `[${n.trim()}]`;
                                            fragment.appendChild(s);
                                        }
                                    } else {
                                        const s = document.createElement('span');
                                        s.className = 'sxng-chunk';
                                        s.textContent = `[${n.trim()}]`;
                                        fragment.appendChild(s);
                                    }
                                });
                                lastIdx = match.index + match[0].length;
                            });
                            
                            if (lastIdx < text.length) {
                                const s = document.createElement('span');
                                s.className = 'sxng-chunk';
                                // Preserve whitespace by not trimming
                                s.textContent = text.substring(lastIdx);
                                fragment.appendChild(s);
                            }
                            return fragment;
                        }
'''

INTERACTIVE_JS = '''
                        const footer = document.getElementById('sxng-footer');
                        const input = document.getElementById('sxng-action-input');
                        // Inherited from outer scope: box, data, conversation

                        // Theme detection: inherit host accent color
                        if (window.getComputedStyle && box) {
                            try {
                                const docStyles = getComputedStyle(document.documentElement);
                                let accent = docStyles.getPropertyValue('--color-result-link').trim();
                                if (!accent) {
                                    const a = document.createElement('a');
                                    document.body.appendChild(a);
                                    accent = getComputedStyle(a).color;
                                    document.body.removeChild(a);
                                }
                                if (accent) {
                                    box.style.setProperty('--color-result-link', accent);
                                    box.style.setProperty('--sxng-ai-accent', accent);
                                }
                            } catch(e) {}
                        }

                        // Persist conversation state to URL hash (stateless)
                        const updateState = () => {
                            try {
                                const state = {
                                    t: conversation.turns.map(t => ({
                                        r: t.role === 'user' ? 'u' : 'a',
                                        c: t.content.replace(/\s+/g, ' ').trim()
                                    })),
                                    u: urls
                                };
                                const b64 = btoa(encodeURIComponent(JSON.stringify(state)).replace(/%([0-9A-F]{2})/g, (m,p)=>String.fromCharCode('0x'+p)));
                                history.replaceState(null, null, '#ai=' + b64);
                            } catch(e) {}
                        };

                        if (location.hash.includes('ai=')) {
                            try {
                                const b64 = location.hash.split('ai=')[1];
                                const json = decodeURIComponent(atob(b64).split('').map(c => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2)).join(''));
                                const state = JSON.parse(json);
                                if (state.t && state.t.length > 0) {
                                    // Restore URLs for citation indexing
                                    if (state.u && Array.isArray(state.u)) {
                                        urls = state.u;
                                    }
                                    
                                    conversation.turns = state.t.map(t => ({
                                        role: t.r === 'u' ? 'user' : 'assistant',
                                        content: t.c.trim(),
                                        ts: 0
                                    }));
                                    
                                    // Helper function to inject citations into text
                                    const injectCitations = (text) => {
                                        return renderCitations(text, urls);
                                    };
                                    
                                    data.innerHTML = '';
                                    conversation.turns.forEach((turn, i) => {
                                        if (turn.role === 'user') {
                                            if (turn.content !== conversation.originalQuery) {
                                                const u = document.createElement('span');
                                                u.className = 'sxng-user-msg';
                                                u.textContent = turn.content;
                                                data.appendChild(u);
                                                const clr = document.createElement('div');
                                                clr.style.clear = 'both';
                                                data.appendChild(clr);
                                            }
                                        } else {
                                            // Inject citations for assistant responses
                                            data.appendChild(injectCitations(turn.content));
                                        }
                                    });
                                    box.style.display = 'block';
                                    if(wrapper) wrapper.style.display = '';
                                    if(footer && is_interactive) footer.style.display = 'flex';
                                    restored = true;
                                }
                            } catch(e) { console.warn('Restore failed', e); }
                        }
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

                        const handleAction = async (e) => {
                            if (e) e.preventDefault();
                            const val = input.value.trim();
                            
                            conversation.turns.push({role: 'user', content: val, ts: Date.now()});
                            updateState();
                            
                            const currentText = conversation.turns.slice(0, -1).slice(-6)
                                .map(t => (t.role === 'user' ? 'Q' : 'A') + ': ' + t.content)
                                .join('\\n\\n');

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
                                const clr = document.createElement('div');
                                clr.style.clear = 'both';
                                data.appendChild(clr);

                                const newCursor = document.createElement('span');
                                newCursor.className = 'sxng-cursor';
                                data.appendChild(newCursor);
                                
                                const synthesized = synthesizeQuery(q_init, val);
                                let auxContext = null;
                                try {
                                    const auxData = await fetch('/ai-auxiliary-search', {
                                        method: 'POST',
                                        headers: {'Content-Type': 'application/json'},
                                        body: JSON.stringify({query: synthesized, lang: lang_init, offset: urls.length})
                                    }).then(r => r.json());
                                    if (auxData.context) {
                                        const originalBackground = conversation.originalContext.substring(0, 1500);
                                        auxContext = `FRESH SOURCES (most relevant):\\n${auxData.context}\\n\\nBACKGROUND (for reference):\\n${originalBackground}`;
                                        if (auxData.new_urls && Array.isArray(auxData.new_urls)) {
                                            urls = urls.concat(auxData.new_urls);
                                        }
                                    }
                                } catch (err) {}
                                
                                await startStream(val, currentText, auxContext);
                                updateState();
                            } else {
                                const cursor = data.querySelector('.sxng-cursor');
                                if (cursor) cursor.remove();
                                data.appendChild(document.createElement('br'));
                                data.appendChild(document.createElement('br'));
                                const newCursor = document.createElement('span');
                                newCursor.className = 'sxng-cursor';
                                data.appendChild(newCursor);
                                await startStream("Continue", currentText);
                                updateState();
                            }
                        };

                        document.getElementById('sxng-action-form').onsubmit = handleAction;
                        input.onfocus = () => {
                            setTimeout(() => {
                                input.scrollIntoView({behavior: 'smooth', block: 'center'});
                            }, 300);
                        };

                        const _origStream = startStream;
                        startStream = async function(...args) {
                            if (args.length === 0 && restored) return;
                            await _origStream.apply(this, args);
                            if (args.length === 0) updateState();
                        };
'''


import typing
if typing.TYPE_CHECKING:
    from searx.search import SearchWithPlugins
    from searx.extended_types import SXNG_Request
    from . import PluginCfg

class SXNGPlugin(Plugin):
    id = "ai_answers"

    def __init__(self, plg_cfg: "PluginCfg"):
        super().__init__(plg_cfg)
        self.info = PluginInfo(
            id=self.id,
            name=gettext(f"{PLUGIN_NAME} Plugin"),
            description=gettext("Live AI search answers using LLM providers."),
            preference_section="general",
        )
        self._load_config()



    def _load_config(self):
        self.interactive = os.getenv('LLM_INTERACTIVE', 'true').lower().strip() in ('true', '1', 'yes', 'on')
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
            elif 'openai.azure.com' in url_lower or '.azure.com' in url_lower:
                raw_provider = 'azure'
            elif 'huggingface.co' in url_lower:
                raw_provider = 'huggingface'
            else:
                # Unknown URL fallback to OpenAI-compatible
                raw_provider = 'openai'
                logger.info(f"{PLUGIN_NAME}: Using OpenAI-compatible mode for custom URL")
        
        if not raw_provider:
            self.provider = ''
            self.model = ''
            self.is_gemini = False
            self.api_key = ''
            return
        
        if raw_provider not in PROVIDER_PRESETS:
            logger.warning(f"{PLUGIN_NAME}: Unknown provider '{raw_provider}', falling back to 'openai'")
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
            self.context_deep_count = max(0, int(os.getenv('LLM_CONTEXT_DEEP_COUNT', 5)))
        except ValueError:
            self.context_deep_count = 5
        try:
            self.context_shallow_count = max(0, int(os.getenv('LLM_CONTEXT_SHALLOW_COUNT', 15)))
        except ValueError:
            self.context_shallow_count = 15

        self.allowed_tabs = set(t.strip() for t in os.getenv('LLM_TABS', DEFAULT_TABS).split(','))
        
        preset_url = preset['url']
        if preset_url and '{model}' in preset_url:
            preset_url = preset_url.format(model=self.model)
        
        raw_url = os.getenv('LLM_URL', '').strip() or preset_url
        if not raw_url.startswith(('http://', 'https://')):
            raw_url = f"https://{raw_url}"
        self.endpoint_url = raw_url
        
        if self.api_key:
            self.secret = os.getenv('SXNG_LLM_SECRET') or hashlib.sha256(self.api_key.encode()).hexdigest()
        else:
             self.secret = os.getenv('SXNG_LLM_SECRET', '')

    def _parse_aux_results(self, raw_results, raw_infoboxes, raw_answers):
        results = []
        limit = self.context_deep_count + self.context_shallow_count
        for r in raw_results[:limit]:
            results.append({
                'title': r.get('title', ''),
                'content': r.get('content', ''),
                'url': r.get('url', ''),
                'publishedDate': r.get('publishedDate', '')
            })
        
        infoboxes = []
        for ib in raw_infoboxes[:2]:
            infoboxes.append({
                'name': ib.get('infobox', '') or ib.get('title', ''),
                'content': ib.get('content', '')[:400],
                'attributes': ib.get('attributes', [])[:3]
            })
            
        answers = [a.get('answer', '') for a in raw_answers[:2] 
                   if a.get('answer') and not str(a.get('answer')).startswith('<')]
                   
        return results, infoboxes, answers

    def _format_aux_context_string(self, results, infoboxes, answers, offset):
        sections = []
        aux_urls = []
        
        kg_lines = []
        for ib in infoboxes:
            if ib.get('name'):
                content = ib.get('content', '')
                kg_lines.append(f"INFOBOX [{ib['name']}]: {content}")
        
        for a in answers:
            if a:
                kg_lines.append(f"ANSWER: {a}")
                
        if kg_lines:
            sections.append('KNOWLEDGE GRAPH:\n' + '\n'.join(kg_lines))
            
        source_lines = []
        for i, r in enumerate(results):
            url = r.get('url', '')
            aux_urls.append(url)
            # Match JS logic: domain extraction
            domain = urlparse(url).netloc.replace('www.', '')
            date = f" ({r['publishedDate']})" if r.get('publishedDate') else ''
            title = r.get('title', '')
            content = r.get('content', '')[:600]
            # [index] domain(date): title: content
            idx = i + 1 + offset
            source_lines.append(f"[{idx}] {domain}{date}: {title}: {content}")
            
        if source_lines:
            sections.append('SOURCES:\n' + '\n'.join(source_lines))
            
        return "\n\n".join(sections), aux_urls



    def init(self, app):
        if not self.provider:
            return

        @app.route('/ai-auxiliary-search', methods=['POST'])
        def ai_auxiliary_search():
            if not self.api_key:
                abort(403)
            
            data = request.json or {}
            query = data.get('query', '').strip()
            lang = data.get('lang', 'all')
            categories = data.get('categories', 'general')
            offset = data.get('offset', 0)
            if not query:
                return jsonify({'results': []})
            
            # Direct kernel access (bypasses HTTP loopback)
            try:
                from searx.search import SearchWithPlugins
                from searx.search.models import SearchQuery
                from searx.query import RawTextQuery
                from searx.webadapter import get_engineref_from_category_list
                
                preferences = getattr(request, 'preferences', None)
                disabled_engines = preferences.engines.get_disabled() if preferences else []
                rtq = RawTextQuery(query, disabled_engines)
                if isinstance(categories, str):
                    category_list = [c.strip() for c in categories.split(',') if c.strip()]
                else:
                    category_list = categories or ['general']
                
                enginerefs = get_engineref_from_category_list(category_list, disabled_engines)
                sq = SearchQuery(
                    query=rtq.getQuery(),
                    engineref_list=enginerefs,
                    lang=lang,
                    pageno=1,
                )
                # Empty plugins list prevents recursion
                search_obj = SearchWithPlugins(sq, request, user_plugins=[])
                result_container = search_obj.search()
                
                raw_results = result_container.get_ordered_results()
                raw_infoboxes = getattr(result_container, 'infoboxes', [])
                raw_answers = getattr(result_container, 'answers', [])
                
                results, infoboxes, answers = self._parse_aux_results(raw_results, raw_infoboxes, raw_answers)
                
                context_str, new_urls = self._format_aux_context_string(results, infoboxes, answers, offset)

                return jsonify({
                    'context': context_str,
                    'new_urls': new_urls,
                    'results': results, 
                    'infoboxes': infoboxes,
                    'answers': answers,
                    'query': query
                })

            except ImportError:
                try:
                    search_url = f'{request.url_root}search'
                    params = {
                        'q': query,
                        'format': 'json',
                        'categories': categories,
                        'language': lang
                    }
                    
                    headers = {
                        'X-AI-Auxiliary': '1',
                        'Accept-Language': request.headers.get('Accept-Language', '')
                    }
                    
                    
                    res = network.get(search_url, params=params, headers=headers, timeout=2)
                    search_data = res.json()
                        
                    

                    results, infoboxes, answers = self._parse_aux_results(
                        search_data.get('results', []),
                        search_data.get('infoboxes', []),
                        search_data.get('answers', [])
                    )
                    
                    context_str, new_urls = self._format_aux_context_string(results, infoboxes, answers, offset)

                    return jsonify({
                        'context': context_str,
                        'new_urls': new_urls,
                        'results': results, 
                        'infoboxes': infoboxes,
                        'answers': answers,
                        'query': query
                    })
                except Exception as e:
                    return jsonify({'results': [], 'error': str(e)})
            except Exception as e:
                return jsonify({'results': [], 'error': str(e)})

        @app.route('/ai-stream', methods=['POST'])
        def handle_ai_stream():
            data = request.json or {}
            if data.get('warmup'):
                return Response('', status=204)
            
            token = data.get('tk', '')
            q = data.get('q', '')
            lang = data.get('lang', 'all')
            
            try:
                ts, sig = token.rsplit('.', 1)
                expected = hashlib.sha256(f"{ts}{self.secret}".encode()).hexdigest()
                if sig != expected or (time.time() - float(ts)) > TOKEN_EXPIRY_SEC:
                    abort(403)
            except (ValueError, KeyError, AttributeError):
                abort(403)

            context_text = data.get('context', '')
            prev_answer = (data.get('prev_answer') or '')[-4000:]
            
            if not self.api_key:
                return Response("Missing API key or query", status=400)
            
            today = time.strftime("%Y-%m-%d")
            target_words = int(self.max_tokens * 0.2)
            lang_instruction = f" Respond in {lang}." if lang not in ('all', 'auto') else ""

            SYSTEM = f"You are a search synthesis engine. Direct, grounded, citation-accurate. Today is {today}.{lang_instruction}"
            max_source_idx = 0
            if context_text:
                indices = re.findall(r'\[(\d+)\]', context_text)
                if indices:
                    max_source_idx = max(map(int, indices))

            CORE_RULES = [
                "DENSITY 4/5: Expert-briefing level. No filler, no transitions. Every sentence = new information.",
                f"BREVITY: {target_words} words max. Complete, not verbose.",
                f"CITATIONS: Cite format is [n] for facts from grounding sources",
                "NO HEDGE: State answers confidently. Note uncertainty only if critical.",
            ]

            if q == "Continue":
                task = "CONTINUE: Pick up exactly where previous answer stopped. No repetition. Seamless flow."
            elif prev_answer:
                task = "FOLLOW-UP: Address the new question using prior context. Prioritize the new query."
            else:
                task = "ANSWER FIRST: Lead with the direct answer. No preamble, no context-setting."

            grounding = "GROUNDING: KNOWLEDGE GRAPH > DEEP > SHALLOW." if context_text else "GROUNDING: No sources available. Use knowledge and note 'based on general knowledge'."
            history_rule = "HISTORY: Refer to prior exchange for context. Ideally, do not repeat any claims." if prev_answer else None

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
                if '?' in self.endpoint_url:
                    url = f"{self.endpoint_url}&key={self.api_key}"
                else:
                    url = f"{self.endpoint_url}?key={self.api_key}"

                try:
                    payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"maxOutputTokens": self.max_tokens, "temperature": self.temperature, "stopSequences": ["</answer>"]}}
                    headers = {"Content-Type": "application/json"}
                    res, chunk_gen = network.stream('POST', url, json=payload, headers=headers, timeout=60)
                    
                    if res.status_code != 200:
                        for _ in chunk_gen: pass  # Drain to prevent resource leak
                        logger.error(f"{PLUGIN_NAME}: Gemini API {res.status_code}")
                        return

                    decoder = json.JSONDecoder()
                    buffer = ""
                    utf8_decoder = codecs.getincrementaldecoder("utf-8")(errors='replace')
                    for chunk in chunk_gen:
                        if not chunk: continue
                        buffer += utf8_decoder.decode(chunk, final=False)
                        while buffer:
                            buffer = buffer.lstrip()
                            if not buffer: break
                            try:
                                obj, idx = decoder.raw_decode(buffer)
                                items = obj if isinstance(obj, list) else [obj]
                                for item in items:
                                    candidates = item.get('candidates', [])
                                    if candidates:
                                        content = candidates[0].get('content', {})
                                        parts = content.get('parts', [])
                                        if parts:
                                            text = parts[0].get('text', '')
                                            if text: yield text
                                buffer = buffer[idx:]
                            except json.JSONDecodeError: break
                except Exception as e:
                    logger.error(f"{PLUGIN_NAME}: Gemini stream error: {e}")

            def stream_openai_compatible():
                try:
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
                    res, chunk_gen = network.stream('POST', self.endpoint_url, json=payload, headers=headers, timeout=60)

                    if res.status_code != 200:
                        for _ in chunk_gen: pass
                        logger.error(f"{PLUGIN_NAME}: {self.provider} API {res.status_code}")
                        return

                    decoder = json.JSONDecoder()
                    buffer = b""
                    for chunk in chunk_gen:
                        if not chunk: continue
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
                    logger.error(f"{PLUGIN_NAME}: {self.provider} stream error: {e}")

            generator = stream_gemini if self.is_gemini else stream_openai_compatible
            return Response(generator(), mimetype='text/event-stream', headers={
                'X-Accel-Buffering': 'no',
                'Cache-Control': 'no-cache, no-store',
                'Connection': 'keep-alive',
                'Content-Encoding': 'identity'
            })
        return True

    def _assemble_context(self, search, raw_results) -> str:
        """Builds three-tier context string from search results."""
        context_parts = []
        knowledge_graph_lines = []
        for infobox in getattr(search.result_container, 'infoboxes', [])[:3]:
            ib_name = infobox.get('infobox', '') or infobox.get('title', '')
            ib_content = str(infobox.get('content', '')).replace('\n', ' ').strip()
            
            if ib_name:
                parts = [f"INFOBOX [{ib_name}]:"]
                if ib_content:
                    parts.append(ib_content[:600])
                for attr in infobox.get('attributes', [])[:5]:
                    attr_label = attr.get('label', '')
                    attr_value = attr.get('value', '')
                    if attr_label and attr_value:
                        parts.append(f"  {attr_label}: {attr_value}")
                
                knowledge_graph_lines.append(" ".join(parts) if len(parts) == 2 else "\n".join(parts))

        for answer in getattr(search.result_container, 'answers', []):
            if hasattr(answer, 'answer'):
                ans_text = str(answer.answer).replace('\n', ' ').strip()[:300]
                ans_url = getattr(answer, 'url', '')
                if ans_text and not ans_text.startswith('<'):
                    knowledge_graph_lines.append(f"ANSWER: {ans_text}" + (f" [via {ans_url}]" if ans_url else ""))
        
        if knowledge_graph_lines:
            context_parts.append("KNOWLEDGE GRAPH:\n" + "\n".join(knowledge_graph_lines))
        
        deep_lines = []
        for i, r in enumerate(raw_results[:self.context_deep_count]):
            domain = urlparse(r.get('url', '')).netloc
            date = r.get('publishedDate')
            date_str = f" ({date})" if date else ""
            title = (r.get('title') or "").replace('\n', ' ').strip()
            content = str(r.get('content', '')).replace('\n', ' ').strip()[:800]
            deep_lines.append(f"[{i+1}] {domain}{date_str}: {title}: {content}")
        
        if deep_lines:
            context_parts.append("DEEP SOURCES:\n" + "\n".join(deep_lines))
            
        if self.context_shallow_count > 0:
            shallow_lines = []
            start_idx = self.context_deep_count
            end_idx = self.context_deep_count + self.context_shallow_count
            for i, r in enumerate(raw_results[start_idx:end_idx]):
                domain = urlparse(r.get('url', '')).netloc.replace('www.', '')
                title = (r.get('title') or '').replace('\n', ' ').strip()[:60]
                shallow_lines.append(f"[{i+1+start_idx}] {domain}: {title}")
            
            if shallow_lines:
                context_parts.append("SHALLOW SOURCES (headlines):\n" + "\n".join(shallow_lines))
        
        return "\n\n".join(context_parts)

    def post_search(self, request: "SXNG_Request", search: "SearchWithPlugins") -> EngineResults:
        results = EngineResults()
        try:
            if request and hasattr(request, 'headers') and request.headers.get('X-AI-Auxiliary'):
                return results
            
            current_tabs = set(search.search_query.categories)
            if not current_tabs: current_tabs = {'general'}

            if not self.active or not self.api_key or search.search_query.pageno > 1 or not self.allowed_tabs.intersection(current_tabs):
                return results

            raw_results = search.result_container.get_ordered_results()
            context_str = self._assemble_context(search, raw_results)


            ts = str(int(time.time()))
            q_clean = search.search_query.query.strip()
            lang = search.search_query.lang
            sig = hashlib.sha256(f"{ts}{self.secret}".encode()).hexdigest()
            tk = f"{ts}.{sig}"
            
            b64_context = base64.b64encode(context_str.encode('utf-8')).decode('utf-8')
            js_q = json.dumps(q_clean)
            js_lang = json.dumps(lang)
            total_context_count = self.context_deep_count + self.context_shallow_count
            js_urls = json.dumps([r.get('url') for r in raw_results[:total_context_count]])

            is_interactive = self.interactive
            
            interactive_css = INTERACTIVE_CSS if is_interactive else ''
            interactive_html = INTERACTIVE_HTML if is_interactive else ''
            interactive_js_init = INTERACTIVE_JS if is_interactive else ''

            interactive_js_complete = "footer.style.display = 'flex';" if is_interactive else ''
            stream_fn_sig = 'async function startStream(overrideQ = null, prevAnswer = null, auxContext = null)'
            stream_q = 'overrideQ || q_init' if is_interactive else 'q_init'
            stream_body = f'''prev_answer: prevAnswer''' if is_interactive else ''

            html_payload = f'''
                <article id="sxng-stream-box" class="answer" style="display:none; margin: 1rem 0;">
                    <style>
                        @keyframes sxng-fade-pulse {{
                            0%, 100% {{ opacity: 0.1; }}
                            50% {{ opacity: 1; }}
                        }}
                        @keyframes sxng-fade-in {{
                            from {{ opacity: 0; }}
                            to {{ opacity: 1; }}
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
                            background: var(--color-result-link-visited, var(--color-result-link, #b48ead));
                            vertical-align: text-bottom;
                            animation: sxng-fade-pulse 1s ease-in-out infinite;
                            margin-right: 0.2rem;
                            border-radius: 2px;
                        }}
                        .sxng-chunk {{
                            opacity: 1;
                        }}
                        @media (min-width: 769px) {{
                            .sxng-chunk {{
                                animation: sxng-fade-in 0.3s ease-out;
                            }}
                        }}
                        {interactive_css}
                    </style>
                    <p id="sxng-stream-data" style="white-space: pre-wrap; color: var(--color-result-description); font-size: 0.95rem; margin:0;"><span class="sxng-cursor"></span></p>
                    {interactive_html}
                    <script>
                    (async () => {{
                        const is_interactive = {'true' if is_interactive else 'false'};
                        const q_init = {js_q};
                        const lang_init = {js_lang};
                        let urls = {js_urls};
                        const b64_init = "{b64_context}";
                        const tk_init = "{tk}";
                        const conversation = {{
                            originalQuery: q_init,
                            originalContext: new TextDecoder().decode(Uint8Array.from(atob(b64_init), c => c.charCodeAt(0))),
                            originalSources: [...urls],
                            turns: [{{role: 'user', content: q_init, ts: Date.now()}}]
                        }};
                        const box = document.getElementById('sxng-stream-box');
                        const data = document.getElementById('sxng-stream-data');
                        const wrapper = box.closest('.answer');
                        if (wrapper) wrapper.style.display = 'none';
                        let restored = false;
                        let isStreaming = false;
                        
                        {CITATION_HELPER_JS}

                        {interactive_js_init}
                        function synthesizeQuery(original, followup) {{
                            // combine with original for context, stripping generic question starters
                            const cleanOrig = original.replace(/^(what|how|why|when|where|who|which|is|are|can|does|do)(\s+(is|are|do|does|can|to|a|an|the))?\s+/i, '');
                            const origWords = cleanOrig.split(' ').slice(0, 12);
                            return `${{origWords.join(' ')}} ${{followup}}`.trim();
                        }}



                        {stream_fn_sig} {{
                            if (isStreaming) {{
                                console.warn('[AI Answers] Stream already in progress, ignoring duplicate call');
                                return;
                            }}
                            
                            isStreaming = true;
                            try {{
                                const ctx = auxContext || conversation.originalContext;
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
                                let lastScrollKick = 0;
                                let collectedResponse = '';

                                let buffer = '';
                                const flushBuffer = (force = false) => {{
                                    if (!buffer) return;
                                    
                                    if (force) {{
                                        const fragment = renderCitations(buffer, urls);
                                        if (cursor) cursor.before(fragment);
                                        else data.appendChild(fragment);
                                        buffer = '';
                                        return;
                                    }}

                                    while (true) {{
                                        const match = buffer.match(/(\\[\\d+(?:,\\s*\\d+)*\\])/);
                                        
                                        if (!match) break;
                                        
                                        const preText = buffer.substring(0, match.index);
                                        if (preText) {{
                                            const s = document.createElement('span');
                                            s.className = 'sxng-chunk';
                                            s.textContent = preText;
                                            cursor.before(s);
                                        }}

                                        const citationText = match[0];
                                        const fragment = renderCitations(citationText, urls);
                                        cursor.before(fragment);

                                        buffer = buffer.substring(match.index + match[0].length);
                                    }}

                                    const openIdx = buffer.lastIndexOf('[');
                                    if (openIdx === -1) {{
                                        if (buffer) {{
                                            const s = document.createElement('span');
                                            s.className = 'sxng-chunk';
                                            s.textContent = buffer;
                                            cursor.before(s);
                                            buffer = '';
                                        }}
                                    }} else {{
                                        const safeChunk = buffer.substring(0, openIdx);
                                        if (safeChunk) {{
                                            const s = document.createElement('span');
                                            s.className = 'sxng-chunk';
                                            s.textContent = safeChunk;
                                            cursor.before(s);
                                        }}
                                        buffer = buffer.substring(openIdx);
                                        
                                        if (buffer.length > 50) {{
                                            const s = document.createElement('span');
                                            s.className = 'sxng-chunk';
                                            s.textContent = buffer[0];
                                            cursor.before(s);
                                            buffer = buffer.substring(1);
                                        }}
                                    }}
                                }};

                                while (true) {{
                                    const {{done, value}} = await reader.read();
                                    if (done) break;

                                    const chunk = decoder.decode(value, {{stream: true}});
                                    if (chunk) {{
                                        collectedResponse += chunk;
                                        
                                        // Initial scroll/focus logic (only once)
                                        if (!started) {{
                                            const trimmed = chunk.replace(/^[\\s.,;:!?]+/, '');
                                            if (!trimmed && !collectedResponse.trim()) continue; // Skip leading garbage
                                            if (cursor && !cursor.isConnected) data.appendChild(cursor);
                                            started = true;
                                        }}

                                        buffer += chunk;
                                        flushBuffer(false);

                                        const now = Date.now();  // Periodic repaint for mobile
                                        if (now - lastScrollKick > 500) {{
                                            lastScrollKick = now;
                                            void window.getComputedStyle(data).opacity;
                                        }}
                                    }}
                                }}
                                
                                // Final flush of any partial text (e.g. unclosed brackets)
                                flushBuffer(true);
                                
                                if (cursor) cursor.remove();

                                // Cleanup trailing newlines
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
                                    const cursor = data.querySelector('.sxng-cursor');
                                    if (cursor) cursor.remove();
                                    const errSpan = document.createElement('span');
                                    errSpan.style.color = '#bf616a';
                                    errSpan.textContent = 'No response received. Check API configuration.';
                                    data.appendChild(errSpan);
                                    return;
                                }}

                                {interactive_js_complete}

                                if (collectedResponse) {{
                                    conversation.turns.push({{role: 'assistant', content: collectedResponse.trim(), ts: Date.now()}});
                                }}

                            }} catch (e) {{
                                console.error(e);
                                if (box.parentElement) box.parentElement.remove();
                                else box.remove();
                            }} finally {{
                                // Always release lock, even on error
                                isStreaming = false;
                            }}
                        }}

                        // Warmup handshake
                        fetch('/ai-stream', {{
                            method: 'POST',
                            headers: {{'Content-Type': 'application/json'}},
                            body: JSON.stringify({{warmup: true}}),
                            keepalive: true
                        }}).catch(() => {{}});

                        if (!restored) startStream();
                    }})();
                    </script>
                </article>
            '''
            search.result_container.answers.add(results.types.Answer(answer=Markup(html_payload)))
        except Exception as e:
            logger.error(f"{PLUGIN_NAME}: {e}")
        return results
