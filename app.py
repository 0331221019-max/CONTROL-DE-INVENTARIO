import importlib
import os
import time
import httpx
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from supabase import create_client, Client

import agentes_ia
import correo

# Streamlit no recarga los módulos importados cuando cambian: sin esto, editar
# agentes_ia.py o correo.py deja la versión vieja en memoria y la app falla con ImportError.
# Solo se recarga si el archivo cambió, y las excepciones se consultan como correo.X /
# agentes_ia.X en el momento de usarlas: tras una recarga las clases son objetos nuevos.
def recargar_si_cambio(modulo):
    modificado = os.path.getmtime(modulo.__file__)
    if getattr(modulo, "_modificado", None) not in (None, modificado):
        modulo = importlib.reload(modulo)
    modulo._modificado = modificado


recargar_si_cambio(correo)
recargar_si_cambio(agentes_ia)
from agentes_ia import (  # noqa: E402
    MODELO_POR_DEFECTO, MODELOS_RESPALDO_POR_DEFECTO, ClienteGemini, agente_correos, agente_graficos,
    agente_respuestas, clave_configurada, construir_grafico,
)
from correo import (  # noqa: E402
    SMTP_HOST_POR_DEFECTO, SMTP_PUERTO_POR_DEFECTO, es_clave_app_gmail, separar_destinatarios,
)

# ----------------------------------------------------------------------------
# CONFIGURACIÓN DE SUPABASE
# ----------------------------------------------------------------------------
SUPABASE_URL = "https://xhdasxqdoiqhwfqiaeck.supabase.co"
SUPABASE_KEY = "sb_publishable_9s1D-AG-8cdjHpNxMXtLIQ_OaxFdOJD"

TABLA = "INVENTARIO EMPRESA"

@st.cache_resource
def init_connection() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase = init_connection()


def con_reintento(func, intentos=3, espera=1.0):
    """Reintenta una llamada a Supabase ante cortes de red pasajeros
    (p. ej. una conexión reutilizada que el servidor ya había cerrado)."""
    ultimo_error = None
    for intento in range(intentos):
        try:
            return func()
        except (httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadTimeout) as e:
            ultimo_error = e
            if intento < intentos - 1:
                time.sleep(espera)
    raise ultimo_error

# ----------------------------------------------------------------------------
# CONFIGURACIÓN DE PÁGINA Y ESTILOS (azul, beige, blanco + sidebar oscuro)
# ----------------------------------------------------------------------------
st.set_page_config(
    page_title="Control de Inventario",
    page_icon="💎",
    layout="wide",
)

