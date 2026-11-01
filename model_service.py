"""
model_service.py — สร้าง/ฝึกสอน/โหลดโมเดลพยากรณ์ (ขอบเขตข้อ 2.3.5 และ 2.3.6)

โมเดล 3 ตัว × สินทรัพย์ 2 ตัว ใช้วิธีเดียวกับใน notebook:
- Prophet : เทรนบน log(ราคา), เลื่อนเส้นพยากรณ์ให้เริ่มจากราคาล่าสุด (anchor), ทองลดความชันเทรนด์ครึ่งหนึ่ง
- GRU     : เรียนจากผลตอบแทนรายวัน 60 วันย้อนหลัง → พยากรณ์วันถัดไป แล้วพยากรณ์ต่อกัน (recursive)
- XGBoost : 28 feature จากผลตอบแทนในอดีต → พยากรณ์วันถัดไป แล้วพยากรณ์ต่อกัน (recursive)

การพยากรณ์ (ข้อ 2.3.6) โหลดไฟล์โมเดลที่ฝึกไว้แล้ว + ราคาล่าสุดจาก CSV/API → พยากรณ์ 7 วัน โดยไม่ต้องเทรนใหม่
การประเมิน (ข้อ 2.3.5.2) ทุกโมเดลวัดแบบเดียวกัน: ชุดทดสอบ 1 ปีล่าสุด, พยากรณ์ 7 วันจากหลายจุดเริ่ม, คำนวณ MAE/RMSE/MAPE เทียบ Naive
"""
import json
import logging
import os
import threading
from datetime import datetime

import numpy as np
import pandas as pd

import data_service as ds

MODEL_DIR = os.path.join(ds.BASE_DIR, "MODEL")
os.makedirs(MODEL_DIR, exist_ok=True)

HORIZON = 7            # พยากรณ์ล่วงหน้า 7 วันทำการ (ข้อ 2.3.6.2)
TEST_DAYS = 365        # ชุดทดสอบ = 1 ปีล่าสุด
SEED = 42

MODELS = {
    "prophet": "Prophet",
    "gru": "GRU",
    "xgb": "XGBoost",
}

PROPHET_CFG = {   # ค่าที่เลือกจาก cross-validation ใน notebook
    "gold": {"changepoint_prior_scale": 0.05, "trend_damp": 0.5},
    "oil": {"changepoint_prior_scale": 0.01, "trend_damp": 1.0},
}
GRU_CFG = dict(LOOKBACK=60, VAL_RATIO=0.15, CLIP_SD=5, MIN_EPOCHS=15, EPOCHS=100, BATCH=32)
XGB_CFG = dict(LAGS=20, VAL_RATIO=0.15, CLIP_SD=5)
XGB_PARAMS = dict(n_estimators=2000, learning_rate=0.01, max_depth=3, min_child_weight=20,
                  subsample=0.8, colsample_bytree=0.8, reg_lambda=5.0,
                  objective="reg:squarederror", random_state=SEED)

logging.getLogger("cmdstanpy").disabled = True
logging.getLogger("prophet").disabled = True
_lock = threading.Lock()
_art_cache = {}
_fc_cache = {}


def paths(asset, model):
    ext = {"prophet": "json", "gru": "keras", "xgb": "json"}[model]
    return {
        "model": os.path.join(MODEL_DIR, f"{asset}_{model}_model.{ext}"),
        "params": os.path.join(MODEL_DIR, f"{asset}_{model}_params.json"),
        "metrics": os.path.join(MODEL_DIR, f"{asset}_{model}_metrics_web.json"),
        "forecast": os.path.join(MODEL_DIR, f"{asset}_{model}_forecast.csv"),
    }


def _rets(hist):
    return np.log(hist["Close"].values[1:] / hist["Close"].values[:-1])


def _future_dates(hist, horizon):
    return pd.bdate_range(hist["Date"].iloc[-1] + pd.Timedelta(days=1), periods=horizon)


# ================================================================ Prophet
def prophet_fit(df, asset, **_):
    from prophet import Prophet
    m = Prophet(daily_seasonality=False, weekly_seasonality=False, yearly_seasonality=False,
                changepoint_prior_scale=PROPHET_CFG[asset]["changepoint_prior_scale"], changepoint_range=0.95)
    m.fit(pd.DataFrame({"ds": df["Date"], "y": np.log(df["Close"])}))
    return {"model": m, "params": {"LOG_Y": True, "ANCHOR": True, **PROPHET_CFG[asset]}}


