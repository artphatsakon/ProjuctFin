"""
เว็บไซต์ติดตามและพยากรณ์ราคาทองคำและน้ำมันดิบ (Streamlit — Python ล้วน)

รัน:   streamlit run app.py   หรือ   python app.py   (หรือกด ▶ ใน VS Code) แล้วเปิด http://localhost:8501
Admin: เลือกเมนู "ผู้ดูแลระบบ" ทางซ้าย (ค่าเริ่มต้น admin / admin1234 — เปลี่ยนรหัสได้ในแท็บตั้งค่า)
"""
import hmac
import subprocess
import sys

import streamlit as st
from streamlit import runtime

# ถ้ารันด้วย "python app.py" หรือกดปุ่ม ▶ ใน VS Code → เปิด Streamlit ให้อัตโนมัติ
if __name__ == "__main__" and not runtime.exists():
    sys.exit(subprocess.call([sys.executable, "-m", "streamlit", "run", __file__]))

import pandas as pd
import plotly.graph_objects as go

import data_service as ds
import model_service as ms

st.set_page_config(page_title="พยากรณ์ราคาทองคำและน้ำมันดิบ", page_icon="📈", layout="wide")

MODEL_COLORS = {"prophet": "#2563eb", "gru": "#d97706", "xgb": "#059669"}
RANGES = {"1 เดือน": 31, "3 เดือน": 92, "6 เดือน": 183, "1 ปี": 365, "5 ปี": 1826, "ทั้งหมด": None}


def cloud_admin():
    """บน Streamlit Cloud ตั้งรหัส Admin ใน Secrets (ADMIN_USER / ADMIN_PASSWORD) — คืน (user, password) หรือ None"""
    try:
        pw = st.secrets.get("ADMIN_PASSWORD")
        return (st.secrets.get("ADMIN_USER", "admin"), pw) if pw else None
    except Exception:
        return None


# ================================================================ cached data
@st.cache_data(ttl=300, show_spinner=False)
def get_price(asset):
    return ds.current_price(asset)


@st.cache_data(ttl=3600, show_spinner=False)
def get_fx():
    return ds.usd_thb()


def get_forecast(asset, model):
    try:
        return ms.forecast(asset, model), None
    except Exception as e:
        return None, str(e)


