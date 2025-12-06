import sqlite3
import yfinance as yf
import uuid
import os
import secrets
import hashlib
import numpy as np
from datetime import datetime, timedelta
from functools import wraps
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# --- CONFIGURATION ---
IS_CLOUD = 'DATABASE_URL' in os.environ
TRADING_FEE_PERCENT = 0.001  # 0.1% per trade
STARTING_CASH = 100000.00
MAX_POSITION_PERCENT = 0.10  # 10% max in single stock
MIN_STOCK_PRICE = 1.00

# --- SECURITY ---
app.secret_key = os.environ.get('SECRET_KEY')
if not app.secret_key:
    if IS_CLOUD:
        raise RuntimeError("SECRET_KEY environment variable required!")
    else:
        app.secret_key = 'dev-arena-key'

# --- YFINANCE FIX FOR RENDER ---
if IS_CLOUD:
    if not os.path.exists('/tmp/py-yfinance'):
        os.makedirs('/tmp/py-yfinance')
    yf.set_tz_cache_location('/tmp/py-yfinance')

# --- DATABASE ---
def get_db():
    if IS_CLOUD:
        conn = psycopg2.connect(os.environ['DATABASE_URL'], cursor_factory=RealDictCursor)
    else:
        conn = sqlite3.connect('arena.db')
        conn.row_factory = sqlite3.Row
    return conn

def get_ph():
    return '%s' if IS_CLOUD else '?'

# --- API KEY AUTH ---
def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        if not api_key:
            return jsonify({"error": "Missing API key"}), 401
        
        # Hash the key to compare with stored hash
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        
        conn = get_db()
        ph = get_ph()
        cursor = conn.cursor()
        cursor.execute(f'SELECT * FROM bots WHERE api_key_hash = {ph}', (key_hash,))
        bot = cursor.fetchone()
        conn.close()
        
        if not bot:
            return jsonify({"error": "Invalid API key"}), 401
        
        # Attach bot info to request
        request.bot = dict(bot)
        return f(*args, **kwargs)
    return decorated

# --- HELPER FUNCTIONS ---
def get_stock_price(ticker):
    """Get current stock price with error handling"""
    try:
        stock = yf.Ticker(ticker)
        try:
            price = stock.fast_info['last_price']
        except:
            hist = stock.history(period="1d")
            if not hist.empty:
                price = hist['Close'].iloc[-1]
            else:
                return None
        return price if price and price > 0 else None
    except:
        return None

def calculate_portfolio_value(bot_id):
    """Calculate total portfolio value (cash + stocks)"""
    conn = get_db()
    ph = get_ph()
    cursor = conn.cursor()
    
    # Get cash
    cursor.execute(f'SELECT cash FROM bots WHERE id = {ph}', (bot_id,))
    cash = cursor.fetchone()['cash']
    
    # Get holdings
    cursor.execute(f'SELECT ticker, shares, avg_price FROM holdings WHERE bot_id = {ph}', (bot_id,))
    holdings = cursor.fetchall()
    conn.close()
    
    stock_value = 0
    for h in holdings:
        price = get_stock_price(h['ticker']) or h['avg_price']
        stock_value += price * h['shares']
    
    return cash + stock_value

def calculate_portfolio_correlation(bot_id, new_ticker=None):
    """
    Calculate average correlation of portfolio holdings.
    Returns correlation score (lower is better for diversification).
    """
    conn = get_db()
    ph = get_ph()
    cursor = conn.cursor()
    cursor.execute(f'SELECT ticker FROM holdings WHERE bot_id = {ph}', (bot_id,))
    holdings = cursor.fetchall()
    conn.close()
    
    tickers = [h['ticker'] for h in holdings]
    if new_ticker and new_ticker not in tickers:
        tickers.append(new_ticker)
    
    if len(tickers) < 2:
        return 0.0  # No correlation with single stock
    
    try:
        # Get 30 days of price history
        data = yf.download(tickers, period="30d", progress=False)['Close']
        if data.empty:
            return 0.0
        
        # Calculate returns
        returns = data.pct_change().dropna()
        if len(returns) < 5:
            return 0.0
        
        # Calculate correlation matrix
        corr_matrix = returns.corr()
        
        # Get average off-diagonal correlation
        n = len(tickers)
        if n < 2:
            return 0.0
        
        total_corr = 0
        count = 0
        for i in range(n):
            for j in range(i+1, n):
                total_corr += abs(corr_matrix.iloc[i, j])
                count += 1
        
        return total_corr / count if count > 0 else 0.0
    except:
        return 0.0

