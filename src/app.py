"""
Mewgenics Breeding Analyzer - Desktop App
Uses PyWebView for a native window with embedded HTML.
No server, no firewall popup, no browser dependency.
"""
import json
import os
import sys
import webview

# Handle PyInstaller bundling
if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(__file__)

sys.path.insert(0, BASE_DIR)
from extract_data import extract_all_cats, build_breeding_insights, REAL_SAVE_PATH


class Api:
    """Python API exposed to JavaScript via window.pywebview.api"""
    
    def __init__(self):
        self._cats = None
        self._insights = None
    
    def _extract(self):
        """Extract once, reuse for subsequent calls."""
        if self._cats is None:
            self._cats = extract_all_cats(REAL_SAVE_PATH)
            self._insights = build_breeding_insights(self._cats)
    
    def load_data(self):
        """Load and return all data as JSON. Called by JS on page load."""
        try:
            self._extract()
            # Return summary + cats (insights loaded separately to avoid size limits)
            return json.dumps({
                'ok': True,
                'total': len(self._cats),
                'available': self._insights['available_cats'],
                'pairs': len(self._insights['compatible_pairs']),
                'cats': self._cats,
            })
        except Exception as e:
            return json.dumps({'ok': False, 'error': str(e)})
    
    def load_insights(self):
        """Return only insights JSON (smaller than full cats). Called after load_data."""
        try:
            self._extract()
            return json.dumps({'ok': True, 'insights': self._insights})
        except Exception as e:
            return json.dumps({'ok': False, 'error': str(e)})
    
    def refresh_data(self):
        """Re-extract save data."""
        try:
            self._cats = None
            self._insights = None
            self._extract()
            return json.dumps({
                'ok': True,
                'total': len(self._cats),
                'available': self._insights['available_cats'],
                'pairs': len(self._insights['compatible_pairs']),
                'cats': self._cats,
            })
        except Exception as e:
            return json.dumps({'ok': False, 'error': str(e)})


if __name__ == '__main__':
    html_path = os.path.join(BASE_DIR, 'app.html')
    if not os.path.exists(html_path):
        print(f"app.html not found at {html_path}")
        input("Press Enter to exit.")
        sys.exit(1)

    with open(html_path, 'r', encoding='utf-8') as f:
        html = f.read()

    # Inject PyWebView bridge indicator
    bridge_script = '<script>window.IS_PYWEBVIEW = true;</script>'
    html = html.replace('</head>', bridge_script + '</head>')

    try:
        print("Mewgenics Breeding Analyzer")
    except UnicodeEncodeError:
        print("Mewgenics Breeding Analyzer")
    print(f"   Save: {REAL_SAVE_PATH}")
    print()

    # Use a temp dir for WebView storage (enables localStorage)
    storage_dir = os.path.join(os.environ.get('TEMP', '.'), 'MewgenicsBreeding')
    os.makedirs(storage_dir, exist_ok=True)

    webview.create_window(
        'Mewgenics Breeding Analyzer',
        html=html,
        js_api=Api(),
        width=1200,
        height=800,
        min_size=(700, 500),
        text_select=True,
    )

    webview.start(debug=False, storage_path=storage_dir)
