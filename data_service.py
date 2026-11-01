"""
data_service.py — จัดการข้อมูลราคา (ขอบเขตข้อ 2.3.4 และ 2.3.7)

- เก็บข้อมูลราคาเป็นไฟล์ CSV แยกตามสินทรัพย์ (gold_15y.csv, crude_oil_15y.csv)
- อ่าน/จัดการข้อมูลด้วย Pandas
- ดึงราคาปัจจุบันและข้อมูลย้อนหลังจาก Yahoo Finance (ทองคำ GC=F, น้ำมันดิบ CL=F)
- ตรวจความถูกต้องของข้อมูล (ค่าหาย ค่าซ้ำ ค่าผิดปกติ) ก่อนนำไปแสดงผล/พยากรณ์
"""
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

ASSETS = {
    "gold": {
        "name": "ทองคำ",
        "name_en": "Gold",
        "ticker": "GC=F",
        "csv": "gold_15y.csv",
        "unit": "USD/ออนซ์",
    },
    "oil": {
        "name": "น้ำมันดิบ WTI",
        "name_en": "WTI Crude Oil",
        "ticker": "CL=F",
        "csv": "crude_oil_15y.csv",
        "unit": "USD/บาร์เรล",
    },
}
CSV_COLUMNS = ["Date", "Open", "High", "Low", "Close", "Adj Close", "Volume"]

TROY_OZ_G = 31.1034768        # กรัม/ทรอยออนซ์
THAI_BAHT_WEIGHT_G = 15.244   # กรัม/ทองหนัก 1 บาท
THAI_GOLD_PURITY = 0.965      # ทองไทย 96.5%
BARREL_L = 158.987294928      # ลิตร/บาร์เรล

_lock = threading.Lock()
_cache = {}


# ---------------------------------------------------------------- config / รหัสผ่าน
def hash_password(pw):
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 200_000).hex()
    return f"pbkdf2${salt}${h}"


def check_password(pw, stored):
    if stored.startswith("pbkdf2$"):
        _, salt, h = stored.split("$")
        return hmac.compare_digest(hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 200_000).hex(), h)
    try:   # config.json จากเวอร์ชัน Flask เดิม
        from werkzeug.security import check_password_hash
        return check_password_hash(stored, pw)
    except ImportError:
        return False