def prophet_forecast(art, hist, horizon):
    m, prm = art["model"], art["params"]
    fut = _future_dates(hist, horizon)
    p = m.predict(pd.DataFrame({"ds": [hist["Date"].iloc[-1], *fut]}))
    base = p["yhat"].iloc[0]
    yh, lo, hi = p["yhat"].values[1:], p["yhat_lower"].values[1:], p["yhat_upper"].values[1:]
    adj = np.log(hist["Close"].iloc[-1]) + prm.get("trend_damp", 1.0) * (yh - base)   # anchor + damping
    return pd.DataFrame({"ds": fut, "yhat": np.exp(adj), "lower": np.exp(adj - (yh - lo)), "upper": np.exp(adj + (hi - yh))})


def prophet_save(art, p):
    from prophet.serialize import model_to_json
    with open(p["model"], "w") as f:
        f.write(model_to_json(art["model"]))
    with open(p["params"], "w") as f:
        json.dump(art["params"], f, indent=2)


def prophet_load(asset, p):
    from prophet.serialize import model_from_json
    with open(p["model"]) as f:
        m = model_from_json(f.read())
    prm = {"LOG_Y": True, "ANCHOR": True, **PROPHET_CFG[asset]}
    if os.path.exists(p["params"]):
        with open(p["params"]) as f:
            prm.update(json.load(f))
    return {"model": m, "params": prm}


# ================================================================ GRU
def _gru_build(lookback):
    from tensorflow import keras
    m = keras.Sequential([
        keras.Input(shape=(lookback, 1)),
        keras.layers.GRU(64, return_sequences=True),
        keras.layers.Dropout(0.2),
        keras.layers.GRU(32),
        keras.layers.Dropout(0.2),
        keras.layers.Dense(16, activation="relu"),
        keras.layers.Dense(1),
    ])
    m.compile(optimizer=keras.optimizers.Adam(5e-4), loss="mse")
    return m


def gru_fit(df, asset, epochs=None, **_):
    from tensorflow import keras
    keras.utils.set_random_seed(SEED)
    c = GRU_CFG
    r = _rets(df)
    n = len(r)
    val_start = int(n * (1 - c["VAL_RATIO"])) if epochs is None else n
    sd0 = r[:val_start].std()
    clip = c["CLIP_SD"] * sd0
    rc = np.clip(r, -clip, clip)
    mu, sd = rc[:val_start].mean(), rc[:val_start].std()
    z = (rc - mu) / sd
    L = c["LOOKBACK"]
    X = np.array([z[i - L:i] for i in range(L, n)])[..., None]
    y = z[L:]
    m = _gru_build(L)
    if epochs is None:   # หา epoch ที่ดีที่สุดด้วย validation
        cut = val_start - L
        cb = [keras.callbacks.EarlyStopping(monitor="val_loss", patience=15, restore_best_weights=True,
                                            start_from_epoch=c["MIN_EPOCHS"]),
              keras.callbacks.ReduceLROnPlateau(monitor="val_loss", factor=0.5, patience=5, min_lr=1e-5)]
        h = m.fit(X[:cut], y[:cut], validation_data=(X[cut:], y[cut:]), epochs=c["EPOCHS"],
                  batch_size=c["BATCH"], callbacks=cb, verbose=0)
        vl = np.array(h.history["val_loss"])
        best = c["MIN_EPOCHS"] + int(np.argmin(vl[c["MIN_EPOCHS"]:])) + 1 if len(vl) > c["MIN_EPOCHS"] else len(vl)
    else:
        m.fit(X, y, epochs=epochs, batch_size=c["BATCH"], verbose=0)
        best = epochs
    prm = {"LOOKBACK": L, "MU": float(mu), "SD": float(sd), "CLIP": float(clip)}
    return {"model": m, "params": prm, "best": best}


def gru_forecast(art, hist, horizon):
    m, prm = art["model"], art["params"]
    L, mu, sd = prm["LOOKBACK"], prm["MU"], prm["SD"]
    clip = prm.get("CLIP")
    r = _rets(hist)
    if clip is None:   # ไฟล์ params เก่าจาก notebook รุ่นแรก
        clip = 5 * r.std()
    w = list((np.clip(r, -clip, clip) - mu) / sd)
    price, out = float(hist["Close"].iloc[-1]), []
    for _ in range(horizon):
        zz = float(m(np.array(w[-L:], dtype="float32")[None, :, None], training=False).numpy()[0, 0])
        w.append(zz)
        price *= np.exp(zz * sd + mu)
        out.append(price)
    return pd.DataFrame({"ds": _future_dates(hist, horizon), "yhat": out})