CUSTOM_CSS = """
<style>
:root {
    --azul: #1E3A5F;
    --azul-claro: #3E6FA8;
    --beige: #F2E8D8;
    --beige-oscuro: #E4D4B8;
    --blanco: #FFFFFF;
    --verde: #2E7D32;
    --rojo: #C0392B;
    --texto-secundario: #6B7280;
    --sidebar-bg: #14161A;
}

.stApp {
    background-color: var(--beige);
}

h1, h2, h3 {
    color: var(--azul);
}

.block-container {
    padding-top: 1.5rem;
    max-width: 1400px;
}

/* Barra lateral de navegación */
section[data-testid="stSidebar"] {
    background-color: var(--sidebar-bg);
}
section[data-testid="stSidebar"] * {
    color: #D7DAE0;
}
section[data-testid="stSidebar"] h3 {
    color: var(--blanco) !important;
}
section[data-testid="stSidebar"] div.stButton > button {
    background-color: transparent;
    color: #C9CDD3;
    border: none;
    text-align: left;
    font-weight: 500;
    padding: 0.55rem 0.9rem;
    border-radius: 8px;
    width: 100%;
}
section[data-testid="stSidebar"] div.stButton > button:hover {
    background-color: rgba(255, 255, 255, 0.08);
    color: var(--blanco);
}
.st-key-nav_activo button {
    background-color: var(--rojo) !important;
    color: var(--blanco) !important;
    font-weight: 700 !important;
}

/* Botones generales (fuera del sidebar) */
div.stButton > button {
    background-color: var(--azul);
    color: var(--blanco);
    border-radius: 8px;
    border: none;
    padding: 0.5rem 1.2rem;
    font-weight: 600;
}
div.stButton > button:hover {
    background-color: var(--azul-claro);
    color: var(--blanco);
}

/* Pestañas */
.stTabs [data-baseweb="tab-list"] {
    gap: 4px;
    background-color: var(--beige-oscuro);
    border-radius: 10px;
    padding: 4px;
}
.stTabs [data-baseweb="tab"] {
    background-color: var(--blanco);
    border-radius: 8px;
    color: var(--azul);
    font-weight: 600;
    padding: 8px 16px;
}
.stTabs [aria-selected="true"] {
    background-color: var(--azul) !important;
    color: var(--blanco) !important;
}

/* Tarjetas KPI (franja superior estilo Zoho) */
.kpi-card {
    background: var(--blanco);
    border: 1px solid var(--beige-oscuro);
    border-radius: 12px;
    padding: 1rem 1.2rem;
    box-shadow: 0 2px 8px rgba(30, 58, 95, 0.06);
}
.kpi-valor {
    font-size: 1.9rem;
    font-weight: 800;
    line-height: 1.1;
}
.kpi-etiqueta {
    color: var(--texto-secundario);
    font-size: 0.78rem;
    font-weight: 600;
    letter-spacing: 0.03em;
    margin-top: 4px;
    text-transform: uppercase;
}

/* Tarjetas del panel principal (contenedores nativos con borde) */
div[data-testid="stVerticalBlockBorderWrapper"] {
    border-radius: 12px !important;
}
.card-label {
    color: var(--texto-secundario);
    font-weight: 700;
    font-size: 0.75rem;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    margin-bottom: 0.7rem;
}

hr {
    border-color: var(--beige-oscuro);
}
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

CATEGORIAS_PRODUCTO = ["Aretes", "Collares", "Pulseras", "Anillos", "Dijes", "Relojes", "Piedras", "Otro"]
CANALES_VENTA = ["Ventas directas", "Online", "Mayorista", "Otro"]
ESTADOS_VENTA = ["Borrador", "Confirmado", "Empaquetado", "Enviado", "Facturado"]
ESTADOS_COMPRA = ["Pedido", "Recibido"]
UMBRAL_STOCK_BAJO = 5

COLUMNAS_VENTAS = ["id", "created_at", "CLIENTE_NOMBRE", "CLIENTE_DNI", "CLIENTE_TELEFONO", "CANAL", "ESTADO", "TOTAL"]
COLUMNAS_VENTA_DETALLE = ["id", "VENTA_ID", "CÓDIGO", "PRODUCTO", "CANTIDAD", "PRECIO_UNITARIO", "TOTAL"]
COLUMNAS_COMPRAS = ["id", "created_at", "PROVEEDOR", "ESTADO", "TOTAL"]
COLUMNAS_COMPRA_DETALLE = ["id", "COMPRA_ID", "CÓDIGO", "PRODUCTO", "CANTIDAD", "COSTO_UNITARIO", "TOTAL"]

# ----------------------------------------------------------------------------
# FUNCIONES DE ACCESO A DATOS
# ----------------------------------------------------------------------------
def obtener_productos() -> pd.DataFrame:
    response = con_reintento(lambda: supabase.table(TABLA).select("*").order('"CÓDIGO"').execute())
    data = response.data
    if not data:
        return pd.DataFrame(columns=["CÓDIGO", "PROVEEDOR", "NOMBRE", "CATEGORÍA", "CANTIDAD", "COSTO", "PRECIO"])
    return pd.DataFrame(data)


def obtener_proveedores() -> list:
    try:
        response = supabase.table("PROVEEDOR").select('"Proveedor"').execute()
        nombres = sorted({fila["Proveedor"] for fila in response.data if fila.get("Proveedor")})
        return nombres
    except Exception:
        return []


def obtener_proveedores_df() -> pd.DataFrame:
    columnas = ["Proveedor", "RUC", "DIRECCION", "TELEFONO"]
    try:
        response = supabase.table("PROVEEDOR").select("*").execute()
        if not response.data:
            return pd.DataFrame(columns=columnas)
        df_prov = pd.DataFrame(response.data)
        for col in columnas:
            if col not in df_prov.columns:
                df_prov[col] = None
        return df_prov.sort_values("Proveedor").reset_index(drop=True)
    except Exception:
        return pd.DataFrame(columns=columnas)


def insertar_producto(codigo, proveedor, nombre, categoria, cantidad, costo, precio):
    payload = {
        "CÓDIGO": codigo,
        "PROVEEDOR": proveedor,
        "NOMBRE": nombre,
        "CATEGORÍA": categoria,
        "CANTIDAD": cantidad,
        "COSTO": costo,
        "PRECIO": precio,
    }
    return supabase.table(TABLA).insert(payload).execute()


def actualizar_producto(codigo, campos: dict):
    return supabase.table(TABLA).update(campos).eq('"CÓDIGO"', codigo).execute()


def eliminar_producto(codigo):
    return supabase.table(TABLA).delete().eq('"CÓDIGO"', codigo).execute()


def insertar_proveedor(nombre, ruc="", direccion="", telefono=""):
    payload = {
        "Proveedor": nombre,
        "RUC": ruc or None,
        "DIRECCION": direccion or None,
        "TELEFONO": telefono or None,
    }
    return supabase.table("PROVEEDOR").insert(payload).execute()


def eliminar_proveedor(proveedor_id):
    return supabase.table("PROVEEDOR").delete().eq("id", proveedor_id).execute()


def ajustar_stock(codigo, delta):
    fila = supabase.table(TABLA).select('"CANTIDAD"').eq('"CÓDIGO"', codigo).execute().data
    if fila:
        nueva_cantidad = max(0, int(fila[0]["CANTIDAD"]) + delta)
        supabase.table(TABLA).update({"CANTIDAD": nueva_cantidad}).eq('"CÓDIGO"', codigo).execute()


def obtener_ventas() -> pd.DataFrame:
    try:
        response = supabase.table("VENTAS").select("*").order("created_at", desc=True).execute()
        if not response.data:
            return pd.DataFrame(columns=COLUMNAS_VENTAS)
        return pd.DataFrame(response.data)
    except Exception:
        return pd.DataFrame(columns=COLUMNAS_VENTAS)


def obtener_venta_detalle(venta_id=None) -> pd.DataFrame:
    try:
        consulta = supabase.table("VENTA_DETALLE").select("*")
        if venta_id is not None:
            consulta = consulta.eq("VENTA_ID", venta_id)
        response = consulta.execute()
        if not response.data:
            return pd.DataFrame(columns=COLUMNAS_VENTA_DETALLE)
        return pd.DataFrame(response.data)
    except Exception:
        return pd.DataFrame(columns=COLUMNAS_VENTA_DETALLE)


def insertar_venta(cliente_nombre, cliente_dni, cliente_telefono, canal, estado, items):
    """items: lista de dicts con codigo, producto, cantidad, precio_unitario."""
    total_venta = round(sum(it["cantidad"] * it["precio_unitario"] for it in items), 2)
    respuesta = supabase.table("VENTAS").insert(
        {
            "CLIENTE_NOMBRE": cliente_nombre or None,
            "CLIENTE_DNI": cliente_dni or None,
            "CLIENTE_TELEFONO": cliente_telefono or None,
            "CANAL": canal,
            "ESTADO": estado,
            "TOTAL": total_venta,
        }
    ).execute()
    venta_id = respuesta.data[0]["id"]

    detalle = [
        {
            "VENTA_ID": venta_id,
            "CÓDIGO": it["codigo"],
            "PRODUCTO": it["producto"],
            "CANTIDAD": it["cantidad"],
            "PRECIO_UNITARIO": it["precio_unitario"],
            "TOTAL": round(it["cantidad"] * it["precio_unitario"], 2),
        }
        for it in items
    ]
    supabase.table("VENTA_DETALLE").insert(detalle).execute()

    if estado != "Borrador":
        for it in items:
            ajustar_stock(it["codigo"], -it["cantidad"])

    return venta_id


def obtener_compras() -> pd.DataFrame:
    try:
        response = supabase.table("COMPRAS").select("*").order("created_at", desc=True).execute()
        if not response.data:
            return pd.DataFrame(columns=COLUMNAS_COMPRAS)
        return pd.DataFrame(response.data)
    except Exception:
        return pd.DataFrame(columns=COLUMNAS_COMPRAS)


def obtener_compra_detalle(compra_id=None) -> pd.DataFrame:
    try:
        consulta = supabase.table("COMPRA_DETALLE").select("*")
        if compra_id is not None:
            consulta = consulta.eq("COMPRA_ID", compra_id)
        response = consulta.execute()
        if not response.data:
            return pd.DataFrame(columns=COLUMNAS_COMPRA_DETALLE)
        return pd.DataFrame(response.data)
    except Exception:
        return pd.DataFrame(columns=COLUMNAS_COMPRA_DETALLE)


def insertar_compra(proveedor, estado, items):
    """items: lista de dicts con codigo, producto, cantidad, costo_unitario."""
    total_compra = round(sum(it["cantidad"] * it["costo_unitario"] for it in items), 2)
    respuesta = supabase.table("COMPRAS").insert(
        {"PROVEEDOR": proveedor, "ESTADO": estado, "TOTAL": total_compra}
    ).execute()
    compra_id = respuesta.data[0]["id"]

    detalle = [
        {
            "COMPRA_ID": compra_id,
            "CÓDIGO": it["codigo"],
            "PRODUCTO": it["producto"],
            "CANTIDAD": it["cantidad"],
            "COSTO_UNITARIO": it["costo_unitario"],
            "TOTAL": round(it["cantidad"] * it["costo_unitario"], 2),
        }
        for it in items
    ]
    supabase.table("COMPRA_DETALLE").insert(detalle).execute()

    if estado == "Recibido":
        for it in items:
            if it["codigo"] is not None:
                ajustar_stock(it["codigo"], it["cantidad"])

    return compra_id


# ----------------------------------------------------------------------------
# COMPONENTES VISUALES
# ----------------------------------------------------------------------------
def tarjeta_kpi(valor, etiqueta, icono, color):
    st.markdown(
        f"""
        <div class="kpi-card">
            <div class="kpi-valor" style="color:{color}">{valor}</div>
            <div class="kpi-etiqueta">{icono} {etiqueta}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def grafico_donut(porcentaje, color="#1E3A5F"):
    fig = go.Figure(
        data=[
            go.Pie(
                values=[porcentaje, max(0, 100 - porcentaje)],
                hole=0.72,
                marker=dict(colors=[color, "#E4D4B8"]),
                textinfo="none",
                sort=False,
                direction="clockwise",
            )
        ]
    )
    fig.update_layout(
        showlegend=False,
        margin=dict(l=0, r=0, t=0, b=0),
        height=150,
        paper_bgcolor="rgba(0,0,0,0)",
        annotations=[
            dict(text=f"{porcentaje:.0f}%", x=0.5, y=0.5, font_size=22, showarrow=False, font_color="#1E3A5F")
        ],
    )
    return fig


