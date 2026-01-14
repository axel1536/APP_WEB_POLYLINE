import streamlit as st
from datetime import datetime, date
import os
import json
import io
import base64
import traceback
import requests
from caja_chica import mostrar_caja_chica()

# PDF
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from PIL import Image, ImageOps

st.set_page_config(page_title="Arq. Supervisor 2025", layout="wide")

# Carpeta destino (por si tu Apps Script acepta folderId)
DEFAULT_DRIVE_FOLDER_ID = "1L_0QzSQRk6-uGgTs2lin1LGb4YwsoDJ-"

# Carpetas locales (en Streamlit Cloud son temporales)
for folder in ["obras", "obras/fotos"]:
    os.makedirs(folder, exist_ok=True)

OBRAS = {
    "rinconada": "La Rinconada – La Molina",
    "pachacutec": "Ciudad Pachacútec – Ventanilla"
}

PRESUPUESTO_BASE = {
    "pachacutec": 99524.0
}

CATEGORIAS_GASTO = ["Materiales", "Mano de obra", "Equipos", "Transporte", "Otros"]


# =========================
# Utils
# =========================
def slugify(txt: str) -> str:
    return (txt.lower()
            .replace("–", "-")
            .replace("—", "-")
            .replace(" ", "_")
            .replace("ó", "o").replace("í", "i").replace("á", "a").replace("é", "e").replace("ú", "u"))


def safe_filename(name: str) -> str:
    s = slugify(name)
    s = "".join(ch for ch in s if ch.isalnum() or ch in ("_", "-", "."))
    return s


def init_state(key: str, default):
    if key not in st.session_state:
        st.session_state[key] = default


# =========================
# Apps Script Upload
# =========================
def upload_pdf_via_apps_script(pdf_bytes: io.BytesIO, filename: str) -> dict:
    cfg = st.secrets.get("apps_script", {})
    url = str(cfg.get("upload_url", "")).strip()
    token = str(cfg.get("token", "")).strip()
    folder_id = str(cfg.get("folder_id", DEFAULT_DRIVE_FOLDER_ID)).strip()

    if not url or not token:
        raise RuntimeError("Falta [apps_script].upload_url o [apps_script].token en Secrets.")

    pdf_bytes.seek(0)
    b64 = base64.b64encode(pdf_bytes.read()).decode("utf-8")

    # Enviar CLAVES compatibles (por si tu Apps Script espera 'base64' o 'file_base64')
    payload = {
        "token": token,
        "filename": filename,
        "fileName": filename,      # compat extra
        "base64": b64,             # <-- clave que tu Apps Script pidió
        "file_base64": b64,        # compat con tu intento anterior
        "mimeType": "application/pdf",
        "folderId": folder_id
    }

    r = requests.post(
        url,
        data=json.dumps(payload),
        headers={"Content-Type": "application/json"},
        timeout=120
    )

    # Intentar parsear JSON
    try:
        data = r.json()
    except Exception:
        raise RuntimeError(f"Respuesta no-JSON. HTTP {r.status_code}: {r.text[:600]}")

    # Apps Script puede devolver HTTP 200 con ok:false
    if r.status_code != 200 or not data.get("ok", False):
        raise RuntimeError(f"Fallo subida: HTTP {r.status_code} | Respuesta: {data}")

    return data


# =========================
# PDF (Bytes)
# =========================
def _draw_wrapped_text(c, text, x, y, max_width, line_height=14, font="Helvetica", size=10):
    c.setFont(font, size)
    words = (text or "").split()
    if not words:
        return y

    line = ""
    for w in words:
        test = (line + " " + w).strip()
        if c.stringWidth(test, font, size) <= max_width:
            line = test
        else:
            c.drawString(x, y, line)
            y -= line_height
            line = w

    if line:
        c.drawString(x, y, line)
        y -= line_height

    return y


