# ETF Overlap Analyzer

**Analyze overlap between ETFs to identify concentration risks and improve portfolio diversification.**

## 🚀 Quick Start

### Console Tool
```bash
# Install dependencies
pip install requests beautifulsoup4

# Analyze two ETFs
python etf_overlap.py --isin1 IE00B4L5Y983 --isin2 IE00B3RBWM25

# Analyze multiple ETFs
python etf_overlap.py --multi IE00B4L5Y983,IE00B3RBWM25,IE00BK5BQT80

# Get JSON output for integration
python etf_overlap.py --multi IE00B4L5Y983,IE00B3RBWM25 --json
```

### Web Interface
```bash
cd etf_web
pip install flask
python app.py  # Runs on http://localhost:3003
```

## 📊 Features

- **Stock-Centric Analysis**: Identifies which stocks appear in multiple ETFs
- **Concentration Risk Detection**: Highlights over-concentration in specific stocks
- **Interactive Visualizations**: Charts showing overlap patterns
- **JSON API**: Clean output for programmatic use
- **Caching**: Improves performance with SQLite caching

## 📋 Requirements

- Python 3.7+
- `requests`, `beautifulsoup4` (console)
- `flask` (web interface)

## 📁 Files

```
.
├── etf_overlap.py          # Main analysis tool
├── etf_web/                # Web interface
│   ├── app.py              # Flask server
│   └── templates/index.html # Web UI
├── README.md               # This file
└── LICENSE                 # MIT License
```

## ⚠️ Important Disclaimers

**NO FINANCIAL ADVICE**: This tool provides data analysis only. It does not provide financial advice or recommendations. Consult a qualified financial advisor before making investment decisions.

**SCRAPING RESPONSIBILITY**: This tool scrapes data from justetf.com. Users are solely responsible for complying with justetf.com's terms of service and applicable laws. Use at your own risk.

**DATA ACCURACY**: Results depend on data availability from justetf.com. Some ETFs may not have holdings information available.

## 🔧 Security Notes

- **Web Server**: Flask development server is not production-ready. Use with production WSGI server for deployment.
- **Input Validation**: Basic validation is implemented but additional hardening may be needed for public deployment.
- **Rate Limiting**: No rate limiting is implemented. Consider adding if exposing to public internet.

## 🎯 Example Usage

**Input**: 3 ETF ISINs
**Output**:
- Alphabet, Inc. A: 6 appearances, 9.91% total weight
- NVIDIA: 3 appearances, 15.97% total weight
- Interactive charts showing concentration risks

## 📖 License

MIT License - See [LICENSE](LICENSE) for details.