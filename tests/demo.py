import sys
import os
import logging
from types import ModuleType
from flask import Flask, request

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
# os.environ.setdefault('LLM_STYLE', 'interactive')  # Removed to let plugin config decide defaults

# SearXNG module mocks
searx = ModuleType("searx")
searx_plugins = ModuleType("searx.plugins")
searx_results = ModuleType("searx.result_types")

class MockPlugin:
    def __init__(self, cfg):
        self.active = getattr(cfg, 'active', True)

class MockPluginInfo:
    def __init__(self, **kwargs):
        self.meta = kwargs

class MockEngineResults:
    def __init__(self):
        self.types = ModuleType("types")
        self.types.Answer = lambda *args, **kwargs: kwargs.get('answer', args[0] if args else "")
        self._results = []
    
    def add(self, res):
        self._results.append(res)

searx_plugins.Plugin = MockPlugin
searx_plugins.PluginInfo = MockPluginInfo
searx_results.EngineResults = MockEngineResults

sys.modules["searx"] = searx
sys.modules["searx.plugins"] = searx_plugins
sys.modules["searx.result_types"] = searx_results

# Network module mock
searx_network = ModuleType("searx.network")
def mock_network_call(method, url, **kwargs):
    import http.client, ssl, json
    from urllib.parse import urlparse
    
    parsed = urlparse(url)
    port = parsed.port or (443 if parsed.scheme=='https' else 80)
    target = f"{parsed.hostname}:{port}"
    
    if parsed.scheme == 'https':
        conn = http.client.HTTPSConnection(target, timeout=30, context=ssl.create_default_context())
    else:
        conn = http.client.HTTPConnection(target, timeout=30)
    
    headers = kwargs.get('headers', {})
    body = None
    if kwargs.get('json'):
        body = json.dumps(kwargs['json'])
    elif kwargs.get('data'):
        body = kwargs['data']

    path = parsed.path
    if parsed.query:
        path += f"?{parsed.query}"
    
    if kwargs.get('params'):
        from urllib.parse import urlencode
        query_str = urlencode(kwargs['params'])
        if '?' in path:
            path += f"&{query_str}"
        else:
            path += f"?{query_str}"

    conn.request(method, path, body=body, headers=headers)
    return conn.getresponse()

def mock_stream(method, url, **kwargs):
    res = mock_network_call(method, url, **kwargs)
    
    class MockResponse:
        def __init__(self, r):
            self.status_code = r.status
            self.text = "Mock Response" # Stub
            self._r = r
    
    def generator():
        while True:
            chunk = res.read(128)
            if not chunk: break
            yield chunk

    return MockResponse(res), generator()

def mock_get(url, **kwargs):
    import json
    res = mock_network_call('GET', url, **kwargs)
    
    class MockResponse:
        def __init__(self, r):
            self.status_code = r.status
            self._content = r.read()
            self.text = self._content.decode('utf-8')
        
        def json(self):
            return json.loads(self.text)
            
    return MockResponse(res)

searx_network.stream = mock_stream
searx_network.get = mock_get
sys.modules["searx.network"] = searx_network

from ai_answers import SXNGPlugin
from flask_babel import Babel

app = Flask(__name__)
babel = Babel(app)

class MockConfig:
    active = True

plugin = SXNGPlugin(MockConfig())
plugin.init(app)

@app.route("/search")
def mock_search():
    query = request.args.get("q", "")
    format_type = request.args.get("format", "html")
    
    if format_type != "json":
        return "Demo only supports JSON format", 400
    
    results = [
        {"title": f"Result 1 for: {query}", "content": f"This is simulated content about {query}. It contains relevant information.", "url": f"https://example.com/1/{query.replace(' ', '-')}", "publishedDate": "2026-01-18"},
        {"title": f"Result 2 for: {query}", "content": f"Additional information regarding {query}. More context and details.", "url": f"https://example.com/2/{query.replace(' ', '-')}", "publishedDate": "2026-01-17"},
        {"title": f"Result 3 for: {query}", "content": f"Further reading on {query}. Expert analysis.", "url": f"https://example.com/3/{query.replace(' ', '-')}", "publishedDate": "2026-01-16"},
    ]
    
    return {
        "results": results,
        "infoboxes": [],
        "answers": [],
        "suggestions": [f"{query} explained", f"{query} tutorial"]
    }