def generate_parte_diario_pdf_bytes(
    obra_key: str,
    obra_name: str,
    fecha_str: str,
    responsable: str,
    avance_pct: int,
    obs: str,
    gastos_rows: list,
    total_gastos_hoy: float,
    rutas_fotos: list
) -> io.BytesIO:
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    margin = 2 * cm
    y = height - margin

    # Header
    c.setFont("Helvetica-Bold", 16)
    c.drawString(margin, y, "PARTE DIARIO DE OBRA")
    y -= 18

    c.setFont("Helvetica", 11)
    c.drawString(margin, y, f"Obra: {obra_name}")
    y -= 14
    c.drawString(margin, y, f"Fecha: {fecha_str}")
    y -= 14
    c.drawString(margin, y, f"Responsable: {responsable}")
    y -= 14
    c.drawString(margin, y, f"Avance logrado hoy: {avance_pct}%")
    y -= 18

    # Observaciones
    c.setFont("Helvetica-Bold", 12)
    c.drawString(margin, y, "Observaciones")
    y -= 14
    c.setFont("Helvetica", 10)
    y = _draw_wrapped_text(c, obs or "-", margin, y, max_width=width - 2 * margin, line_height=13, size=10)
    y -= 6

    # Gastos
    c.setFont("Helvetica-Bold", 12)
    c.drawString(margin, y, "Gastos del día")
    y -= 14

    col_tipo = margin
    col_det = margin + 4.2 * cm

    c.setFont("Helvetica-Bold", 10)
    c.drawString(col_tipo, y, "Tipo")
    c.drawString(col_det, y, "Detalle")
    c.drawRightString(width - margin, y, "Monto (S/)")
    y -= 10
    c.line(margin, y, width - margin, y)
    y -= 12

    c.setFont("Helvetica", 9)

    if not gastos_rows:
        c.drawString(margin, y, "Sin gastos registrados.")
        y -= 14
    else:
        for row in gastos_rows:
            tipo = str(row.get("tipo", "")).strip()
            detalle = str(row.get("detalle", "")).strip() or "-"
            monto = float(row.get("monto", 0.0) or 0.0)

            if y < 6 * cm:
                c.showPage()
                y = height - margin
                c.setFont("Helvetica-Bold", 12)
                c.drawString(margin, y, "Gastos del día (continuación)")
                y -= 16
                c.setFont("Helvetica", 9)

            c.drawString(col_tipo, y, (tipo[:28] + "…") if len(tipo) > 28 else tipo)

            max_det_w = (width - margin) - col_det - 4.0 * cm
            y_det = _draw_wrapped_text(c, detalle, col_det, y, max_width=max_det_w, line_height=11, font="Helvetica", size=9)

            c.drawRightString(width - margin, y, f"{monto:,.2f}")
            y = min(y_det, y - 11)

    y -= 8
    c.setFont("Helvetica-Bold", 10)
    c.drawRightString(width - margin, y, f"TOTAL HOY: S/ {float(total_gastos_hoy):,.2f}")
    y -= 18

    # Fotos
    c.setFont("Helvetica-Bold", 12)
    c.drawString(margin, y, "Evidencia fotográfica")
    y -= 14

    if not rutas_fotos:
        c.setFont("Helvetica", 10)
        c.drawString(margin, y, "Sin fotos adjuntas.")
        y -= 14
    else:
        max_img_w = width - 2 * margin
        max_img_h = 7.5 * cm

        for i, path in enumerate(rutas_fotos, start=1):
            if not os.path.exists(path):
                continue

            if y < (max_img_h + 3 * cm):
                c.showPage()
                y = height - margin
                c.setFont("Helvetica-Bold", 12)
                c.drawString(margin, y, "Evidencia fotográfica (continuación)")
                y -= 18

            try:
                img = Image.open(path)
                img = ImageOps.exif_transpose(img)
                img = img.convert("RGB")

                iw, ih = img.size
                scale = min(max_img_w / iw, max_img_h / ih)
                draw_w = iw * scale
                draw_h = ih * scale

                img_reader = ImageReader(img)

                c.setFont("Helvetica", 9)
                c.drawString(margin, y, f"Foto {i}: {os.path.basename(path)}")
                y -= 12

                c.drawImage(
                    img_reader,
                    margin,
                    y - draw_h,
                    width=draw_w,
                    height=draw_h,
                    preserveAspectRatio=True,
                    mask="auto"
                )
                y -= (draw_h + 14)

            except Exception as e:
                c.setFont("Helvetica", 10)
                c.drawString(margin, y, f"No se pudo insertar la imagen: {os.path.basename(path)} | {e}")
                y -= 14

    c.setFont("Helvetica-Oblique", 8)
    c.drawString(margin, 1.2 * cm, f"Generado automáticamente | Obra: {obra_key}")
    c.save()

    buffer.seek(0)
    return buffer


