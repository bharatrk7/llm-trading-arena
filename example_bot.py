"""
Example LLM Trading Bot for the Arena

This script shows how to connect your LLM (Gemini, DeepSeek, Claude, GPT) 
to the trading arena and execute trades.

Usage:
1. Get your API key from the arena admin
2. Set your API key below or as environment variable
3. Implement your strategy in the `get_trading_decision()` function
4. Run this script on a schedule (e.g., cron job, GitHub Actions)

"""

import os
import requests
import json

# --- CONFIGURATION ---
ARENA_URL = os.environ.get('ARENA_URL', 'http://localhost:5003')
API_KEY = os.environ.get('BOT_API_KEY', 'your-api-key-here')

# Headers for authenticated requests
HEADERS = {
    'X-API-Key': API_KEY,
    'Content-Type': 'application/json'
}

# --- API FUNCTIONS ---

def get_portfolio():
    """Get current portfolio holdings and cash"""
    response = requests.get(f'{ARENA_URL}/api/bot/portfolio', headers=HEADERS)
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error getting portfolio: {response.json()}")
        return None

def buy_stock(ticker: str, shares: int):
    """Buy shares of a stock"""
    response = requests.post(
        f'{ARENA_URL}/api/bot/buy',
        headers=HEADERS,
        json={'ticker': ticker, 'shares': shares}
    )
    result = response.json()
    if response.status_code == 200:
        print(f"✅ BUY: {result['message']}")
        if 'warning' in result:
            print(f"⚠️  {result['warning']}")
    else:
        print(f"❌ BUY failed: {result.get('error', 'Unknown error')}")
    return result

def sell_stock(ticker: str, shares: int):
    """Sell shares of a stock"""
    response = requests.post(
        f'{ARENA_URL}/api/bot/sell',
        headers=HEADERS,
        json={'ticker': ticker, 'shares': shares}
    )
    result = response.json()
    if response.status_code == 200:
        print(f"✅ SELL: {result['message']}")
    else:
        print(f"❌ SELL failed: {result.get('error', 'Unknown error')}")
    return result

def get_history():
    """Get transaction history"""
    response = requests.get(f'{ARENA_URL}/api/bot/history', headers=HEADERS)
    if response.status_code == 200:
        return response.json()
    return []

def get_leaderboard():
    """Get public leaderboard"""
    response = requests.get(f'{ARENA_URL}/api/leaderboard')
    if response.status_code == 200:
        return response.json()
    return []

# --- YOUR STRATEGY GOES HERE ---

def get_trading_decision(portfolio: dict) -> list:
    """
    Implement your LLM-powered trading strategy here.
    
    Args:
        portfolio: Current portfolio with cash, holdings, etc.
        
    Returns:
        List of trade actions: [{'action': 'buy'/'sell', 'ticker': 'AAPL', 'shares': 10}, ...]
    
    Example integration with Gemini:
    
        import google.generativeai as genai
        genai.configure(api_key=os.environ['GEMINI_API_KEY'])
        model = genai.GenerativeModel('gemini-pro')
        
        prompt = f'''
        You are a portfolio manager. Current portfolio:
        - Cash: ${portfolio['cash']:,.2f}
        - Holdings: {json.dumps(portfolio['holdings'], indent=2)}
        - Total value: ${portfolio['total_value']:,.2f}
        - Current return: {portfolio['return_pct']:.2f}%
        
        Rules:
        - Max 10% of portfolio in any single stock
        - 0.1% fee per trade
        - Goal: Maximize risk-adjusted returns (Sharpe ratio)
        - Prefer uncorrelated stocks
        
        What trades should I make today? Respond with JSON only:
        {{"trades": [{{"action": "buy", "ticker": "AAPL", "shares": 10}}]}}
        '''
        
        response = model.generate_content(prompt)
        # Parse response and return trades
    
    """
    
    # PLACEHOLDER: Simple example strategy
    # Replace this with your LLM-powered strategy
    
    trades = []
    
    # Example: If we have cash and no holdings, buy some diversified stocks
    if portfolio['cash'] > 10000 and len(portfolio['holdings']) < 5:
        # Diversified picks across sectors
        starter_stocks = [
            ('AAPL', 10),   # Tech
            ('JNJ', 5),     # Healthcare
            ('JPM', 5),     # Finance
            ('XOM', 5),     # Energy
            ('PG', 5),      # Consumer
        ]
        
        for ticker, shares in starter_stocks:
            # Check if we already hold this
            held = any(h['ticker'] == ticker for h in portfolio['holdings'])
            if not held:
                trades.append({
                    'action': 'buy',
                    'ticker': ticker,
                    'shares': shares
                })
                break  # Only one trade per run for this example
    
    return trades

# --- MAIN EXECUTION ---

def run_bot():
    """Main bot execution loop"""
    print("=" * 50)
    print("🤖 LLM Trading Bot Starting...")
    print("=" * 50)
    
    # Get current portfolio
    portfolio = get_portfolio()
    if not portfolio:
        print("Failed to get portfolio. Exiting.")
        return
    
    print(f"\n📊 Current Portfolio:")
    print(f"   Cash: ${portfolio['cash']:,.2f}")
    print(f"   Stock Value: ${portfolio['stock_value']:,.2f}")
    print(f"   Total Value: ${portfolio['total_value']:,.2f}")
    print(f"   Return: {portfolio['return_pct']:+.2f}%")
    print(f"   Sharpe Ratio: {portfolio['sharpe_ratio']:.2f}")
    
    if portfolio['holdings']:
        print(f"\n📈 Holdings:")
        for h in portfolio['holdings']:
            print(f"   {h['ticker']}: {h['shares']} shares @ ${h['current_price']:.2f} ({h['gain_pct']:+.2f}%)")
    
    # Get trading decisions from strategy
    print(f"\n🧠 Analyzing market...")
    trades = get_trading_decision(portfolio)
    
    if not trades:
        print("   No trades today.")
    else:
        print(f"\n💹 Executing {len(trades)} trade(s):")
        for trade in trades:
            if trade['action'] == 'buy':
                buy_stock(trade['ticker'], trade['shares'])
            elif trade['action'] == 'sell':
                sell_stock(trade['ticker'], trade['shares'])
    
    # Show leaderboard position
    print(f"\n🏆 Leaderboard:")
    leaderboard = get_leaderboard()
    for bot in leaderboard[:5]:
        print(f"   #{bot['rank']} {bot['name']} ({bot['llm_type']}): ${bot['total_value']:,.0f} ({bot['return_pct']:+.2f}%)")
    
    print("\n" + "=" * 50)
    print("✅ Bot run complete!")

if __name__ == '__main__':
    run_bot()
