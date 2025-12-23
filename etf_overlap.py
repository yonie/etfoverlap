#!/usr/bin/env python3
"""
ETF Overlap Analysis Tool
Analyzes overlap between ETFs using justetf.com data

SECURITY NOTES:
- This tool scrapes data from justetf.com - users are responsible for compliance
- No authentication/authorization is implemented
- Input validation is basic - additional hardening needed for public use
- SQLite cache uses local file storage - ensure proper file permissions
- No rate limiting - consider adding if exposing to public internet
"""
import sys

import os
import json
import time
import argparse
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
import sqlite3
from typing import List, Dict, Optional, Tuple

# Constants
DATABASE_FILE = 'etf_cache.db'
CACHE_EXPIRY_HOURS = 24
JUSTETF_URL = 'https://www.justetf.com/en/etf-profile.html?isin={}&tab=analyses'

# OPTIMIZATION: Pre-compile regex patterns for better performance
import re
WEIGHT_CLEAN_PATTERN = re.compile(r'[^\d.]')

class ETFData:
    """Data structure for ETF holdings"""
    def __init__(self, isin: str, name: str, holdings: List[Dict]):
        self.isin = isin
        self.name = name
        self.holdings = holdings

class OverlapCalculator:
    """Calculates overlap between ETFs"""

    @staticmethod
    def calculate_overlap(etf1: ETFData, etf2: ETFData) -> Dict:
        """Calculate overlap between two ETFs"""
        common_holdings = []
        total_overlap = 0.0

        # Create ISIN to holding map
        etf1_map = {h['isin']: h for h in etf1.holdings}
        etf2_map = {h['isin']: h for h in etf2.holdings}

        # Find common holdings
        for isin, holding1 in etf1_map.items():
            if isin in etf2_map:
                holding2 = etf2_map[isin]
                min_weight = min(holding1['weight'], holding2['weight'])
                common_holdings.append({
                    'isin': holding1['isin'],
                    'name': holding1['name'],
                    'weight': min_weight,
                    'etf1_weight': holding1['weight'],
                    'etf2_weight': holding2['weight']
                })
                total_overlap += min_weight

        # Calculate diversification score (0-100)
        score = 100 - total_overlap
        if total_overlap > 20:
            score -= (total_overlap - 20) * 2
        if total_overlap > 50:
            score -= (total_overlap - 50) * 3
        score = max(0, min(100, score))

        return {
            'etf1': etf1,
            'etf2': etf2,
            'common_holdings': common_holdings,
            'total_overlap_percentage': total_overlap,
            'diversification_score': score
        }

    @staticmethod
    def calculate_multi_overlap(etfs: List[ETFData]) -> Dict:
        """Calculate overlap between multiple ETFs"""
        matrix = {}
        total_overlap = 0
        pair_count = 0

        # Initialize matrix
        for etf in etfs:
            matrix[etf.isin] = {}

        # Calculate all pairs
        for i, etf1 in enumerate(etfs):
            for j, etf2 in enumerate(etfs[i+1:], i+1):
                result = OverlapCalculator.calculate_overlap(etf1, etf2)
                matrix[etf1.isin][etf2.isin] = {
                    'common_holdings': result['common_holdings'],
                    'overlap_percentage': result['total_overlap_percentage']
                }
                matrix[etf2.isin][etf1.isin] = {
                    'common_holdings': result['common_holdings'],
                    'overlap_percentage': result['total_overlap_percentage']
                }
                total_overlap += result['total_overlap_percentage']
                pair_count += 1

        avg_overlap = total_overlap / pair_count if pair_count > 0 else 0

        return {
            'etfs': etfs,
            'overlap_matrix': matrix,
            'average_overlap': avg_overlap
        }

