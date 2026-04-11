import os
import io
import qrcode
import psycopg2
import psycopg2.extras
from flask import Flask, render_template_string, request, redirect, url_for, session, jsonify, make_response
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "nashmi-secret-2024")

DATABASE_URL = os.environ.get("DATABASE_URL", "")

# ─── DATABASE ────────────────────────────────────────────────────
def get_db():
    """Open a new PostgreSQL connection using DATABASE_URL env var."""
    url = DATABASE_URL
    # Railway sometimes returns postgres:// — psycopg2 needs postgresql://
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    conn = psycopg2.connect(url)
    return conn

def cur(conn):
    """Return a RealDictCursor (rows behave like dicts)."""
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

def qry(conn, sql, params=()):
    """Execute a SELECT and return the cursor (caller calls .fetchone()/.fetchall())."""
    c = cur(conn)
    c.execute(sql, params)
    return c

def exe(conn, sql, params=()):
    """Execute an INSERT/UPDATE/DELETE without returning rows."""
    c = cur(conn)
    c.execute(sql, params)

def exe_returning(conn, sql, params=()):
    """Execute INSERT … RETURNING id and return the new row id."""
    c = cur(conn)
    c.execute(sql, params)
    return c.fetchone()["id"]

def init_db():
    conn = get_db()
    c = cur(conn)

    # ── DDL — PostgreSQL syntax ───────────────────────────────────
    ddl_statements = [
        """CREATE TABLE IF NOT EXISTS users (
            id   SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            role TEXT NOT NULL,
            pin  TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS menu_items (
            id        SERIAL PRIMARY KEY,
            name      TEXT    NOT NULL,
            price     FLOAT   NOT NULL,
            category  TEXT    NOT NULL,
            available INTEGER DEFAULT 1
        )""",
        """CREATE TABLE IF NOT EXISTS days (
            id         SERIAL PRIMARY KEY,
            started_at TEXT,
            closed_at  TEXT,
            status     TEXT DEFAULT 'open'
        )""",
        """CREATE TABLE IF NOT EXISTS orders (
            id         SERIAL PRIMARY KEY,
            day_id     INTEGER,
            total      FLOAT  DEFAULT 0,
            payment    TEXT   DEFAULT 'نقدي',
            status     TEXT   DEFAULT 'pending',
            source     TEXT   DEFAULT 'staff',
            employee   TEXT,
            note       TEXT,
            created_at TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS order_items (
            id         SERIAL PRIMARY KEY,
            order_id   INTEGER,
            item_name  TEXT,
            price      FLOAT,
            qty        INTEGER DEFAULT 1,
            note       TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS expenses (
            id         SERIAL PRIMARY KEY,
            day_id     INTEGER,
            amount     FLOAT,
            reason     TEXT,
            employee   TEXT,
            created_at TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS draws (
            id         SERIAL PRIMARY KEY,
            day_id     INTEGER,
            amount     FLOAT,
            employee   TEXT,
            note       TEXT,
            created_at TEXT
        )""",
    ]
    for stmt in ddl_statements:
        c.execute(stmt)

    # ── Seed default users if table is empty ─────────────────────
    c.execute("SELECT COUNT(*) AS cnt FROM users")
    if c.fetchone()["cnt"] == 0:
        seed = [
            ("نشمي",   "admin",    "8888"),
            ("المالك", "admin",    "1234"),
            ("عمر",    "employee", "1997"),
            ("ناصر",   "employee", "0000"),
        ]
        for name, role, pin in seed:
            c.execute(
                "INSERT INTO users (name, role, pin) VALUES (%s, %s, %s)",
                (name, role, pin)
            )

    conn.commit()
    conn.close()

