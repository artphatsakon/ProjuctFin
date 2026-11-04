"""
เก็บและตรวจสอบว่าโมเดลชุดปัจจุบันเทรนด้วยข้อมูลถึงวันไหน และถึงรอบเทรนใหม่หรือยัง

กติกา: โมเดลพยากรณ์ล่วงหน้า HORIZON วันทำการ (7 วัน) ดังนั้นเมื่อข้อมูลราคาใหม่กว่าวันที่เทรนไว้
เป็นอย่างน้อย HORIZON วันทำการ ถือว่าครบรอบแล้ว ต้องเทรนใหม่

รัน:  python train_state.py          แสดงสถานะ
      python train_state.py --check  ออก exit code 0 ถ้าถึงรอบเทรน, 1 ถ้ายังไม่ถึง
"""
import argparse
import json
import os
import sys
from datetime import date, datetime

import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import data_service as ds  # noqa: E402

STATE_FILE = os.path.join(BASE, "train_state.json")
HORIZON = 7  # ต้องตรงกับ model_service.HORIZON


def read_state():
    """คืนค่า dict ของ {asset: วันที่เทรนถึง (date)} ถ้ายังไม่มีไฟล์คืน {}"""
    if not os.path.exists(STATE_FILE):
        return {}
    with open(STATE_FILE, encoding="utf-8") as f:
        raw = json.load(f).get("trained_until", {})
    return {a: date.fromisoformat(d) for a, d in raw.items()}


def write_state(trained_until):
    """บันทึกวันที่เทรนถึงของแต่ละสินทรัพย์ (รวมกับค่าเดิมของสินทรัพย์อื่น)"""
    state = read_state()
    state.update(trained_until)
    payload = {
        "trained_until": {a: d.isoformat() for a, d in state.items()},
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def latest_dates():
    """วันที่ล่าสุดในไฟล์ CSV ของแต่ละสินทรัพย์"""
    return {a: ds.load_clean(a)["Date"].max().date() for a in ds.ASSETS}


def bdays_between(trained_until, latest):
    """จำนวนวันทำการหลังวันที่เทรนถึง จนถึงวันล่าสุด"""
    if latest <= trained_until:
        return 0
    return len(pd.bdate_range(trained_until + pd.Timedelta(days=1), latest))


def is_due(latest=None):
    """ถึงรอบเทรนใหม่หรือยัง: สินทรัพย์ใดก็ได้ที่ข้อมูลใหม่เกิน HORIZON วันทำการ หรือยังไม่มีบันทึก"""
    latest = latest or latest_dates()
    state = read_state()
    for a, last in latest.items():
        if a not in state:
            return True
        if bdays_between(state[a], last) >= HORIZON:
            return True
    return False


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--check", action="store_true", help="exit 0 ถ้าถึงรอบเทรน, 1 ถ้ายัง")
    args = p.parse_args()

    latest = latest_dates()
    state = read_state()
    due = is_due(latest)
    for a, last in latest.items():
        t = state.get(a)
        n = bdays_between(t, last) if t else None
        print(f"[{a}] เทรนถึง {t or '—'} · ข้อมูลถึง {last} · วันทำการที่เพิ่มมา {n if n is not None else '—'}")
    print("ถึงรอบเทรนใหม่" if due else "ยังไม่ถึงรอบเทรนใหม่")

    if args.check:
        return 0 if due else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
