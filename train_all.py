"""
เทรนโมเดลทั้งหมด 6 ตัว (Prophet / GRU / XGBoost × ทองคำ / น้ำมัน) แล้วบันทึกลงโฟลเดอร์ MODEL
รัน:  python train_all.py            (ทั้งหมด)
      python train_all.py gold xgb   (เฉพาะตัว)
"""
import sys

import model_service as ms

assets = [sys.argv[1]] if len(sys.argv) > 1 else ["gold", "oil"]
models = [sys.argv[2]] if len(sys.argv) > 2 else list(ms.MODELS)

for a in assets:
    for m in models:
        ms.train(a, m)
