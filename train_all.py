"""
เทรนโมเดลทั้งหมด 6 ตัว (Prophet / GRU / XGBoost × ทองคำ / น้ำมัน) แล้วบันทึกลงโฟลเดอร์ MODEL
เมื่อเทรนสำเร็จทั้งสินทรัพย์ จะบันทึกวันที่เทรนถึงลง train_state.json

รัน:  python train_all.py                  เทรนทั้งหมด
      python train_all.py gold             เฉพาะทอง (3 โมเดล)
      python train_all.py gold xgb         เฉพาะ XGBoost ของทอง
      python train_all.py --if-due         เทรนเฉพาะเมื่อถึงรอบ 7 วันทำการ (ใช้ใน GitHub Actions)
"""
import argparse
import sys
from datetime import datetime

import data_service as ds
import model_service as ms
import train_state as ts


def run(assets=None, models=None, log=print):
    """เทรนตามรายการที่ระบุ คืนค่า True ถ้าทุกโมเดลที่ระบุเทรนสำเร็จ"""
    assets = assets or list(ds.ASSETS)
    models = models or list(ms.MODELS)
    for a in assets:
        if a not in ds.ASSETS:
            raise ValueError(f"ไม่รู้จักสินทรัพย์ '{a}' (ใช้ได้: {', '.join(ds.ASSETS)})")
    for m in models:
        if m not in ms.MODELS:
            raise ValueError(f"ไม่รู้จักโมเดล '{m}' (ใช้ได้: {', '.join(ms.MODELS)})")

    all_ok = True
    trained = {}
    for a in assets:
        last = ts.latest_dates()[a]  # วันที่ข้อมูลล่าสุดก่อนเทรน
        asset_ok = True
        for m in models:
            try:
                ms.train(a, m, log=log)
            except Exception as e:
                asset_ok = False
                all_ok = False
                log(f"[{a}/{m}] เทรนไม่สำเร็จ: {e}")
        if asset_ok:
            trained[a] = last

    if trained:
        ts.write_state(trained)
        log(f"บันทึกสถานะการเทรน: {', '.join(f'{a} ถึง {d}' for a, d in trained.items())}")
    return all_ok


def main():
    p = argparse.ArgumentParser()
    p.add_argument("assets", nargs="*", help="gold / oil (ไม่ระบุ = ทั้งสอง)")
    p.add_argument("--models", nargs="*", help="prophet / gru / xgb (ไม่ระบุ = ทั้งสาม)")
    p.add_argument("--if-due", action="store_true", help="เทรนเฉพาะเมื่อถึงรอบ 7 วันทำการ")
    args = p.parse_args()

    # รองรับรูปแบบเดิม: python train_all.py gold xgb
    models = args.models
    if args.assets and args.assets[-1] in ms.MODELS and models is None and len(args.assets) == 2:
        models = [args.assets.pop()]

    try:
        if args.if_due:
            if not ts.is_due():
                print(f"[{datetime.now():%Y-%m-%d %H:%M}] ยังไม่ถึงรอบเทรนใหม่ ข้ามการเทรน")
                return 0
            print("ถึงรอบเทรนใหม่ เริ่มเทรนทั้งหมด")
        ok = run(args.assets or None, models, log=print)
    except ValueError as e:
        print(f"ผิดพลาด: {e}")
        return 2
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