def calculate_sharpe_ratio(bot_id):
    """Calculate Sharpe ratio based on transaction history"""
    conn = get_db()
    ph = get_ph()
    cursor = conn.cursor()
    
    # Get daily portfolio values from snapshots
    cursor.execute(f'''
        SELECT date, value FROM portfolio_snapshots 
        WHERE bot_id = {ph} 
        ORDER BY date ASC
    ''', (bot_id,))
    snapshots = cursor.fetchall()
    conn.close()
    
    if len(snapshots) < 2:
        return 0.0
    
    # Calculate daily returns
    values = [s['value'] for s in snapshots]
    returns = []
    for i in range(1, len(values)):
        if values[i-1] > 0:
            returns.append((values[i] - values[i-1]) / values[i-1])
    
    if len(returns) < 2:
        return 0.0
    
    # Sharpe = (mean return - risk free rate) / std dev
    # Assuming 0% risk-free rate for simplicity
    mean_return = np.mean(returns)
    std_return = np.std(returns)
    
    if std_return == 0:
        return 0.0
    
    # Annualize (assuming 252 trading days)
    sharpe = (mean_return / std_return) * np.sqrt(252)
    return round(sharpe, 2)

# --- ADMIN ROUTES ---

@app.route('/api/admin/create_bot', methods=['POST'])
def create_bot():
    """Create a new bot (admin only - protected by admin key)"""
    admin_key = request.headers.get('X-Admin-Key')
    if admin_key != os.environ.get('ADMIN_KEY', 'admin123'):
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.get_json()
    bot_name = data.get('name', '').strip()
    llm_type = data.get('llm_type', '').strip()  # gemini, deepseek, claude, gpt
    
    if not bot_name or not llm_type:
        return jsonify({"error": "Name and llm_type required"}), 400
    
    # Generate API key
    api_key = secrets.token_urlsafe(32)
    api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    
    conn = get_db()
    ph = get_ph()
    cursor = conn.cursor()
    
    try:
        cursor.execute(f'''
            INSERT INTO bots (name, llm_type, api_key_hash, cash) 
            VALUES ({ph}, {ph}, {ph}, {ph})
        ''', (bot_name, llm_type, api_key_hash, STARTING_CASH))
        conn.commit()
    except Exception as e:
        conn.close()
        return jsonify({"error": f"Bot name already exists: {e}"}), 400
    
    conn.close()
    
    # Return the API key (only shown once!)
    return jsonify({
        "message": f"Bot '{bot_name}' created!",
        "api_key": api_key,
        "warning": "Save this API key - it won't be shown again!"
    })

@app.route('/api/admin/reset_bot', methods=['POST'])
def reset_bot():
    """Reset a bot's portfolio (admin only)"""
    admin_key = request.headers.get('X-Admin-Key')
    if admin_key != os.environ.get('ADMIN_KEY', 'admin123'):
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.get_json()
    bot_name = data.get('name', '').strip()
    
    conn = get_db()
    ph = get_ph()
    cursor = conn.cursor()
    
    cursor.execute(f'SELECT id FROM bots WHERE name = {ph}', (bot_name,))
    bot = cursor.fetchone()
    
    if not bot:
        conn.close()
        return jsonify({"error": "Bot not found"}), 404
    
    bot_id = bot['id']
    
    # Reset
    cursor.execute(f'UPDATE bots SET cash = {ph} WHERE id = {ph}', (STARTING_CASH, bot_id))
    cursor.execute(f'DELETE FROM holdings WHERE bot_id = {ph}', (bot_id,))
    cursor.execute(f'DELETE FROM transactions WHERE bot_id = {ph}', (bot_id,))
    cursor.execute(f'DELETE FROM portfolio_snapshots WHERE bot_id = {ph}', (bot_id,))
    
    conn.commit()
    conn.close()
    
    return jsonify({"message": f"Bot '{bot_name}' reset to ${STARTING_CASH:,.2f}"})

