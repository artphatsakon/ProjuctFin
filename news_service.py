"""
ข่าวสารและการวิเคราะห์ความรู้สึก (ข้อ 2.3.3.1: ผู้ใช้ทั่วไปดูผลการวิเคราะห์ข่าวได้โดยไม่ต้อง Login)

- ดึงข่าวล่าสุดของ GC=F / CL=F จาก Yahoo Finance ผ่าน yfinance (Ticker.news)
- ให้คะแนนความรู้สึกของหัวข้อข่าวด้วยคำศัพท์ภาษาอังกฤษที่ใช้บ่อยในข่าวทองคำและน้ำมัน
  คะแนนอยู่ระหว่าง -1 (ลบ) ถึง +1 (บวก) เป็นการนับคำอย่างง่าย ไม่ใช่โมเดล NLP
- ไม่นำคะแนนข่าวไปเป็น feature ของโมเดลพยากรณ์ แสดงผลบนหน้าเว็บอย่างเดียว

ตัวเลขและข้อความข่าวมาจากผู้ให้บริการภายนอก ควรระบุแหล่งที่มาเสมอเมื่อนำไปแสดงหรือรายงาน
"""
import re
from datetime import datetime, timedelta, timezone

import data_service as ds

# คำศัพท์ที่ใช้นับ (ตัวพิมพ์เล็ก)
POSITIVE = {"rise", "rises", "rising", "rally", "rallies", "surge", "surges", "gain", "gains",
            "jump", "jumps", "climb", "climbs", "record", "bullish", "strong", "stronger", "boost",
            "soar", "soars", "higher", "rebound", "rebounds", "optimism", "upbeat"}
NEGATIVE = {"fall", "falls", "falling", "drop", "drops", "slump", "slumps", "plunge", "plunges",
            "decline", "declines", "bearish", "weak", "weaker", "glut", "selloff", "slide",
            "slides", "tumble", "tumbles", "loss", "losses", "lower", "pressure"}
THRESHOLD = 0.2   # > 0.2 = บวก, < -0.2 = ลบ, นอกนั้น = กลาง

_cache = {}          # {asset: (เวลาที่ดึง, ผลลัพธ์)}
CACHE_SECONDS = 900  # 15 นาที


def _to_dt(value):
    """แปลงเวลาได้ทั้งแบบ epoch (รูปแบบเก่า) และแบบสตริง ISO 8601 (รูปแบบใหม่)"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def extract(item):
    """ดึง title, link, publisher, time จากข่าวหนึ่งชิ้น รองรับทั้งโครงสร้างเก่าและใหม่ของ yfinance"""
    c = item.get("content") or {}          # โครงสร้างใหม่ซ้อนอยู่ใน content
    title = c.get("title") or item.get("title")
    link = ((c.get("canonicalUrl") or {}).get("url") or (c.get("clickThroughUrl") or {}).get("url")
            or item.get("link"))
    publisher = ((c.get("provider") or {}).get("displayName") or item.get("publisher"))
    when = _to_dt(c.get("pubDate") or item.get("providerPublishTime"))
    return {"title": title, "link": link, "publisher": publisher, "time": when}


def sentiment(title):
    """คะแนนความรู้สึกของหัวข้อข่าว: (บวก − ลบ) ÷ (บวก + ลบ), ถ้าไม่มีคำที่นับได้ = 0"""
    words = re.findall(r"[a-z]+", (title or "").lower())
    p = sum(w in POSITIVE for w in words)
    n = sum(w in NEGATIVE for w in words)
    return 0.0 if p + n == 0 else round((p - n) / (p + n), 2)


def label(score):
    if score > THRESHOLD:
        return "บวก"
    if score < -THRESHOLD:
        return "ลบ"
    return "กลาง"


def summarize(items, days=7, now=None):
    """สรุปคะแนนรวมจากข่าวที่อยู่ในช่วง days วันล่าสุด (คะแนนเฉลี่ยของหัวข้อที่มีคำนับได้)"""
    now = now or datetime.now(timezone.utc)
    recent = [i for i in items if i["time"] and i["time"] >= now - timedelta(days=days)]
    scored = [i["score"] for i in recent if i["score"] != 0]
    if not scored:
        return {"count": len(recent), "score": None, "label": "ไม่มีข้อมูล"}
    avg = round(sum(scored) / len(scored), 2)
    return {"count": len(recent), "score": avg, "label": label(avg)}


def fetch(asset, limit=10):
    """ดึงข่าวล่าสุดของสินทรัพย์ คืน (รายการข่าว, ข้อความผิดพลาดหรือ None) ผลถูกเก็บไว้ในแคช"""
    now = datetime.now().timestamp()
    if asset in _cache and now - _cache[asset][0] < CACHE_SECONDS:
        return _cache[asset][1]
    try:
        import yfinance as yf
        raw = yf.Ticker(ds.ASSETS[asset]["ticker"]).news or []
        items = []
        for it in raw:
            d = extract(it)
            if not d["title"] or not d["link"]:
                continue
            d["score"] = sentiment(d["title"])
            d["label"] = label(d["score"])
            items.append(d)
        items.sort(key=lambda x: x["time"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        result = (items[:limit], None)
    except Exception as e:
        result = ([], f"ดึงข่าวไม่สำเร็จ: {e}")
    _cache[asset] = (now, result)
    return result