# ================================================================ หน้าหลัก (ข้อ 2.3.1, 2.3.2, 2.3.3.1 — ไม่ต้อง Login)
def page_home():
    st.title("ราคาทองคำและน้ำมันดิบ")
    st.caption("ติดตามราคาปัจจุบัน ราคาย้อนหลัง และผลพยากรณ์ล่วงหน้า 7 วันจากโมเดล Prophet, GRU และ XGBoost")

    c1, c2 = st.columns([1, 1])
    asset = c1.segmented_control("สินทรัพย์", list(ds.ASSETS), default="gold",
                                 format_func=lambda a: ds.ASSETS[a]["name"], key="asset") or "gold"
    model = c2.segmented_control("โมเดลพยากรณ์", list(ms.MODELS), default="xgb",
                                 format_func=lambda m: ms.MODELS[m], key="model") or "xgb"

    hist = ds.load_clean(asset)
    price = get_price(asset)
    fx = get_fx()
    rate = fx["rate"]
    thai = ds.thai_units(asset, price["price"], rate)
    unit = ds.ASSETS[asset]["unit"]

    # ---- ราคาปัจจุบัน + ค่าเงิน
    m1, m2, m3, m4 = st.columns(4)
    m1.metric(f"ราคาปัจจุบัน ({unit})", f"{price['price']:,.2f}",
              f"{price['change']:+,.2f} ({price['change_pct']:+.2f}%)")
    m2.metric("คิดเป็นเงินบาท", f"฿{price['price'] * rate:,.2f}", help=f"1 USD = {rate:,.4f} บาท ({fx['source']})")
    m3.metric(thai["label"], f"฿{thai['value']:,.2f}", help="ค่าประมาณ ไม่รวมค่ากำเหน็จ ภาษี หรือค่าการตลาด")
    last252 = hist["Close"].iloc[-252:]
    m4.metric("สูงสุด / ต่ำสุด 52 สัปดาห์", f"{last252.max():,.0f} / {last252.min():,.0f}",
              help=f"สูงสุด {last252.max():,.2f} · ต่ำสุด {last252.min():,.2f}")
    st.caption(f"แหล่งข้อมูล: {price['source']} · {price['time']} · 1 USD = {rate:,.4f} บาท ({fx['source']}) · "
               f"ราคาปิดล่าสุด {hist['Close'].iloc[-1]:,.2f} ({hist['Date'].iloc[-1]:%Y-%m-%d})")

    # ---- กราฟราคาย้อนหลัง + ผลพยากรณ์
    st.subheader("ราคาย้อนหลังและผลพยากรณ์")
    r1, r2 = st.columns([3, 1])
    rng = r1.segmented_control("ช่วงเวลา", list(RANGES), default="3 เดือน", key="range", label_visibility="collapsed") or "3 เดือน"
    show_all = r2.toggle("เปรียบเทียบทุกโมเดล", key="show_all")

    view = hist if RANGES[rng] is None else hist[hist["Date"] >= hist["Date"].iloc[-1] - pd.Timedelta(days=RANGES[rng])]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=view["Date"], y=view["Close"], name="ราคาจริง", line=dict(color="#111827", width=1.6)))
    last_d, last_p = hist["Date"].iloc[-1], hist["Close"].iloc[-1]
    for m in (list(ms.MODELS) if show_all else [model]):
        fc, err = get_forecast(asset, m)
        if fc is None:
            continue
        xs, ys = [last_d, *fc["ds"]], [last_p, *fc["yhat"]]
        if not show_all and "lower" in fc:
            fig.add_trace(go.Scatter(x=[last_d, *fc["ds"], *fc["ds"][::-1], last_d],
                                     y=[last_p, *fc["upper"], *fc["lower"][::-1], last_p],
                                     fill="toself", fillcolor="rgba(37,99,235,0.12)", line=dict(width=0),
                                     name="ช่วงความเชื่อมั่น", hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=xs, y=ys, name=f"พยากรณ์ {ms.MODELS[m]}", mode="lines+markers",
                                 line=dict(color=MODEL_COLORS[m], dash="dash", width=2), marker=dict(size=5)))
    fig.update_layout(height=430, margin=dict(l=10, r=10, t=10, b=10), hovermode="x unified",
                      legend=dict(orientation="h", y=1.08), yaxis_title=unit, plot_bgcolor="white")
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor="#eef0f3", tickformat=",.0f")
    st.plotly_chart(fig, width="stretch")

    # ---- ตารางพยากรณ์ 7 วัน + ความแม่นยำ
    left, right = st.columns(2)
    with left:
        st.subheader(f"พยากรณ์ล่วงหน้า 7 วัน · {ms.MODELS[model]}")
        fc, err = get_forecast(asset, model)
        if fc is None:
            st.error(err)
        else:
            thai_col = "ทองไทย/บาท (฿)" if asset == "gold" else "บาท/ลิตร (฿)"
            table = pd.DataFrame({
                "วันที่": fc["ds"].dt.strftime("%Y-%m-%d"),
                "USD": fc["yhat"].round(2),
                "บาท (฿)": (fc["yhat"] * rate).round(2),
                thai_col: [round(ds.thai_units(asset, v, rate)["value"], 2) for v in fc["yhat"]],
                "เทียบล่าสุด (%)": ((fc["yhat"] / last_p - 1) * 100).round(2),
            })
            st.dataframe(table, hide_index=True, width="stretch",
                         column_config={c: st.column_config.NumberColumn(format="%,.2f") for c in table.columns[1:4]}
                         | {"เทียบล่าสุด (%)": st.column_config.NumberColumn(format="%+.2f%%")})
            mt = ms.read_metrics(asset, model)
            if mt:
                st.caption(f"ฝึกสอนเมื่อ {mt['trained_at']} (ข้อมูลถึง {mt['trained_until']}) · พยากรณ์ต่อจากราคาปิดล่าสุด {last_d:%Y-%m-%d}")

    with right:
        st.subheader("ความแม่นยำของโมเดล")
        rows, naive, info = [], None, None
        for m, name in ms.MODELS.items():
            mt = ms.read_metrics(asset, m)
            if mt:
                rows.append({"โมเดล": name, "MAE": mt["MAE"], "RMSE": mt["RMSE"], "MAPE (%)": mt["MAPE"], "Accuracy (%)": mt["Accuracy"]})
                naive, info = mt["naive"], mt
            else:
                rows.append({"โมเดล": f"{name} (ยังไม่ได้เทรน)"})
        if naive:
            best = min((r for r in rows if "MAPE (%)" in r), key=lambda r: r["MAPE (%)"])
            best["โมเดล"] += " ★"
            rows.append({"โมเดล": "Naive (เกณฑ์เทียบ)", "MAE": naive["MAE"], "RMSE": naive["RMSE"],
                         "MAPE (%)": naive["MAPE"], "Accuracy (%)": naive["Accuracy"]})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                     column_config={c: st.column_config.NumberColumn(format="%,.2f") for c in ["MAE", "RMSE", "MAPE (%)", "Accuracy (%)"]})
        if info:
            st.caption(f"★ = MAPE ต่ำสุด · วัดจากการพยากรณ์ล่วงหน้า {info['horizon']} วัน จำนวน {info['windows']} รอบ "
                       f"ในชุดทดสอบ {info['test_from']} ถึง {info['test_to']} · Naive = เดาว่าราคาเท่ากับราคาล่าสุด · Accuracy = 100 − MAPE")

    st.divider()
    st.caption("ข้อมูลราคาจาก Yahoo Finance · ผลพยากรณ์เป็นการประมาณทางสถิติ ไม่ใช่คำแนะนำในการลงทุน")


