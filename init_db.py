import sqlite3
import os
import psycopg2

# --- CONFIGURATION ---
IS_CLOUD = 'DATABASE_URL' in os.environ
STARTING_CASH = 100000.00

def get_db():
    if IS_CLOUD:
        return psycopg2.connect(os.environ['DATABASE_URL'])
    else:
        return sqlite3.connect('arena.db')

def get_ph():
    return '%s' if IS_CLOUD else '?'

# --- CONNECT ---
connection = get_db()
cursor = connection.cursor()
ph = get_ph()

print(f"🤖 Initializing LLM Trading Arena ({'Postgres' if IS_CLOUD else 'SQLite'})...")

# --- DROP TABLES ---
tables = ['portfolio_snapshots', 'transactions', 'holdings', 'bots']
for table in tables:
    cursor.execute(f'DROP TABLE IF EXISTS {table} CASCADE' if IS_CLOUD else f'DROP TABLE IF EXISTS {table}')

# --- CREATE TABLES ---

# 1. BOTS
cursor.execute(f'''
    CREATE TABLE bots (
        id {'SERIAL' if IS_CLOUD else 'INTEGER'} PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        llm_type TEXT NOT NULL,
        api_key_hash TEXT NOT NULL,
        cash REAL NOT NULL DEFAULT {STARTING_CASH},
        created_at {'TIMESTAMP' if IS_CLOUD else 'DATETIME'} DEFAULT CURRENT_TIMESTAMP
    )
''')

# 2. HOLDINGS
cursor.execute(f'''
    CREATE TABLE holdings (
        id {'SERIAL' if IS_CLOUD else 'INTEGER'} PRIMARY KEY,
        bot_id INTEGER NOT NULL,
        ticker TEXT NOT NULL,
        shares INTEGER NOT NULL,
        avg_price REAL NOT NULL,
        FOREIGN KEY (bot_id) REFERENCES bots (id),
        UNIQUE(bot_id, ticker)
    )
''')

# 3. TRANSACTIONS
cursor.execute(f'''
    CREATE TABLE transactions (
        id {'SERIAL' if IS_CLOUD else 'INTEGER'} PRIMARY KEY,
        bot_id INTEGER NOT NULL,
        type TEXT NOT NULL,
        ticker TEXT NOT NULL,
        shares INTEGER NOT NULL,
        price REAL NOT NULL,
        fee REAL NOT NULL DEFAULT 0,
        created_at {'TIMESTAMP' if IS_CLOUD else 'DATETIME'} DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (bot_id) REFERENCES bots (id)
    )
''')

# 4. PORTFOLIO SNAPSHOTS (for Sharpe ratio calculation)
cursor.execute(f'''
    CREATE TABLE portfolio_snapshots (
        id {'SERIAL' if IS_CLOUD else 'INTEGER'} PRIMARY KEY,
        bot_id INTEGER NOT NULL,
        date DATE NOT NULL,
        value REAL NOT NULL,
        FOREIGN KEY (bot_id) REFERENCES bots (id),
        UNIQUE(bot_id, date)
    )
''')

connection.commit()
connection.close()

print("✅ LLM Trading Arena Database Ready!")
print("")
print("Next steps:")
print("1. Set environment variables: SECRET_KEY, ADMIN_KEY")
print("2. Run the app: python arena_app.py")
print("3. Create bots via API:")
print("   curl -X POST http://localhost:5003/api/admin/create_bot \\")
print("     -H 'X-Admin-Key: your-admin-key' \\")
print("     -H 'Content-Type: application/json' \\")
print("     -d '{\"name\": \"Gemini-Bot\", \"llm_type\": \"gemini\"}'")