# --- BOT TRADING ROUTES ---

@app.route('/api/bot/portfolio', methods=['GET'])
@require_api_key
def get_portfolio():
    """Get bot's current portfolio"""
    bot = request.bot
    conn = get_db()
    ph = get_ph()
    cursor = conn.cursor()
    
    cursor.execute(f'SELECT ticker, shares, avg_price FROM holdings WHERE bot_id = {ph}', (bot['id'],))
    holdings = cursor.fetchall()
    conn.close()
    
    portfolio = []
    total_stock_value = 0
    
    for h in holdings:
        price = get_stock_price(h['ticker']) or h['avg_price']
        value = price * h['shares']
        total_stock_value += value
        portfolio.append({
            "ticker": h['ticker'],
            "shares": h['shares'],
            "avg_price": round(h['avg_price'], 2),
            "current_price": round(price, 2),
            "value": round(value, 2),
            "gain_pct": round((price - h['avg_price']) / h['avg_price'] * 100, 2)
        })
    
    total_value = bot['cash'] + total_stock_value
    
    return jsonify({
        "cash": round(bot['cash'], 2),
        "stock_value": round(total_stock_value, 2),
        "total_value": round(total_value, 2),
        "return_pct": round((total_value - STARTING_CASH) / STARTING_CASH * 100, 2),
        "holdings": portfolio,
        "sharpe_ratio": calculate_sharpe_ratio(bot['id'])
    })

@app.route('/api/bot/buy', methods=['POST'])
@require_api_key
def buy():
    """Buy stocks"""
    bot = request.bot
    data = request.get_json()
    
    ticker = data.get('ticker', '').upper().strip()
    shares = data.get('shares')
    
    # Validate ticker
    if not ticker or len(ticker) > 5:
        return jsonify({"error": "Invalid ticker"}), 400
    
    # Validate shares
    try:
        shares = int(shares)
        if shares < 1:
            raise ValueError()
    except:
        return jsonify({"error": "Invalid share quantity"}), 400
    
    # Get price
    price = get_stock_price(ticker)
    if not price:
        return jsonify({"error": f"Could not get price for {ticker}"}), 400
    
    if price < MIN_STOCK_PRICE:
        return jsonify({"error": f"Stock price ${price:.2f} below minimum ${MIN_STOCK_PRICE}"}), 400
    
    # Calculate costs
    trade_value = price * shares
    fee = trade_value * TRADING_FEE_PERCENT
    total_cost = trade_value + fee
    
    # Check cash
    if bot['cash'] < total_cost:
        return jsonify({"error": f"Insufficient cash. Need ${total_cost:,.2f}, have ${bot['cash']:,.2f}"}), 400
    
    # Check position limit (10% rule)
    total_portfolio = calculate_portfolio_value(bot['id'])
    max_position = total_portfolio * MAX_POSITION_PERCENT
    
    conn = get_db()
    ph = get_ph()
    cursor = conn.cursor()
    
    cursor.execute(f'SELECT shares, avg_price FROM holdings WHERE bot_id = {ph} AND ticker = {ph}', 
                   (bot['id'], ticker))
    existing = cursor.fetchone()
    
    current_position_value = 0
    if existing:
        current_position_value = existing['shares'] * price
    
    new_position_value = current_position_value + trade_value
    
    if new_position_value > max_position:
        conn.close()
        return jsonify({
            "error": f"Position would exceed 10% limit. Max allowed: ${max_position:,.2f}, would be: ${new_position_value:,.2f}"
        }), 400
    
    # Check correlation (warn but don't block)
    avg_correlation = calculate_portfolio_correlation(bot['id'], ticker)
    correlation_warning = None
    if avg_correlation > 0.7:
        correlation_warning = f"Warning: High portfolio correlation ({avg_correlation:.2f}). Consider diversifying."
    
    # Execute trade
    new_cash = bot['cash'] - total_cost
    cursor.execute(f'UPDATE bots SET cash = {ph} WHERE id = {ph}', (new_cash, bot['id']))
    
    if existing:
        # Update existing position with new average price
        new_shares = existing['shares'] + shares
        new_avg = ((existing['shares'] * existing['avg_price']) + (shares * price)) / new_shares
        cursor.execute(f'UPDATE holdings SET shares = {ph}, avg_price = {ph} WHERE bot_id = {ph} AND ticker = {ph}',
                       (new_shares, new_avg, bot['id'], ticker))
    else:
        cursor.execute(f'INSERT INTO holdings (bot_id, ticker, shares, avg_price) VALUES ({ph}, {ph}, {ph}, {ph})',
                       (bot['id'], ticker, shares, price))
    
    # Record transaction
    cursor.execute(f'''
        INSERT INTO transactions (bot_id, type, ticker, shares, price, fee) 
        VALUES ({ph}, 'BUY', {ph}, {ph}, {ph}, {ph})
    ''', (bot['id'], ticker, shares, price, fee))
    
    conn.commit()
    conn.close()
    
    response = {
        "message": f"Bought {shares} {ticker} at ${price:.2f}",
        "fee": round(fee, 2),
        "total_cost": round(total_cost, 2),
        "remaining_cash": round(new_cash, 2)
    }
    
    if correlation_warning:
        response["warning"] = correlation_warning
    
    return jsonify(response)

