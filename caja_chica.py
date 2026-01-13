# caja_chica.py
import streamlit as st
import pandas as pd
import os
from datetime import datetime

DATA_FILE = "caja_chica/movimientos.csv"
COMPROBANTES_DIR = "caja_chica/comprobantes"

def init_caja():
    os.makedirs(COMPROBANTES_DIR, exist_ok=True)
    if not os.path.exists(DATA_FILE):
        pd.DataFrame(columns=[
            "fecha", "usuario", "tipo", "monto", "descripcion", 
            "categoria", "comprobante", "estado", "aprobado_por"
        ]).to_csv(DATA_FILE, index=False)

def load_movimientos():
    init_caja()
    return pd.read_csv(DATA_FILE)

def save_movimiento(row):
    df = load_movimientos()
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    df.to_csv(DATA_FILE, index=False)

def get_saldo():
    df = load_movimientos()
    ingresos = df[df["tipo"] == "ingreso"]["monto"].sum()
    egresos = df[(df["tipo"] == "egreso") & (df["estado"] == "Aprobado")]["monto"].sum()
    return ingresos - egresos

def save_comprobante(file, usuario):
    if not file:
        return ""
    ext = os.path.splitext(file.name)[1]
    nombre = f"{usuario}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}"
    path = os.path.join(COMPROBANTES_DIR, nombre)
    with open(path, "wb") as f:
        f.write(file.getbuffer())
    return path

def mostrar_caja():
    init_caja()
    usuario = st.session_state.get("user", "desconocido")
    es_jefe = st.session_state["auth"] == "jefe"

    saldo = get_saldo()
    st.metric("Saldo Caja Chica", f"S/ {saldo:,.2f}")

    tab_reg, tab_mis, tab_apr = st.tabs(["Registrar", "Mis movimientos", "Aprobaciones"])

    with tab_reg:
        with st.form("reg_caja"):
            tipo = st.radio("Tipo", ["Egreso (gasto)", "Ingreso (reposición)"])
            tipo_val = "egreso" if "Egreso" in tipo else "ingreso"

            monto = st.number_input("Monto S/", min_value=0.01, step=0.1)
            desc = st.text_input("Descripción")
            cat = st.selectbox("Categoría", ["Viáticos", "Imprevistos", "Oficina", "Transporte", "Otros"])
            comp = st.file_uploader("Comprobante", type=["jpg","png","pdf"])

            if st.form_submit_button("Registrar"):
                if monto > 0:
                    ruta = save_comprobante(comp, usuario) if comp else ""
                    row = {
                        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "usuario": usuario,
                        "tipo": tipo_val,
                        "monto": monto,
                        "descripcion": desc,
                        "categoria": cat,
                        "comprobante": ruta,
                        "estado": "Pendiente" if tipo_val == "egreso" else "Aprobado",
                        "aprobado_por": "" if tipo_val == "egreso" else "Auto"
                    }
                    save_movimiento(row)
                    st.success("Registrado")
                    st.rerun()

    with tab_mis:
        df = load_movimientos()
        mios = df[df["usuario"] == usuario]
        if mios.empty:
            st.info("Sin movimientos")
        else:
            st.dataframe(mios[["fecha", "tipo", "monto", "descripcion", "estado"]])

    with tab_apr:
        if not es_jefe:
            st.info("Solo jefe")
            return
        df = load_movimientos()
        pend = df[(df["tipo"] == "egreso") & (df["estado"] == "Pendiente")]
        if pend.empty:
            st.success("No hay pendientes")
        else:
            for i, row in pend.iterrows():
                with st.expander(f"{row['fecha']} - {row['usuario']} - S/ {row['monto']}"):
                    st.write(row["descripcion"])
                    st.write(row["categoria"])
                    if row["comprobante"]:
                        if row["comprobante"].endswith((".jpg",".png")):
                            st.image(row["comprobante"])
                    col1, col2 = st.columns(2)
                    if col1.button("Aprobar", key=f"ap_{i}"):
                        df.loc[i, "estado"] = "Aprobado"
                        df.loc[i, "aprobado_por"] = usuario
                        df.to_csv(DATA_FILE, index=False)
                        st.rerun()
                    if col2.button("Rechazar", key=f"re_{i}"):
                        df.loc[i, "estado"] = "Rechazado"
                        df.to_csv(DATA_FILE, index=False)
                        st.rerun()
