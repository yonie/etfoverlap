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

from flask import Flask, request, jsonify, send_from_directory, Response
import subprocess
import json
import os
import re
from functools import wraps
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

# SECURITY: Production configuration
app.config['DEBUG'] = False
app.config['TESTING'] = False

# SECURITY: HTTP Basic Authentication password from .env
AUTH_PASSWORD = os.getenv('AUTH_PASSWORD')
if not AUTH_PASSWORD:
    raise ValueError("AUTH_PASSWORD not set in .env file. Please copy .env.example to .env and set your password.")

# SECURITY: Rate limiting to prevent abuse
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)

def check_auth(password):
    """Check if password is correct"""
    return password == AUTH_PASSWORD

def authenticate():
    """Send 401 response that enables basic auth"""
    return Response(
        'Authentication required. Please enter the password.',
        401,
        {'WWW-Authenticate': 'Basic realm="ETF Overlap Analyzer - Restricted Access"'}
    )

def requires_auth(f):
    """Decorator to require HTTP Basic Authentication on all routes"""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated

# ISIN validation regex: exactly 12 chars, format: CC[A-Z0-9]{9}[0-9]
ISIN_PATTERN = re.compile(r'^[A-Z]{2}[A-Z0-9]{9}[0-9]$')

def validate_isin(isin: str) -> bool:
    """
    Validate ISIN format to prevent injection attacks.
    ISIN format: 2 letter country code + 9 alphanumeric + 1 check digit
    Example: IE00B4L5Y983
    """
    if not isinstance(isin, str):
        return False
    
    # Remove whitespace and convert to uppercase
    isin = isin.strip().upper()
    
    # Check format
    if not ISIN_PATTERN.match(isin):
        return False
    
    return True

@app.route('/')
@requires_auth
def index():
    return send_from_directory('templates', 'index.html')

@app.route('/api/analyze', methods=['POST'])
@limiter.limit("10 per minute")  # Additional rate limit for expensive operation
@requires_auth
def analyze():
    data = request.get_json()
    if not data or 'isins' not in data:
        return jsonify({'error': 'Invalid request - missing isins parameter'}), 400

    isins = data.get('isins', [])
    if not isinstance(isins, list) or len(isins) < 2:
        return jsonify({'error': 'At least 2 ETF ISINs required'}), 400
    
    # SECURITY: Validate all ISINs to prevent injection attacks
    invalid_isins = []
    validated_isins = []
    
    for isin in isins:
        isin_cleaned = isin.strip().upper()
        if validate_isin(isin_cleaned):
            validated_isins.append(isin_cleaned)
        else:
            invalid_isins.append(isin)
    
    if invalid_isins:
        return jsonify({
            'error': f'Invalid ISIN format detected. ISINs must be exactly 12 characters (2 letters + 9 alphanumeric + 1 digit). Invalid: {", ".join(invalid_isins)}'
        }), 400
    
    if len(validated_isins) < 2:
        return jsonify({'error': 'At least 2 valid ETF ISINs required'}), 400

    try:
        # SECURITY: Only use validated ISINs in subprocess
        # ISINs are now guaranteed to match ^[A-Z]{2}[A-Z0-9]{9}[0-9]$ pattern
        result = subprocess.run([
            'python', 'etf_overlap.py',
            '--multi', ','.join(validated_isins),
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
    # SECURITY: Production mode - debug is disabled
    # Bind to 0.0.0.0 for reverse proxy access
    # Web server (Apache/Nginx) will handle authentication via .htaccess
    app.run(host='0.0.0.0', port=3003, debug=False)