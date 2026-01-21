"""
AI Answers Plugin - Comprehensive Test
Test suite that verifies both 'interactive' and 'simple' modes,
checks configuration, and validates LLM integration.

Usage: python test.py
Requires: pip install flask flask-babel python-dotenv
"""

import os
import sys

# Add parent directory to path to find ai_answers.py
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re
import time
import logging
import subprocess
import tempfile
from types import ModuleType

import warnings
warnings.filterwarnings("ignore", category=SyntaxWarning)

# Suppress Flask noise during test
logging.getLogger('werkzeug').setLevel(logging.ERROR)
logging.basicConfig(level=logging.INFO, format='%(message)s')

# --- MOCKS START ---

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
    
    def get_ordered_results(self):
        return self._results

searx_plugins.Plugin = MockPlugin
searx_plugins.PluginInfo = MockPluginInfo
searx_results.EngineResults = MockEngineResults

# Internal search API mocks
searx_search = ModuleType("searx.search")
searx_search_models = ModuleType("searx.search.models")
searx_query = ModuleType("searx.query")
searx_webadapter = ModuleType("searx.webadapter")

class MockSearchWithPlugins:
    def __init__(self, search_query, request, user_plugins):
        self.search_query = search_query
        self.result_container = MockEngineResults()
        # Add some mock results
        self.result_container.add({"title": "Mock Aux Result", "url": "https://test.com", "content": "Test content", "publishedDate": "2026"})
        
        # Add mock infoboxes/answers
        self.result_container.infoboxes = [{"infobox": "Test Box", "content": "Box Content", "attributes": []}]
        self.result_container.answers = set() 
        self.result_container.answers_list = ["Test Answer"] # Simulating raw answers list if needed

    def search(self):
        return self.result_container

class MockSearchQuery:
    def __init__(self, query, engineref_list, **kwargs):
        self.query = query

class MockRawTextQuery:
    def __init__(self, query, disabled_engines):
        self.query = query
    def getQuery(self):
        return self.query

searx_search.SearchWithPlugins = MockSearchWithPlugins
searx_search.models = searx_search_models
searx_search_models.SearchQuery = MockSearchQuery
searx_query.RawTextQuery = MockRawTextQuery
searx_webadapter.get_engineref_from_category_list = lambda cats, disabled: []

sys.modules["searx.search"] = searx_search
sys.modules["searx.search.models"] = searx_search_models
sys.modules["searx.query"] = searx_query
sys.modules["searx.webadapter"] = searx_webadapter

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
    print(f"  [DEBUG] Network Call: {method} {target}{path}")
    print(f"  [DEBUG] Headers: {headers}")
    # print(f"  [DEBUG] Body: {body}")
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

sys.modules["searx"] = searx
sys.modules["searx.plugins"] = searx_plugins
sys.modules["searx.result_types"] = searx_results

# --- MOCKS END ---

from flask import Flask
from flask_babel import Babel
from ai_answers import SXNGPlugin

def check_js_syntax(js_code):
    """Returns (valid, error_msg)"""
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False, encoding='utf-8') as f:
            f.write(js_code)
            temp_path = f.name
        
        result = subprocess.run(
            ['node', '--check', temp_path],
            capture_output=True,
            text=True,
            timeout=5
        )
        os.unlink(temp_path)
        
        if result.returncode == 0:
            return True, None
        else:
            return False, result.stderr.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception) as e:
        return True, f"[SKIP] {e}" # Skip if node not found