# =========================
# Auth
# =========================
def check_password():
    def password_entered():
        users = st.secrets["users"]
        if (st.session_state["password"] == users["jefe_pass"] and
                st.session_state["user"] == users["jefe_user"]):
            st.session_state["auth"] = "jefe"
        elif (st.session_state["password"] == users["pasante_pass"] and
              st.session_state["user"].startswith(users["pasante_user_prefix"])):
            st.session_state["auth"] = st.session_state["user"]
        else:
            st.session_state["auth"] = False

    if "auth" not in st.session_state:
        st.title("CONTROL DE OBRAS 2025")
        st.text_input("Usuario", key="user")
        st.text_input("Contraseña", type="password", key="password")
        st.button("INGRESAR", on_click=password_entered)
        return False

    if not st.session_state["auth"]:
        st.error("Usuario o contraseña incorrecta")
        return False

    return True


if not check_password():
    st.stop()


# =========================
# Obra
# =========================
if st.session_state["auth"] == "jefe":
    obra_actual = st.sidebar.selectbox(
        "Seleccionar obra",
        options=list(OBRAS.keys()),
        format_func=lambda x: OBRAS[x]
    )
else:
    obra_actual = st.session_state["auth"].split("-")[1]
    st.sidebar.success(f"Obra asignada: {OBRAS[obra_actual]}")

if st.sidebar.button("Caja Chica"):
    st.session_state["pagina"] = "caja"


# =========================
# Persistencia local JSON
# =========================
def guardar(obra, datos):
    with open(f"obras/{obra}.json", "w", encoding="utf-8") as f:
        json.dump(datos, f, indent=2, ensure_ascii=False, default=str)


def cargar(obra):
    archivo = f"obras/{obra}.json"
    presupuesto_def = float(PRESUPUESTO_BASE.get(obra, 0.0))

    plantilla = {
        "info": OBRAS[obra],
        "avance": [],
        "presupuesto_total": presupuesto_def,
        "gastos": [],
        "gasto_acumulado": 0.0
    }

    if not os.path.exists(archivo):
        guardar(obra, plantilla)
        return plantilla

    try:
        with open(archivo, "r", encoding="utf-8") as f:
            datos = json.load(f)
    except Exception:
        datos = plantilla

    if not isinstance(datos, dict):
        datos = plantilla

    datos.setdefault("info", OBRAS[obra])
    datos.setdefault("avance", [])
    datos.setdefault("gastos", [])
    datos["presupuesto_total"] = float(PRESUPUESTO_BASE.get(obra, datos.get("presupuesto_total", 0.0) or 0.0))

    # recalcular acumulado
    gasto_acum = 0.0
    for g in datos.get("gastos", []):
        try:
            gasto_acum += float(g.get("monto", 0) or 0)
        except Exception:
            pass
    datos["gasto_acumulado"] = float(gasto_acum)

    guardar(obra, datos)
    return datos


def recalcular_gasto_acumulado(datos_obra):
    gasto_acum = 0.0
    for g in datos_obra.get("gastos", []):
        try:
            gasto_acum += float(g.get("monto", 0) or 0)
        except Exception:
            pass
    datos_obra["gasto_acumulado"] = float(gasto_acum)


datos = cargar(obra_actual)


# =========================
# Semáforo
# =========================
def calcular_totales_gastos(gastos, hoy_str):
    gasto_acumulado = 0.0
    gasto_diario = 0.0
    for g in gastos:
        try:
            m = float(g.get("monto", 0))
        except Exception:
            m = 0.0
        gasto_acumulado += m
        if str(g.get("fecha", "")) == hoy_str:
            gasto_diario += m
    return float(gasto_diario), float(gasto_acumulado)


def semaforo_porcentaje(pct):
    if pct is None:
        return ("#95a5a6", "SIN DATOS")
    if pct <= 95:
        return ("#2ecc71", f"VERDE ({pct:.1f}%)")
    if pct <= 100:
        return ("#f1c40f", f"ÁMBAR ({pct:.1f}%)")
    return ("#e74c3c", f"ROJO ({pct:.1f}%)")


# =========================
# UI
# =========================
st.title(f"Obra: {OBRAS[obra_actual]}")
if st.session_state["auth"] == "jefe":
    st.sidebar.success("MODO JEFE – Acceso total")
else:
    st.sidebar.info("MODO PASANTE – Solo parte diario de hoy")

hoy = date.today()
hoy_str = str(hoy)