class DataCache:
    """Manages caching of ETF data"""

    def __init__(self):
        self.conn = sqlite3.connect(DATABASE_FILE)
        self._initialize_db()

    def _initialize_db(self):
        """Initialize database tables"""
        cursor = self.conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS etf_cache (
                isin TEXT PRIMARY KEY,
                name TEXT,
                holdings TEXT,
                fetched_at TIMESTAMP
            )
        ''')
        self.conn.commit()

    def get_cached_data(self, isin: str) -> Optional[ETFData]:
        """Get cached ETF data if not expired"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT name, holdings, fetched_at FROM etf_cache
            WHERE isin = ?
        ''', (isin,))
        result = cursor.fetchone()

        if not result:
            return None

        name, holdings_json, fetched_at_str = result
        fetched_at = datetime.fromisoformat(fetched_at_str)

        # Check if expired
        if datetime.now() - fetched_at < timedelta(hours=CACHE_EXPIRY_HOURS):
            holdings = json.loads(holdings_json)
            return ETFData(isin, name, holdings)

        return None

    def cache_data(self, etf: ETFData):
        """Cache ETF data"""
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO etf_cache
            VALUES (?, ?, ?, ?)
        ''', (
            etf.isin,
            etf.name,
            json.dumps(etf.holdings),
            datetime.now().isoformat()
        ))
        self.conn.commit()

    def close(self):
        """Close database connection"""
        self.conn.close()

class DataFetcher:
    """Fetches ETF data from justetf.com"""

    def __init__(self, cache: DataCache):
        self.cache = cache
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept-Language': 'en-US,en;q=0.9'
        })

    def fetch_etf_data(self, isin: str) -> ETFData:
        """Fetch ETF data with caching"""
        # Try cache first
        cached = self.cache.get_cached_data(isin)
        if cached:
            return cached

        url = JUSTETF_URL.format(isin)
        response = self.session.get(url)

        if response.status_code != 200:
            raise Exception(f"Failed to fetch {isin}: HTTP {response.status_code}")

        soup = BeautifulSoup(response.text, 'html.parser')

        # Get ETF name
        name_tag = soup.find('h1', class_='etf-profile__name')
        if not name_tag:
            # Try alternative selector
            name_tag = soup.find('h1')
            if not name_tag:
                raise Exception(f"Could not find ETF name for {isin}")
        name = name_tag.get_text(strip=True)

        # Get holdings table - use the correct selector based on our analysis
        table = soup.find('table', {'data-testid': 'etf-holdings_top-holdings_table'})
        if not table:
            raise Exception(f"ETF {isin} does not provide holdings information on justetf.com. This ETF may not have a holdings tab or the data is not available. Please remove this ISIN from your input.")

        holdings = []
        tbody = table.find('tbody')
        if not tbody:
            tbody = table

        for row in tbody.find_all('tr'):
            cols = row.find_all('td')
            if len(cols) >= 2:
                # Extract stock ISIN from profile link in first column
                stock_link = cols[0].find('a', href=True)
                stock_isin = None
                if stock_link and '/stock-profiles/' in stock_link['href']:
                    # Extract ISIN from href like "/en/stock-profiles/US67066G1040"
                    href_parts = stock_link['href'].split('/')
                    if len(href_parts) > 0:
                        stock_isin = href_parts[-1]  # Last part is the ISIN
                
                # Extract stock name from first column
                stock_name_element = cols[0].find('span')
                stock_name = stock_name_element.get_text(strip=True) if stock_name_element else cols[0].get_text(strip=True)

                # Extract percentage from second column
                percentage_element = cols[1].find('span', {'data-testid': 'tl_etf-holdings_top-holdings_value_percentage'})
                percentage_text = percentage_element.get_text(strip=True) if percentage_element else cols[1].get_text(strip=True)

                # Clean percentage and convert to float (using pre-compiled regex for performance)
                percentage_text = WEIGHT_CLEAN_PATTERN.sub('', percentage_text).strip()
                try:
                    weight = float(percentage_text)
                    # Use ISIN as unique identifier, fallback to stock name if ISIN not available
                    holdings.append({
                        'isin': stock_isin if stock_isin else stock_name,  # Unique identifier
                        'name': stock_name,
                        'weight': weight
                    })
                except ValueError:
                    # Skip if we can't parse the percentage
                    continue

        etf_data = ETFData(isin, name, holdings)
        self.cache.cache_data(etf_data)
        return etf_data

class ReportGenerator:
    """Generates formatted reports"""

    @staticmethod
    def generate_text_report(result: Dict) -> str:
        """Generate text report for two ETFs"""
        etf1 = result['etf1']
        etf2 = result['etf2']
        common = result['common_holdings']
        overlap = result['total_overlap_percentage']
        score = result['diversification_score']

        report = []
        report.append('=' * 80)
        report.append('ETF OVERLAP ANALYSIS REPORT'.center(80))
        report.append('=' * 80 + '\n')

        report.append(ReportGenerator._format_etf_info(etf1, 'ETF 1'))
        report.append(ReportGenerator._format_etf_info(etf2, 'ETF 2') + '\n')

        report.append('OVERLAP SUMMARY'.center(80))
        report.append('-' * 80)
        report.append(f"Total Overlap Percentage: {overlap:.2f}%")
        report.append(f"Diversification Score: {score:.1f}/100")
        report.append(f"Number of Common Holdings: {len(common)}\n")

        report.append('HOLDINGS COMPARISON'.center(80))
        report.append('-' * 80)
        report.append(f"ETF 1 Total Holdings: {len(etf1.holdings)}")
        report.append(f"ETF 2 Total Holdings: {len(etf2.holdings)}")
        report.append(f"ETF 1 Unique Holdings: {len(etf1.holdings) - len(common)}")
        report.append(f"ETF 2 Unique Holdings: {len(etf2.holdings) - len(common)}\n")

        if common:
            report.append('COMMON HOLDINGS'.center(80))
            report.append('-' * 80)
            report.append(ReportGenerator._format_holdings_table(common))
            report.append('\n')

        report.append('RECOMMENDATIONS'.center(80))
        report.append('-' * 80)
        recommendations = ReportGenerator._generate_recommendations(score)
        # Replace Unicode characters with ASCII equivalents for Windows compatibility
        recommendations = recommendations.replace('✓', 'OK').replace('✗', 'XX').replace('⚠', 'WW')
        report.append(recommendations)
        report.append('\n')

        report.append('=' * 80)
        report.append('End of Report'.center(80))
        report.append('=' * 80)

        return '\n'.join(report)

    @staticmethod
    def generate_multi_report(result: Dict) -> str:
        """Generate report for multiple ETFs"""
        etfs = result['etfs']
        matrix = result['overlap_matrix']
        avg_overlap = result['average_overlap']

        # Calculate total stock overlap across all ETFs
        stock_appearances = {}
        stock_total_weights = {}

        # Count how many ETFs each stock appears in and total weight
        for etf in etfs:
            for holding in etf.holdings:
                isin = holding['isin']
                if isin not in stock_appearances:
                    stock_appearances[isin] = 0
                    stock_total_weights[isin] = 0
                stock_appearances[isin] += 1
                stock_total_weights[isin] += holding['weight']

        # Create sorted list of stocks by appearance count and total weight
        stocks_by_appearance = sorted(
            stock_appearances.items(),
            key=lambda x: (-x[1], -stock_total_weights[x[0]])
        )

        # Generate clean JSON output
        json_output = {
            "etfs": [],
            "summary": {
                "total_etfs": len(etfs),
                "average_overlap_percentage": avg_overlap,
                "total_unique_stocks": len(stock_appearances)
            },
            "stock_overlap_analysis": [],
            "pairwise_comparisons": []
        }

        # Add ETF information
        for etf in etfs:
            json_output["etfs"].append({
                "isin": etf.isin,
                "name": etf.name,
                "total_holdings": len(etf.holdings),
                "holdings": etf.holdings
            })

        # Add stock overlap analysis (sorted by appearance)
        for isin, appearance_count in stocks_by_appearance:
            total_weight = stock_total_weights[isin]
            # Find the stock name from any ETF that has it
            stock_name = ""
            for etf in etfs:
                for holding in etf.holdings:
                    if holding['isin'] == isin:
                        stock_name = holding['name']
                        break
                if stock_name:
                    break

            json_output["stock_overlap_analysis"].append({
                "isin": isin,
                "name": stock_name,
                "appears_in_etfs": appearance_count,
                "total_weight_across_all_etfs": total_weight,
                "average_weight_per_etf": total_weight / appearance_count
            })

        # Add pairwise comparisons
        for i, etf1 in enumerate(etfs):
            for j, etf2 in enumerate(etfs):
                if i < j:
                    overlap = matrix[etf1.isin][etf2.isin]
                    json_output["pairwise_comparisons"].append({
                        "etf1_isin": etf1.isin,
                        "etf2_isin": etf2.isin,
                        "overlap_percentage": overlap['overlap_percentage'],
                        "common_holdings_count": len(overlap['common_holdings']),
                        "common_holdings": overlap['common_holdings']
                    })

        # Generate clean text output for console
        report = []
        report.append('=' * 80)
        report.append('MULTI-ETF OVERLAP ANALYSIS REPORT'.center(80))
        report.append('=' * 80 + '\n')

        report.append('ETFS IN ANALYSIS'.center(80))
        report.append('-' * 80)
        for i, etf in enumerate(etfs, 1):
            report.append(f"{i}. {etf.name} ({etf.isin})")
            report.append(f"   Holdings: {len(etf.holdings)}\n")
        report.append('\n')

        report.append('STOCK OVERLAP ANALYSIS (ACROSS ALL ETFs)'.center(80))
        report.append('-' * 80)
        report.append(f"Total Unique Stocks: {len(stock_appearances)}")
        report.append(f"Average Overlap: {avg_overlap:.2f}%\n")

        # Show stocks that appear in multiple ETFs (concentration risk)
        report.append("STOCKS WITH HIGHEST CONCENTRATION RISK:")
        report.append("| {:<15} | {:<30} | {:<15} | {:<25} | {:<20} |".format(
            "ISIN", "Name", "ETF Count", "Total Weight", "Avg Weight/ETF"))
        report.append("|" + "-" * 15 + "|" + "-" * 30 + "|" + "-" * 15 + "|" + "-" * 25 + "|" + "-" * 20 + "|")

        for stock in stocks_by_appearance:
            if stock[1] > 1:  # Only show stocks in multiple ETFs
                isin = stock[0]
                total_weight = stock_total_weights[isin]
                avg_weight = total_weight / stock[1]
                stock_name = ""
                for etf in etfs:
                    for holding in etf.holdings:
                        if holding['isin'] == isin:
                            stock_name = holding['name']
                            break
                    if stock_name:
                        break

                report.append("| {:<15} | {:<30} | {:<15} | {:<25.2f}% | {:<20.2f}% |".format(
                    isin[:13], stock_name[:28], f"{stock[1]}/{len(etfs)}", total_weight, avg_weight))

        report.append('\n')

        # Add JSON output section
        report.append('JSON OUTPUT (FOR PROGRAMMATIC USE)'.center(80))
        report.append('-' * 80)
        report.append(json.dumps(json_output, indent=2))
        report.append('\n')

        report.append('=' * 80)
        report.append('End of Report'.center(80))
        report.append('=' * 80)

        return '\n'.join(report)

    @staticmethod
    def _format_etf_info(etf: ETFData, label: str) -> str:
        """Format ETF information"""
        info = []
        info.append(f"{label}: {etf.name} ({etf.isin})".center(80))
        info.append('-' * 80)
        info.append(f"Holdings: {len(etf.holdings)}")
        info.append("Top 5 Holdings:")
        for h in sorted(etf.holdings, key=lambda x: x['weight'], reverse=True)[:5]:
            info.append(f"  - {h['name']}: {h['weight']:.2f}% (ISIN: {h['isin']})")
        return '\n'.join(info)

    @staticmethod
    def _format_holdings_table(holdings: List[Dict]) -> str:
        """Format holdings as a table"""
        lines = []
        # Header
        lines.append("| {:<15} | {:<30} | {:>8} | {:>8} | {:>8} |".format(
            "ISIN", "Name", "Weight", "ETF1", "ETF2"))
        lines.append("|" + "-" * 15 + "|" + "-" * 30 + "|" + "-" * 8 + "|" + "-" * 8 + "|" + "-" * 8 + "|")

        # Rows
        for h in sorted(holdings, key=lambda x: x['weight'], reverse=True):
            lines.append("| {:<15} | {:<30} | {:>8.2f}% | {:>8.2f}% | {:>8.2f}% |".format(
                h['isin'][:13], h['name'][:28], h['weight'], h['etf1_weight'], h['etf2_weight']))

        return '\n'.join(lines)

    @staticmethod
    def _generate_recommendations(score: float) -> str:
        """Generate recommendations based on score"""
        if score >= 80:
            return """OK Excellent diversification! These ETFs have minimal overlap.
OK Consider holding both for broad market exposure."""
        elif score >= 60:
            return """OK Good diversification with some overlap.
OK Monitor the common holdings for concentration risk."""
        elif score >= 40:
            return """WW Moderate overlap detected.
WW Consider reducing position size in one of these ETFs.
WW Look for alternative ETFs with less overlap."""
        else:
            return """XX High overlap - poor diversification!
XX These ETFs are essentially investing in the same stocks.
XX Strongly consider holding only one of these ETFs.
XX Look for ETFs with different sector/geographic focus."""

    @staticmethod
    def _get_stock_overlap_analysis(etfs: List[ETFData]) -> List[Dict]:
        """Get stock overlap analysis for JSON output"""
        stock_appearances = {}
        stock_total_weights = {}
        stock_etf_details = {}

        # Count how many ETFs each stock appears in and total weight
        for etf in etfs:
            for holding in etf.holdings:
                isin = holding['isin']
                if isin not in stock_appearances:
                    stock_appearances[isin] = 0
                    stock_total_weights[isin] = 0
                    stock_etf_details[isin] = []
                stock_appearances[isin] += 1
                stock_total_weights[isin] += holding['weight']
                stock_etf_details[isin].append({
                    "etf_isin": etf.isin,
                    "etf_name": etf.name,
                    "weight": holding['weight']
                })

        # Create sorted list of stocks by appearance count and total weight
        stocks_by_appearance = sorted(
            stock_appearances.items(),
            key=lambda x: (-x[1], -stock_total_weights[x[0]])
        )

        # Build analysis
        analysis = []
        for isin, appearance_count in stocks_by_appearance:
            total_weight = stock_total_weights[isin]
            # Find the stock name from any ETF that has it
            stock_name = ""
            for etf in etfs:
                for holding in etf.holdings:
                    if holding['isin'] == isin:
                        stock_name = holding['name']
                        break
                if stock_name:
                    break

            analysis.append({
                "isin": isin,
                "name": stock_name,
                "appears_in_etfs": appearance_count,
                "total_weight_across_all_etfs": total_weight,
                "average_weight_per_etf": total_weight / appearance_count,
                "etf_breakdown": stock_etf_details[isin]
            })

        return analysis

def main():
    """Main application entry point"""
    parser = argparse.ArgumentParser(description='ETF Overlap Analysis Tool')
    parser.add_argument('--isin1', help='First ETF ISIN code')
    parser.add_argument('--isin2', help='Second ETF ISIN code')
    parser.add_argument('--multi', help='Multiple ETF ISIN codes (comma-separated)')
    parser.add_argument('--expire-cache', action='store_true', help='Expire cache and fetch fresh data')
    parser.add_argument('--json', action='store_true', help='Output JSON format for programmatic use')

    args = parser.parse_args()

    # Initialize components
    cache = DataCache()
    fetcher = DataFetcher(cache)
    calculator = OverlapCalculator()
    report_gen = ReportGenerator()

    try:
        # Handle cache expiration if requested
        if args.expire_cache:
            print("Expiring cache...")
            cursor = cache.conn.cursor()
            cursor.execute('DELETE FROM etf_cache')
            cache.conn.commit()
            print("Cache expired.")

        if args.isin1 and args.isin2:
            # Analyze two ETFs - act as a proper backend service
            try:
                etf1 = fetcher.fetch_etf_data(args.isin1)
                etf2 = fetcher.fetch_etf_data(args.isin2)
                result = calculator.calculate_overlap(etf1, etf2)

                # Always output clean JSON - this is a backend service
                json_result = {
                    "etf1": {
                        "isin": etf1.isin,
                        "name": etf1.name,
                        "holdings": etf1.holdings
                    },
                    "etf2": {
                        "isin": etf2.isin,
                        "name": etf2.name,
                        "holdings": etf2.holdings
                    },
                    "summary": {
                        "total_overlap_percentage": result['total_overlap_percentage'],
                        "diversification_score": result['diversification_score'],
                        "common_holdings_count": len(result['common_holdings'])
                    },
                    "common_holdings": result['common_holdings']
                }
                print(json.dumps(json_result, indent=2))

            except Exception as e:
                # Return proper JSON error response
                error_response = {
                    "error": str(e),
                    "status": "failed"
                }
                print(json.dumps(error_response, indent=2))
                return 1

        elif args.multi:
            # Analyze multiple ETFs - act as a proper backend service
            isins = [i.strip() for i in args.multi.split(',')]

            # Try to fetch all ETFs, but continue with valid ones if some fail
            etfs = []
            failed_isins = []
            for isin in isins:
                try:
                    etf = fetcher.fetch_etf_data(isin)
                    etfs.append(etf)
                except Exception as e:
                    failed_isins.append((isin, str(e)))

            if len(etfs) < 2:
                # Return proper JSON error response
                error_response = {
                    "error": "At least 2 valid ETFs are required for analysis",
                    "failed_isins": [{isin: error} for isin, error in failed_isins],
                    "valid_isins_count": len(etfs)
                }
                print(json.dumps(error_response, indent=2))
                return 1

            result = calculator.calculate_multi_overlap(etfs)

            # Always output clean JSON - this is a backend service
            output = {
                "etfs": [{
                    "isin": etf.isin,
                    "name": etf.name,
                    "holdings": etf.holdings
                } for etf in result['etfs']],
                "summary": {
                    "total_etfs": len(result['etfs']),
                    "average_overlap_percentage": result['average_overlap'],
                    "total_unique_stocks": len(set(stock['isin'] for etf in result['etfs'] for stock in etf.holdings))
                },
                "stock_overlap_analysis": ReportGenerator._get_stock_overlap_analysis(result['etfs'])
            }

            # Add warnings if any ETFs failed
            if failed_isins:
                output['warnings'] = {
                    "failed_isins": [{isin: error} for isin, error in failed_isins],
                    "message": f"{len(failed_isins)} ETF(s) could not be analyzed but analysis continued with {len(etfs)} valid ETF(s)"
                }

            print(json.dumps(output, indent=2))

        else:
            parser.print_help()
            return 1

    finally:
        cache.close()

    return 0

if __name__ == '__main__':
    exit(main())