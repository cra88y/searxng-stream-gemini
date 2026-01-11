import sys
import os
import logging
from types import ModuleType
from flask import Flask, request
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO)
load_dotenv()

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

from gemini_flash import SXNGPlugin
from flask_babel import Babel

app = Flask(__name__)
babel = Babel(app)

class MockConfig:
    active = True

plugin = SXNGPlugin(MockConfig())
plugin.init(app)

@app.route("/")
def index():
    class MockSearchQuery:
        pageno = 1
        query = request.args.get("q", "why is the sky blue")
    
    class MockSearch:
        search_query = MockSearchQuery()
        class MockResultContainer:
            def __init__(self):
                self.answers = set()

            def get_ordered_results(self):
                return [
                    {"title": "Fact About Sky", "content": "The sky is blue because of Rayleigh scattering."},
                    {"title": "Atmosphere Info", "content": "The atmosphere scatters shorter blue wavelengths more than red ones."},
                    {"title": "NASA Science", "content": "Sunlight reaches Earth's atmosphere and is scattered in all directions by gases."}
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
        <title>Plugin Test</title>
        <style>
            body {{ font-family: sans-serif; padding: 2rem; max-width: 800px; margin: 0 auto; }}
            :root {{
                --color-result-border: #ccc;
                --color-result-description: #333;
            }}
        </style>
    </head>
    <body>
        <h1>Gemini Plugin Test</h1>
        <p>Testing query: <strong>{MockSearch.search_query.query}</strong></p>
        <p><a href="/?q=tell me a joke">Try: "tell me a joke"</a> | <a href="/?q=explain quantum physics">Try: "explain quantum physics"</a></p>
        <hr>
        {injection_html}
    </body>
    </html>
    """

import unittest

class PluginTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    def test_html_injection(self):
        response = self.app.get('/')
        content = response.data.decode('utf-8')
        self.assertIn('<div id="ai-shell"', content)
        self.assertIn('const q = "why is the sky blue";', content)
        self.assertIn('/gemini-stream', content)

    def test_stream_endpoint(self):
        if not os.getenv("GEMINI_API_KEY"):
            self.skipTest("GEMINI_API_KEY not set")

        payload = {
            "q": "why is the sky blue",
            "context": "The sky is blue because of Rayleigh scattering."
        }
        
        response = self.app.post('/gemini-stream', json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.data.decode('utf-8')
        self.assertTrue(len(data) > 0)

if __name__ == "__main__":
    unittest.main()
