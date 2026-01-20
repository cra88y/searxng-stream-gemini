"""
AI Answers Plugin - One-Shot Test
Comprehensive test that outputs everything: config, injection, LLM response.

Usage: python test.py
Requires: pip install flask flask-babel python-dotenv
"""

import sys
import os
import re
import time
import logging
from types import ModuleType
from dotenv import load_dotenv

load_dotenv()

# Suppress Flask noise during test
logging.getLogger('werkzeug').setLevel(logging.ERROR)
logging.basicConfig(level=logging.INFO, format='%(message)s')

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

from flask import Flask
from flask_babel import Babel
from ai_answers import SXNGPlugin

def run_tests():
    print()
    print("=" * 60)
    print("  AI Answers Plugin - Comprehensive Test")
    print("=" * 60)
    
    # === CONFIG TEST ===
    print("\n[1/4] Configuration")
    print("-" * 40)
    
    app = Flask(__name__)
    Babel(app)
    
    class MockConfig:
        active = True
    
    plugin = SXNGPlugin(MockConfig())
    plugin.init(app)
    
    print(f"  Provider:      {plugin.provider or 'NOT SET'}")
    print(f"  Model:         {plugin.model or 'N/A'}")
    print(f"  API Key:       {'[OK]' if plugin.api_key else '[MISSING]'}")
    print(f"  Max Tokens:    {getattr(plugin, 'max_tokens', 'N/A')}")
    print(f"  Temperature:   {getattr(plugin, 'temperature', 'N/A')}")
    print(f"  Context Count: {getattr(plugin, 'context_count', 'N/A')}")
    print(f"  Allowed Tabs:  {getattr(plugin, 'allowed_tabs', 'N/A')}")
    
    if not plugin.api_key:
        print("\n" + "=" * 60)
        print("  SKIPPED: No LLM_KEY configured")
        print("  Set LLM_PROVIDER and LLM_KEY in .env to run full test")
        print("=" * 60)
        return False
    
    # === INJECTION TEST ===
    print("\n[2/4] HTML Injection")
    print("-" * 40)
    
    class MockSearchQuery:
        pageno = 1
        query = "why is the sky blue"
        lang = 'en'
        categories = ['general']
    
    class MockSearch:
        search_query = MockSearchQuery()
        class MockResultContainer:
            def __init__(self):
                self.answers = set()
            def get_ordered_results(self):
                return [
                    {"title": "Wikipedia", "content": "The sky appears blue due to Rayleigh scattering.", "url": "https://example.com/1", "publishedDate": "2026-01-15"},
                    {"title": "NASA", "content": "Blue wavelengths scatter more than red.", "url": "https://example.com/2", "publishedDate": "2026-01-10"},
                ]
        result_container = MockResultContainer()
    
    search = MockSearch()
    plugin.post_search(None, search)
    
    if not search.result_container.answers:
        print("  FAIL: No HTML injected")
        return False
    
    html = str(list(search.result_container.answers)[0])
    
    has_box = 'id="sxng-stream-box"' in html
    has_endpoint = '/ai-stream' in html
    
    token_match = re.search(r'const tk = "(.*?)";', html)
    has_token = bool(token_match)
    
    print(f"  Stream box:    {'[OK]' if has_box else '[FAIL]'}")
    print(f"  Endpoint ref:  {'[OK]' if has_endpoint else '[FAIL]'}")
    print(f"  Auth token:    {'[OK]' if has_token else '[FAIL]'}")
    print(f"  HTML size:     {len(html):,} bytes")
    
    if not (has_box and has_endpoint and has_token):
        print("  FAIL: Missing required elements")
        return False
    
    # === STREAM ENDPOINT TEST ===
    print("\n[3/4] Stream Endpoint")
    print("-" * 40)
    
    with app.test_client() as client:
        payload = {
            "q": "why is the sky blue",
            "context": "[1] Wikipedia: The sky appears blue due to Rayleigh scattering.",
            "lang": "en",
            "tk": token_match.group(1)
        }
        
        start = time.time()
        response = client.post('/ai-stream', json=payload)
        elapsed = time.time() - start
        
        print(f"  Status:        {response.status_code}")
        print(f"  Time:          {elapsed:.2f}s")
        
        if response.status_code != 200:
            print(f"  FAIL: Expected 200, got {response.status_code}")
            return False
    
    # === LLM RESPONSE TEST ===
    print("\n[4/4] LLM Response")
    print("-" * 40)
    
    data = response.data.decode('utf-8')
    print(f"  Bytes:         {len(data):,}")
    print(f"  Words:         ~{len(data.split())}")
    
    if len(data) < 10:
        print("  FAIL: Response too short (API error?)")
        return False
    
    print("\n  --- Response Preview ---")
    preview = data[:500] + ("..." if len(data) > 500 else "")
    for line in preview.split('\n'):
        print(f"  {line}")
    print("  --- End Preview ---")
    
    # === SUMMARY ===
    print("\n" + "=" * 60)
    print("  ALL TESTS PASSED")
    print("=" * 60)
    return True

if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