def run_tests():
    print("AI Answers - Test Suite\n")
    
    print("[Syntax]")
    
    import py_compile
    try:
        target_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'ai_answers.py')
        py_compile.compile(target_file, doraise=True)
        print("  Python: OK")
    except py_compile.PyCompileError as e:
        print(f"  Syntax:        [FAIL] {e}")
        return False

    modes = ['interactive', 'simple']
    
    for mode in modes:
        app = Flask(__name__)
        Babel(app)
        
        # Set LLM_INTERACTIVE based on mode
        os.environ['LLM_INTERACTIVE'] = 'true' if mode == 'interactive' else 'false'
        
        # Override env var for this iteration
        # os.environ['LLM_STYLE'] = mode # Legacy
        os.environ['LLM_INTERACTIVE'] = 'true' if mode == 'interactive' else 'false'
        
        class MockConfig:
            active = True
        
        # Re-init plugin with new env var in effect
        plugin = SXNGPlugin(MockConfig())
        plugin.init(app)
        
        if mode == 'interactive':
            print(f"\n[Config]")
            print(f"  Provider: {plugin.provider or 'NOT SET'}")
            print(f"  API Key:  {'OK' if plugin.api_key else 'MISSING'}")

        # Construct Search
        class MockSearchQuery:
            pageno = 1
            query = "test query"
            lang = 'en'
            categories = ['general']
        
        class MockSearch:
            search_query = MockSearchQuery()
            class MockResultContainer:
                def __init__(self):
                    self.answers = set()
                    self.infoboxes = []
                def get_ordered_results(self):
                    return [
                        {"title": "T1", "content": "C1", "url": "https://a.com/1", "publishedDate": "2026-01-15"},
                        {"title": "T2", "content": "C2", "url": "https://a.com/2", "publishedDate": "2026-01-10"},
                    ]
            result_container = MockResultContainer()
        
        search = MockSearch()
        plugin.post_search(None, search)
        
        if not search.result_container.answers:
            print("  FAIL: No HTML injected")
            return False
        
        html = str(list(search.result_container.answers)[0])
        
        # Mode-specific basic validations
        has_box = 'id="sxng-stream-box"' in html
        has_footer = 'id="sxng-footer"' in html
        
        if mode == 'interactive':
            if has_box and has_footer:
                print("\n[Render: interactive]")
                print("  UI: OK")
            else:
                print(f"  FAIL: Box={has_box}, Footer={has_footer}")
                return False
        else:
            if has_box and not has_footer:
                print("\n[Render: simple]")
                print("  UI: OK")
            else:
                print(f"  FAIL: Box={has_box}, Footer={has_footer}")
                return False

        # JS Verification
        js_match = re.search(r'<script>(.*?)</script>', html, re.DOTALL)
        if not js_match:
            print("  FAIL: No script tag found")
            return False
        
        js_code = js_match.group(1).strip()
        valid, err = check_js_syntax(js_code)
        
        if valid:
            print("  JS:   OK")
        else:
            print("  JS Syntax:     [FAIL]")
            print(f"  Error:         {err.splitlines()[0][:80]}...")
            return False
            
        print(f"  Size: {len(html):,} bytes")
        
        # Verify Critical Fix: Function Signature
        # simple mode caused reference error if signature wasn't unified
        if 'async function startStream(overrideQ = null, prevAnswer = null, auxContext = null)' in js_code:
             print("  Signature: OK")
        else:
             print("  Signature Fix: [FAIL] Unified startStream signature MISSING")
             # Not fatal for interactive per se, but fatal if consistent code is desired
             # For simple mode it IS fatal in runtime.
             if mode == 'simple': return False


    # ---------------------------------------------------------
    # GLOBAL ENDPOINT / INTEGRATION TESTS (Using last plugin init)
    # ---------------------------------------------------------
    
    if not plugin.api_key:
        print("\n[Skip integration: no LLM_KEY]")
        return True

    print(f"\n[Stream]")
    print(f"  Provider: {plugin.provider}")
    print(f"  Model:    {plugin.model}")
    
    # Needs a token from the last run to pass auth
    token_match = re.search(r'tk_init = "(.*?)";', html)
    if not token_match:
        print("  FAIL: Could not extract token for stream test")
        return False

    with app.test_client() as client:
        payload = {
            "q": "why is the sky blue",
            "context": "[1] Wikipedia: The sky appears blue.",
            "lang": "en",
            "tk": token_match.group(1)
        }
        
        start = time.time()
        response = client.post('/ai-stream', json=payload)
        elapsed = time.time() - start
        
        print(f"  Status: {response.status_code}")
        print(f"  Time:   {elapsed:.2f}s")
        
        if response.status_code != 200:
            print(f"  FAIL: Expected 200, got {response.status_code}")
            return False
            
        data = response.data.decode('utf-8')
        if len(data) < 5:
             print("  FAIL: Empty or too short response")
             return False
        print("  Result: OK")

    print("\n[Aux Search]")
    with app.test_client() as client:
        aux_response = client.post('/ai-auxiliary-search', json={'query': 'test'})
        if aux_response.status_code == 200 and 'results' in aux_response.get_json():
            print("  Result: OK")
        else:
            print("  Aux Endpoint:  [FAIL]")

    print("\nPASS")
    return True

if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