def gru_save(art, p, hist):
    art["model"].save(p["model"])
    with open(p["params"], "w") as f:
        json.dump({**art["params"], "last_date": str(hist["Date"].iloc[-1].date()),
                   "last_price": float(hist["Close"].iloc[-1])}, f, indent=2)


def gru_load(asset, p):
    from tensorflow import keras
    with open(p["params"]) as f:
        prm = json.load(f)
    return {"model": keras.models.load_model(p["model"]), "params": prm}


# ================================================================ XGBoost
def xgb_features(r, lags):
    s = pd.Series(r)
    f = {f"lag_{k}": s.shift(k - 1) for k in range(1, lags + 1)}
    for w in (5, 10, 20):
        f[f"mean_{w}"] = s.rolling(w).mean()
        f[f"std_{w}"] = s.rolling(w).std()
    logp = s.cumsum()
    for w in (20, 60):
        f[f"mom_{w}"] = logp - logp.rolling(w).mean()
    return pd.DataFrame(f)


def xgb_fit(df, asset, n_estimators=None, **_):
    import xgboost as xgb
    c = XGB_CFG
    r = _rets(df)
    n = len(r)
    val_start = int(n * (1 - c["VAL_RATIO"]))
    clip = c["CLIP_SD"] * r[:val_start].std()
    rc = np.clip(r, -clip, clip)
    F = xgb_features(rc, c["LAGS"]).shift(1)
    y = pd.Series(rc)
    ok = F.notna().all(axis=1).values
    idx = np.arange(n)
    if n_estimators is None:
        tr, va = ok & (idx < val_start), ok & (idx >= val_start)
        m = xgb.XGBRegressor(**XGB_PARAMS, early_stopping_rounds=50, eval_metric="rmse")
        m.fit(F[tr], y[tr], eval_set=[(F[va], y[va])], verbose=False)
        best = m.best_iteration + 1
    else:
        m = xgb.XGBRegressor(**{**XGB_PARAMS, "n_estimators": n_estimators})
        m.fit(F[ok], y[ok])
        best = n_estimators
    prm = {"FEATURES": list(F.columns), "LAGS": c["LAGS"], "CLIP": float(clip)}
    return {"model": m, "params": prm, "best": best}


def xgb_forecast(art, hist, horizon):
    m, prm = art["model"], art["params"]
    r = list(np.clip(_rets(hist), -prm["CLIP"], prm["CLIP"]))
    price, out = float(hist["Close"].iloc[-1]), []
    for _ in range(horizon):
        x = xgb_features(np.array(r), prm["LAGS"]).iloc[[-1]][prm["FEATURES"]]
        p = float(m.predict(x)[0])
        r.append(p)
        price *= np.exp(p)
        out.append(price)
    return pd.DataFrame({"ds": _future_dates(hist, horizon), "yhat": out})


def xgb_save(art, p, hist):
    art["model"].save_model(p["model"])
    with open(p["params"], "w") as f:
        json.dump({**art["params"], "last_date": str(hist["Date"].iloc[-1].date()),
                   "last_price": float(hist["Close"].iloc[-1])}, f, indent=2)


def xgb_load(asset, p):
    import xgboost as xgb
    m = xgb.XGBRegressor()
    m.load_model(p["model"])
    with open(p["params"]) as f:
        prm = json.load(f)
    return {"model": m, "params": prm}


# ================================================================ dispatch
FIT = {"prophet": prophet_fit, "gru": gru_fit, "xgb": xgb_fit}
FORECAST = {"prophet": prophet_forecast, "gru": gru_forecast, "xgb": xgb_forecast}
LOAD = {"prophet": prophet_load, "gru": gru_load, "xgb": xgb_load}


def model_exists(asset, model):
    p = paths(asset, model)
    need = [p["model"]] + ([p["params"]] if model != "prophet" else [])
    return all(os.path.exists(x) for x in need)


