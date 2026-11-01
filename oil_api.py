"""
ดึงข้อมูลน้ำมันดิบ WTI (USD/บาร์เรล) ย้อนหลัง 15 ปีจาก Yahoo Finance แล้วบันทึกเป็น CSV
ติดตั้ง:  pip install yfinance pandas
รัน:      python oil_api.py   ->  ได้ไฟล์ crude_oil_15y.csv
"""
from datetime import date
from pathlib import Path

import yfinance as yf

TICKER = "CL=F"
CSV_FILE = Path(__file__).resolve().parent / "crude_oil_15y.csv"
YEARS = 15


def get_data(years=YEARS):
    today = date.today()
    start = today.replace(year=today.year - years, day=min(today.day, 28))
    df = yf.download(TICKER, start=start.isoformat(), auto_adjust=False, progress=False)
    if df.empty:
        raise RuntimeError("ดึงข้อมูล " + TICKER + " ไม่ได้ ตรวจสอบอินเทอร์เน็ตแล้วลองใหม่")
    if hasattr(df.columns, "levels"):          # yfinance รุ่นใหม่คืนคอลัมน์ 2 ชั้น
        df.columns = df.columns.get_level_values(0)
    df = df.reset_index()
    df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")
    df = df[["Date", "Open", "High", "Low", "Close", "Adj Close", "Volume"]].dropna(subset=["Close"])
    return df.round(4)


def save_csv(years=YEARS):
    df = get_data(years)
    df.to_csv(CSV_FILE, index=False, encoding="utf-8-sig")
    print(f"บันทึก {len(df)} แถว ({df['Date'].iloc[0]} ถึง {df['Date'].iloc[-1]}) -> {CSV_FILE}")
    return df


if __name__ == "__main__":
    save_csv()