presupuesto_total = float(datos.get("presupuesto_total", 0.0))
gastos = datos.get("gastos", [])
gasto_diario, gasto_acumulado = calcular_totales_gastos(gastos, hoy_str)

pct = (gasto_acumulado / presupuesto_total) * 100.0 if presupuesto_total > 0 else None
color, estado = semaforo_porcentaje(pct)

st.subheader("Semáforo de presupuesto (control de rentabilidad)")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Presupuesto total", f"S/ {presupuesto_total:,.2f}" if presupuesto_total > 0 else "—")
c2.metric("Gasto diario (hoy)", f"S/ {gasto_diario:,.2f}")
c3.metric("Gasto acumulado", f"S/ {gasto_acumulado:,.2f}")
c4.metric("% consumido", f"{pct:.1f}%" if pct is not None else "—")

st.markdown(
    f"""
    <div style="display:flex;align-items:center;gap:12px;padding:14px;border:1px solid rgba(255,255,255,0.15);border-radius:12px;">
      <div style="width:18px;height:18px;border-radius:50%;background:{color};box-shadow:0 0 10px {color};"></div>
      <div style="font-size:16px;"><b>{estado}</b></div>
      <div style="opacity:0.8;font-size:14px;">
        &nbsp;| Verde ≤95% &nbsp;| Ámbar 96–100% &nbsp;| Rojo &gt;100%
      </div>
    </div>
    """,
    unsafe_allow_html=True
)

st.divider()

if st.session_state.get("pagina") == "caja":
    st.header("Caja Chica")
    if st.button("Volver"):
        st.session_state["pagina"] = None
        st.rerun()
    mostrar_caja_chica()
    st.stop()

# =========================
# Parte Diario
# =========================
st.header("Parte Diario del Día")

flash_key = f"flash_{obra_actual}"
flash = st.session_state.get(flash_key)
if flash:
    if flash.get("ok"):
        st.success(flash.get("msg", ""))
    else:
        st.warning(flash.get("msg", ""))

    if flash.get("link"):
        st.markdown(f"[Abrir PDF en Google Drive]({flash.get('link')})")

    if flash.get("err"):
        with st.expander("Ver detalle del error"):
            st.code(flash["err"])

    st.session_state[flash_key] = None

base_key = f"{obra_actual}_{hoy_str}"
k_nombre = f"pd_nombre_{base_key}"
k_avance = f"pd_avance_{base_key}"
k_obs = f"pd_obs_{base_key}"
reset_flag_key = f"pd_reset_{base_key}"
uploader_ver_key = f"pd_uploader_ver_{base_key}"

init_state(uploader_ver_key, 0)
init_state(reset_flag_key, False)
init_state(k_nombre, st.session_state.get("user", ""))
init_state(k_obs, "")

def det_key(cat: str) -> str:
    return f"det_{base_key}_{slugify(cat)}"

def mon_key(cat: str) -> str:
    return f"mon_{base_key}_{slugify(cat)}"

if st.session_state.get(reset_flag_key, False):
    for cat in CATEGORIAS_GASTO:
        st.session_state[det_key(cat)] = ""
        st.session_state[mon_key(cat)] = 0.0
    st.session_state[k_nombre] = st.session_state.get("user", "")
    st.session_state[k_obs] = ""
    st.session_state.pop(k_avance, None)
    st.session_state[uploader_ver_key] += 1
    st.session_state[reset_flag_key] = False

responsable = st.text_input("Tu nombre", key=k_nombre)

st.subheader("Gastos del día")
st.caption(f"Fecha actual: {hoy.strftime('%d/%m/%Y')}")

for cat in CATEGORIAS_GASTO:
    init_state(det_key(cat), "")
    init_state(mon_key(cat), 0.0)

    a, b, c = st.columns([2, 6, 2])
    a.write(cat)
    b.text_input("Detalle", key=det_key(cat), label_visibility="collapsed")
    c.number_input("Monto (S/)", key=mon_key(cat), label_visibility="collapsed",
                   min_value=0.0, step=10.0, format="%.2f")

total_hoy = sum(float(st.session_state.get(mon_key(cat), 0.0) or 0.0) for cat in CATEGORIAS_GASTO)
st.metric("Monto total diario", f"S/ {total_hoy:,.2f}")