def current_day():
    conn = get_db()
    day = qry(conn, "SELECT * FROM days WHERE status='open' ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    return dict(day) if day else None

def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# ─── BASE TEMPLATE ────────────────────────────────────────────────
BASE_HTML = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>☕ Nashmi Café</title>
<link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;900&display=swap" rel="stylesheet">
<style>
  :root {
    --bg: #0a0604;
    --surface: #150e08;
    --surface2: #1f1409;
    --surface3: #2a1c0d;
    --accent: #d4880a;
    --accent2: #f5b835;
    --accent3: #ff8c42;
    --cream: #f5e2b8;
    --text: #ede0c4;
    --text2: #b89464;
    --muted: #5a4030;
    --green: #2ecc71;
    --red: #e74c3c;
    --blue: #3498db;
    --border: #2e1c0e;
    --radius: 14px;
    --glow: 0 0 20px rgba(212,136,10,0.2);
    /* Safe area insets for notched / Dynamic Island phones */
    --safe-top: env(safe-area-inset-top, 0px);
    --safe-bottom: env(safe-area-inset-bottom, 0px);
    --safe-left: env(safe-area-inset-left, 0px);
    --safe-right: env(safe-area-inset-right, 0px);
  }

  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  html { -webkit-text-size-adjust: 100%; text-size-adjust: 100%; }

  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'Cairo', sans-serif;
    min-height: 100vh;
    min-height: 100dvh;          /* dynamic viewport on mobile browsers */
    font-size: 15px;
    position: relative;
    overflow-x: hidden;
    /* prevent rubber-band pull revealing white bg on iOS */
    overscroll-behavior-y: contain;
  }

  /* ── Animated background beans ── */
  body::before {
    content: '';
    position: fixed;
    inset: 0;
    background:
      radial-gradient(ellipse at 20% 20%, rgba(212,136,10,0.06) 0%, transparent 50%),
      radial-gradient(ellipse at 80% 80%, rgba(255,140,66,0.05) 0%, transparent 50%),
      radial-gradient(ellipse at 50% 50%, rgba(20,10,5,0.8) 0%, transparent 70%);
    pointer-events: none;
    z-index: 0;
  }

  .bg-beans {
    position: fixed;
    inset: 0;
    pointer-events: none;
    z-index: 0;
    overflow: hidden;
  }
  .bean {
    position: absolute;
    border-radius: 50% 50% 50% 50% / 60% 60% 40% 40%;
    opacity: 0;
    animation: floatBean linear infinite;
  }
  @keyframes floatBean {
    0%   { opacity: 0; transform: translateY(110vh) rotate(0deg); }
    10%  { opacity: 0.12; }
    90%  { opacity: 0.08; }
    100% { opacity: 0; transform: translateY(-10vh) rotate(360deg); }
  }
  @keyframes pulse-glow {
    0%,100% { box-shadow: 0 0 12px rgba(212,136,10,0.3); }
    50%      { box-shadow: 0 0 28px rgba(245,184,53,0.5); }
  }

  body > *:not(.bg-beans) { position: relative; z-index: 1; }

  a { color: inherit; text-decoration: none; -webkit-tap-highlight-color: transparent; }

  /* ── Topbar ── */
  .topbar {
    background: rgba(21,14,8,0.95);
    border-bottom: 1px solid var(--border);
    padding: 10px 14px;
    padding-top: calc(10px + var(--safe-top));
    display: flex;
    justify-content: space-between;
    align-items: center;
    position: sticky;
    top: 0;
    z-index: 50;
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    gap: 8px;
  }
  .topbar-left  { min-width: 0; flex: 1; }
  .topbar-title { font-size: clamp(15px, 4vw, 18px); font-weight: 900; color: var(--accent2); letter-spacing: -0.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .topbar-sub   { font-size: 11px; color: var(--text2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .topbar-right { display: flex; align-items: center; gap: 6px; flex-shrink: 0; }

  /* ── Pages ── */
  .page      { padding: 14px; max-width: 480px; margin: 0 auto; }
  .page-wide { padding: 14px; }

  /* ── Card ── */
  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 14px;
    margin-bottom: 12px;
  }
  .card-title { font-size: 13px; font-weight: 700; color: var(--text2); margin-bottom: 12px; }

  /* ── Buttons — min 44 px tall for touch targets ── */
  .btn {
    display: inline-flex; align-items: center; justify-content: center;
    gap: 6px;
    padding: 12px 18px;
    min-height: 44px;
    border-radius: 11px; border: none;
    font-family: 'Cairo', sans-serif; font-size: 15px; font-weight: 700;
    cursor: pointer; transition: all 0.18s; width: 100%; text-align: center;
    -webkit-tap-highlight-color: transparent;
    touch-action: manipulation;
  }
  .btn-primary { background: linear-gradient(135deg, var(--accent), var(--accent3)); color: #000; }
  .btn-primary:active { filter: brightness(1.15); transform: scale(0.98); box-shadow: 0 4px 16px rgba(212,136,10,0.4); }
  .btn-primary:disabled { opacity: 0.4; cursor: not-allowed; transform: none; }
  .btn-green  { background: var(--green); color: #000; }
  .btn-green:active  { filter: brightness(1.1); }
  .btn-red    { background: var(--red);   color: #fff; }
  .btn-red:active    { filter: brightness(1.1); }
  .btn-purple { background: linear-gradient(135deg, #8e44ad, #9b59b6); color: #fff; }
  .btn-purple:active { filter: brightness(1.15); }
  .btn-outline { background: none; border: 1px solid var(--border); color: var(--text2); }
  .btn-outline:active { border-color: var(--accent); color: var(--accent); }
  .btn-sm { padding: 8px 14px; font-size: 13px; width: auto; min-height: 38px; }

  /* ── Inputs — 16 px prevents iOS auto-zoom on focus ── */
  .input {
    background: var(--surface2); border: 1px solid var(--border);
    color: var(--text); padding: 12px 14px; border-radius: 10px;
    font-size: 16px;                 /* ← MUST be ≥16px on iOS */
    font-family: 'Cairo', sans-serif; outline: none;
    width: 100%; text-align: right;
    -webkit-appearance: none;
    min-height: 48px;
  }
  .input:focus { border-color: var(--accent); box-shadow: 0 0 0 3px rgba(212,136,10,0.15); }

  .select {
    background: var(--surface2); border: 1px solid var(--border);
    color: var(--text); padding: 12px 14px; border-radius: 10px;
    font-size: 16px;                 /* ← MUST be ≥16px on iOS */
    font-family: 'Cairo', sans-serif; outline: none;
    width: 100%; text-align: right;
    -webkit-appearance: none;
    min-height: 48px;
  }

  .label { font-size: 12px; color: var(--text2); font-weight: 700; margin-bottom: 6px; display: block; }

  .form-group { margin-bottom: 12px; }
  .form-row   { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }

  /* Stack form-row on very small screens */
  @media (max-width: 360px) {
    .form-row { grid-template-columns: 1fr; }
  }

  /* ── Badges ── */
  .badge {
    display: inline-flex; align-items: center; justify-content: center;
    background: var(--accent); color: #000; border-radius: 20px;
    padding: 2px 10px; font-size: 12px; font-weight: 700; min-width: 24px;
  }
  .badge-green  { background: var(--green); color: #000; }
  .badge-red    { background: var(--red);   color: #fff; }
  .badge-purple { background: #8e44ad;       color: #fff; }

  /* ── Nav tabs — hide scrollbar while keeping scrollability ── */
  .nav-tabs {
    display: flex;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: none;          /* Firefox */
    gap: 0;
  }
  .nav-tabs::-webkit-scrollbar { display: none; } /* Chrome/Safari */

  .nav-tab {
    flex: 0 0 auto;
    min-width: 0;
    padding: 11px 10px;
    text-align: center;
    font-size: clamp(11px, 2.8vw, 13px);
    font-weight: 700;
    color: var(--text2);
    border: none;
    background: none;
    cursor: pointer;
    font-family: 'Cairo', sans-serif;
    border-bottom: 2px solid transparent;
    transition: all 0.15s;
    white-space: nowrap;
    min-height: 44px;
    -webkit-tap-highlight-color: transparent;
    touch-action: manipulation;
  }
  .nav-tab.active { color: var(--accent2); border-bottom-color: var(--accent2); }

  /* ── List items ── */
  .list-item {
    display: flex; align-items: center; justify-content: space-between;
    padding: 13px 0; border-bottom: 1px solid var(--border); gap: 10px;
  }
  .list-item:last-child { border-bottom: none; }

  /* ── Stats ── */
  .stat-row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 12px; }
  .stat {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 12px 8px; text-align: center;
  }
  .stat-val   { font-size: clamp(18px, 5vw, 22px); font-weight: 900; color: var(--accent2); }
  .stat-label { font-size: 11px; color: var(--text2); margin-top: 4px; }

  /* ── Alerts ── */
  .alert { padding: 12px 14px; border-radius: 10px; font-size: 13px; margin-bottom: 12px; }
  .alert-warn   { background: rgba(212,136,10,0.12); border: 1px solid var(--accent); color: var(--accent2); }
  .alert-success{ background: rgba(46,204,113,0.12); border: 1px solid var(--green); color: var(--green); }
  .alert-err    { background: rgba(231,76,60,0.12);  border: 1px solid var(--red);   color: var(--red); }
  .alert-purple { background: rgba(142,68,173,0.12); border: 1px solid #9b59b6;      color: #c39bd3; }

  .cat-title {
    font-size: 13px; font-weight: 700; color: var(--text2);
    padding: 10px 0 6px; border-bottom: 1px solid var(--border); margin-bottom: 8px;
  }

  /* ── PIN pad ── */
  .pin-wrap { display: flex; flex-direction: column; align-items: center; }
  .pin-display {
    background: var(--surface2); border: 1px solid var(--border); border-radius: 10px;
    padding: 14px; text-align: center; font-size: 28px; letter-spacing: 10px;
    color: var(--accent2); width: 100%; max-width: 260px;
    margin-bottom: 14px; height: 60px;
  }
  /* Fluid pin grid: 3 equal columns that fill available width */
  .pin-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 10px;
    width: 100%;
    max-width: 260px;
  }
  .pin-key {
    background: var(--surface2); border: 1px solid var(--border); color: var(--text);
    font-size: clamp(18px, 5vw, 22px);
    padding: 0;
    height: clamp(52px, 13vw, 66px);
    border-radius: 10px; cursor: pointer;
    transition: background 0.1s, border-color 0.1s;
    font-family: 'Cairo', sans-serif; font-weight: 700;
    -webkit-tap-highlight-color: transparent;
    touch-action: manipulation;
  }
  .pin-key:active { background: var(--surface); border-color: var(--accent); }
  .pin-key.confirm { background: linear-gradient(135deg, var(--accent), var(--accent3)); color: #000; }
  .pin-key.del     { color: var(--text2); }

  /* ── Menu item cards ── */
  .menu-item-card {
    background: var(--surface2); border: 1px solid var(--border); border-radius: 10px;
    padding: 12px 14px; display: flex; justify-content: space-between;
    align-items: center; margin-bottom: 10px; gap: 10px;
    transition: border-color 0.15s;
  }
  .menu-item-card:active { border-color: var(--accent); }
  .menu-item-name  { font-weight: 700; font-size: 15px; }
  .menu-item-price { font-size: 13px; color: var(--accent2); font-weight: 700; margin-top: 2px; }
  .menu-item-cat   { font-size: 11px; color: var(--text2); margin-top: 2px; }

  /* ── Order cards ── */
  .order-card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); overflow: hidden; margin-bottom: 14px; }
  .order-card-head { padding: 10px 14px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 6px; }
  .order-card-body { padding: 10px 14px; }
  .order-card-foot { padding: 10px 14px; border-top: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap; }

  /* ── Banners ── */
  .day-banner      { background: var(--green); color: #000; padding: 10px 16px; text-align: center; font-size: 13px; font-weight: 700; }
  .day-banner-warn { background: var(--red);   color: #fff; }

  /* ── Larger screens ── */
  @media (min-width: 600px) {
    .page      { padding: 24px; }
    .page-wide { padding: 24px; max-width: 700px; margin: 0 auto; }
    .form-row-3 { grid-template-columns: 1fr 1fr 1fr; }
    .nav-tab { font-size: 13px; padding: 12px 14px; }
    .btn:hover { filter: brightness(1.1); }
    .btn-primary:hover { transform: translateY(-1px); box-shadow: 0 4px 16px rgba(212,136,10,0.4); }
    .btn-outline:hover { border-color: var(--accent); color: var(--accent); }
    .menu-item-card:hover { border-color: var(--accent); }
  }
</style>
</head>
<body>
<div class="bg-beans" id="bgBeans"></div>
{% block body %}{% endblock %}
<script>
// ── Floating coffee beans background ──
(function() {
  const container = document.getElementById('bgBeans');
  if (!container) return;
  const colors = ['#d4880a','#f5b835','#8B4513','#a0522d','#ff8c42','#cd853f'];
  for (let i = 0; i < 18; i++) {
    const bean = document.createElement('div');
    bean.className = 'bean';
    const size = Math.random() * 14 + 6;
    bean.style.cssText = `
      width:${size}px; height:${size * 0.65}px;
      left:${Math.random()*100}%;
      background:${colors[Math.floor(Math.random()*colors.length)]};
      animation-duration:${Math.random()*18+12}s;
      animation-delay:${Math.random()*-20}s;
      filter: blur(${Math.random()*1}px);
    `;
    container.appendChild(bean);
  }
})();

function setPIN(val) {
  const d = document.getElementById('pinDisplay');
  const h = document.getElementById('pinHidden');
  if (!d || !h) return;
  let p = h.value;
  if (val === 'DEL') { p = p.slice(0,-1); }
  else if (p.length < 4) { p += val; }
  h.value = p;
  d.textContent = '●'.repeat(p.length).padEnd(4, '○');
  if (p.length === 4) {
    document.getElementById('userIdField').value = document.getElementById('userSelect').value;
    setTimeout(() => document.getElementById('pinForm').submit(), 200);
  }
}
function addToCart(name, price) {
  let cart = JSON.parse(localStorage.getItem('cart') || '[]');
  const ex = cart.find(i => i.name === name);
  if (ex) { ex.qty++; }
  else { cart.push({name, price, qty: 1}); }
  localStorage.setItem('cart', JSON.stringify(cart));
  renderCart();
}
function removeFromCart(name) {
  let cart = JSON.parse(localStorage.getItem('cart') || '[]');
  cart = cart.filter(i => i.name !== name);
  localStorage.setItem('cart', JSON.stringify(cart));
  renderCart();
}
function renderCart() {
  const cart = JSON.parse(localStorage.getItem('cart') || '[]');
  const el = document.getElementById('cartItems');
  const totalEl = document.getElementById('cartTotal');
  const countEl = document.getElementById('cartCount');
  const emptyEl = document.getElementById('cartEmpty');
  const submitEl = document.getElementById('submitOrder');
  if (!el) return;
  const total = cart.reduce((s, i) => s + i.price * i.qty, 0);
  if (countEl) countEl.textContent = cart.reduce((s,i)=>s+i.qty,0) || '';
  if (totalEl) totalEl.textContent = total.toFixed(2) + ' ر.س';
  if (emptyEl) emptyEl.style.display = cart.length ? 'none' : 'block';
  if (submitEl) submitEl.disabled = cart.length === 0;
  el.innerHTML = cart.map(i => `
    <div class="list-item">
      <button onclick="removeFromCart('${i.name.replace(/'/g,"\\'")}'); return false;" style="background:none;border:none;color:var(--red);font-size:18px;cursor:pointer;">×</button>
      <div style="flex:1"><div style="font-weight:700">${i.name}</div><div style="font-size:12px;color:var(--text2)">${i.price.toFixed(2)} ر.س × ${i.qty}</div></div>
      <div style="font-weight:700;color:var(--accent2)">${(i.price*i.qty).toFixed(2)} ر.س</div>
    </div>`).join('');
}
function submitOrder() {
  const cart = JSON.parse(localStorage.getItem('cart') || '[]');
  if (!cart.length) return;
  const pay = document.getElementById('payMethod');
  const note = document.getElementById('orderNote');
  fetch('/pos/submit', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      items: cart,
      payment: pay ? pay.value : 'نقدي',
      note: note ? note.value : '',
      source: 'staff'
    })
  }).then(r => r.json()).then(d => {
    if (d.ok) {
      localStorage.removeItem('cart');
      renderCart();
      const msg = document.getElementById('orderMsg');
      if (msg) { msg.style.display='block'; setTimeout(()=>msg.style.display='none', 3000); }
    }
  });
}
function submitCustomerOrder() {
  const cart = JSON.parse(localStorage.getItem('customerCart') || '[]');
  if (!cart.length) return;
  const note = document.getElementById('customerNote');
  const btn = document.getElementById('customerSubmitBtn');
  if(btn) btn.disabled = true;
  fetch('/customer/submit', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      items: cart,
      note: note ? note.value : '',
    })
  }).then(r => r.json()).then(d => {
    if (d.ok) {
      localStorage.removeItem('customerCart');
      document.getElementById('customerCartSection').style.display = 'none';
      document.getElementById('customerSuccessMsg').style.display = 'flex';
    } else {
      alert(d.error || 'حدث خطأ');
      if(btn) btn.disabled = false;
    }
  });
}
function addToCustomerCart(name, price) {
  let cart = JSON.parse(localStorage.getItem('customerCart') || '[]');
  const ex = cart.find(i => i.name === name);
  if (ex) { ex.qty++; }
  else { cart.push({name, price, qty: 1}); }
  localStorage.setItem('customerCart', JSON.stringify(cart));
  renderCustomerCart();
}
function removeFromCustomerCart(name) {
  let cart = JSON.parse(localStorage.getItem('customerCart') || '[]');
  cart = cart.filter(i => i.name !== name);
  localStorage.setItem('customerCart', JSON.stringify(cart));
  renderCustomerCart();
}
function changeCustomerQty(name, delta) {
  let cart = JSON.parse(localStorage.getItem('customerCart') || '[]');
  const item = cart.find(i => i.name === name);
  if (!item) return;
  item.qty += delta;
  if (item.qty <= 0) cart = cart.filter(i => i.name !== name);
  localStorage.setItem('customerCart', JSON.stringify(cart));
  renderCustomerCart();
}
function renderCustomerCart() {
  const cart = JSON.parse(localStorage.getItem('customerCart') || '[]');
  const el = document.getElementById('customerCartItems');
  const totalEl = document.getElementById('customerCartTotal');
  const countEl = document.getElementById('customerCartCount');
  const submitEl = document.getElementById('customerSubmitBtn');
  const section = document.getElementById('customerCartSection');
  if (!el) return;
  const total = cart.reduce((s, i) => s + i.price * i.qty, 0);
  const count = cart.reduce((s,i)=>s+i.qty,0);
  if (countEl) countEl.textContent = count || '';
  if (totalEl) totalEl.textContent = total.toFixed(2) + ' ر.س';
  if (submitEl) submitEl.disabled = cart.length === 0;
  if (section) section.style.display = cart.length ? 'block' : 'none';
  el.innerHTML = cart.map(i => `
    <div style="display:flex;align-items:center;gap:10px;padding:10px 0;border-bottom:1px solid rgba(255,255,255,0.08);">
      <div style="flex:1;">
        <div style="font-weight:700;font-size:14px;color:#fff;">${i.name}</div>
        <div style="font-size:12px;color:rgba(255,255,255,0.5);">${i.price.toFixed(2)} ر.س للواحدة</div>
      </div>
      <div style="display:flex;align-items:center;gap:8px;">
        <button onclick="changeCustomerQty('${i.name.replace(/'/g,"\\'")}', -1)" style="background:rgba(255,255,255,0.1);border:none;color:#fff;width:28px;height:28px;border-radius:50%;cursor:pointer;font-size:16px;display:flex;align-items:center;justify-content:center;">−</button>
        <span style="font-weight:700;color:#f5b835;min-width:20px;text-align:center;">${i.qty}</span>
        <button onclick="changeCustomerQty('${i.name.replace(/'/g,"\\'")}', 1)" style="background:rgba(212,136,10,0.5);border:none;color:#fff;width:28px;height:28px;border-radius:50%;cursor:pointer;font-size:16px;display:flex;align-items:center;justify-content:center;">+</button>
      </div>
      <div style="font-weight:700;color:#f5b835;min-width:60px;text-align:left;">${(i.price*i.qty).toFixed(2)} ر.س</div>
    </div>`).join('');
}
window.addEventListener('DOMContentLoaded', () => { renderCart(); renderCustomerCart(); });
</script>
</body>
</html>
"""

CATEGORIES = {
    "hot_coffee": "☕ قهوة ساخنة",
    "cold_coffee": "🧊 قهوة باردة",
    "hot_drinks": "🫖 مشروبات ساخنة",
    "cold_drinks": "🍹 مشروبات باردة",
    "snacks": "🍽️ وجبات خفيفة",
}

CATEGORY_IMG = {
    "hot_coffee":  "https://images.unsplash.com/photo-1509042239860-f550ce710b93?w=500&auto=format&fit=crop",
    "cold_coffee": "https://images.unsplash.com/photo-1461023058943-07fcbe16d735?w=500&auto=format&fit=crop",
    "hot_drinks":  "https://images.unsplash.com/photo-1597318181409-cf64d0b5d8a2?w=500&auto=format&fit=crop",
    "cold_drinks": "https://images.unsplash.com/photo-1622483767028-3f66f32aef97?w=500&auto=format&fit=crop",
    "snacks":      "https://images.unsplash.com/photo-1558961363-fa8fdf82db35?w=500&auto=format&fit=crop",
}

CATEGORY_GRADIENT = {
    "hot_coffee":  "linear-gradient(135deg,#6B2D0E,#d4880a)",
    "cold_coffee": "linear-gradient(135deg,#0e4d6b,#3498db)",
    "hot_drinks":  "linear-gradient(135deg,#5a1a0e,#e67e22)",
    "cold_drinks": "linear-gradient(135deg,#0e6b3e,#2ecc71)",
    "snacks":      "linear-gradient(135deg,#4a2a0e,#c0392b)",
}

# ─── HELPERS ─────────────────────────────────────────────────────
def render(template, **kwargs):
    full = BASE_HTML.replace("{% block body %}{% endblock %}", template)
    kwargs.setdefault("categories", CATEGORIES)
    kwargs.setdefault("category_img", CATEGORY_IMG)
    kwargs.setdefault("category_gradient", CATEGORY_GRADIENT)
    return render_template_string(full, **kwargs)

def login_required(fn):
    from functools import wraps
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect("/")
        return fn(*args, **kwargs)
    return wrapper

def admin_required(fn):
    from functools import wraps
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if session.get("user_role") != "admin":
            return redirect("/pos")
        return fn(*args, **kwargs)
    return wrapper

# ─── LOGIN ────────────────────────────────────────────────────────
LOGIN_HTML = """
<div style="min-height:100vh;min-height:100dvh;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:20px 16px;padding-top:calc(20px + var(--safe-top));padding-bottom:calc(20px + var(--safe-bottom));">
  <div style="width:100%;max-width:340px;">
    <div style="text-align:center;margin-bottom:28px;">
      <div style="font-size:52px;margin-bottom:8px;filter:drop-shadow(0 0 20px rgba(212,136,10,0.5));">☕</div>
      <div style="font-size:30px;font-weight:900;background:linear-gradient(135deg,var(--accent2),var(--accent3));-webkit-background-clip:text;-webkit-text-fill-color:transparent;">Nashmi Café</div>
      <div style="font-size:13px;color:var(--text2);margin-top:4px;">نظام إدارة المقهى</div>
    </div>

    {% if error %}<div class="alert alert-err">{{ error }}</div>{% endif %}

    <div class="card" style="border-color:rgba(212,136,10,0.2);box-shadow:0 0 30px rgba(0,0,0,0.5);">
      <div class="form-group">
        <label class="label">اختر الحساب</label>
        <select class="select" id="userSelect" onchange="document.getElementById('pinHidden').value='';document.getElementById('pinDisplay').textContent='○○○○';">
          {% for u in users %}<option value="{{ u['id'] }}">{{ u['name'] }} ({{ 'مدير' if u['role']=='admin' else 'موظف' }})</option>{% endfor %}
        </select>
      </div>

      <div class="form-group">
        <label class="label">أدخل الرمز السري</label>
        <form id="pinForm" method="POST" action="/login">
          <input type="hidden" name="user_id" id="userIdField">
          <input type="hidden" name="pin" id="pinHidden" value="">
          <div class="pin-display" id="pinDisplay">○○○○</div>
          <div class="pin-grid" style="margin:0 auto;">
            {% for k in ['1','2','3','4','5','6','7','8','9','DEL','0','✓'] %}
            <button type="button" class="pin-key {% if k=='✓' %}confirm{% elif k=='DEL' %}del{% endif %}" onclick="setPIN('{{ k }}')">{{ k }}</button>
            {% endfor %}
          </div>
        </form>
      </div>
    </div>
  </div>
</div>
<script>
document.getElementById('pinForm').addEventListener('submit', function() {
  document.getElementById('userIdField').value = document.getElementById('userSelect').value;
});
</script>
"""

@app.route("/")
def index():
    if "user_id" in session:
        return redirect("/pos")
    conn = get_db()
    users = qry(conn, "SELECT * FROM users ORDER BY id").fetchall()
    conn.close()
    error = request.args.get("error", "")
    return render(LOGIN_HTML, users=users, error=error)

@app.route("/login", methods=["POST"])
def login():
    uid = request.form.get("user_id")
    pin = request.form.get("pin")
    conn = get_db()
    user = qry(conn, "SELECT * FROM users WHERE id=%s", (uid,)).fetchone()
    conn.close()
    if user and user["pin"] == pin:
        session["user_id"]   = user["id"]
        session["user_name"] = user["name"]
        session["user_role"] = user["role"]
        return redirect("/pos")
    return redirect("/?error=رمز خاطئ، حاول مجدداً")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ─── POS ─────────────────────────────────────────────────────────
POS_HTML = """
{% if not day %}
<div class="day-banner day-banner-warn">⚠️ اليوم لم يبدأ بعد. اطلب من المدير بدء اليوم.</div>
{% endif %}

<div class="topbar">
  <div>
    <div class="topbar-title">☕ Nashmi Café</div>
    <div class="topbar-sub">{{ user_name }} · {{ 'مدير' if user_role=='admin' else 'موظف' }}</div>
  </div>
  <div class="topbar-right">
    {% if user_role == 'admin' %}<a href="/admin" class="btn btn-outline btn-sm">⚙️ إدارة</a>{% endif %}
    <a href="/logout" class="btn btn-outline btn-sm">خروج</a>
  </div>
</div>

<div class="nav-tabs" id="mainTabs">
  <button class="nav-tab active" onclick="switchTab('menu', this)">📋 القائمة</button>
  <button class="nav-tab" onclick="switchTab('cart', this)">🛒 الطلب <span id="cartCount" class="badge" style="margin-right:4px;font-size:10px;"></span></button>
  <button class="nav-tab" onclick="switchTab('queue', this)">⏳ الطابور</button>
  <button class="nav-tab" onclick="switchTab('draws', this)" style="color:#c39bd3;">💜 سحوبات</button>
</div>

<!-- MENU TAB -->
<div id="tab-menu" class="page-wide" style="padding:16px;max-width:600px;margin:0 auto;">
  {% if not items %}
  <div class="card" style="text-align:center;color:var(--muted);padding:40px;">
    <div style="font-size:36px;margin-bottom:10px;">📭</div>
    <div>القائمة فارغة. أضف أصنافاً من <a href="/admin" style="color:var(--accent2);">الإدارة</a>.</div>
  </div>
  {% endif %}
  {% for cat_key, cat_label in categories.items() %}
    {% set cat_items = items | selectattr('category','equalto',cat_key) | list %}
    {% if cat_items %}
    <div class="cat-title">{{ cat_label }}</div>
    {% for item in cat_items %}
    <div class="menu-item-card">
      <div>
        <div class="menu-item-name">{{ item['name'] }}</div>
        <div class="menu-item-price">{{ "%.2f"|format(item['price']) }} ر.س</div>
      </div>
      <button class="btn btn-primary btn-sm" onclick="addToCart('{{ item['name']|replace("'", "\\'") }}', {{ item['price'] }})">+ إضافة</button>
    </div>
    {% endfor %}
    {% endif %}
  {% endfor %}
</div>

<!-- CART TAB -->
<div id="tab-cart" class="page" style="display:none;">
  <div class="card">
    <div class="card-title">🛒 الطلب الحالي</div>
    <div id="cartEmpty" style="text-align:center;color:var(--muted);padding:24px;font-size:13px;">لم تضف أي صنف بعد</div>
    <div id="cartItems"></div>
    <div class="list-item" style="border-top:1px solid var(--border);padding-top:14px;margin-top:4px;">
      <span style="font-weight:700;font-size:16px;">الإجمالي</span>
      <span id="cartTotal" style="font-weight:900;font-size:18px;color:var(--accent2);">0.00 ر.س</span>
    </div>
  </div>

  <div class="card">
    <div class="form-group">
      <label class="label">طريقة الدفع</label>
      <select class="select" id="payMethod">
        <option>نقدي</option>
        <option>بطاقة</option>
        <option>دفع إلكتروني</option>
      </select>
    </div>
    <div class="form-group">
      <label class="label">ملاحظة (اختياري)</label>
      <input class="input" id="orderNote" placeholder="مثال: بدون سكر...">
    </div>
  </div>

  <div id="orderMsg" class="alert alert-success" style="display:none;">✅ تم تسجيل الطلب!</div>

  <button class="btn btn-primary" id="submitOrder" onclick="submitOrder()" {% if not day %}disabled{% endif %}>
    {% if day %}✅ تأكيد الطلب{% else %}⚠️ اليوم لم يبدأ{% endif %}
  </button>
  <button class="btn btn-outline" style="margin-top:10px;" onclick="localStorage.removeItem('cart');renderCart();">🗑️ مسح الطلب</button>
</div>

<!-- QUEUE TAB -->
<div id="tab-queue" class="page" style="display:none;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">
    <div style="font-size:16px;font-weight:700;">طابور الطلبات</div>
    <button class="btn btn-outline btn-sm" onclick="location.reload()">🔄 تحديث</button>
  </div>
  {% if orders %}
    {% for o in orders %}
    <div class="order-card" style="{% if o['status']=='pending' %}border-right:3px solid var(--accent){% else %}opacity:0.6;border-right:3px solid var(--green){% endif %}">
      <div class="order-card-head">
        <div>
          <span style="font-family:monospace;color:var(--accent2);font-weight:700;">#{{ o['id'] }}</span>
          <span style="font-size:11px;color:var(--text2);margin-right:8px;">{{ o['created_at'][-8:-3] }}</span>
          {% if o['source']=='customer' %}<span class="badge" style="font-size:10px;background:var(--blue);color:#fff;">زبون</span>{% endif %}
        </div>
        <span class="badge {% if o['status']=='pending' %}{% else %}badge-green{% endif %}">
          {{ 'قيد التنفيذ' if o['status']=='pending' else 'مكتمل' }}
        </span>
      </div>
      <div class="order-card-body">
        {% for it in o['items'] %}
        <div style="display:flex;justify-content:space-between;font-size:13px;margin-bottom:4px;">
          <span style="color:var(--text2);">{{ "%.2f"|format(it['price']*it['qty']) }} ر.س</span>
          <span>{{ it['qty'] }}× {{ it['item_name'] }}</span>
        </div>
        {% endfor %}
        {% if o['note'] %}<div style="font-size:12px;color:var(--text2);margin-top:6px;">📝 {{ o['note'] }}</div>{% endif %}
      </div>
      <div class="order-card-foot">
        <span style="font-weight:700;color:var(--accent2);">{{ "%.2f"|format(o['total']) }} ر.س · {{ o['payment'] }}</span>
        {% if o['status']=='pending' %}
        <form method="POST" action="/pos/done/{{ o['id'] }}" style="margin:0;">
          <button class="btn btn-green btn-sm" type="submit">✓ تم</button>
        </form>
        {% endif %}
      </div>
    </div>
    {% endfor %}
  {% else %}
  <div class="card" style="text-align:center;color:var(--muted);padding:30px;">لا توجد طلبات اليوم</div>
  {% endif %}
</div>

<!-- DRAWS (سحوبات) TAB -->
<div id="tab-draws" class="page" style="display:none;">
  <div class="card" style="border-color:rgba(142,68,173,0.3);">
    <div class="card-title" style="color:#c39bd3;">💜 تسجيل سحب</div>
    {% if not day %}
    <div class="alert alert-warn">اليوم لم يبدأ بعد</div>
    {% else %}
    <form method="POST" action="/pos/draw">
      <div class="form-group">
        <label class="label">المبلغ (ر.س)</label>
        <input class="input" name="amount" type="number" step="0.5" min="0" placeholder="0.00" required>
      </div>
      <div class="form-group">
        <label class="label">ملاحظة (اختياري)</label>
        <input class="input" name="note" placeholder="مثال: سلفة شخصية">
      </div>
      <button class="btn btn-purple" type="submit">💜 تسجيل السحب</button>
    </form>
    {% endif %}
  </div>

  <div class="card">
    <div class="card-title" style="color:#c39bd3;">سحوبات اليوم ({{ draws|length }})</div>
    {% for dr in draws %}
    <div class="list-item">
      <div>
        <div style="font-weight:700;">{{ dr['employee'] }}</div>
        <div style="font-size:11px;color:var(--text2);">{{ dr['note'] or '—' }} · {{ dr['created_at'][11:16] }}</div>
      </div>
      <div style="color:#c39bd3;font-weight:700;">−{{ "%.2f"|format(dr['amount']) }} ر.س</div>
    </div>
    {% endfor %}
    {% if not draws %}<div style="text-align:center;color:var(--muted);padding:16px;">لا توجد سحوبات اليوم</div>{% endif %}
  </div>
</div>

<script>
function switchTab(name, btn) {
  document.querySelectorAll('[id^="tab-"]').forEach(el => el.style.display = 'none');
  document.querySelectorAll('.nav-tab').forEach(el => el.classList.remove('active'));
  document.getElementById('tab-' + name).style.display = 'block';
  btn.classList.add('active');
  renderCart();
}
</script>
"""

@app.route("/pos")
@login_required
def pos():
    conn = get_db()
    items = qry(conn, "SELECT * FROM menu_items WHERE available=1 ORDER BY category, name").fetchall()
    day = current_day()
    orders = []
    draws  = []
    if day:
        raw = qry(conn, "SELECT * FROM orders WHERE day_id=%s ORDER BY id DESC", (day["id"],)).fetchall()
        for o in raw:
            its = qry(conn, "SELECT * FROM order_items WHERE order_id=%s", (o["id"],)).fetchall()
            orders.append({**dict(o), "items": [dict(i) for i in its]})
        draws = [dict(d) for d in qry(conn, "SELECT * FROM draws WHERE day_id=%s ORDER BY id DESC", (day["id"],)).fetchall()]
    conn.close()
    return render(POS_HTML,
        items=items, day=day, orders=orders, draws=draws,
        user_name=session["user_name"],
        user_role=session["user_role"])

@app.route("/pos/submit", methods=["POST"])
@login_required
def pos_submit():
    data = request.json
    day  = current_day()
    if not day:
        return jsonify({"ok": False, "error": "اليوم لم يبدأ بعد"})
    items = data.get("items", [])
    if not items:
        return jsonify({"ok": False, "error": "لا يوجد أصناف"})
    total = sum(i["price"] * i["qty"] for i in items)
    conn  = get_db()
    oid = exe_returning(conn,
        "INSERT INTO orders (day_id, total, payment, status, source, employee, note, created_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        (day["id"], total, data.get("payment","نقدي"), "pending",
         data.get("source","staff"), session.get("user_name",""),
         data.get("note",""), now_str()))
    for it in items:
        exe(conn,
            "INSERT INTO order_items (order_id, item_name, price, qty, note) VALUES (%s,%s,%s,%s,%s)",
            (oid, it["name"], it["price"], it["qty"], it.get("note","")))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "order_id": oid})

@app.route("/pos/done/<int:oid>", methods=["POST"])
@login_required
def pos_done(oid):
    conn = get_db()
    exe(conn, "UPDATE orders SET status='completed' WHERE id=%s", (oid,))
    conn.commit()
    conn.close()
    return redirect("/pos")

@app.route("/pos/draw", methods=["POST"])
@login_required
def pos_draw():
    day = current_day()
    if not day:
        return redirect("/pos")
    amount = float(request.form.get("amount", 0))
    note   = request.form.get("note", "").strip()
    if amount > 0:
        conn = get_db()
        exe(conn,
            "INSERT INTO draws (day_id, amount, employee, note, created_at) VALUES (%s,%s,%s,%s,%s)",
            (day["id"], amount, session["user_name"], note, now_str()))
        conn.commit()
        conn.close()
    return redirect("/pos")

# ─── CUSTOMER QR PAGE ─────────────────────────────────────────────
CUSTOMER_HTML = """
<style>
/* ── Customer page specific styles ── */
.cust-hero {
  position: relative;
  min-height: 220px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  padding: 40px 20px 30px;
}
.cust-hero-bg {
  position: absolute;
  inset: 0;
  background: linear-gradient(160deg, #1a0a00 0%, #3d1a00 40%, #0a0604 100%);
}
.cust-hero-bg::after {
  content:'';
  position:absolute;
  inset:0;
  background:
    radial-gradient(ellipse at 30% 50%, rgba(212,136,10,0.25) 0%, transparent 60%),
    radial-gradient(ellipse at 75% 30%, rgba(255,140,66,0.15) 0%, transparent 50%);
}
.cust-hero-rings {
  position: absolute;
  inset: 0;
  overflow: hidden;
}
.cust-ring {
  position: absolute;
  border-radius: 50%;
  border: 1px solid rgba(212,136,10,0.12);
  animation: ringPulse ease-in-out infinite;
}
@keyframes ringPulse {
  0%,100% { transform: scale(1); opacity: 0.6; }
  50% { transform: scale(1.05); opacity: 0.3; }
}
.cust-logo {
  position: relative;
  z-index: 2;
  text-align: center;
}
.cust-logo-icon {
  font-size: 56px;
  display: block;
  margin-bottom: 10px;
  filter: drop-shadow(0 0 20px rgba(212,136,10,0.6));
  animation: iconFloat 3s ease-in-out infinite;
}
@keyframes iconFloat {
  0%,100% { transform: translateY(0); }
  50% { transform: translateY(-6px); }
}
.cust-logo-name {
  font-size: 32px;
  font-weight: 900;
  background: linear-gradient(135deg, #f5b835, #ff8c42, #f5b835);
  background-size: 200% 200%;
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  animation: shimmer 3s linear infinite;
}
@keyframes shimmer {
  0% { background-position: 0% 50%; }
  100% { background-position: 200% 50%; }
}
.cust-logo-sub {
  font-size: 14px;
  color: rgba(255,220,160,0.7);
  margin-top: 6px;
  letter-spacing: 1px;
}

.cust-cat-header {
  position: relative;
  height: 110px;
  border-radius: 14px 14px 0 0;
  overflow: hidden;
  margin-bottom: 0;
}
.cust-cat-header img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  filter: brightness(0.55);
  transition: transform 0.4s;
}
.cust-cat-section:hover .cust-cat-header img {
  transform: scale(1.05);
}
.cust-cat-label {
  position: absolute;
  bottom: 10px;
  right: 14px;
  font-size: 17px;
  font-weight: 900;
  color: #fff;
  text-shadow: 0 2px 8px rgba(0,0,0,0.8);
}
.cust-cat-section {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  overflow: hidden;
  margin-bottom: 16px;
}
.cust-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-bottom: 1px solid rgba(255,255,255,0.05);
  gap: 12px;
  transition: background 0.15s;
}
.cust-item:last-child { border-bottom: none; }
.cust-item:hover { background: rgba(212,136,10,0.05); }
.cust-item-name { font-weight: 700; font-size: 15px; color: var(--text); }
.cust-item-price {
  font-size: 13px;
  font-weight: 700;
  color: var(--accent2);
  margin-top: 2px;
}
.cust-add-btn {
  background: linear-gradient(135deg, var(--accent), var(--accent3));
  border: none;
  color: #000;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  font-size: 20px;
  font-weight: 700;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: all 0.15s;
  box-shadow: 0 2px 8px rgba(212,136,10,0.3);
}
.cust-add-btn:hover { transform: scale(1.15); box-shadow: 0 4px 16px rgba(212,136,10,0.5); }

.cust-cart-bar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  z-index: 100;
  padding: 14px 16px;
  padding-bottom: calc(14px + var(--safe-bottom));
  background: rgba(15,8,4,0.97);
  border-top: 1px solid rgba(212,136,10,0.3);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  max-width: 540px;
  margin: 0 auto;
}
.cust-pay-methods {
  display: flex;
  gap: 6px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.cust-pay-btn {
  flex: 1 1 80px;
  padding: 9px 6px;
  min-height: 40px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface2);
  color: var(--text2);
  font-family: 'Cairo', sans-serif;
  font-size: clamp(12px, 3.2vw, 14px);
  font-weight: 700;
  cursor: pointer;
  transition: all 0.15s;
  text-align: center;
  -webkit-tap-highlight-color: transparent;
  touch-action: manipulation;
}
.cust-pay-btn.active {
  border-color: var(--accent);
  color: var(--accent2);
  background: rgba(212,136,10,0.12);
}

.cust-closed {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 60vh;
  text-align: center;
  padding: 40px 20px;
}

.cust-success {
  display: none;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 70vh;
  text-align: center;
  padding: 40px 20px;
}

@keyframes successPop {
  0% { transform: scale(0.5); opacity: 0; }
  80% { transform: scale(1.1); }
  100% { transform: scale(1); opacity: 1; }
}
.success-icon { animation: successPop 0.5s ease forwards; }
</style>

<!-- SUCCESS STATE -->
<div id="customerSuccessMsg" class="cust-success">
  <div class="success-icon" style="font-size:80px;margin-bottom:20px;">✅</div>
  <div style="font-size:24px;font-weight:900;color:var(--green);margin-bottom:10px;">تم استلام طلبك!</div>
  <div style="color:var(--text2);font-size:15px;line-height:1.7;">سيتم تحضير طلبك في أقرب وقت.<br>شكراً لزيارتك ☕</div>
  <button onclick="localStorage.removeItem('customerCart');location.reload();"
    style="margin-top:28px;background:linear-gradient(135deg,var(--accent),var(--accent3));border:none;color:#000;font-family:'Cairo',sans-serif;font-size:15px;font-weight:700;padding:14px 32px;border-radius:12px;cursor:pointer;">
    🔄 طلب جديد
  </button>
</div>

<div id="customerMenuSection">

<!-- HERO HEADER -->
<div class="cust-hero">
  <div class="cust-hero-bg"></div>
  <div class="cust-hero-rings">
    <div class="cust-ring" style="width:300px;height:300px;top:50%;left:50%;transform:translate(-50%,-50%);animation-duration:4s;"></div>
    <div class="cust-ring" style="width:200px;height:200px;top:50%;left:50%;transform:translate(-50%,-50%);animation-duration:3s;animation-delay:-1s;"></div>
    <div class="cust-ring" style="width:120px;height:120px;top:50%;left:50%;transform:translate(-50%,-50%);animation-duration:2.5s;animation-delay:-2s;"></div>
  </div>
  <div class="cust-logo">
    <span class="cust-logo-icon">☕</span>
    <div class="cust-logo-name">Nashmi Café</div>
    <div class="cust-logo-sub">اختر ما تحب وأرسل طلبك مباشرةً</div>
  </div>
</div>

{% if not open %}
<!-- CLOSED STATE -->
<div class="cust-closed">
  <div style="font-size:64px;margin-bottom:18px;filter:grayscale(0.5);">⏸️</div>
  <div style="font-size:20px;font-weight:900;color:var(--text);margin-bottom:10px;">المقهى مغلق الآن</div>
  <div style="color:var(--text2);font-size:14px;">الطلبات غير متاحة في الوقت الحالي<br>تفضل بزيارتنا خلال ساعات العمل</div>
</div>

{% else %}
<!-- MENU -->
<div style="padding:16px;max-width:540px;margin:0 auto;">

  {% if not items %}
  <div class="card" style="text-align:center;color:var(--muted);padding:40px;">القائمة غير متاحة حالياً</div>
  {% endif %}

  {% for cat_key, cat_label in categories.items() %}
    {% set cat_items = items | selectattr('category','equalto',cat_key) | list %}
    {% if cat_items %}
    <div class="cust-cat-section">
      <div class="cust-cat-header">
        <img src="{{ category_img[cat_key] }}" alt="{{ cat_label }}" loading="lazy"
             onerror="this.style.display='none';this.parentElement.style.background='{{ category_gradient[cat_key] }}'">
        <div class="cust-cat-label">{{ cat_label }}</div>
      </div>
      {% for item in cat_items %}
      <div class="cust-item">
        <div style="flex:1;">
          <div class="cust-item-name">{{ item['name'] }}</div>
          <div class="cust-item-price">{{ "%.2f"|format(item['price']) }} ر.س</div>
        </div>
        <button class="cust-add-btn"
          onclick="addToCustomerCart('{{ item['name']|replace("'", "\\'") }}', {{ item['price'] }})">+</button>
      </div>
      {% endfor %}
    </div>
    {% endif %}
  {% endfor %}

</div>
<div style="height:calc(260px + var(--safe-bottom));"></div>
{% endif %}
</div>

<!-- FLOATING CART BAR -->
<div id="customerCartSection" class="cust-cart-bar" style="display:none;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
    <div style="font-weight:900;font-size:15px;color:var(--text);">🛒 طلبك <span id="customerCartCount" style="background:var(--accent);color:#000;border-radius:20px;padding:1px 9px;font-size:12px;"></span></div>
    <span id="customerCartTotal" style="font-weight:900;font-size:18px;color:var(--accent2);">0.00 ر.س</span>
  </div>

  <div id="customerCartItems"></div>

  <!-- Payment method -->
  <div style="margin:12px 0 8px;">
    <div style="font-size:12px;color:var(--text2);font-weight:700;margin-bottom:6px;">طريقة الدفع</div>
    <div class="cust-pay-methods" id="payMethodBtns">
      <button class="cust-pay-btn active" onclick="selectPay(this,'نقدي')">💵 نقدي</button>
      <button class="cust-pay-btn" onclick="selectPay(this,'بطاقة')">💳 بطاقة</button>
      <button class="cust-pay-btn" onclick="selectPay(this,'دفع إلكتروني')">📱 إلكتروني</button>
    </div>
  </div>

  <input class="input" id="customerNote" placeholder="ملاحظة: مثلاً بدون سكر..." style="margin-bottom:10px;background:rgba(255,255,255,0.05);border-color:rgba(255,255,255,0.1);">
  <button class="btn btn-primary" id="customerSubmitBtn" onclick="submitCustomerOrder()" style="font-size:16px;padding:14px;">
    ✅ أرسل الطلب
  </button>
</div>

<script>
var selectedPayMethod = 'نقدي';
function selectPay(btn, method) {
  selectedPayMethod = method;
  document.querySelectorAll('.cust-pay-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
}

// Override submitCustomerOrder to include payment
function submitCustomerOrder() {
  const cart = JSON.parse(localStorage.getItem('customerCart') || '[]');
  if (!cart.length) return;
  const note = document.getElementById('customerNote');
  const btn = document.getElementById('customerSubmitBtn');
  if(btn) btn.disabled = true;
  btn.textContent = '⏳ جارٍ الإرسال...';
  fetch('/customer/submit', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      items: cart,
      note: note ? note.value : '',
      payment: selectedPayMethod,
    })
  }).then(r => r.json()).then(d => {
    if (d.ok) {
      localStorage.removeItem('customerCart');
      document.getElementById('customerCartSection').style.display = 'none';
      document.getElementById('customerMenuSection').style.display = 'none';
      document.getElementById('customerSuccessMsg').style.display = 'flex';
    } else {
      alert(d.error || 'حدث خطأ');
      if(btn) { btn.disabled = false; btn.textContent = '✅ أرسل الطلب'; }
    }
  });
}
</script>
"""

@app.route("/customer")
def customer():
    day = current_day()
    conn = get_db()
    items = qry(conn, "SELECT * FROM menu_items WHERE available=1 ORDER BY category, name").fetchall()
    conn.close()
    return render(CUSTOMER_HTML, items=items, open=bool(day))

@app.route("/customer/submit", methods=["POST"])
def customer_submit():
    data = request.json
    day  = current_day()
    if not day:
        return jsonify({"ok": False, "error": "المقهى مغلق"})
    items = data.get("items", [])
    if not items:
        return jsonify({"ok": False, "error": "لا يوجد أصناف"})
    total   = sum(i["price"] * i["qty"] for i in items)
    payment = data.get("payment", "نقدي")
    conn    = get_db()
    oid = exe_returning(conn,
        "INSERT INTO orders (day_id, total, payment, status, source, employee, note, created_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        (day["id"], total, payment, "pending", "customer", "زبون", data.get("note",""), now_str()))
    for it in items:
        exe(conn,
            "INSERT INTO order_items (order_id, item_name, price, qty, note) VALUES (%s,%s,%s,%s,%s)",
            (oid, it["name"], it["price"], it["qty"], ""))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

# ─── ADMIN ────────────────────────────────────────────────────────
ADMIN_HTML = """
<div class="topbar">
  <div>
    <div class="topbar-title">⚙️ الإدارة</div>
    <div class="topbar-sub">{{ user_name }} · مدير</div>
  </div>
  <div class="topbar-right">
    <a href="/pos" class="btn btn-outline btn-sm">🛒 POS</a>
    <a href="/logout" class="btn btn-outline btn-sm">خروج</a>
  </div>
</div>

<div class="nav-tabs">
  <button class="nav-tab active" onclick="switchAdminTab('day', this)">📅 اليوم</button>
  <button class="nav-tab" onclick="switchAdminTab('menu', this)">📋 القائمة</button>
  <button class="nav-tab" onclick="switchAdminTab('expenses', this)">💸 مصاريف</button>
  <button class="nav-tab" onclick="switchAdminTab('draws', this)" style="color:#c39bd3;">💜 سحوبات</button>
  <button class="nav-tab" onclick="switchAdminTab('qr', this)">📱 QR</button>
  <button class="nav-tab" onclick="switchAdminTab('report', this)">📊 تقرير</button>
</div>

<!-- DAY TAB -->
<div id="atab-day" class="page">
  {% if day %}
  <div class="alert alert-success">✅ اليوم مفتوح منذ {{ day['started_at'][11:16] }}</div>
  <div class="stat-row">
    <div class="stat"><div class="stat-val">{{ orders|length }}</div><div class="stat-label">الطلبات</div></div>
    <div class="stat"><div class="stat-val">{{ "%.0f"|format(total_sales) }} ر.س</div><div class="stat-label">المبيعات</div></div>
  </div>
  <form method="POST" action="/admin/day/close">
    <button class="btn btn-red" type="submit" onclick="return confirm('هل تريد إغلاق اليوم؟')">🔒 إغلاق اليوم</button>
  </form>
  {% else %}
  <div class="alert alert-warn">⚠️ اليوم لم يبدأ بعد. اضغط لبدء اليوم.</div>
  <form method="POST" action="/admin/day/start">
    <button class="btn btn-primary" type="submit" style="font-size:18px;padding:16px;">🌅 بدء اليوم</button>
  </form>
  {% endif %}

  {% if prev_days %}
  <div class="card" style="margin-top:20px;">
    <div class="card-title">أيام سابقة</div>
    {% for d in prev_days %}
    <div class="list-item">
      <span style="font-size:12px;color:var(--text2);">{{ d['started_at'][:10] }}</span>
      <span style="font-weight:700;color:var(--accent2);">{{ "%.2f"|format(d['sales'] or 0) }} ر.س</span>
    </div>
    {% endfor %}
  </div>
  {% endif %}
</div>

<!-- MENU TAB -->
<div id="atab-menu" class="page" style="display:none;">
  <div class="card">
    <div class="card-title">➕ إضافة صنف جديد</div>
    <form method="POST" action="/admin/menu/add">
      <div class="form-group">
        <label class="label">اسم الصنف</label>
        <input class="input" name="name" placeholder="مثال: قهوة تركية" required>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label class="label">السعر (ر.س)</label>
          <input class="input" name="price" type="number" step="0.5" min="0" placeholder="0.00" required>
        </div>
        <div class="form-group">
          <label class="label">الفئة</label>
          <select class="select" name="category">
            {% for k,v in categories.items() %}<option value="{{ k }}">{{ v }}</option>{% endfor %}
          </select>
        </div>
      </div>
      <button class="btn btn-primary" type="submit">+ إضافة</button>
    </form>
  </div>

  {% if msg %}<div class="alert alert-success">{{ msg }}</div>{% endif %}

  <div class="card">
    <div class="card-title">الأصناف الحالية ({{ items|length }})</div>
    {% if not items %}
    <div style="text-align:center;color:var(--muted);padding:20px;">القائمة فارغة</div>
    {% endif %}
    {% for cat_key, cat_label in categories.items() %}
      {% set cat_items = items | selectattr('category','equalto',cat_key) | list %}
      {% if cat_items %}
      <div class="cat-title">{{ cat_label }}</div>
      {% for item in cat_items %}
      <div class="list-item">
        <div>
          <div style="font-weight:700;">{{ item['name'] }}</div>
          <div style="font-size:13px;color:var(--accent2);">{{ "%.2f"|format(item['price']) }} ر.س</div>
        </div>
        <form method="POST" action="/admin/menu/delete/{{ item['id'] }}" style="margin:0;">
          <button class="btn btn-red btn-sm" type="submit" onclick="return confirm('حذف {{ item['name'] }}؟')">🗑️</button>
        </form>
      </div>
      {% endfor %}
      {% endif %}
    {% endfor %}
  </div>
</div>

<!-- EXPENSES TAB -->
<div id="atab-expenses" class="page" style="display:none;">
  <div class="card">
    <div class="card-title">➕ تسجيل مصروف</div>
    <form method="POST" action="/admin/expenses/add">
      <div class="form-row">
        <div class="form-group">
          <label class="label">المبلغ (ر.س)</label>
          <input class="input" name="amount" type="number" step="0.5" min="0" placeholder="0.00" required>
        </div>
        <div class="form-group">
          <label class="label">السبب</label>
          <input class="input" name="reason" placeholder="مثال: حبوب قهوة" required>
        </div>
      </div>
      <button class="btn btn-primary" type="submit">+ تسجيل</button>
    </form>
  </div>

  <div class="card">
    <div class="card-title">المصاريف ({{ expenses|length }})</div>
    {% for ex in expenses %}
    <div class="list-item">
      <div>
        <div style="font-weight:700;">{{ ex['reason'] }}</div>
        <div style="font-size:11px;color:var(--text2);">{{ ex['employee'] }} · {{ ex['created_at'][11:16] }}</div>
      </div>
      <div style="color:var(--red);font-weight:700;">−{{ "%.2f"|format(ex['amount']) }} ر.س</div>
    </div>
    {% endfor %}
    {% if not expenses %}<div style="text-align:center;color:var(--muted);padding:16px;">لا توجد مصاريف</div>{% endif %}
  </div>
</div>

<!-- DRAWS TAB (Admin view) -->
<div id="atab-draws" class="page" style="display:none;">
  <div class="stat-row">
    <div class="stat">
      <div class="stat-val" style="color:#c39bd3;">{{ draws|length }}</div>
      <div class="stat-label">عدد السحوبات</div>
    </div>
    <div class="stat">
      <div class="stat-val" style="color:#c39bd3;">{{ "%.2f"|format(total_draws) }}</div>
      <div class="stat-label">إجمالي السحوبات (ر.س)</div>
    </div>
  </div>
  <div class="card" style="border-color:rgba(142,68,173,0.3);">
    <div class="card-title" style="color:#c39bd3;">💜 سحوبات اليوم</div>
    {% for dr in draws %}
    <div class="list-item">
      <div>
        <div style="font-weight:700;">{{ dr['employee'] }}</div>
        <div style="font-size:11px;color:var(--text2);">{{ dr['note'] or '—' }} · {{ dr['created_at'][11:16] }}</div>
      </div>
      <div style="color:#c39bd3;font-weight:700;">−{{ "%.2f"|format(dr['amount']) }} ر.س</div>
    </div>
    {% endfor %}
    {% if not draws %}<div style="text-align:center;color:var(--muted);padding:16px;">لا توجد سحوبات اليوم</div>{% endif %}
  </div>
</div>

<!-- QR TAB -->
<div id="atab-qr" class="page" style="display:none;text-align:center;">
  <div class="card" style="text-align:center;">
    <div class="card-title">📱 QR Code للزبائن</div>
    <p style="color:var(--text2);font-size:13px;margin-bottom:16px;">اطبع هذا وضعه على الطاولات. الزبون يمسحه ويطلب مباشرة.</p>
    <img src="/admin/qr/image" alt="QR Code" style="width:220px;height:220px;border-radius:12px;">
    <div style="margin-top:14px;font-size:12px;color:var(--muted);">{{ customer_url }}</div>
    <a href="{{ customer_url }}" target="_blank" class="btn btn-outline btn-sm" style="margin-top:12px;width:auto;display:inline-flex;">🔗 افتح صفحة الزبون</a>
  </div>
</div>

<!-- REPORT TAB -->
<div id="atab-report" class="page" style="display:none;">
  <div class="stat-row">
    <div class="stat"><div class="stat-val" style="color:var(--accent2);">{{ "%.2f"|format(total_sales) }}</div><div class="stat-label">المبيعات (ر.س)</div></div>
    <div class="stat"><div class="stat-val" style="color:var(--red);">{{ "%.2f"|format(total_expenses) }}</div><div class="stat-label">المصاريف (ر.س)</div></div>
  </div>
  <div class="stat-row">
    <div class="stat"><div class="stat-val" style="color:#c39bd3;">{{ "%.2f"|format(total_draws) }}</div><div class="stat-label">السحوبات (ر.س)</div></div>
    <div class="stat"><div class="stat-val" style="color:{% if net >= 0 %}var(--green){% else %}var(--red){% endif %};">{{ "%.2f"|format(net) }}</div><div class="stat-label">صافي الربح (ر.س)</div></div>
  </div>
  <div class="card">
    <div class="card-title">الطلبات المكتملة</div>
    {% for o in orders %}
    <div class="list-item">
      <div>
        <div style="font-weight:700;font-family:monospace;color:var(--accent2);">#{{ o['id'] }}</div>
        <div style="font-size:11px;color:var(--text2);">{{ o['payment'] }} · {{ o['employee'] }} · {{ o['created_at'][11:16] }}</div>
      </div>
      <div style="font-weight:700;color:var(--accent2);">{{ "%.2f"|format(o['total']) }} ر.س</div>
    </div>
    {% endfor %}
    {% if not orders %}<div style="text-align:center;color:var(--muted);padding:16px;">لا توجد طلبات</div>{% endif %}
  </div>
</div>

<script>
function switchAdminTab(name, btn) {
  document.querySelectorAll('[id^="atab-"]').forEach(el => el.style.display = 'none');
  document.querySelectorAll('.nav-tab').forEach(el => el.classList.remove('active'));
  document.getElementById('atab-' + name).style.display = 'block';
  btn.classList.add('active');
}
</script>
"""

@app.route("/admin")
@login_required
@admin_required
def admin():
    conn = get_db()
    day   = current_day()
    items = qry(conn, "SELECT * FROM menu_items ORDER BY category, name").fetchall()
    expenses     = []
    orders       = []
    draws        = []
    total_sales  = 0
    total_expenses = 0
    total_draws  = 0
    if day:
        raw = qry(conn, "SELECT * FROM orders WHERE day_id=%s ORDER BY id DESC", (day["id"],)).fetchall()
        for o in raw:
            its = qry(conn, "SELECT * FROM order_items WHERE order_id=%s", (o["id"],)).fetchall()
            orders.append({**dict(o), "items": [dict(i) for i in its]})
        total_sales = sum(o["total"] for o in orders)
        expenses = [dict(e) for e in qry(conn, "SELECT * FROM expenses WHERE day_id=%s ORDER BY id DESC", (day["id"],)).fetchall()]
        total_expenses = sum(e["amount"] for e in expenses)
        draws = [dict(d) for d in qry(conn, "SELECT * FROM draws WHERE day_id=%s ORDER BY id DESC", (day["id"],)).fetchall()]
        total_draws = sum(d["amount"] for d in draws)

    prev_raw = qry(conn, """
        SELECT d.id, d.started_at, SUM(o.total) AS sales
        FROM days d LEFT JOIN orders o ON o.day_id=d.id
        WHERE d.status='closed' GROUP BY d.id ORDER BY d.id DESC LIMIT 7
    """).fetchall()
    prev_days = [dict(r) for r in prev_raw]
    conn.close()

    host         = request.host_url.rstrip("/")
    customer_url = f"{host}/customer"
    msg          = request.args.get("msg", "")
    return render(ADMIN_HTML,
        day=day, items=items, orders=orders, expenses=expenses, draws=draws,
        total_sales=total_sales, total_expenses=total_expenses,
        total_draws=total_draws,
        net=total_sales - total_expenses - total_draws,
        prev_days=prev_days, customer_url=customer_url,
        user_name=session["user_name"], msg=msg)

@app.route("/admin/day/start", methods=["POST"])
@login_required
@admin_required
def day_start():
    conn = get_db()
    exe(conn, "INSERT INTO days (started_at, status) VALUES (%s, 'open')", (now_str(),))
    conn.commit()
    conn.close()
    return redirect("/admin")

@app.route("/admin/day/close", methods=["POST"])
@login_required
@admin_required
def day_close():
    day = current_day()
    if day:
        conn = get_db()
        exe(conn, "UPDATE days SET status='closed', closed_at=%s WHERE id=%s", (now_str(), day["id"]))
        conn.commit()
        conn.close()
    return redirect("/admin")

@app.route("/admin/menu/add", methods=["POST"])
@login_required
@admin_required
def menu_add():
    name     = request.form.get("name", "").strip()
    price    = float(request.form.get("price", 0))
    category = request.form.get("category", "hot_coffee")
    if name and price > 0:
        conn = get_db()
        exe(conn, "INSERT INTO menu_items (name, price, category) VALUES (%s,%s,%s)", (name, price, category))
        conn.commit()
        conn.close()
    return redirect("/admin?msg=تم إضافة الصنف#atab-menu")

@app.route("/admin/menu/delete/<int:item_id>", methods=["POST"])
@login_required
@admin_required
def menu_delete(item_id):
    conn = get_db()
    exe(conn, "DELETE FROM menu_items WHERE id=%s", (item_id,))
    conn.commit()
    conn.close()
    return redirect("/admin#atab-menu")

@app.route("/admin/expenses/add", methods=["POST"])
@login_required
@admin_required
def expense_add():
    day = current_day()
    if not day:
        return redirect("/admin")
    amount = float(request.form.get("amount", 0))
    reason = request.form.get("reason", "").strip()
    if amount > 0 and reason:
        conn = get_db()
        exe(conn,
            "INSERT INTO expenses (day_id, amount, reason, employee, created_at) VALUES (%s,%s,%s,%s,%s)",
            (day["id"], amount, reason, session["user_name"], now_str()))
        conn.commit()
        conn.close()
    return redirect("/admin")

@app.route("/admin/qr/image")
@login_required
def qr_image():
    host = request.host_url.rstrip("/")
    url = f"{host}/customer"
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    resp = make_response(buf.read())
    resp.headers["Content-Type"] = "image/png"
    return resp

# ─── RUN ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)