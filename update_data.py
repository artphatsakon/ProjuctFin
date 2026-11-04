"""
อัปเดตข้อมูลราคาทองคำและน้ำมันดิบจาก Yahoo Finance อัตโนมัติ (ตั้งให้ Windows Task Scheduler รันทุกวัน)

รัน:  python update_data.py              อัปเดตข้อมูล CSV
      python update_data.py --if-due     อัปเดตข้อมูล แล้วเทรนใหม่เฉพาะเมื่อครบรอบ 7 วันทำการ
      python update_data.py --train      อัปเดตข้อมูล แล้วเทรนใหม่ทั้งหมดทันที (ประมาณ 10 นาที)
ผลการทำงานบันทึกต่อท้ายไฟล์ update_log.txt
"""
import argparse
import os
import sys
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
sys.path.insert(0, BASE)

import data_service as ds  # noqa: E402


def log(msg):
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
    print(line, flush=True)
    with open(os.path.join(BASE, "update_log.txt"), "a", encoding="utf-8") as f:
        f.write(line + "\n")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--train", action="store_true", help="เทรนโมเดลใหม่ทั้งหมดหลังอัปเดตข้อมูล")
    p.add_argument("--if-due", action="store_true", help="เทรนใหม่เฉพาะเมื่อครบรอบ 7 วันทำการ")
    args = p.parse_args()

    ok = True
    for a, info in ds.ASSETS.items():
        try:
            r = ds.update_from_yahoo(a)
            s = ds.validate(a)
            log(f"[{a}] อัปเดตสำเร็จ: เพิ่ม {r['added']} วัน · ข้อมูลถึง {s['last_date']} · ค่าที่หายไป {s['missing_close']}")
        except Exception as e:
            ok = False
            log(f"[{a}] อัปเดตไม่สำเร็จ: {e}")

    if ok and (args.train or args.if_due):
        import train_state as ts
        import train_all
        if args.train or ts.is_due():
            log("เริ่มเทรนโมเดลใหม่" + ("" if args.train else " (ครบรอบ 7 วันทำการ)"))
            if not train_all.run(log=log):
                ok = False
        else:
            log("ยังไม่ถึงรอบเทรนใหม่ ข้ามการเทรน")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
