"""
ETF Overlap Analyzer - Web Interface

SECURITY NOTES:
- Flask development server is NOT production-ready - use Gunicorn/Nginx for production
- No authentication/authorization implemented - anyone can access the API
- Basic input validation only - additional sanitization needed for public use
- No rate limiting - consider adding if exposing to public internet
- No CSRF protection - consider adding for web forms
- No HTTPS enforcement - ensure proper TLS configuration in production
- Subprocess calls use user input - ensure proper escaping/sanitization
"""

from flask import Flask, request, jsonify, send_from_directory
import subprocess
import json
import os

app = Flask(__name__)

@app.route('/')
def index():
    return send_from_directory('templates', 'index.html')

@app.route('/api/analyze', methods=['POST'])
def analyze():
    data = request.get_json()
    if not data or 'isins' not in data:
        return jsonify({'error': 'Invalid request - missing isins parameter'}), 400

    isins = data.get('isins', [])
    if not isinstance(isins, list) or len(isins) < 2:
        return jsonify({'error': 'At least 2 ETF ISINs required'}), 400

    try:
        # Change to parent directory where etf_overlap.py is located
        result = subprocess.run([
            'python', 'etf_overlap.py',
            '--multi', ','.join(isins),
            '--json'
        ], capture_output=True, text=True, cwd='..')

        # First try to parse stdout as JSON (might contain valid data even with stderr warnings)
        try:
            json_data = json.loads(result.stdout)
            response = {'data': json_data}

            # Add warnings if there were any
            if result.stderr.strip():
                response['warnings'] = result.stderr.split('\n')

            return jsonify(response)
        except json.JSONDecodeError:
            if result.returncode != 0:
                return jsonify({'error': result.stderr or 'Analysis failed'}), 500
            else:
                return jsonify({'error': 'Invalid JSON output from analysis tool'}), 500

    except Exception as e:
        return jsonify({'error': f'Server error: {str(e)}'}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3003, debug=True)