# ----------------------------------------------------------------------------
# PÁGINAS
# ----------------------------------------------------------------------------
def pagina_dashboard(df, proveedores, ventas_df, compras_df, compra_detalle_df, venta_detalle_df):
    hay_ventas = not ventas_df.empty

    def _cantidad_en_estados(estados):
        if not hay_ventas or venta_detalle_df.empty:
            return 0
        ids = ventas_df.loc[ventas_df["ESTADO"].isin(estados), "id"]
        if ids.empty:
            return 0
        return int(venta_detalle_df[venta_detalle_df["VENTA_ID"].isin(ids)]["CANTIDAD"].sum())

    por_empaquetar = _cantidad_en_estados(["Confirmado"])
    por_enviar = int((ventas_df["ESTADO"] == "Empaquetado").sum()) if hay_ventas else 0
    por_entregar = int((ventas_df["ESTADO"] == "Enviado").sum()) if hay_ventas else 0
    por_facturar = _cantidad_en_estados(["Confirmado", "Empaquetado", "Enviado"])

    k1, k2, k3, k4 = st.columns(4)
    with k1:
        tarjeta_kpi(por_empaquetar, "Por empaquetar", "📦", "#C0392B")
    with k2:
        tarjeta_kpi(por_enviar, "Por enviar", "🚚", "#1E3A5F")
    with k3:
        tarjeta_kpi(por_entregar, "Por entregar", "✅", "#2E7D32")
    with k4:
        tarjeta_kpi(por_facturar, "Por facturar", "🧾", "#3E6FA8")

    st.write("")
    fila1_izq, fila1_der = st.columns(2)

    with fila1_izq:
        with st.container(border=True):
            st.markdown('<p class="card-label">Detalles de inventario</p>', unsafe_allow_html=True)
            col_txt, col_donut = st.columns([3, 2])
            with col_txt:
                stock_bajo = int((df["CANTIDAD"] < UMBRAL_STOCK_BAJO).sum()) if not df.empty else 0
                color_bajo = "#C0392B" if stock_bajo > 0 else "#1E3A5F"
                st.markdown(
                    f"<p style='margin-bottom:0.4rem'><span style='color:{color_bajo};font-weight:700'>Productos con stock bajo</span><br>{stock_bajo}</p>",
                    unsafe_allow_html=True,
                )
                st.markdown(f"Total de categorías &nbsp; **{df['CATEGORÍA'].nunique() if not df.empty else 0}**")
                st.markdown(f"Total de productos &nbsp; **{len(df)}**")
                st.markdown(f"Proveedores registrados &nbsp; **{len(proveedores)}**")
            with col_donut:
                con_stock = int((df["CANTIDAD"] > 0).sum()) if not df.empty else 0
                pct = (con_stock / len(df) * 100) if len(df) else 0.0
                st.plotly_chart(grafico_donut(pct), use_container_width=True, config={"displayModeBar": False})
                st.caption("Productos con stock disponible")

    with fila1_der:
        with st.container(border=True):
            st.markdown('<p class="card-label">Productos más vendidos</p>', unsafe_allow_html=True)
            if venta_detalle_df.empty:
                st.info("Aún no hay ventas registradas.")
            else:
                top = venta_detalle_df.groupby("PRODUCTO")["CANTIDAD"].sum().sort_values(ascending=False).head(5)
                for nombre_prod, cant in top.items():
                    st.markdown(f"**{nombre_prod}** &nbsp;&nbsp; {int(cant)} unidades vendidas")

    fila2_izq, fila2_der = st.columns(2)

    with fila2_izq:
        with st.container(border=True):
            st.markdown('<p class="card-label">Compras de este mes</p>', unsafe_allow_html=True)
            if compras_df.empty:
                st.info("Aún no hay compras registradas.")
            else:
                fechas = pd.to_datetime(compras_df["created_at"], utc=True)
                ahora = pd.Timestamp.now(tz="UTC")
                compras_mes = compras_df[(fechas.dt.month == ahora.month) & (fechas.dt.year == ahora.year)]
                costo_total = compras_mes["TOTAL"].sum() if not compras_mes.empty else 0.0
                if compra_detalle_df.empty:
                    cantidad_pedida = 0
                else:
                    detalle_mes = compra_detalle_df[compra_detalle_df["COMPRA_ID"].isin(compras_mes["id"])]
                    cantidad_pedida = detalle_mes["CANTIDAD"].sum() if not detalle_mes.empty else 0
                col_a, col_b = st.columns(2)
                with col_a:
                    st.metric("Cantidad pedida", f"{cantidad_pedida:,.0f}")
                with col_b:
                    st.metric("Costo total (S/.)", f"{costo_total:,.2f}")

    with fila2_der:
        with st.container(border=True):
            st.markdown('<p class="card-label">Ventas por canal</p>', unsafe_allow_html=True)
            if not hay_ventas:
                st.info("Aún no hay ventas registradas.")
            else:
                cantidades = venta_detalle_df.groupby("VENTA_ID")["CANTIDAD"].sum().rename("CANTIDAD_TOTAL")
                ventas_con_cantidad = ventas_df.merge(cantidades, left_on="id", right_index=True, how="left")
                ventas_con_cantidad["CANTIDAD_TOTAL"] = ventas_con_cantidad["CANTIDAD_TOTAL"].fillna(0)
                pivote = pd.pivot_table(
                    ventas_con_cantidad, index="CANAL", columns="ESTADO", values="CANTIDAD_TOTAL",
                    aggfunc="sum", fill_value=0,
                )
                st.dataframe(pivote, use_container_width=True)

    st.write("")
    with st.container(border=True):
        st.markdown('<p class="card-label">Unidades por categoría</p>', unsafe_allow_html=True)
        if df.empty:
            st.info("Aún no hay datos suficientes para mostrar el gráfico.")
        else:
            resumen_categoria = df.groupby("CATEGORÍA")["CANTIDAD"].sum().sort_values(ascending=False)
            st.bar_chart(resumen_categoria, color="#1E3A5F")