avance = st.slider("Avance logrado hoy (%)", 0, 30, 5, key=k_avance)
obs = st.text_area("Observaciones", key=k_obs)

fotos_key = f"fotos_{base_key}_v{st.session_state[uploader_ver_key]}"
fotos = st.file_uploader(
    "Fotos del avance (mínimo 3)",
    accept_multiple_files=True,
    type=["jpg", "png", "jpeg"],
    key=fotos_key
)

enviar = st.button("ENVIAR PARTE DIARIO", type="primary")

if enviar:
    if "pasante" in st.session_state["auth"] and (not fotos or len(fotos) < 3):
        st.error("¡Sube mínimo 3 fotos!")
        st.stop()

    # Guardar fotos (para histórico y PDF)
    rutas_fotos = []
    if fotos:
        for f in fotos:
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            ruta = f"obras/fotos/{obra_actual}_{hoy_str}_{timestamp}_{f.name}"
            with open(ruta, "wb") as file:
                file.write(f.getbuffer())
            rutas_fotos.append(ruta)

    # Guardar avance
    datos["avance"].append({
        "fecha": hoy_str,
        "responsable": responsable,
        "avance": int(avance),
        "obs": obs,
        "fotos": rutas_fotos
    })

    # Guardar gastos + tabla para PDF
    gastos_hoy_rows = []
    for cat in CATEGORIAS_GASTO:
        detalle = str(st.session_state.get(det_key(cat), "")).strip()
        monto = float(st.session_state.get(mon_key(cat), 0.0) or 0.0)
        if monto > 0:
            row = {
                "fecha": hoy_str,
                "responsable": st.session_state.get("user", "").strip(),
                "tipo": cat,
                "detalle": detalle,
                "monto": monto
            }
            datos["gastos"].append(row)
            gastos_hoy_rows.append({"tipo": cat, "detalle": detalle, "monto": monto})

    recalcular_gasto_acumulado(datos)
    guardar(obra_actual, datos)

    # Generar PDF + subir por Apps Script
    try:
        obra_name = OBRAS[obra_actual]
        obra_tag = safe_filename(obra_name)
        filename = f"Informe_{obra_tag}_{hoy_str}_ParteDiario.pdf"

        pdf_bytes = generate_parte_diario_pdf_bytes(
            obra_key=obra_actual,
            obra_name=obra_name,
            fecha_str=hoy_str,
            responsable=responsable,
            avance_pct=int(avance),
            obs=obs,
            gastos_rows=gastos_hoy_rows,
            total_gastos_hoy=float(total_hoy),
            rutas_fotos=rutas_fotos
        )

        uploaded = upload_pdf_via_apps_script(pdf_bytes, filename)

        # Soportar varias respuestas posibles del Apps Script
        link = uploaded.get("url") or uploaded.get("webViewLink") or uploaded.get("link")

        st.session_state[flash_key] = {
            "ok": True,
            "msg": "¡Parte diario registrado y PDF subido a Google Drive correctamente!",
            "link": link,
            "err": None
        }

    except Exception:
        st.session_state[flash_key] = {
            "ok": False,
            "msg": "Parte diario registrado, pero falló la subida a Drive.",
            "link": None,
            "err": traceback.format_exc()
        }

    st.session_state[reset_flag_key] = True
    st.rerun()

# =========================
# Historial
# =========================
st.header("Historial de Avances")

avances = datos.get("avance", [])
if not avances:
    st.info("No hay partes diarios registrados para esta obra aún.")
else:
    def _parse_date(s):
        try:
            return datetime.strptime(str(s), "%Y-%m-%d")
        except Exception:
            return datetime.min

    avances_sorted = sorted(avances, key=lambda r: _parse_date(r.get("fecha")), reverse=True)

    for row in avances_sorted:
        fecha_txt = row.get("fecha", "")
        with st.expander(f"Avance del {fecha_txt} - Responsable: {row.get('responsable','')} ({row.get('avance',0)}%)"):
            st.write(f"*Observaciones:* {row.get('obs','')}")
            fotos_row = row.get("fotos", []) or []
            if fotos_row:
                cols = st.columns(min(len(fotos_row), 3))
                for i, foto_path in enumerate(fotos_row):
                    with cols[i % 3]:

                        if os.path.exists(foto_path):
                            st.image(foto_path, caption=os.path.basename(foto_path), use_container_width=True)
                        else:
                            st.warning(f"No se encontró la imagen: {foto_path}")