# ================================================================ ผู้ดูแลระบบ (ข้อ 2.3.3.2 — ต้อง Login)
def login_form():
    st.title("เข้าสู่ระบบผู้ดูแลระบบ")
    st.caption("เฉพาะผู้ดูแลระบบ สำหรับสั่งฝึกสอนโมเดลใหม่ แก้ไขข้อมูล และตั้งค่า API")
    with st.form("login"):
        u = st.text_input("ชื่อผู้ใช้")
        p = st.text_input("รหัสผ่าน", type="password")
        if st.form_submit_button("เข้าสู่ระบบ", type="primary"):
            cloud = cloud_admin()
            if cloud:
                ok = u == cloud[0] and hmac.compare_digest(p.encode(), str(cloud[1]).encode())
            else:
                c = ds.load_config()
                ok = u == c["admin_user"] and ds.check_password(p, c["admin_password_hash"])
            if ok:
                st.session_state.admin = True
                st.rerun()
            st.error("ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")


def admin_data_tab():
    cols = st.columns(len(ds.ASSETS))
    for col, (a, info) in zip(cols, ds.ASSETS.items()):
        with col, st.container(border=True):
            s = ds.validate(a)
            st.markdown(f"#### {info['name']}")
            st.markdown(
                f"- ไฟล์: `{info['csv']}`\n"
                f"- ช่วงข้อมูล: {s['first_date']} ถึง {s['last_date']}\n"
                f"- จำนวนแถว: {s['rows']:,} (ใช้ได้ {s['rows_clean']:,})\n"
                f"- ค่าที่หายไป: {s['missing_close']} · วันที่ซ้ำ: {s['duplicates']} · วันที่ผิดรูปแบบ: {s['bad_dates']}\n"
                f"- ราคา ≤ 0: {s['non_positive']} (ระบบตัดออกก่อนพยากรณ์) · ช่องว่างเกิน 5 วัน: {s['gaps_over_5d']}\n"
                f"- ราคาเปลี่ยน > 15%/วัน: {len(s['big_moves'])} วัน"
                + (f" ({', '.join(s['big_moves'][:4])}{'…' if len(s['big_moves']) > 4 else ''})" if s["big_moves"] else ""))
            if st.button("อัปเดตจาก Yahoo Finance", key=f"yh_{a}", width="stretch"):
                with st.spinner("กำลังดึงข้อมูล…"):
                    try:
                        r = ds.update_from_yahoo(a)
                        st.success(f"เพิ่ม {r['added']} วัน")
                    except Exception as e:
                        st.error(str(e))
                st.cache_data.clear()