def pagina_inventario(df, proveedores_existentes):
    with st.container(border=True):
        st.markdown('<p class="card-label">Inventario actual</p>', unsafe_allow_html=True)
        if df.empty:
            st.info("Aún no hay productos registrados en la tabla.")
        else:
            col_cat, col_busq = st.columns(2)
            with col_cat:
                categorias = ["Todas"] + sorted(df["CATEGORÍA"].dropna().unique().tolist())
                cat_sel = st.selectbox("Filtrar por categoría", categorias)
            with col_busq:
                busqueda = st.text_input("Buscar por nombre o proveedor")

            df_vista = df if cat_sel == "Todas" else df[df["CATEGORÍA"] == cat_sel]
            if busqueda:
                mascara = df_vista["NOMBRE"].str.contains(busqueda, case=False, na=False) | df_vista[
                    "PROVEEDOR"
                ].str.contains(busqueda, case=False, na=False)
                df_vista = df_vista[mascara]
            st.dataframe(df_vista, use_container_width=True, hide_index=True)

    st.write("")
    with st.container(border=True):
        sub_agregar, sub_editar, sub_eliminar = st.tabs(["➕ Agregar", "✏️ Editar", "🗑️ Eliminar"])

        with sub_agregar:
            st.markdown("**Registrar nuevo producto**")
            with st.form("form_agregar", clear_on_submit=True):
                codigo = st.number_input("Código", min_value=1, step=1)
                if proveedores_existentes:
                    proveedor = st.selectbox("Proveedor", proveedores_existentes + ["Otro (escribir abajo)"])
                    if proveedor == "Otro (escribir abajo)":
                        proveedor = st.text_input("Nombre del nuevo proveedor")
                else:
                    proveedor = st.text_input("Proveedor")
                nombre = st.text_input("Nombre del producto")
                categoria = st.selectbox("Categoría", CATEGORIAS_PRODUCTO)
                cantidad = st.number_input("Cantidad", min_value=0, step=1)
                costo = st.number_input("Costo (S/.)", min_value=0.0, step=0.1, format="%.2f")
                precio = st.number_input("Precio (S/.)", min_value=0.0, step=0.1, format="%.2f")

                enviado = st.form_submit_button("Guardar producto")
                if enviado:
                    if not nombre or not proveedor:
                        st.error("Completa al menos el proveedor y el nombre del producto.")
                    else:
                        try:
                            insertar_producto(int(codigo), proveedor, nombre, categoria, int(cantidad), float(costo), float(precio))
                            st.success(f"Producto '{nombre}' agregado correctamente.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error al insertar: {e}")

        with sub_editar:
            st.markdown("**Editar producto existente**")
            if df.empty:
                st.info("No hay productos para editar.")
            else:
                codigo_editar = st.selectbox("Selecciona el código a editar", df["CÓDIGO"].tolist(), key="sel_editar")
                fila = df[df["CÓDIGO"] == codigo_editar].iloc[0]

                with st.form("form_editar"):
                    proveedor_e = st.text_input("Proveedor", value=fila["PROVEEDOR"] or "")
                    nombre_e = st.text_input("Nombre", value=fila["NOMBRE"] or "")
                    idx_cat = CATEGORIAS_PRODUCTO.index(fila["CATEGORÍA"]) if fila["CATEGORÍA"] in CATEGORIAS_PRODUCTO else 0
                    categoria_e = st.selectbox("Categoría", CATEGORIAS_PRODUCTO, index=idx_cat)
                    cantidad_e = st.number_input("Cantidad", min_value=0, step=1, value=int(fila["CANTIDAD"]))
                    costo_e = st.number_input("Costo (S/.)", min_value=0.0, step=0.1, format="%.2f", value=float(fila["COSTO"]))
                    precio_e = st.number_input("Precio (S/.)", min_value=0.0, step=0.1, format="%.2f", value=float(fila["PRECIO"]))

                    guardar = st.form_submit_button("Actualizar producto")
                    if guardar:
                        campos = {
                            "PROVEEDOR": proveedor_e,
                            "NOMBRE": nombre_e,
                            "CATEGORÍA": categoria_e,
                            "CANTIDAD": int(cantidad_e),
                            "COSTO": float(costo_e),
                            "PRECIO": float(precio_e),
                        }
                        try:
                            actualizar_producto(int(codigo_editar), campos)
                            st.success(f"Producto con código {codigo_editar} actualizado.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error al actualizar: {e}")

        with sub_eliminar:
            st.markdown("**Eliminar producto**")
            if df.empty:
                st.info("No hay productos para eliminar.")
            else:
                codigo_eliminar = st.selectbox("Selecciona el código a eliminar", df["CÓDIGO"].tolist(), key="sel_eliminar")
                fila_del = df[df["CÓDIGO"] == codigo_eliminar].iloc[0]
                st.warning(f"Vas a eliminar: **{fila_del['NOMBRE']}** ({fila_del['PROVEEDOR']})")

                confirmar = st.checkbox("Confirmo que quiero eliminar este producto")
                if st.button("Eliminar definitivamente", disabled=not confirmar):
                    try:
                        eliminar_producto(int(codigo_eliminar))
                        st.success(f"Producto con código {codigo_eliminar} eliminado.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error al eliminar: {e}")


