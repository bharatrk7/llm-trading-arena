"""
Gemini LLM Trading Bot for the Arena
"""

import os
import requests
import json
import google.generativeai as genai

# --- CONFIGURATION ---
ARENA_URL = os.environ.get('ARENA_URL')
BOT_API_KEY = os.environ.get('GEMINI_BOT_API_KEY')  # Arena API key for this bot
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')   # Google Gemini API key

HEADERS = {
    'X-API-Key': BOT_API_KEY,
    'Content-Type': 'application/json'
}

# --- ARENA API FUNCTIONS ---

def get_portfolio():
    """Get current portfolio from arena"""
    response = requests.get(f'{ARENA_URL}/api/bot/portfolio', headers=HEADERS)
    if response.status_code == 200:
        return response.json()
    print(f"Error getting portfolio: {response.text}")
    return None

def buy_stock(ticker: str, shares: int):
    """Buy shares"""
    response = requests.post(
        f'{ARENA_URL}/api/bot/buy',
        headers=HEADERS,
        json={'ticker': ticker, 'shares': shares}
    )
    result = response.json()
    if response.status_code == 200:
        print(f"✅ BUY: {result['message']}")
    else:
        print(f"❌ BUY failed: {result.get('error')}")
    return response.status_code == 200

def sell_stock(ticker: str, shares: int):
    """Sell shares"""
    response = requests.post(
        f'{ARENA_URL}/api/bot/sell',
        headers=HEADERS,
        json={'ticker': ticker, 'shares': shares}
    )
    result = response.json()
    if response.status_code == 200:
        print(f"✅ SELL: {result['message']}")
    else:
        print(f"❌ SELL failed: {result.get('error')}")
    return response.status_code == 200

# --- GEMINI STRATEGY ---

def get_trading_decisions(portfolio: dict) -> list:
    """Ask Gemini for trading decisions"""
    
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    prompt = f"""You are an expert portfolio manager competing in a trading arena. Your goal is to maximize risk-adjusted returns (Sharpe ratio) while following these strict rules:

RULES:
- Maximum 10% of portfolio in any single stock (STRICTLY ENFORCED)
- 0.1% fee on every trade (buy and sell)
- No penny stocks (min $1.00)
- Prefer uncorrelated stocks for diversification
- Goal: Highest returns NET of fees with good Sharpe ratio

CURRENT PORTFOLIO:
- Cash: ${portfolio['cash']:,.2f}
- Total Value: ${portfolio['total_value']:,.2f}
- Current Return: {portfolio['return_pct']:+.2f}%
- Sharpe Ratio: {portfolio['sharpe_ratio']}

CURRENT HOLDINGS:
{json.dumps(portfolio['holdings'], indent=2) if portfolio['holdings'] else "None - portfolio is empty"}

IMPORTANT CONSTRAINTS:
- Max position size is ${portfolio['total_value'] * 0.10:,.2f} (10% of portfolio)
- Consider transaction fees before trading (0.1% each way)
- Only trade if you have strong conviction - fees eat into returns
- Diversify across sectors to reduce correlation

Based on current market conditions and the above constraints, what trades should be made?

Respond with ONLY valid JSON in this exact format (no markdown, no explanation):
{{"trades": [{{"action": "buy", "ticker": "AAPL", "shares": 10, "reason": "brief reason"}}, {{"action": "sell", "ticker": "XYZ", "shares": 5, "reason": "brief reason"}}]}}

If no trades should be made, respond with:
{{"trades": []}}
"""

    try:
        response = model.generate_content(prompt)
        response_text = response.text.strip()
        
        # Clean up response if needed
        if response_text.startswith('```'):
            response_text = response_text.split('```')[1]
            if response_text.startswith('json'):
                response_text = response_text[4:]
        response_text = response_text.strip()
        
        print(f"🧠 Gemini response: {response_text}")
        
        result = json.loads(response_text)
        return result.get('trades', [])
        
    except json.JSONDecodeError as e:
        print(f"❌ Failed to parse Gemini response: {e}")
        print(f"   Raw response: {response.text}")
        return []
    except Exception as e:
        print(f"❌ Gemini API error: {e}")
        return []

# --- MAIN ---

def run():
    print("=" * 50)
    print("🤖 GEMINI TRADING BOT")
    print("=" * 50)
    
    # Validate config
    if not all([ARENA_URL, BOT_API_KEY, GEMINI_API_KEY]):
        print("❌ Missing environment variables!")
        print(f"   ARENA_URL: {'✓' if ARENA_URL else '✗'}")
        print(f"   GEMINI_BOT_API_KEY: {'✓' if BOT_API_KEY else '✗'}")
        print(f"   GEMINI_API_KEY: {'✓' if GEMINI_API_KEY else '✗'}")
        return
    
    # Get portfolio
    portfolio = get_portfolio()
    if not portfolio:
        print("❌ Failed to get portfolio")
        return
    
    print(f"\n📊 Portfolio Status:")
    print(f"   Cash: ${portfolio['cash']:,.2f}")
    print(f"   Stock Value: ${portfolio['stock_value']:,.2f}")
    print(f"   Total: ${portfolio['total_value']:,.2f}")
    print(f"   Return: {portfolio['return_pct']:+.2f}%")
    
    if portfolio['holdings']:
        print(f"\n📈 Holdings:")
        for h in portfolio['holdings']:
            print(f"   {h['ticker']}: {h['shares']} @ ${h['current_price']:.2f} ({h['gain_pct']:+.2f}%)")
    
    # Get trading decisions from Gemini
    print(f"\n🧠 Asking Gemini for trading decisions...")
    trades = get_trading_decisions(portfolio)
    
    if not trades:
        print("📭 No trades recommended")
    else:
        print(f"\n💹 Executing {len(trades)} trade(s):")
        for trade in trades:
            print(f"   → {trade['action'].upper()} {trade['shares']} {trade['ticker']}: {trade.get('reason', 'N/A')}")
            
            if trade['action'] == 'buy':
                buy_stock(trade['ticker'], trade['shares'])
            elif trade['action'] == 'sell':
                sell_stock(trade['ticker'], trade['shares'])
    
    print("\n" + "=" * 50)
    print("✅ Gemini bot run complete!")

if __name__ == '__main__':
    run()
