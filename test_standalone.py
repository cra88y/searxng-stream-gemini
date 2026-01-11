import sys
import os
import logging
from types import ModuleType
from flask import Flask, request
from dotenv import load_dotenv

# Configure logging to show INFO messages
logging.basicConfig(level=logging.INFO)

# Load environment variables from .env file
load_dotenv()

# --- 1. Mock SearXNG dependencies BEFORE importing the plugin ---
# We create fake modules so gemini_flash.py can import 'searx.plugins' etc. without error.

searx = ModuleType("searx")
searx_plugins = ModuleType("searx.plugins")
searx_results = ModuleType("searx.result_types")

class MockPlugin:
    """Mocks searx.plugins.Plugin"""
    def __init__(self, cfg):
        pass

class MockPluginInfo:
    """Mocks searx.plugins.PluginInfo"""
    def __init__(self, **kwargs):
        self.meta = kwargs

class MockEngineResults:
    """Mocks searx.result_types.EngineResults"""
    def __init__(self):
        # We need a 'types' object that has an 'Answer' class
        self.types = ModuleType("types")
        # Handle both positional and keyword arguments for Answer
        self.types.Answer = lambda *args, **kwargs: kwargs.get('answer', args[0] if args else "")
        self._results = []
    
    def add(self, res):
        self._results.append(res)

# Assign mocks to the fake modules
searx_plugins.Plugin = MockPlugin
searx_plugins.PluginInfo = MockPluginInfo
searx_results.EngineResults = MockEngineResults

# Inject them into sys.modules
sys.modules["searx"] = searx
sys.modules["searx.plugins"] = searx_plugins
sys.modules["searx.result_types"] = searx_results

# --- 2. Import the actual plugin code ---
# Now that dependencies are mocked, we can import the file.
from gemini_flash import SXNGPlugin
from flask_babel import Babel

# --- 3. Setup the Test Harness ---
app = Flask(__name__)
babel = Babel(app) # Initialize Babel to handle gettext calls if needed

# Mock the configuration object expected by the plugin
class MockConfig:
    active = True

# Initialize the plugin
print("Initializing Plugin...")
if not os.getenv("GEMINI_API_KEY"):
    print("WARNING: GEMINI_API_KEY environment variable is NOT set. The stream will likely fail.")

plugin = SXNGPlugin(MockConfig())
plugin.init(app) # This registers the /gemini-stream route

@app.route("/")
def index():
    print(">>> INDEX ROUTE HIT <<<")
    """
    Simulates a search result page.
    It calls post_search() to get the script, then embeds it in a basic HTML page.
    """
    # 1. Create a Mock Search Object
    class MockSearchQuery:
        pageno = 1
        query = request.args.get("q", "why is the sky blue") # Allow query via url param
    
    class MockSearch:
        search_query = MockSearchQuery()
        class MockResultContainer:
            def get_ordered_results(self):
                return [
                    {"title": "Fact About Sky", "content": "The sky is blue because of Rayleigh scattering."},
                    {"title": "Atmosphere Info", "content": "The atmosphere scatters shorter blue wavelengths more than red ones."},
                    {"title": "NASA Science", "content": "Sunlight reaches Earth's atmosphere and is scattered in all directions by gases."}
                ]
        result_container = MockResultContainer()

    # 2. Run the Plugin's post_search hook
    results = plugin.post_search(None, MockSearch())
    
    # 3. Extract the injected HTML (if any)
    injection_html = ""
    if results._results:
        injection_html = results._results[0]
    
    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Plugin Test</title>
        <style>
            body {{ font-family: sans-serif; padding: 2rem; max-width: 800px; margin: 0 auto; }}
            /* Mimic SearXNG variables for the injection styles to work */
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
        
        <!-- The Plugin Injection -->
        {injection_html}
        
    </body>
    </html>
    """

if __name__ == "__main__":
    print("\n--- TEST SERVER RUNNING ---")
    print("1. Ensure GEMINI_API_KEY is set in your terminal.")
    print("2. Open http://localhost:5000 in your browser.")
    app.run(host='0.0.0.0', port=5000, debug=False)