@app.route('/api/bot/sell', methods=['POST'])
@require_api_key
def sell():
    """Sell stocks"""
    bot = request.bot
    data = request.get_json()
    
    ticker = data.get('ticker', '').upper().strip()
    shares = data.get('shares')
    
    # Validate
    if not ticker:
        return jsonify({"error": "Invalid ticker"}), 400
    
    try:
        shares = int(shares)
        if shares < 1:
            raise ValueError()
    except:
        return jsonify({"error": "Invalid share quantity"}), 400
    
    conn = get_db()
    ph = get_ph()
    cursor = conn.cursor()
    
    # Check holdings
    cursor.execute(f'SELECT shares, avg_price FROM holdings WHERE bot_id = {ph} AND ticker = {ph}',
                   (bot['id'], ticker))
    holding = cursor.fetchone()
    
    if not holding or holding['shares'] < shares:
        conn.close()
        return jsonify({"error": f"Insufficient shares. Have {holding['shares'] if holding else 0}"}), 400
    
    # Get price
    price = get_stock_price(ticker)
    if not price:
        price = holding['avg_price']  # Fallback
    
    # Calculate proceeds
    trade_value = price * shares
    fee = trade_value * TRADING_FEE_PERCENT
    proceeds = trade_value - fee
    
    # Execute trade
    new_cash = bot['cash'] + proceeds
    cursor.execute(f'UPDATE bots SET cash = {ph} WHERE id = {ph}', (new_cash, bot['id']))
    
    if holding['shares'] == shares:
        cursor.execute(f'DELETE FROM holdings WHERE bot_id = {ph} AND ticker = {ph}', (bot['id'], ticker))
    else:
        cursor.execute(f'UPDATE holdings SET shares = shares - {ph} WHERE bot_id = {ph} AND ticker = {ph}',
                       (shares, bot['id'], ticker))
    
    # Record transaction
    cursor.execute(f'''
        INSERT INTO transactions (bot_id, type, ticker, shares, price, fee) 
        VALUES ({ph}, 'SELL', {ph}, {ph}, {ph}, {ph})
    ''', (bot['id'], ticker, shares, price, fee))
    
    conn.commit()
    conn.close()
    
    gain = (price - holding['avg_price']) * shares
    
    return jsonify({
        "message": f"Sold {shares} {ticker} at ${price:.2f}",
        "fee": round(fee, 2),
        "proceeds": round(proceeds, 2),
        "gain": round(gain, 2),
        "new_cash": round(new_cash, 2)
    })