def pagina_ventas(df, ventas_df, venta_detalle_df):
    sub_registrar, sub_historial = st.tabs(["🧾 Registrar venta", "📜 Historial"])

    with sub_registrar:
        if "items_venta" not in st.session_state:
            st.session_state.items_venta = []

        with st.container(border=True):
            st.markdown('<p class="card-label">Datos del cliente</p>', unsafe_allow_html=True)
            col1, col2, col3 = st.columns(3)
            with col1:
                cliente_nombre = st.text_input("Nombre del cliente", key="cliente_nombre")
            with col2:
                cliente_dni = st.text_input("DNI", key="cliente_dni")
            with col3:
                cliente_telefono = st.text_input("Teléfono", key="cliente_telefono")
            col4, col5 = st.columns(2)
            with col4:
                canal = st.selectbox("Canal de venta", CANALES_VENTA, key="canal_venta")
            with col5:
                estado = st.selectbox("Estado", ESTADOS_VENTA, index=1, key="estado_venta")

        st.write("")
        with st.container(border=True):
            st.markdown('<p class="card-label">Agregar producto a la venta</p>', unsafe_allow_html=True)
            if df.empty:
                st.info("No hay productos en el inventario para vender.")
            else:
                opciones = {f'{int(fila["CÓDIGO"])} - {fila["NOMBRE"]}': fila for _, fila in df.iterrows()}
                col1, col2, col3, col4 = st.columns([3, 1, 1.3, 1])
                with col1:
                    seleccion = st.selectbox("Producto", list(opciones.keys()), key="producto_venta_agregar")
                fila_sel = opciones[seleccion]
                stock_disponible = int(fila_sel["CANTIDAD"])
                ya_en_carrito = sum(
                    it["cantidad"] for it in st.session_state.items_venta if it["codigo"] == int(fila_sel["CÓDIGO"])
                )
                disponible_real = max(stock_disponible - ya_en_carrito, 0)
                with col2:
                    cantidad_add = st.number_input(
                        "Cantidad", min_value=1, max_value=max(disponible_real, 1), step=1, key="cantidad_venta_agregar"
                    )
                with col3:
                    precio_add = st.number_input(
                        "Precio unit. (S/.)", min_value=0.0, step=0.1, format="%.2f",
                        value=float(fila_sel["PRECIO"]), key="precio_venta_agregar",
                    )
                with col4:
                    st.write("")
                    st.write("")
                    if st.button("➕ Agregar", key="btn_agregar_item_venta"):
                        if cantidad_add > disponible_real:
                            st.error("La cantidad supera el stock disponible.")
                        else:
                            st.session_state.items_venta.append(
                                {
                                    "codigo": int(fila_sel["CÓDIGO"]),
                                    "producto": fila_sel["NOMBRE"],
                                    "cantidad": int(cantidad_add),
                                    "precio_unitario": float(precio_add),
                                }
                            )
                            st.rerun()
                extra = f" ({ya_en_carrito} ya en esta venta)" if ya_en_carrito else ""
                st.caption(f"Stock disponible: {stock_disponible} unidades{extra}")

        st.write("")
        with st.container(border=True):
            st.markdown('<p class="card-label">Productos en esta venta</p>', unsafe_allow_html=True)
            if not st.session_state.items_venta:
                st.info("Agrega al menos un producto para poder registrar la venta.")
            else:
                total_general = 0.0
                encabezado = st.columns([3, 1, 1.3, 1.3, 0.6])
                encabezado[0].markdown("**Producto**")
                encabezado[1].markdown("**Cant.**")
                encabezado[2].markdown("**Precio unit.**")
                encabezado[3].markdown("**Subtotal**")

                for idx, item in enumerate(st.session_state.items_venta):
                    subtotal = item["cantidad"] * item["precio_unitario"]
                    total_general += subtotal
                    fila_cols = st.columns([3, 1, 1.3, 1.3, 0.6])
                    fila_cols[0].write(item["producto"])
                    fila_cols[1].write(item["cantidad"])
                    fila_cols[2].write(f"S/. {item['precio_unitario']:.2f}")
                    fila_cols[3].write(f"S/. {subtotal:.2f}")
                    if fila_cols[4].button("🗑️", key=f"quitar_item_venta_{idx}"):
                        st.session_state.items_venta.pop(idx)
                        st.rerun()

                st.markdown(f"**Total de la venta: S/. {total_general:,.2f}**")

                if st.button("Registrar venta completa", key="btn_registrar_venta"):
                    try:
                        insertar_venta(
                            cliente_nombre.strip(), cliente_dni.strip(), cliente_telefono.strip(),
                            canal, estado, st.session_state.items_venta,
                        )
                        st.session_state.items_venta = []
                        st.success("Venta registrada correctamente.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error al registrar la venta: {e}")

    with sub_historial:
        with st.container(border=True):
            if ventas_df.empty:
                st.info("Aún no hay ventas registradas.")
            else:
                st.dataframe(
                    ventas_df.drop(columns=["id"], errors="ignore").rename(
                        columns={"CLIENTE_NOMBRE": "Cliente", "CLIENTE_DNI": "DNI", "CLIENTE_TELEFONO": "Teléfono"}
                    ),
                    use_container_width=True,
                    hide_index=True,
                )

                st.markdown("##### Detalle de una venta")
                venta_sel = st.selectbox("Selecciona una venta (por id)", ventas_df["id"].tolist(), key="sel_venta_detalle")
                detalle_sel = (
                    venta_detalle_df[venta_detalle_df["VENTA_ID"] == venta_sel]
                    if not venta_detalle_df.empty
                    else venta_detalle_df
                )
                if detalle_sel.empty:
                    st.info("Esta venta no tiene productos registrados.")
                else:
                    st.dataframe(
                        detalle_sel.drop(columns=["id", "VENTA_ID"], errors="ignore"),
                        use_container_width=True,
                        hide_index=True,
                    )


def pagina_compras(df, proveedores_existentes, compras_df, compra_detalle_df, proveedores_df):
    sub_registrar, sub_historial = st.tabs(["🧾 Registrar compra", "📜 Historial"])

    with sub_registrar:
        if "items_compra" not in st.session_state:
            st.session_state.items_compra = []

        with st.container(border=True):
            st.markdown('<p class="card-label">Datos de la compra</p>', unsafe_allow_html=True)
            if proveedores_existentes:
                proveedor_c = st.selectbox("Proveedor", proveedores_existentes + ["Otro (escribir abajo)"], key="prov_compra")
                if proveedor_c == "Otro (escribir abajo)":
                    proveedor_c = st.text_input("Nombre del proveedor", key="prov_compra_otro")
                else:
                    fila_prov = proveedores_df[proveedores_df["Proveedor"] == proveedor_c]
                    if not fila_prov.empty:
                        fp = fila_prov.iloc[0]
                        detalles = []
                        if fp.get("RUC"):
                            detalles.append(f"RUC: {fp['RUC']}")
                        if fp.get("DIRECCION"):
                            detalles.append(f"Dirección: {fp['DIRECCION']}")
                        if fp.get("TELEFONO"):
                            detalles.append(f"Teléfono: {fp['TELEFONO']}")
                        if detalles:
                            st.caption(" · ".join(detalles))
                        else:
                            st.caption("Este proveedor no tiene RUC, dirección ni teléfono registrados todavía.")
            else:
                proveedor_c = st.text_input("Proveedor", key="prov_compra_txt")
            estado_c = st.selectbox("Estado de la compra", ESTADOS_COMPRA, key="estado_compra")

        st.write("")
        with st.container(border=True):
            st.markdown('<p class="card-label">Agregar producto a la compra</p>', unsafe_allow_html=True)
            if df.empty:
                st.info("No hay productos registrados en el inventario para agregar.")
            else:
                opciones_c = {f'{int(fila["CÓDIGO"])} - {fila["NOMBRE"]}': fila for _, fila in df.iterrows()}
                col1, col2, col3, col4 = st.columns([3, 1, 1.3, 1])
                with col1:
                    seleccion_c = st.selectbox("Producto", list(opciones_c.keys()), key="producto_a_agregar")
                fila_c = opciones_c[seleccion_c]
                with col2:
                    cantidad_add = st.number_input("Cantidad", min_value=1, step=1, key="cantidad_a_agregar")
                with col3:
                    costo_add = st.number_input(
                        "Costo unit. (S/.)", min_value=0.0, step=0.1, format="%.2f",
                        value=float(fila_c["COSTO"]), key="costo_a_agregar",
                    )
                with col4:
                    st.write("")
                    st.write("")
                    if st.button("➕ Agregar", key="btn_agregar_item"):
                        st.session_state.items_compra.append(
                            {
                                "codigo": int(fila_c["CÓDIGO"]),
                                "producto": fila_c["NOMBRE"],
                                "cantidad": int(cantidad_add),
                                "costo_unitario": float(costo_add),
                            }
                        )
                        st.rerun()

        st.write("")
        with st.container(border=True):
            st.markdown('<p class="card-label">Productos en esta compra</p>', unsafe_allow_html=True)
            if not st.session_state.items_compra:
                st.info("Agrega al menos un producto para poder registrar la compra.")
            else:
                total_general = 0.0
                encabezado = st.columns([3, 1, 1.3, 1.3, 0.6])
                encabezado[0].markdown("**Producto**")
                encabezado[1].markdown("**Cant.**")
                encabezado[2].markdown("**Costo unit.**")
                encabezado[3].markdown("**Subtotal**")

                for idx, item in enumerate(st.session_state.items_compra):
                    subtotal = item["cantidad"] * item["costo_unitario"]
                    total_general += subtotal
                    fila_cols = st.columns([3, 1, 1.3, 1.3, 0.6])
                    fila_cols[0].write(item["producto"])
                    fila_cols[1].write(item["cantidad"])
                    fila_cols[2].write(f"S/. {item['costo_unitario']:.2f}")
                    fila_cols[3].write(f"S/. {subtotal:.2f}")
                    if fila_cols[4].button("🗑️", key=f"quitar_item_{idx}"):
                        st.session_state.items_compra.pop(idx)
                        st.rerun()

                st.markdown(f"**Total de la compra: S/. {total_general:,.2f}**")

                if st.button("Registrar compra completa", key="btn_registrar_compra"):
                    if not proveedor_c:
                        st.error("Indica el proveedor de la compra.")
                    else:
                        try:
                            insertar_compra(proveedor_c, estado_c, st.session_state.items_compra)
                            st.session_state.items_compra = []
                            st.success("Compra registrada correctamente.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error al registrar la compra: {e}")

    with sub_historial:
        with st.container(border=True):
            if compras_df.empty:
                st.info("Aún no hay compras registradas.")
            else:
                st.dataframe(compras_df.drop(columns=["id"], errors="ignore"), use_container_width=True, hide_index=True)

                st.markdown("##### Detalle de una compra")
                compra_sel = st.selectbox("Selecciona una compra (por id)", compras_df["id"].tolist(), key="sel_compra_detalle")
                detalle_sel = compra_detalle_df[compra_detalle_df["COMPRA_ID"] == compra_sel] if not compra_detalle_df.empty else compra_detalle_df
                if detalle_sel.empty:
                    st.info("Esta compra no tiene productos registrados.")
                else:
                    st.dataframe(
                        detalle_sel.drop(columns=["id", "COMPRA_ID"], errors="ignore"),
                        use_container_width=True,
                        hide_index=True,
                    )