def admin_model_tab():
    rows = []
    for a in ds.ASSETS:
        for m, name in ms.MODELS.items():
            mt = ms.read_metrics(a, m)
            rows.append({"สินทรัพย์": ds.ASSETS[a]["name"], "โมเดล": name,
                         "ไฟล์โมเดล": "มี" if ms.model_exists(a, m) else "ไม่มี",
                         "MAPE (%)": mt["MAPE"] if mt else None, "Naive (%)": mt["naive"]["MAPE"] if mt else None,
                         "ฝึกสอนเมื่อ": mt["trained_at"] if mt else "—", "ข้อมูลถึง": mt["trained_until"] if mt else "—"})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                 column_config={"MAPE (%)": st.column_config.NumberColumn(format="%.2f"),
                                "Naive (%)": st.column_config.NumberColumn(format="%.2f")})

    st.markdown("#### สั่งฝึกสอนโมเดลใหม่")
    c1, c2, c3 = st.columns([1, 1, 1])
    a = c1.selectbox("สินทรัพย์", ["all", *ds.ASSETS], format_func=lambda x: "ทั้งหมด" if x == "all" else ds.ASSETS[x]["name"])
    m = c2.selectbox("โมเดล", ["all", *ms.MODELS], format_func=lambda x: "ทั้งหมด" if x == "all" else ms.MODELS[x])
    c3.write("")
    go_train = c3.button("เริ่มเทรน", type="primary", width="stretch")
    st.caption("GRU ใช้เวลานานที่สุด (ประมาณ 2–5 นาทีต่อตัว) · แนะนำให้อัปเดตข้อมูลก่อนเทรน · ระหว่างเทรนอย่าปิดหน้านี้")
    if go_train:
        assets = list(ds.ASSETS) if a == "all" else [a]
        models = list(ms.MODELS) if m == "all" else [m]
        with st.status("กำลังฝึกสอนโมเดล…", expanded=True) as status:
            try:
                for aa in assets:
                    for mm in models:
                        ms.train(aa, mm, log=st.write)
                status.update(label="ฝึกสอนเสร็จแล้ว", state="complete")
            except Exception as e:
                st.error(str(e))
                status.update(label="ฝึกสอนไม่สำเร็จ", state="error")
        st.cache_data.clear()


def admin_edit_tab():
    a = st.selectbox("สินทรัพย์", list(ds.ASSETS), format_func=lambda x: ds.ASSETS[x]["name"], key="edit_asset")
    q = st.text_input("ค้นหาวันที่ (เช่น 2026-09) — เว้นว่างเพื่อดู 60 แถวล่าสุด", key="edit_q")
    raw = ds.read_raw(a)
    view = raw[raw["Date"].astype(str).str.startswith(q)] if q else raw
    view = view.sort_values("Date", ascending=False).head(60)[["Date", "Open", "High", "Low", "Close", "Volume"]].reset_index(drop=True)
    st.caption("แก้ไขตัวเลขในตารางได้โดยตรง · เพิ่มแถวที่ท้ายตาราง · เลือกแถวแล้วกด Delete เพื่อลบ · จากนั้นกด \"บันทึกการเปลี่ยนแปลง\"")
    edited = st.data_editor(view, num_rows="dynamic", hide_index=True, width="stretch", key=f"editor_{a}_{q}",
                            column_config={"Date": st.column_config.TextColumn("วันที่ (YYYY-MM-DD)", required=True),
                                           "Close": st.column_config.NumberColumn("ปิด", min_value=0.01, required=True, format="%.2f"),
                                           "Open": st.column_config.NumberColumn("เปิด", format="%.2f"),
                                           "High": st.column_config.NumberColumn("สูงสุด", format="%.2f"),
                                           "Low": st.column_config.NumberColumn("ต่ำสุด", format="%.2f"),
                                           "Volume": st.column_config.NumberColumn("Volume", disabled=True)})
    if st.button("บันทึกการเปลี่ยนแปลง", type="primary"):
        try:
            before = set(view["Date"].astype(str))
            after = set(edited["Date"].dropna().astype(str))
            for d in before - after:
                ds.delete_row(a, d)
            n = 0
            orig = view.set_index(view["Date"].astype(str))
            for _, r in edited.dropna(subset=["Date", "Close"]).iterrows():
                d = pd.to_datetime(str(r["Date"])).strftime("%Y-%m-%d")
                if d in orig.index and orig.loc[d, ["Open", "High", "Low", "Close"]].equals(r[["Open", "High", "Low", "Close"]]):
                    continue
                ds.upsert_row(a, d, r["Close"], r["Open"] if pd.notna(r["Open"]) else None,
                              r["High"] if pd.notna(r["High"]) else None, r["Low"] if pd.notna(r["Low"]) else None)
                n += 1
            st.success(f"บันทึกแล้ว: แก้ไข/เพิ่ม {n} แถว · ลบ {len(before - after)} แถว")
            st.cache_data.clear()
        except Exception as e:
            st.error(f"บันทึกไม่สำเร็จ: {e}")