@app.route('/api/bot/history', methods=['GET'])
@require_api_key
def get_history():
    """Get bot's transaction history"""
    bot = request.bot
    conn = get_db()
    ph = get_ph()
    cursor = conn.cursor()
    
    cursor.execute(f'''
        SELECT type, ticker, shares, price, fee, created_at 
        FROM transactions 
        WHERE bot_id = {ph} 
        ORDER BY created_at DESC 
        LIMIT 100
    ''', (bot['id'],))
    
    transactions = cursor.fetchall()
    conn.close()
    
    return jsonify([{
        "type": t['type'],
        "ticker": t['ticker'],
        "shares": t['shares'],
        "price": round(t['price'], 2),
        "fee": round(t['fee'], 2),
        "date": str(t['created_at'])
    } for t in transactions])

# --- PUBLIC ROUTES ---

@app.route('/api/leaderboard', methods=['GET'])
def leaderboard():
    """Public leaderboard"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT id, name, llm_type, cash FROM bots')
    bots = cursor.fetchall()
    conn.close()
    
    rankings = []
    for bot in bots:
        total_value = calculate_portfolio_value(bot['id'])
        sharpe = calculate_sharpe_ratio(bot['id'])
        return_pct = (total_value - STARTING_CASH) / STARTING_CASH * 100
        
        rankings.append({
            "name": bot['name'],
            "llm_type": bot['llm_type'],
            "total_value": round(total_value, 2),
            "return_pct": round(return_pct, 2),
            "sharpe_ratio": sharpe
        })
    
    # Sort by total value (highest first)
    rankings.sort(key=lambda x: x['total_value'], reverse=True)
    
    # Add rank
    for i, r in enumerate(rankings):
        r['rank'] = i + 1
    
    return jsonify(rankings)

@app.route('/api/bot/<name>/details', methods=['GET'])
def bot_details(name):
    """Public view of a bot's holdings"""
    conn = get_db()
    ph = get_ph()
    cursor = conn.cursor()
    
    cursor.execute(f'SELECT id, name, llm_type, cash FROM bots WHERE name = {ph}', (name,))
    bot = cursor.fetchone()
    
    if not bot:
        conn.close()
        return jsonify({"error": "Bot not found"}), 404
    
    cursor.execute(f'SELECT ticker, shares FROM holdings WHERE bot_id = {ph}', (bot['id'],))
    holdings = cursor.fetchall()
    conn.close()
    
    portfolio = []
    for h in holdings:
        price = get_stock_price(h['ticker']) or 0
        portfolio.append({
            "ticker": h['ticker'],
            "shares": h['shares'],
            "value": round(price * h['shares'], 2)
        })
    
    total_value = calculate_portfolio_value(bot['id'])
    
    return jsonify({
        "name": bot['name'],
        "llm_type": bot['llm_type'],
        "total_value": round(total_value, 2),
        "return_pct": round((total_value - STARTING_CASH) / STARTING_CASH * 100, 2),
        "sharpe_ratio": calculate_sharpe_ratio(bot['id']),
        "holdings": portfolio
    })

@app.route('/api/config', methods=['GET'])
def get_config():
    """Return arena configuration"""
    return jsonify({
        "starting_cash": STARTING_CASH,
        "trading_fee_percent": TRADING_FEE_PERCENT * 100,
        "max_position_percent": MAX_POSITION_PERCENT * 100,
        "min_stock_price": MIN_STOCK_PRICE
    })

@app.route('/')
def home():
    return send_from_directory('.', 'arena.html')

if __name__ == '__main__':
    debug_mode = not IS_CLOUD
    app.run(debug=debug_mode, port=5003)
