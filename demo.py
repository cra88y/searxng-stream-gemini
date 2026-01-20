"""
AI Answers Plugin - Interactive Demo Server
Simulates SearXNG environment for local development and testing.

Usage: python demo.py
Then visit: http://localhost:5000/?q=your+query+here

Requires: pip install flask flask-babel python-dotenv
"""

import sys
import os
import logging
from types import ModuleType
from flask import Flask, request
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
load_dotenv()
os.environ.setdefault('LLM_STYLE', 'interactive')

# Mock SearXNG modules
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

from ai_answers import SXNGPlugin
from flask_babel import Babel

app = Flask(__name__)
babel = Babel(app)

class MockConfig:
    active = True

plugin = SXNGPlugin(MockConfig())
plugin.init(app)

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
                if 'quantum' in query.lower():
                    return [
                        {"title": "IBM Quantum", "content": "Quantum computers rely on qubits, which can represent 0, 1, or both via superposition. They solve complex problems faster.", "url": "https://www.ibm.com/quantum", "publishedDate": "2026-01-15"},
                        {"title": "Nature Physics", "content": "Entanglement allows qubits to be correlated instantly across distances. This is key for quantum cryptography and teleportation.", "url": "https://nature.com/articles/quantum", "publishedDate": "2026-01-10"},
                        {"title": "Wikipedia", "content": "Quantum computing uses quantum mechanics. Major applications include drug discovery and materials science.", "url": "https://en.wikipedia.org/wiki/Quantum_computing", "publishedDate": "2025-12-01"}
                    ]
                return [
                    {"title": "Wikipedia", "content": "The sky appears blue due to Rayleigh scattering of sunlight.", "url": "https://en.wikipedia.org/wiki/Rayleigh_scattering", "publishedDate": "2026-01-15"},
                    {"title": "NASA Science", "content": "Shorter blue wavelengths scatter more than longer red wavelengths.", "url": "https://science.nasa.gov/blue-sky", "publishedDate": "2026-01-10"},
                    {"title": "Physics Today", "content": "The atmosphere acts as a filter, scattering blue light in all directions.", "url": "https://physicstoday.org/atmosphere", "publishedDate": "2026-01-01"}
                ]
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
    print()
    print("=" * 50)
    print("  AI Answers Plugin - Demo Server")
    print("=" * 50)
    print(f"  Provider: {plugin.provider or 'NOT SET'}")
    print(f"  Model:    {plugin.model or 'N/A'}")
    print(f"  Style:    {plugin.style}")
    print(f"  Status:   {'Active' if plugin.api_key else 'Inactive (no LLM_KEY)'}")
    print("=" * 50)
    print("  http://localhost:5000/?q=your+query+here")
    print("=" * 50)
    print()
    app.run(debug=True, port=5000)