def pagina_proveedores(proveedores_df):
    with st.container(border=True):
        st.markdown("**Registrar nuevo proveedor**")
        with st.form("form_proveedor", clear_on_submit=True):
            nombre_proveedor = st.text_input("Nombre del proveedor")
            ruc_proveedor = st.text_input("RUC")
            direccion_proveedor = st.text_input("Dirección")
            telefono_proveedor = st.text_input("Teléfono")
            enviado_proveedor = st.form_submit_button("Guardar proveedor")
            if enviado_proveedor:
                if not nombre_proveedor.strip():
                    st.error("Escribe un nombre de proveedor.")
                else:
                    try:
                        insertar_proveedor(
                            nombre_proveedor.strip(),
                            ruc_proveedor.strip(),
                            direccion_proveedor.strip(),
                            telefono_proveedor.strip(),
                        )
                        st.success(f"Proveedor '{nombre_proveedor}' agregado correctamente.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error al insertar proveedor: {e}")

        st.markdown("##### Proveedores registrados")
        if not proveedores_df.empty:
            st.dataframe(
                proveedores_df.rename(columns={"DIRECCION": "Dirección", "TELEFONO": "Teléfono"}),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("Aún no hay proveedores registrados.")

    st.write("")
    with st.container(border=True):
        st.markdown('<p class="card-label">Eliminar proveedor</p>', unsafe_allow_html=True)
        if proveedores_df.empty:
            st.info("No hay proveedores para eliminar.")
        else:
            opciones_eliminar = {
                f'{fila["Proveedor"]} (id {fila["id"]})': fila["id"] for _, fila in proveedores_df.iterrows()
            }
            seleccion_eliminar = st.selectbox(
                "Selecciona el proveedor a eliminar", list(opciones_eliminar.keys()), key="sel_prov_eliminar"
            )
            confirmar_prov = st.checkbox("Confirmo que quiero eliminar este proveedor", key="chk_prov_eliminar")
            if st.button("Eliminar proveedor definitivamente", disabled=not confirmar_prov, key="btn_prov_eliminar"):
                try:
                    eliminar_proveedor(opciones_eliminar[seleccion_eliminar])
                    st.success("Proveedor eliminado correctamente.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al eliminar el proveedor: {e}")


# ----------------------------------------------------------------------------
# ASISTENTE IA (dos agentes: uno responde, otro grafica)
# ----------------------------------------------------------------------------
# Lógica de los agentes en agentes_ia.py (especificación en specs/asistente-ia/).
def leer_config(nombre, por_defecto):
    try:
        if nombre in st.secrets:
            return str(st.secrets[nombre]).strip()
    except Exception:
        pass
    return os.environ.get(nombre, por_defecto).strip()


def aviso_respaldo(cliente) -> str:
    """Nota cuando respondió un modelo de respaldo (R5.8)."""
    if cliente.ultimo_modelo != cliente.modelo:
        return f"Respondido con {cliente.ultimo_modelo} porque {cliente.modelo} no estaba disponible (saturado o sin cuota)."
    return ""


def mostrar_error_ia(error, agente, modelo):
    ia = agentes_ia  # clases vigentes tras una recarga (ver recargar_si_cambio)
    if isinstance(error, ia.ClaveInvalida):
        st.error("La clave de Gemini no es válida. Revisa `GEMINI_API_KEY` en `.streamlit/secrets.toml`.")
    elif isinstance(error, ia.ServicioSaturado):
        st.error("Gemini está saturado en este momento (también los modelos de respaldo). "
                 "Vuelve a intentar en unos minutos.")
    elif isinstance(error, ia.LimiteAlcanzado):
        st.error("Se alcanzó el límite gratuito de Gemini. Espera un minuto o vuelve a intentar mañana.")
    elif isinstance(error, ia.ModeloNoDisponible):
        st.error(f"El modelo `{modelo}` no existe. Cambia `GEMINI_MODEL` en `.streamlit/secrets.toml`.")
    elif isinstance(error, ia.SinConexion):
        st.error("No hay conexión con Google. Revisa tu internet y vuelve a intentar.")
    elif isinstance(error, ia.TiempoAgotado):
        st.error("Gemini tardó demasiado en responder. Vuelve a intentar.")
    else:
        st.error(f"Error del {agente}: {error}")


def pagina_asistente(datos: dict):
    clave = leer_config("GEMINI_API_KEY", "")
    modelo = leer_config("GEMINI_MODEL", MODELO_POR_DEFECTO)
    if not clave_configurada(clave):
        st.warning(
            "El asistente usa **Google Gemini** (plan gratuito). Falta tu clave:\n\n"
            "1. Entra a https://aistudio.google.com/apikey con tu cuenta de Google.\n"
            "2. Pulsa **Create API key** y copia la clave (no pide tarjeta).\n"
            "3. Abre `.streamlit/secrets.toml` (en la carpeta del proyecto) y pégala en "
            "`GEMINI_API_KEY = \"...\"`.\n"
            "4. Guarda el archivo y pulsa 🔄 Actualizar."
        )
        return
    # Sin caché: crear el cliente es instantáneo y así siempre usa la clase recién recargada.
    respaldos_txt = leer_config("GEMINI_MODELOS_RESPALDO", ",".join(MODELOS_RESPALDO_POR_DEFECTO))
    respaldos = [m.strip() for m in respaldos_txt.split(",") if m.strip()]
    cliente = ClienteGemini(clave, modelo, respaldos=respaldos)
    st.caption(
        f"IA: **{modelo}** (Google Gemini, plan gratuito). "
        "En el plan gratuito Google puede usar los datos enviados para mejorar sus productos."
    )

    sub_respuestas, sub_graficos, sub_correos = st.tabs(
        ["💬 Agente de respuestas", "📈 Agente de gráficos", "✉️ Agente de correos"]
    )

    with sub_respuestas:
        if "chat_ia" not in st.session_state:
            st.session_state.chat_ia = []

        with st.container(border=True):
            st.markdown('<p class="card-label">Pregunta sobre tu inventario, ventas y compras</p>', unsafe_allow_html=True)
            if not st.session_state.chat_ia:
                st.caption("Ejemplos: ¿Qué productos tienen stock bajo? · ¿Cuánto vendí este mes? · ¿Qué proveedor me vende más caro?")
            for mensaje in st.session_state.chat_ia:
                with st.chat_message(mensaje["role"], avatar="🧑" if mensaje["role"] == "user" else "💎"):
                    st.markdown(mensaje["content"])

            with st.form("form_chat_ia", clear_on_submit=True):
                pregunta = st.text_area("Tu pregunta", height=80, label_visibility="collapsed",
                                        placeholder="Escribe tu pregunta...")
                col_env, col_limpiar = st.columns([1, 1])
                enviar = col_env.form_submit_button("Preguntar")
                limpiar = col_limpiar.form_submit_button("Limpiar conversación")

            if limpiar:
                st.session_state.chat_ia = []
                st.rerun()
            if enviar and pregunta.strip():
                historial = st.session_state.chat_ia + [{"role": "user", "content": pregunta.strip()}]
                try:
                    with st.spinner("El agente de respuestas está analizando tus datos..."):
                        respuesta = agente_respuestas(cliente, datos, historial)
                    if aviso_respaldo(cliente):
                        respuesta += f"\n\n_{aviso_respaldo(cliente)}_"
                    st.session_state.chat_ia = historial + [{"role": "assistant", "content": respuesta}]
                    st.rerun()
                except Exception as e:
                    mostrar_error_ia(e, "agente de respuestas", modelo)

    with sub_graficos:
        with st.container(border=True):
            st.markdown('<p class="card-label">Describe el gráfico que quieres ver</p>', unsafe_allow_html=True)
            st.caption("Ejemplos: Ventas totales por mes · Top 5 productos más vendidos · Stock por categoría en torta")
            with st.form("form_grafico_ia"):
                pedido = st.text_input("Pedido", label_visibility="collapsed", placeholder="¿Qué quieres graficar?")
                generar = st.form_submit_button("Generar gráfico")
            if generar and pedido.strip():
                try:
                    with st.spinner("El agente de gráficos está diseñando tu gráfico..."):
                        st.session_state.grafico_ia = agente_graficos(cliente, datos, pedido.strip())
                    if aviso_respaldo(cliente):
                        st.caption(aviso_respaldo(cliente))
                except Exception as e:
                    mostrar_error_ia(e, "agente de gráficos", modelo)

        spec = st.session_state.get("grafico_ia")
        if spec:
            st.write("")
            with st.container(border=True):
                try:
                    fig, resumen = construir_grafico(spec, datos)
                    st.plotly_chart(fig, use_container_width=True)
                    st.caption(spec["explicacion"])
                    with st.expander("Ver datos del gráfico"):
                        st.dataframe(resumen, use_container_width=True, hide_index=True)
                except Exception as e:
                    st.error(f"No se pudo construir el gráfico: {e}. Prueba a reformular tu pedido.")

    with sub_correos:
        pagina_correos(cliente, datos, modelo)


def config_correo() -> dict:
    return {
        "remitente": leer_config("EMAIL_REMITENTE", ""),
        "clave_app": leer_config("EMAIL_CLAVE_APP", "").replace(" ", ""),
        "nombre": leer_config("EMAIL_NOMBRE", ""),
        "host": leer_config("EMAIL_SMTP_HOST", SMTP_HOST_POR_DEFECTO),
        "puerto": leer_config("EMAIL_SMTP_PUERTO", str(SMTP_PUERTO_POR_DEFECTO)),
        # R7.16: en la versión publicada se define como false para que nadie envíe desde el Gmail.
        "habilitado": leer_config("EMAIL_ENVIO_HABILITADO", "true").lower() not in ("false", "0", "no"),
    }


def correo_configurado(config: dict) -> bool:
    return bool(config["remitente"]) and clave_configurada(config["clave_app"])


def clave_gmail_mal_formada(config: dict) -> bool:
    """R7.14: Gmail exige una contraseña de aplicación de 16 letras."""
    return (correo_configurado(config) and config["host"] == SMTP_HOST_POR_DEFECTO
            and not es_clave_app_gmail(config["clave_app"]))


def enviar_borrador():
    """Se ejecuta al pulsar "Enviar correo", antes de redibujar la página (R7.3)."""
    para = correo.separar_destinatarios(st.session_state.get("correo_para", ""))
    asunto = st.session_state.get("correo_asunto", "")
    cuerpo = st.session_state.get("correo_cuerpo", "")
    config = config_correo()
    # La configuración se vuelve a revisar al pulsar: la página pudo quedar abierta desde antes.
    if not config["habilitado"]:
        st.session_state.correo_resultado = ("error", "El envío de correos está desactivado en esta versión.")
        return
    if not correo_configurado(config):
        st.session_state.correo_resultado = ("error", "Falta configurar tu Gmail en `.streamlit/secrets.toml`.")
        return
    # Las clases se buscan en el módulo al momento de usarlas (ver recargar_si_cambio).
    try:
        correo.enviar_correo(config, para, asunto, cuerpo)
    except ValueError as e:
        st.session_state.correo_resultado = ("error", str(e))
    except correo.CredencialesCorreoInvalidas as e:
        st.session_state.correo_resultado = (
            "error",
            f"{e} `EMAIL_CLAVE_APP` debe ser una contraseña de aplicación de 16 letras, no tu contraseña "
            "normal. Créala en https://myaccount.google.com/apppasswords",
        )
    except correo.ErrorCorreo as e:
        st.session_state.correo_resultado = ("error", str(e))
    except Exception as e:  # nunca mostrar la pantalla roja de Streamlit por un envío fallido
        st.session_state.correo_resultado = ("error", f"No se pudo enviar el correo: {e}")
    else:
        st.session_state.correos_enviados.append({"Para": ", ".join(para), "Asunto": asunto,
                                                  "Hora": time.strftime("%H:%M")})
        st.session_state.correo_resultado = ("ok", f"Correo enviado a {', '.join(para)}.")
        for clave in ("correo_para", "correo_asunto", "correo_cuerpo", "correo_nota"):
            st.session_state.pop(clave, None)


def pagina_correos(cliente, datos: dict, modelo: str):
    config = config_correo()
    clave_mal = clave_gmail_mal_formada(config)
    configurado = config["habilitado"] and correo_configurado(config) and not clave_mal
    st.session_state.setdefault("correos_enviados", [])

    if not config["habilitado"]:
        st.info(
            "En esta versión publicada el agente **redacta borradores**, pero el **envío está desactivado**. "
            "Copia el texto del borrador y envíalo desde tu correo."
        )
    elif clave_mal:
        st.warning(
            "`EMAIL_CLAVE_APP` no parece una **contraseña de aplicación** de Google. Esa contraseña tiene "
            "**16 letras** (ej. `abcd efgh ijkl mnop`) y **no es tu contraseña normal de Gmail**.\n\n"
            "Créala en https://myaccount.google.com/apppasswords (requiere la verificación en 2 pasos), "
            "pégala en `.streamlit/secrets.toml`, guarda y pulsa 🔄 Actualizar."
        )

    elif not correo_configurado(config):
        st.info(
            "Puedes redactar borradores, pero para **enviar** falta configurar tu Gmail:\n\n"
            "1. Activa la verificación en 2 pasos en https://myaccount.google.com/security\n"
            "2. Crea una contraseña de aplicación en https://myaccount.google.com/apppasswords\n"
            "3. En `.streamlit/secrets.toml` completa `EMAIL_REMITENTE` (tu Gmail) y "
            "`EMAIL_CLAVE_APP` (los 16 caracteres).\n"
            "4. Guarda y pulsa 🔄 Actualizar."
        )

    with st.container(border=True):
        st.markdown('<p class="card-label">¿Qué correo quieres enviar?</p>', unsafe_allow_html=True)
        st.caption(
            "Escribe la dirección del destinatario en tu pedido. Ejemplos: Envía a proveedor@correo.com un pedido "
            "de reposición de los productos con stock bajo · Manda a jefe@correo.com el resumen de ventas del mes"
        )
        with st.form("form_correo_ia"):
            pedido = st.text_area("Pedido", height=80, label_visibility="collapsed",
                                  placeholder="Describe el correo e incluye el correo del destinatario...")
            redactar = st.form_submit_button("Redactar borrador")
        if redactar and pedido.strip():
            try:
                with st.spinner("El agente de correos está redactando el borrador..."):
                    borrador = agente_correos(cliente, datos, pedido.strip(), config["nombre"])
                if aviso_respaldo(cliente):
                    borrador["nota"] = f"{borrador['nota']} {aviso_respaldo(cliente)}".strip()
                st.session_state.correo_para = ", ".join(borrador["para"])
                st.session_state.correo_asunto = borrador["asunto"]
                st.session_state.correo_cuerpo = borrador["cuerpo"]
                st.session_state.correo_nota = borrador["nota"]
                st.session_state.pop("correo_resultado", None)
            except Exception as e:
                mostrar_error_ia(e, "agente de correos", modelo)

    resultado = st.session_state.pop("correo_resultado", None)
    if resultado:
        (st.success if resultado[0] == "ok" else st.error)(resultado[1])

    if "correo_asunto" in st.session_state:
        st.write("")
        with st.container(border=True):
            st.markdown('<p class="card-label">Borrador — revísalo antes de enviar</p>', unsafe_allow_html=True)
            if st.session_state.get("correo_nota"):
                st.warning(st.session_state.correo_nota)
            st.text_input("Para (separa varias direcciones con comas)", key="correo_para")
            st.text_input("Asunto", key="correo_asunto")
            st.text_area("Mensaje", key="correo_cuerpo", height=280)
            if config["remitente"]:
                st.caption(f"Se enviará desde: {config['remitente']}")
            st.button("📨 Enviar correo", key="btn_enviar_correo", on_click=enviar_borrador,
                      disabled=not configurado)

    if st.session_state.correos_enviados:
        st.write("")
        with st.container(border=True):
            st.markdown('<p class="card-label">Correos enviados en esta sesión</p>', unsafe_allow_html=True)
            st.dataframe(pd.DataFrame(st.session_state.correos_enviados), use_container_width=True, hide_index=True)


# ----------------------------------------------------------------------------
# NAVEGACIÓN LATERAL
# ----------------------------------------------------------------------------
PAGINAS = [
    ("Dashboard", "📊", "Panel de información"),
    ("Inventario", "📦", "Inventario"),
    ("Ventas", "🛒", "Ventas"),
    ("Compras", "🧾", "Compras"),
    ("Proveedores", "🚚", "Proveedores"),
    ("Asistente", "🤖", "Asistente IA"),
]

if "pagina" not in st.session_state:
    st.session_state.pagina = "Dashboard"

with st.sidebar:
    st.markdown("### 💎 Inventario")
    st.write("")
    for clave, icono, etiqueta in PAGINAS:
        activo = st.session_state.pagina == clave
        clave_contenedor = "nav_activo" if activo else f"nav_{clave}"
        with st.container(key=clave_contenedor):
            if st.button(f"{icono}  {etiqueta}", key=f"btn_{clave}", use_container_width=True):
                st.session_state.pagina = clave
                st.rerun()

# ----------------------------------------------------------------------------
# DATOS COMPARTIDOS
# ----------------------------------------------------------------------------
try:
    df = obtener_productos()
except Exception:
    st.error(
        "No se pudo conectar con la base de datos (Supabase). "
        "Revisa tu conexión a internet y vuelve a intentar."
    )
    if st.button("🔄 Reintentar conexión"):
        st.rerun()
    st.stop()

proveedores_existentes = obtener_proveedores()
proveedores_df = obtener_proveedores_df()
ventas_df = obtener_ventas()
venta_detalle_df = obtener_venta_detalle()
compras_df = obtener_compras()
compra_detalle_df = obtener_compra_detalle()

TITULOS = {
    "Dashboard": "Panel de información",
    "Inventario": "Inventario",
    "Ventas": "Ventas",
    "Compras": "Compras",
    "Proveedores": "Proveedores",
    "Asistente": "Asistente IA",
}

col_titulo, col_accion = st.columns([5, 1])
with col_titulo:
    st.title(TITULOS[st.session_state.pagina])
with col_accion:
    st.write("")
    if st.button("🔄 Actualizar"):
        st.rerun()

st.divider()

if st.session_state.pagina == "Dashboard":
    pagina_dashboard(df, proveedores_existentes, ventas_df, compras_df, compra_detalle_df, venta_detalle_df)
elif st.session_state.pagina == "Inventario":
    pagina_inventario(df, proveedores_existentes)
elif st.session_state.pagina == "Ventas":
    pagina_ventas(df, ventas_df, venta_detalle_df)
elif st.session_state.pagina == "Compras":
    pagina_compras(df, proveedores_existentes, compras_df, compra_detalle_df, proveedores_df)
elif st.session_state.pagina == "Proveedores":
    pagina_proveedores(proveedores_df)
elif st.session_state.pagina == "Asistente":
    pagina_asistente(
        {
            "inventario": df,
            "ventas": ventas_df,
            "venta_detalle": venta_detalle_df,
            "compras": compras_df,
            "compra_detalle": compra_detalle_df,
            "proveedores": proveedores_df,
        }
    )
