# caja_chica.py
import streamlit as st
import pandas as pd
import os
from datetime import datetime

DATA_FILE = "caja_chica/movimientos.csv"
COMPROBANTES_DIR = "caja_chica/comprobantes"

def inicializar_caja():
    os.makedirs(COMPROBANTES_DIR, exist_ok=True)
    if not os.path.exists(DATA_FILE):
        columnas = ["fecha", "usuario", "tipo", "monto", "descripcion", "categoria", "comprobante", "estado", "aprobado_por"]
        pd.DataFrame(columns=columnas).to_csv(DATA_FILE, index=False)

def cargar_movimientos():
    inicializar_caja()
    return pd.read_csv(DATA_FILE)

def guardar_movimiento(mov):
    df = cargar_movimientos()
    df = pd.concat([df, pd.DataFrame([mov])], ignore_index=True)
    df.to_csv(DATA_FILE, index=False)

def calcular_totales():
    df = cargar_movimientos()
    ingresos = df[df["tipo"] == "ingreso"]["monto"].sum()
    egresos_aprobados = df[(df["tipo"] == "egreso") & (df["estado"] == "Aprobado")]["monto"].sum()
    saldo = ingresos - egresos_aprobados
    return ingresos, egresos_aprobados, saldo

def guardar_comprobante(archivo, usuario):
    if not archivo:
        return ""
    ext = os.path.splitext(archivo.name)[1]
    nombre = f"{usuario}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}"
    ruta = os.path.join(COMPROBANTES_DIR, nombre)
    with open(ruta, "wb") as f:
        f.write(archivo.getbuffer())
    return ruta

def mostrar_caja_chica():
    inicializar_caja()
    usuario = st.session_state.get("usuario_logueado", "desconocido")
    es_jefe = st.session_state["auth"] == "jefe"

    # Nombre de la obra arriba
    obra_nombre = st.session_state.get("obra_nombre", "Obra seleccionada")
    st.header(f"Obra: {obra_nombre}")
    st.subheader("Caja Chica")

    # Saldo actual arriba
    ingresos, egresos_aprobados, saldo = calcular_totales()
    st.metric("Saldo actual", f"S/ {saldo:,.2f}", delta_color="normal")

    # Total Ingresos + tabla de ingresos
    st.markdown("### Total Ingresos (reposiciones)")
    st.metric("", f"S/ {ingresos:,.2f}", delta_color="normal")

    df = cargar_movimientos()
    ingresos_df = df[df["tipo"] == "ingreso"]
    if ingresos_df.empty:
        st.info("No hay ingresos registrados aún")
    else:
        st.dataframe(
            ingresos_df[["fecha", "monto", "descripcion", "categoria", "estado", "aprobado_por"]].sort_values("fecha", ascending=False),
            use_container_width=True,
            hide_index=True,
            column_config={"monto": st.column_config.NumberColumn("Monto", format="S/. %.2f")}
        )

    # Total Egresos aprobados + tabla de egresos aprobados
    st.markdown("### Total Egresos aprobados (gastos)")
    st.metric("", f"S/ {egresos_aprobados:,.2f}", delta_color="inverse")

    egresos_aprobados_df = df[(df["tipo"] == "egreso") & (df["estado"] == "Aprobado")]
    if egresos_aprobados_df.empty:
        st.info("No hay egresos aprobados aún")
    else:
        st.dataframe(
            egresos_aprobados_df[["fecha", "monto", "descripcion", "categoria", "estado", "aprobado_por"]].sort_values("fecha", ascending=False),
            use_container_width=True,
            hide_index=True,
            column_config={"monto": st.column_config.NumberColumn("Monto", format="S/. %.2f")}
        )

    # Botón de registrar
    if st.button("Registrar nuevo movimiento"):
        st.session_state["mostrar_form_registro"] = True
        st.rerun()

    if st.session_state.get("mostrar_form_registro", False):
        with st.form("form_registro_caja"):
            tipo = st.radio("Tipo", ["Egreso (gasto)", "Ingreso (reposición)"], horizontal=True)
            tipo_val = "egreso" if "Egreso" in tipo else "ingreso"

            monto = st.number_input("Monto S/.", min_value=0.01, step=0.01, format="%.2f")
            descripcion = st.text_input("Descripción / motivo")
            categoria = st.selectbox("Categoría", [
                "Viáticos", "Transporte", "Materiales menores", "Limpieza/oficina", "Imprevistos", "Otros"
            ])
            comprobante = st.file_uploader("Comprobante (foto/PDF)", type=["jpg", "png", "pdf"])

            col1, col2 = st.columns(2)
            with col1:
                if st.form_submit_button("Registrar"):
                    if monto > 0:
                        ruta = guardar_comprobante(comprobante, usuario) if comprobante else ""
                        mov = {
                            "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
                            "usuario": usuario,
                            "tipo": tipo_val,
                            "monto": monto,
                            "descripcion": descripcion,
                            "categoria": categoria,
                            "comprobante": ruta,
                            "estado": "Aprobado" if tipo_val == "ingreso" else "Pendiente",
                            "aprobado_por": "Sistema" if tipo_val == "ingreso" else ""
                        }
                        guardar_movimiento(mov)
                        st.success("Movimiento registrado correctamente")
                        st.session_state["mostrar_form_registro"] = False
                        st.rerun()
                    else:
                        st.error("El monto debe ser mayor a 0")
            with col2:
                if st.form_submit_button("Cancelar"):
                    st.session_state["mostrar_form_registro"] = False
                    st.rerun()

    # Pestaña Aprobaciones (solo jefe)
    if es_jefe:
        st.subheader("Aprobaciones pendientes")
        pendientes = df[(df["tipo"] == "egreso") & (df["estado"] == "Pendiente")]
        if pendientes.empty:
            st.success("No hay gastos pendientes")
        else:
            for idx, row in pendientes.iterrows():
                with st.expander(f"{row['fecha']} | {row['usuario']} | S/ {row['monto']:.2f}"):
                    st.write("**Descripción:**", row["descripcion"])
                    st.write("**Categoría:**", row["categoria"])
                    if row["comprobante"]:
                        if row["comprobante"].lower().endswith((".jpg", ".png", ".jpeg")):
                            st.image(row["comprobante"], use_column_width=True)
                        else:
                            st.write("📄 Comprobante PDF adjunto")
                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button("Aprobar", key=f"apr_{idx}"):
                            df.loc[idx, "estado"] = "Aprobado"
                            df.loc[idx, "aprobado_por"] = usuario
                            df.to_csv(DATA_FILE, index=False)
                            st.success("Aprobado")
                            st.rerun()
                    with col2:
                        if st.button("Rechazar", key=f"rec_{idx}"):
                            df.loc[idx, "estado"] = "Rechazado"
                            df.to_csv(DATA_FILE, index=False)
                            st.success("Rechazado")
                            st.rerun()
