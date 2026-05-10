#!/usr/bin/env python3
"""
update_data_json.py - Actualiza data.json con posiciones reales desde Bybit
Se ejecuta DESPUÉS de cualquier trade para reflejar cambios en el dashboard
"""
import json, urllib.request, time, hmac, hashlib, sys, os

# Config - read from environment or use defaults
WILD_KEY = os.environ.get('BYBIT_KEY_WILD', 'E3G3MbtVngOhRpHS6D')
WILD_SECRET = os.environ.get('BYBIT_SECRET_WILD', 'skjTaRenp1Vlf4xF8vftEJ5DTwzYCQteKF7y')
JOAKO_KEY = os.environ.get('BYBIT_KEY_JOAKO', 'hdhT7GmiWLjF4SZ4Fl')
JOAKO_SECRET = os.environ.get('BYBIT_SECRET_JOAKO', 'CAKCUPeaJgUy6XeqPZeoV5lMtaC7NCRReVVR')

DASHBOARD_DIR = os.path.join(os.path.dirname(__file__), '..', 'dashboard-repo')
DATA_FILE = os.path.join(DASHBOARD_DIR, 'data.json')

def bybit_api(method, endpoint, params=None, key=None, secret=None):
    """Call Bybit API with signature"""
    api_key = key
    api_secret = secret
    ts = str(int(time.time() * 1000))
    
    if method == 'GET':
        query = '&'.join(f'{k}={v}' for k,v in sorted((params or {}).items())) if params else ''
        raw = ts + api_key + '5000' + query
        url = f'https://api.bybit.com{endpoint}'
        if query: url += '?' + query
        body_data = None
    else:
        body = json.dumps(params or {})
        raw = ts + api_key + '5000' + body
        url = f'https://api.bybit.com{endpoint}'
        body_data = body.encode()
    
    sig = hmac.new(api_secret.encode(), raw.encode(), hashlib.sha256).hexdigest()
    headers = {
        'X-BAPI-API-KEY': api_key, 'X-BAPI-TIMESTAMP': ts,
        'X-BAPI-SIGN': sig, 'X-BAPI-RECV-WINDOW': '5000',
        'Content-Type': 'application/json'
    }
    req = urllib.request.Request(url, data=body_data, headers=headers, method=method)
    return json.loads(urllib.request.urlopen(req).read())

def get_positions(key, secret, account_name):
    """Get spot balances from unified account"""
    r = bybit_api('GET', '/v5/account/wallet-balance', 
                   {'accountType': 'UNIFIED'}, key, secret)
    
    wallets = []
    if r['retCode'] != 0:
        print(f'  [ERROR] {account_name}: {r["retMsg"]}')
        return wallets
    
    coins = r['result']['list'][0]['coin']
    for c in coins:
        wallet = float(c.get('walletBalance', 0))
        if wallet <= 0:
            continue
        sym = c['coin']
        
        # Get current price for non-USDT
        price = 1.0
        if sym != 'USDT':
            try:
                url = f'https://api.bybit.com/v5/market/tickers?category=spot&symbol={sym}USDT'
                tr = json.loads(urllib.request.urlopen(url).read())
                if tr['retCode'] == 0 and tr['result']['list']:
                    price = float(tr['result']['list'][0]['lastPrice'])
            except:
                price = 0
        
        wallets.append({
            'account': account_name,
            'symbol': sym,
            'quantity': round(wallet, 4),
            'price': price,
            'value': round(wallet * price, 6)
        })
    
    return wallets

# Get positions from both accounts
print("Fetching positions from Bybit...")
all_wallets = []
all_wallets += get_positions(WILD_KEY, WILD_SECRET, 'WILD')
time.sleep(0.5)
all_wallets += get_positions(JOAKO_KEY, JOAKO_SECRET, 'JOAKO')

# Filter: show ALL coins (any value > 0)
wallets = [w for w in all_wallets if w['symbol'] == 'USDT' or w['value'] > 0]

# Calculate totals
total_value = sum(w['value'] for w in wallets)
wild_value = sum(w['value'] for w in wallets if w['account'] == 'WILD')
joako_value = sum(w['value'] for w in wallets if w['account'] == 'JOAKO')

# Read existing data.json for history and strategy
try:
    with open(DATA_FILE) as f:
        existing = json.load(f)
except:
    existing = {}

# Get open positions (non-USDT, ALL values)
positions = [w for w in wallets if w['symbol'] != 'USDT' and w['value'] > 0]

# Fetch BTC price
btc_data = {'price': 80000, 'change': 0}
try:
    import urllib.request
    r = json.loads(urllib.request.urlopen('https://api.bybit.com/v5/market/tickers?category=spot&symbol=BTCUSDT', timeout=5).read())
    if r['retCode'] == 0 and r['result']['list']:
        t = r['result']['list'][0]
        btc_data = {'price': float(t['lastPrice']), 'change': float(t['price24hPcnt']) * 100}