def load_config():
    if not os.path.exists(CONFIG_PATH):
        cfg = {
            "admin_user": "admin",
            "admin_password_hash": hash_password("admin1234"),
            "usdthb_fallback": 33.0,
        }
        save_config(cfg)
        return cfg
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def _cached(key, ttl, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = fn()
    _cache[key] = (time.time(), val)
    return val


def clear_cache():
    _cache.clear()


# ---------------------------------------------------------------- CSV
def csv_path(asset):
    return os.path.join(BASE_DIR, ASSETS[asset]["csv"])


def read_raw(asset):
    path = csv_path(asset)
    if not os.path.exists(path):
        return pd.DataFrame(columns=CSV_COLUMNS)
    df = pd.read_csv(path, encoding="utf-8-sig")
    for c in CSV_COLUMNS:
        if c not in df.columns:
            df[c] = np.nan
    return df[CSV_COLUMNS]


def write_raw(asset, df):
    df = df.copy()
    df["Date"] = pd.to_datetime(df["Date"]).dt.strftime("%Y-%m-%d")
    df = df.drop_duplicates(subset="Date", keep="last").sort_values("Date")
    with _lock:
        df[CSV_COLUMNS].to_csv(csv_path(asset), index=False, encoding="utf-8-sig")
    clear_cache()


def load_clean(asset):
    """อ่าน CSV และทำความสะอาดแบบเดียวกับใน notebook → DataFrame [Date, Close]"""
    path = csv_path(asset)
    mtime = os.path.getmtime(path) if os.path.exists(path) else 0

    def _load():
        df = read_raw(asset)[["Date", "Close"]].copy()
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df["Close"] = pd.to_numeric(df["Close"], errors="coerce")
        df = df.dropna().drop_duplicates(subset="Date", keep="last").sort_values("Date")
        df = df[df["Date"] < pd.Timestamp.today().normalize()]   # ตัดแถววันนี้ (ตลาดยังไม่ปิด)
        df = df[df["Close"] > 0]                                   # ราคาติดลบ/ศูนย์ (WTI 20 เม.ย. 2020)
        df["Close"] = df["Close"].round(2)
        return df.reset_index(drop=True)

    return _cached(("clean", asset, mtime), 3600, _load)


def validate(asset):
    """ตรวจคุณภาพข้อมูล (ข้อ 2.3.4.3)"""
    raw = read_raw(asset)
    d = pd.to_datetime(raw["Date"], errors="coerce")
    close = pd.to_numeric(raw["Close"], errors="coerce")
    clean = load_clean(asset)
    ret = np.log(clean["Close"]).diff()
    big = clean.loc[ret.abs() > 0.15, "Date"].dt.strftime("%Y-%m-%d").tolist()
    gaps = clean["Date"].diff().dt.days
    return {
        "rows": int(len(raw)),
        "rows_clean": int(len(clean)),
        "first_date": clean["Date"].min().strftime("%Y-%m-%d") if len(clean) else "-",
        "last_date": clean["Date"].max().strftime("%Y-%m-%d") if len(clean) else "-",
        "bad_dates": int(d.isna().sum()),
        "missing_close": int(close.isna().sum()),
        "duplicates": int(d.duplicated().sum()),
        "non_positive": int((close <= 0).sum()),
        "big_moves": big,                       # ราคาเปลี่ยน > 15% ในวันเดียว
        "gaps_over_5d": int((gaps > 5).sum()),
    }


# ---------------------------------------------------------------- Yahoo Finance
def update_from_yahoo(asset, years=15):
    """ดึงข้อมูลย้อนหลังจาก Yahoo แล้วรวมเข้ากับ CSV เดิม"""
    import yfinance as yf

    start = date.today().replace(year=date.today().year - years, day=min(date.today().day, 28))
    raw = yf.download(ASSETS[asset]["ticker"], start=start.isoformat(), auto_adjust=False, progress=False)
    if raw.empty:
        raise RuntimeError("ดึงข้อมูลจาก Yahoo ไม่ได้ (ตรวจสอบอินเทอร์เน็ต)")
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    new = raw.reset_index()
    new["Date"] = pd.to_datetime(new["Date"]).dt.strftime("%Y-%m-%d")
    new = new[CSV_COLUMNS].dropna(subset=["Close"])
    new[["Open", "High", "Low", "Close", "Adj Close"]] = new[["Open", "High", "Low", "Close", "Adj Close"]].round(2)
    new["Volume"] = new["Volume"].fillna(0).astype("int64")

    old = read_raw(asset)
    before = set(old["Date"].astype(str))
    merged = pd.concat([old, new], ignore_index=True)
    write_raw(asset, merged)
    return {"source": "Yahoo Finance", "added": int(len(set(new["Date"]) - before)), "rows": int(len(new))}


def yahoo_last_price(asset):
    import yfinance as yf
    h = yf.Ticker(ASSETS[asset]["ticker"]).history(period="5d", auto_adjust=False)
    if h.empty:
        raise RuntimeError("no data")
    return float(h["Close"].iloc[-1]), h.index[-1].to_pydatetime()


# ---------------------------------------------------------------- current price / FX
def current_price(asset):
    """ราคาปัจจุบัน: Yahoo Finance → ถ้าดึงไม่ได้ใช้ราคาปิดล่าสุดใน CSV"""
    def _get():
        clean = load_clean(asset)
        prev = float(clean["Close"].iloc[-1])
        out = None
        if out is None:
            try:
                p, t = yahoo_last_price(asset)
                out = {"price": p, "source": f"Yahoo Finance ({ASSETS[asset]['ticker']})", "time": t.strftime("%Y-%m-%d %H:%M")}
            except Exception:
                out = {"price": prev, "source": "ราคาปิดล่าสุดในไฟล์ CSV",
                       "time": clean["Date"].iloc[-1].strftime("%Y-%m-%d")}
        if "change" not in out:
            # เทียบกับราคาปิดของวันก่อนหน้าวันที่ของราคาปัจจุบัน
            last_csv_day = clean["Date"].iloc[-1].strftime("%Y-%m-%d")
            base = prev if out["time"][:10] > last_csv_day else float(clean["Close"].iloc[-2])
            out["change"] = out["price"] - base
            out["change_pct"] = (out["change"] / base * 100) if base else 0
        return out
    return _cached(("price", asset), 300, _get)


def usd_thb():
    def _get():
        try:
            import yfinance as yf
            h = yf.Ticker("THB=X").history(period="5d")
            if not h.empty:
                return {"rate": float(h["Close"].iloc[-1]), "source": "Yahoo Finance (THB=X)"}
        except Exception:
            pass
        return {"rate": float(load_config().get("usdthb_fallback", 33.0)), "source": "ค่าที่ตั้งไว้ในหน้า Admin (โดยประมาณ)"}
    return _cached("usdthb", 3600, _get)


def thai_units(asset, usd, rate):
    """แปลงเป็นหน่วยที่คนไทยคุ้นเคย (ค่าประมาณ ไม่รวมค่ากำเหน็จ/ภาษี/ค่าการตลาด)"""
    if asset == "gold":
        return {"label": "ทองคำแท่ง 96.5% หนัก 1 บาท (ประมาณ)",
                "value": usd / TROY_OZ_G * THAI_BAHT_WEIGHT_G * THAI_GOLD_PURITY * rate}
    return {"label": "น้ำมันดิบต่อลิตร (ประมาณ)", "value": usd / BARREL_L * rate}


# ---------------------------------------------------------------- admin edit (ข้อ 2.3.3.2)
def upsert_row(asset, day, close, open_=None, high=None, low=None):
    close = float(close)
    row = {"Date": pd.to_datetime(day).strftime("%Y-%m-%d"),
           "Open": float(open_ or close), "High": float(high or close), "Low": float(low or close),
           "Close": close, "Adj Close": close, "Volume": 0}
    old = read_raw(asset)
    if (old["Date"].astype(str) == row["Date"]).any():
        vol = old.loc[old["Date"].astype(str) == row["Date"], "Volume"].iloc[0]
        row["Volume"] = 0 if pd.isna(vol) else vol
    write_raw(asset, pd.concat([old, pd.DataFrame([row])], ignore_index=True))


def delete_row(asset, day):
    old = read_raw(asset)
    write_raw(asset, old[old["Date"].astype(str) != str(day)])