def load_artifact(asset, model):
    """โหลดโมเดลที่ฝึกไว้แล้ว (ข้อ 2.3.6.1) — เก็บไว้ในหน่วยความจำ โหลดใหม่เมื่อไฟล์เปลี่ยน"""
    p = paths(asset, model)
    key = (asset, model, os.path.getmtime(p["model"]))
    with _lock:
        if key not in _art_cache:
            _art_cache[key] = LOAD[model](asset, p)
        return _art_cache[key]


def forecast(asset, model, horizon=HORIZON):
    """พยากรณ์ล่วงหน้า horizon วัน จากราคาล่าสุดใน CSV (ข้อ 2.3.6.2)"""
    if not model_exists(asset, model):
        raise FileNotFoundError(f"ยังไม่มีไฟล์โมเดล {MODELS[model]} ของ {ds.ASSETS[asset]['name']} — ให้ Admin สั่งเทรนก่อน")
    hist = ds.load_clean(asset)
    p = paths(asset, model)
    key = (asset, model, horizon, os.path.getmtime(p["model"]), str(hist["Date"].iloc[-1]), float(hist["Close"].iloc[-1]))
    if key not in _fc_cache:
        art = load_artifact(asset, model)
        _fc_cache[key] = FORECAST[model](art, hist, horizon)
    return _fc_cache[key].copy()


def read_metrics(asset, model):
    p = paths(asset, model)["metrics"]
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _evaluate(y_true, y_pred):
    y_true, y_pred = np.asarray(y_true, float), np.asarray(y_pred, float)
    mape = float(np.mean(np.abs((y_true - y_pred) / y_true)) * 100)
    return {"MAE": float(np.mean(np.abs(y_true - y_pred))),
            "RMSE": float(np.sqrt(np.mean((y_true - y_pred) ** 2))),
            "MAPE": mape, "Accuracy": 100 - mape}


def train(asset, model, log=print):
    """ฝึกสอนใหม่ (ข้อ 2.3.5): ประเมินบนชุดทดสอบ 1 ปี → เทรนใหม่ด้วยข้อมูลทั้งหมด → บันทึกไฟล์โมเดล"""
    df = ds.load_clean(asset)
    dates = df["Date"].values
    ts = int(np.searchsorted(dates, dates[-1] - np.timedelta64(TEST_DAYS, "D"), side="right"))

    log(f"[{asset}/{model}] เทรนเพื่อประเมินผล (ข้อมูลถึง {str(dates[ts - 1])[:10]})")
    art = FIT[model](df.iloc[:ts], asset)

    log(f"[{asset}/{model}] ประเมินผลพยากรณ์ {HORIZON} วันบนชุดทดสอบ 1 ปี")
    rows = []
    for s in range(ts, len(df) - HORIZON + 1, HORIZON):
        hist = df.iloc[:s]
        y = df["Close"].values[s:s + HORIZON]
        pred = FORECAST[model](art, hist, HORIZON)["yhat"].values
        rows.append((_evaluate(y, pred), _evaluate(y, np.full(HORIZON, hist["Close"].iloc[-1]))))
    avg = lambda i: {k: float(np.mean([r[i][k] for r in rows])) for k in rows[0][i]}

    log(f"[{asset}/{model}] เทรนโมเดลสุดท้ายด้วยข้อมูลทั้งหมด")
    extra = {"epochs": art["best"]} if model == "gru" else {"n_estimators": art["best"]} if model == "xgb" else {}
    final = FIT[model](df, asset, **extra)

    p = paths(asset, model)
    if model == "prophet":
        prophet_save(final, p)
    elif model == "gru":
        gru_save(final, p, df)
    else:
        xgb_save(final, p, df)

    metrics = {
        "asset": asset, "model": model, "model_name": MODELS[model], "horizon": HORIZON,
        "windows": len(rows),
        "test_from": str(dates[ts])[:10], "test_to": str(dates[-1])[:10],
        **avg(0), "naive": avg(1),
        "trained_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "trained_until": str(dates[-1])[:10],
        **extra,
    }
    with open(p["metrics"], "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)

    fc = forecast(asset, model)
    fc.assign(ds=fc["ds"].dt.strftime("%Y-%m-%d")).round(2).to_csv(p["forecast"], index=False)
    log(f"[{asset}/{model}] เสร็จ: MAPE {metrics['MAPE']:.2f}% (Naive {metrics['naive']['MAPE']:.2f}%)")
    return metrics