except:
    pass

# Clean trades types
import copy
trade_history = copy.deepcopy(existing.get('trades', existing.get('tradeHistory', [])))
for t in trade_history:
    for k in ('qty','price','value','pnl'):
        if k in t and isinstance(t[k], str):
            try:
                t[k] = float(t[k])
            except:
                t[k] = 0
        if k in t and isinstance(t[k], bool):
            t[k] = 0
    if 'pnl' not in t:
        t['pnl'] = 0

# Get USDT balances
usdt = [w for w in wallets if w['symbol'] == 'USDT']

# Build the new data
new_data = {
    'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S-06:00', time.localtime()),
    'totalCapital': round(total_value, 2),
    'startCapital': existing.get('startCapital', 105),
    'startDate': existing.get('startDate', '2026-04-24'),
    'pnlCycle': round(total_value - (existing.get('startCapital', 105) if total_value > existing.get('startCapital', 105) * 0.5 else 0), 2),
    'pnlPercent': str(round(((total_value / (existing.get('startCapital', 105) or 1)) - 1) * 100, 2)),
    'accounts': {
        'WILD': {
            'capital': round(wild_value, 2),
            'startCapital': existing.get('accounts', {}).get('WILD', {}).get('startCapital', 55),
            'startDate': existing.get('accounts', {}).get('WILD', {}).get('startDate', '2026-04-24'),
            'pnl': round(wild_value - (existing.get('accounts', {}).get('WILD', {}).get('startCapital', 55) if wild_value > 10 else 0), 2)
        },
        'JOAKO': {
            'capital': round(joako_value, 2),
            'startCapital': existing.get('accounts', {}).get('JOAKO', {}).get('startCapital', 50),
            'startDate': existing.get('accounts', {}).get('JOAKO', {}).get('startDate', '2026-04-24'),
            'pnl': round(joako_value - (existing.get('accounts', {}).get('JOAKO', {}).get('startCapital', 50) if joako_value > 10 else 0), 2)
        }
    },
    'wallets': wallets,
    'strategy': existing.get('strategy', {
        'name': 'Wave Trading - Raven',
        'rules': [
            {'at': '+8%', 'action': 'Vender 33% (partial sell)'},
            {'at': '+15%', 'action': 'Vender 30% de lo que queda'},
            {'at': '+25%', 'action': 'Vender 20% de lo que queda'},
            {'at': 'trailing', 'action': 'Stop dinámico 12% desde pico'},
            {'at': 'stop loss', 'action': 'Stop duro -8% desde entrada'}
        ],
        'notes': 'Scalping con momentum. Rotación automática sin preguntar.'
    }),
    'openPositions': len(positions),
    'btc': btc_data,
    'positions': positions,
    'usdtBalances': usdt,
    'capitalHistory': existing.get('capitalHistory', []) + [{
        'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S-06:00', time.localtime()),
        'total': round(total_value, 2),
        'wild': round(wild_value, 2),
        'joako': round(joako_value, 2)
    }],
    'trades': trade_history
}

# Clean types in trade history
for t in new_data.get('tradeHistory', []):
    for k in ('qty','price','value'):
        if k in t and isinstance(t[k], (int, float)):
            t[k] = str(t[k])


# Enrich positions with entryPrice, stop, targets from trade_state
STATE_FILE = os.path.join(os.path.dirname(DATA_FILE), '..', 'logs', 'trade_state.json')
try:
    with open(STATE_FILE) as f:
        ts = json.load(f)
    for p in new_data.get('positions', []):
        key = f"{p.get('account', 'WILD').upper()}:{p['symbol']}"
        if key in ts and ts[key].get('ep'):
            ep = ts[key]['ep']
            p['entryPrice'] = ep
            p['qty'] = p.get('quantity', 0)
            p['stop'] = round(ep * 0.955, 10)
            p['target8'] = round(ep * 1.08, 10)
            p['target15'] = round(ep * 1.15, 10)
            p['target25'] = round(ep * 1.25, 10)
except:
    pass


# Keep only last 500 capital history entries
if len(new_data['capitalHistory']) > 500:
    new_data['capitalHistory'] = new_data['capitalHistory'][-500:]

# Write data.json
os.makedirs(DASHBOARD_DIR, exist_ok=True)
with open(DATA_FILE, 'w') as f:
    json.dump(new_data, f, indent=2)

print(f"Written: ${total_value:.2f} total")
print(f"Positions: {len(positions)} open ({', '.join(p['symbol'] for p in positions)})")
print(f"USDT: {', '.join(f'{u["account"]} ${u["quantity"]:.2f}' for u in usdt)}")