def admin_settings_tab():
    c = ds.load_config()
    with st.form("settings"):
        fx = st.number_input("USD/THB สำรอง (ใช้เมื่อดึงอัตราแลกเปลี่ยนจาก Yahoo ไม่ได้)", value=float(c.get("usdthb_fallback", 33.0)), step=0.01, format="%.4f")
        pw = st.text_input(f"รหัสผ่านใหม่ ({c['admin_user']})", type="password", placeholder="เว้นว่างถ้าไม่เปลี่ยน (อย่างน้อย 8 ตัวอักษร)")
        if st.form_submit_button("บันทึกการตั้งค่า", type="primary"):
            if pw and (len(pw) < 8 or pw == "admin1234"):
                st.error("รหัสผ่านใหม่ต้องยาวอย่างน้อย 8 ตัวอักษร และห้ามใช้รหัสเริ่มต้น")
            else:
                c["usdthb_fallback"] = float(fx)
                if pw:
                    c["admin_password_hash"] = ds.hash_password(pw)
                ds.save_config(c)
                ds.clear_cache()
                st.cache_data.clear()
                st.success("บันทึกการตั้งค่าแล้ว")
    if st.button("ทดสอบการเชื่อมต่อ Yahoo Finance"):
        for a, info in ds.ASSETS.items():
            try:
                p, t = ds.yahoo_last_price(a)
                st.success(f"{info['name']} ({info['ticker']}): {p:,.2f} {info['unit']} · {t:%Y-%m-%d %H:%M}")
            except Exception as e:
                st.error(f"{info['name']}: เชื่อมต่อไม่สำเร็จ ({e})")
    st.caption("แหล่งข้อมูล: Yahoo Finance — ราคาปัจจุบันและข้อมูลย้อนหลัง (GC=F ทองคำ, CL=F น้ำมันดิบ WTI) และอัตราแลกเปลี่ยน USD/THB (THB=X)")


def force_password_change():
    """บังคับเปลี่ยนรหัสผ่านถ้ายังเป็นค่าเริ่มต้น (เว็บเปิดออนไลน์ได้ ห้ามใช้ admin1234)"""
    st.title("ตั้งรหัสผ่านใหม่ก่อนใช้งาน")
    st.warning("รหัสผ่านยังเป็นค่าเริ่มต้น (admin1234) ซึ่งไม่ปลอดภัยเมื่อเว็บเปิดออนไลน์ กรุณาตั้งรหัสผ่านใหม่")
    with st.form("force_pw"):
        p1 = st.text_input("รหัสผ่านใหม่ (อย่างน้อย 8 ตัวอักษร)", type="password")
        p2 = st.text_input("ยืนยันรหัสผ่านใหม่", type="password")
        if st.form_submit_button("บันทึกรหัสผ่าน", type="primary"):
            if len(p1) < 8:
                st.error("รหัสผ่านต้องยาวอย่างน้อย 8 ตัวอักษร")
            elif p1 != p2:
                st.error("รหัสผ่านทั้งสองช่องไม่ตรงกัน")
            elif p1 == "admin1234":
                st.error("ห้ามใช้รหัสผ่านเริ่มต้น")
            else:
                c = ds.load_config()
                c["admin_password_hash"] = ds.hash_password(p1)
                ds.save_config(c)
                st.success("ตั้งรหัสผ่านใหม่แล้ว")
                st.rerun()


def page_admin():
    if not st.session_state.get("admin"):
        login_form()
        return
    if cloud_admin():
        st.info("เว็บนี้รันบน Streamlit Cloud: การแก้ไขข้อมูลและการเทรนโมเดลในหน้านี้จะหายเมื่อเว็บรีสตาร์ท "
                "ข้อมูลราคาถาวรอัปเดตอัตโนมัติทุกเที่ยงคืนผ่าน GitHub · เปลี่ยนรหัส Admin ได้ที่ Settings → Secrets ของแอป")
    elif ds.check_password("admin1234", ds.load_config()["admin_password_hash"]):
        force_password_change()
        return
    h1, h2 = st.columns([5, 1])
    h1.title("จัดการระบบ")
    if h2.button("ออกจากระบบ", width="stretch"):
        st.session_state.admin = False
        st.rerun()
    t1, t2, t3, t4 = st.tabs(["ข้อมูลราคา", "โมเดลพยากรณ์", "แก้ไขข้อมูล", "ตั้งค่า API"])
    with t1:
        admin_data_tab()
    with t2:
        admin_model_tab()
    with t3:
        admin_edit_tab()
    with t4:
        admin_settings_tab()


nav = st.navigation([st.Page(page_home, title="หน้าหลัก", icon="📈", default=True),
                     st.Page(page_admin, title="ผู้ดูแลระบบ", icon="🔒", url_path="admin")])
nav.run()