@app.route("/")
def index():
    query = request.args.get("q", "why is the sky blue")
    
    class MockSearchQuery:
        pageno = 1
        lang = 'en'
        categories = ['general']
    MockSearchQuery.query = query
    
    class MockSearch:
        search_query = MockSearchQuery()
        class MockResultContainer:
            def __init__(self):
                self.answers = set()

            def get_ordered_results(self):
                base_results = [
                    {"title": "Wikipedia", "content": "The sky appears blue due to Rayleigh scattering of sunlight. When sunlight enters the atmosphere, it collides with gas molecules and scatters in all directions. Blue light scatters more than other colors because it travels in shorter waves.", "url": "https://en.wikipedia.org/wiki/Rayleigh_scattering", "publishedDate": "2026-01-15"},
                    {"title": "NASA Science", "content": "Shorter blue wavelengths scatter more than longer red wavelengths. This phenomenon, discovered by Lord Rayleigh in the 1870s, explains why we see a blue sky during the day.", "url": "https://science.nasa.gov/blue-sky", "publishedDate": "2026-01-10"},
                    {"title": "Physics Today", "content": "The atmosphere acts as a filter, scattering blue light in all directions while letting other colors pass through more directly.", "url": "https://physicstoday.org/atmosphere", "publishedDate": "2026-01-01"},
                    {"title": "Scientific American", "content": "At sunset, light travels through more atmosphere, scattering away the blue and leaving reds and oranges.", "url": "https://scientificamerican.com/sunset", "publishedDate": "2025-12-20"},
                    {"title": "National Geographic", "content": "Ocean color also results from light scattering and absorption by water molecules.", "url": "https://nationalgeographic.com/ocean-blue", "publishedDate": "2025-12-15"},
                ]
                broad_results = [
                    {"title": "MIT OpenCourseWare: Atmospheric Physics", "content": "Course materials.", "url": "https://ocw.mit.edu/physics"},
                    {"title": "NOAA: Understanding the Atmosphere", "content": "Educational resource.", "url": "https://noaa.gov/atmosphere"},
                    {"title": "BBC Science: Why is the sky blue?", "content": "Explainer article.", "url": "https://bbc.com/science/sky"},
                    {"title": "Khan Academy: Light and Color", "content": "Video lesson.", "url": "https://khanacademy.org/light"},
                    {"title": "HowStuffWorks: Rayleigh Scattering", "content": "Detailed explanation.", "url": "https://howstuffworks.com/rayleigh"},
                    {"title": "Physics Stack Exchange: Sky color discussion", "content": "Q&A thread.", "url": "https://physics.stackexchange.com/sky"},
                    {"title": "Quora: Atmospheric optics explained", "content": "Community answers.", "url": "https://quora.com/atmosphere"},
                ]
                if 'quantum' in query.lower():
                    return [
                        {"title": "IBM Quantum", "content": "Quantum computers rely on qubits, which can represent 0, 1, or both via superposition. They solve complex problems faster.", "url": "https://www.ibm.com/quantum", "publishedDate": "2026-01-15"},
                        {"title": "Nature Physics", "content": "Entanglement allows qubits to be correlated instantly across distances. This is key for quantum cryptography and teleportation.", "url": "https://nature.com/articles/quantum", "publishedDate": "2026-01-10"},
                        {"title": "Wikipedia", "content": "Quantum computing uses quantum mechanics. Major applications include drug discovery and materials science.", "url": "https://en.wikipedia.org/wiki/Quantum_computing", "publishedDate": "2025-12-01"}
                    ] + broad_results
                return base_results + broad_results
        result_container = MockResultContainer()

    search = MockSearch()
    plugin.post_search(None, search)
    
    injection_html = ""
    if search.result_container.answers:
        injection_html = list(search.result_container.answers)[0]
    
    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>AI Answers Demo</title>
        <style>
            body {{ 
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; 
                padding: 2rem; 
                max-width: 800px; 
                margin: 0 auto;
                background: #2e3440;
                color: #eceff4;
            }}
            :root {{
                --color-result-border: #3b4252;
                --color-result-description: #d8dee9;
                --color-base-font: #88c0d0;
                --color-result-link: #81a1c1;
            }}
            h1 {{ color: #88c0d0; }}
            .meta {{ color: #81a1c1; font-size: 0.9rem; }}
            hr {{ border-color: #4c566a; }}
            a {{ color: #88c0d0; }}
        </style>
    </head>
    <body>
        <div style="margin-top: 2rem;"></div>
        <p class="meta">Provider: <strong>{plugin.provider or 'Not configured'}</strong> | Model: <strong>{plugin.model or 'N/A'}</strong></p>
        <p>Query: <strong>{query}</strong></p>
        <hr>
        {injection_html if injection_html else '<p style="color:#f66;">Plugin inactive. Set LLM_PROVIDER and LLM_KEY in .env</p>'}
        <hr>
        <p class="meta">Try: <a href="/?q=what+is+quantum+computing">/?q=what+is+quantum+computing</a></p>
    </body>
    </html>
    """

if __name__ == "__main__":
    print("AI Answers - Demo\n")
    print(f"  Provider: {plugin.provider or 'NOT SET'}")
    print(f"  Model:    {plugin.model or 'N/A'}")
    print(f"  Mode:     {'interactive' if plugin.interactive else 'simple'}")
    print(f"  Status:   {'active' if plugin.api_key else 'inactive (no LLM_KEY)'}")
    print(f"\n  http://localhost:5000/?q=why+is+the+sky+blue\n")
    app.run(debug=False, port=5000)
