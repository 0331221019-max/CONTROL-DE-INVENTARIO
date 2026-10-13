"""Agentes de IA del sistema de inventario.

Especificación: specs/asistente-ia/ (requirements.md, design.md, tasks.md).
La IA es Google Gemini con el plan gratuito de la API (cambio C2).
Este módulo no depende de Streamlit ni de Supabase (R6.1): el cliente se recibe
como parámetro para poder probarlo con un cliente falso.
"""
import json
import time

import httpx
import pandas as pd
import plotly.graph_objects as go
from google import genai
from google.genai import errors, types

from correo import correos_en_texto

# ----------------------------------------------------------------------------
# CONFIGURACIÓN
# ----------------------------------------------------------------------------
MODELO_POR_DEFECTO = "gemini-3.8-flash"
MODELOS_RESPALDO_POR_DEFECTO = ["gemini-3.6-flash", "gemini-3.5-flash-lite"]
ESPERAS_REINTENTO_S = [2, 5]
TEXTO_EJEMPLO_CLAVE = "PEGA-AQUI"
TIEMPO_MAXIMO_S = 120
TEMPERATURA = 0.2
MAX_FILAS_CONTEXTO = 500
FILAS_EJEMPLO = 3
UMBRAL_STOCK_BAJO = 5

PROMPT_AGENTE_RESPUESTAS = """Eres el asistente del sistema de control de inventario de una joyería en Perú.
Respondes en español, de forma clara y breve, preguntas sobre el inventario, las ventas, las compras y los proveedores.
Los montos están en soles (S/.). Basa tus respuestas únicamente en los datos que se te entregan; si un dato no está, dilo.
Para totales y cifras usa primero el RESUMEN CALCULADO, que ya tiene las sumas correctas; no vuelvas a sumar a mano.
Si ayuda, incluye una tabla corta en markdown.
No generas gráficos: si el usuario pide uno, indícale que use la pestaña "Agente de gráficos"."""

PROMPT_AGENTE_GRAFICOS = """Eres un agente que diseña gráficos a partir de los datos de un sistema de inventario.
Recibes la descripción de las tablas disponibles (columnas y ejemplos) y un pedido del usuario en español.
Devuelves SOLO la especificación del gráfico más adecuado, usando nombres de columna exactamente como aparecen.
Reglas:
- "fuente" es la tabla de donde salen los datos.
- "eje_x" es la columna para categorías o fechas; "eje_y" la columna numérica a medir (vacío si agregacion es "conteo").
- Si eje_x es "created_at", usa agrupar_fecha ("dia", "semana" o "mes") para agrupar por periodo.
- Para "torta" usa pocas categorías (top_n entre 3 y 8 si hay muchas).
- top_n = 0 significa mostrar todas las categorías.
- "explicacion" es una frase corta en español que describe qué muestra el gráfico."""

PROMPT_AGENTE_CORREOS = """Eres el agente que redacta correos electrónicos para una joyería en Perú.
Recibes un pedido del usuario y los datos del sistema. Redactas UN correo en español, profesional, claro y breve.
Reglas:
- "para": solo direcciones de correo que el usuario escribió en su pedido. Nunca inventes direcciones.
  Si el usuario no escribió ninguna, deja la lista vacía y explícalo en "nota".
- Usa las cifras del RESUMEN CALCULADO y los datos entregados; no inventes cantidades, precios ni nombres.
  Los montos van en soles (S/.).
- "asunto": una sola línea.
- "cuerpo": texto plano (sin markdown) con saludo, contenido y despedida. Firma con el nombre del remitente si se indica.
- "nota": aviso corto para el usuario sobre algo que deba revisar (o texto vacío).
No respondes preguntas ni haces gráficos: solo redactas el correo."""

ESQUEMA_CORREO = {
    "type": "object",
    "properties": {
        "para": {"type": "array", "items": {"type": "string"}},
        "asunto": {"type": "string"},
        "cuerpo": {"type": "string"},
        "nota": {"type": "string"},
    },
    "required": ["para", "asunto", "cuerpo", "nota"],
    "additionalProperties": False,
}

TIPOS_GRAFICO = ["barra", "barra_horizontal", "linea", "torta", "dispersion"]
FUENTES = ["inventario", "ventas", "venta_detalle", "compras", "compra_detalle", "proveedores"]
AGREGACIONES = ["suma", "promedio", "conteo", "ninguna"]

ESQUEMA_GRAFICO = {
    "type": "object",
    "properties": {
        "tipo": {"type": "string", "enum": TIPOS_GRAFICO},
        "fuente": {"type": "string", "enum": FUENTES},
        "eje_x": {"type": "string"},
        "eje_y": {"type": "string"},
        "agregacion": {"type": "string", "enum": AGREGACIONES},
        "agrupar_fecha": {"type": "string", "enum": ["ninguno", "dia", "semana", "mes"]},
        "top_n": {"type": "integer"},
        "orden": {"type": "string", "enum": ["desc", "asc", "ninguno"]},
        "titulo": {"type": "string"},
        "explicacion": {"type": "string"},
    },
    "required": ["tipo", "fuente", "eje_x", "eje_y", "agregacion", "agrupar_fecha", "top_n", "orden", "titulo", "explicacion"],
    "additionalProperties": False,
}

COLOR_PRINCIPAL = "#1E3A5F"
PALETA_GRAFICOS = [COLOR_PRINCIPAL, "#C0392B", "#2E7D32", "#3E6FA8", "#B8860B", "#6B7280", "#8E44AD", "#16A085"]


# ----------------------------------------------------------------------------
# CLIENTE GEMINI (T14)
# ----------------------------------------------------------------------------
class ErrorIA(RuntimeError):
    """Error base del asistente."""


class ClaveInvalida(ErrorIA):
    """La clave de Gemini no es válida o no tiene permisos (R5.1)."""


class LimiteAlcanzado(ErrorIA):
    """Se superó el límite del plan gratuito (R5.2)."""


class ModeloNoDisponible(ErrorIA):
    """El modelo configurado no existe (R5.3)."""


class SinConexion(ErrorIA):
    """No hay conexión con Google (R5.4)."""


class TiempoAgotado(ErrorIA):
    """La IA tardó más de TIEMPO_MAXIMO_S (R5.4)."""


class ServicioSaturado(ErrorIA):
    """Gemini respondió 5xx en todos los modelos y reintentos (R5.7)."""


def clave_configurada(clave) -> bool:
    """False si la clave falta o todavía es el texto de ejemplo (R1.3)."""
    clave = (clave or "").strip()
    return bool(clave) and not clave.startswith(TEXTO_EJEMPLO_CLAVE)


class ClienteGemini:
    """Envoltorio del SDK oficial google-genai con la interfaz chat() que usan los agentes (D9)."""

    def __init__(self, api_key, modelo=MODELO_POR_DEFECTO, sdk=None, respaldos=None, esperar=time.sleep):
        self.modelo = modelo
        self.respaldos = [m for m in (MODELOS_RESPALDO_POR_DEFECTO if respaldos is None else respaldos) if m != modelo]
        self.esperar = esperar
        self.ultimo_modelo = modelo
        self.sdk = sdk or genai.Client(
            api_key=api_key, http_options=types.HttpOptions(timeout=TIEMPO_MAXIMO_S * 1000)
        )

    def chat(self, system: str, mensajes: list, formato=None) -> str:
        """Pide la respuesta al modelo principal; ante saturación reintenta y usa respaldos (R5.6)."""
        contenidos = [
            {"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
            for m in mensajes
        ]
        config = types.GenerateContentConfig(system_instruction=system, temperature=TEMPERATURA)
        if formato is not None:
            config.response_mime_type = "application/json"
            config.response_json_schema = formato

        hubo_saturacion = False
        for indice, modelo in enumerate([self.modelo] + self.respaldos):
            es_principal = indice == 0
            for intento in range(len(ESPERAS_REINTENTO_S) + 1):
                try:
                    respuesta = self.sdk.models.generate_content(model=modelo, contents=contenidos, config=config)
                    self.ultimo_modelo = modelo
                    return respuesta.text or ""
                except errors.ServerError:
                    hubo_saturacion = True
                    if intento < len(ESPERAS_REINTENTO_S):
                        self.esperar(ESPERAS_REINTENTO_S[intento])
                        continue
                    break  # siguiente modelo
                except errors.ClientError as e:
                    if e.code in (401, 403) or (e.code == 400 and "API key" in str(e)):
                        raise ClaveInvalida("La clave de Gemini no es válida.") from e
                    if e.code == 429:
                        break  # cada modelo tiene su propia cuota gratuita
                    if e.code == 404:
                        if es_principal:
                            raise ModeloNoDisponible(f"El modelo '{modelo}' no existe.") from e
                        break
                    raise
                except httpx.TimeoutException as e:
                    raise TiempoAgotado("Gemini tardó demasiado en responder.") from e
                except (httpx.TransportError, OSError) as e:
                    raise SinConexion("No hay conexión con Google.") from e
        if hubo_saturacion:
            raise ServicioSaturado("Gemini está saturado en este momento.")
        raise LimiteAlcanzado("Se alcanzó el límite del plan gratuito de Gemini.")


# ----------------------------------------------------------------------------
# CONTEXTO DE DATOS (T1.3, T1.4)
# ----------------------------------------------------------------------------
def _csv(tabla: pd.DataFrame) -> str:
    return tabla.to_csv(index=False, lineterminator="\n")


def tablas_para_ia(datos: dict) -> dict:
    """Quita columnas internas que no aportan al análisis."""
    return {
        nombre: tabla.drop(columns=["id"], errors="ignore") if nombre in ("inventario", "proveedores") else tabla
        for nombre, tabla in datos.items()
    }


def contexto_completo(datos: dict) -> str:
    """Datos de todas las tablas en CSV, recortados a MAX_FILAS_CONTEXTO (R2.1–R2.3)."""
    partes = []
    for nombre, tabla in tablas_para_ia(datos).items():
        if tabla.empty:
            partes.append(f"## {nombre}\n(sin registros)")
        else:
            recorte = tabla.head(MAX_FILAS_CONTEXTO)
            nota = f" (primeras {MAX_FILAS_CONTEXTO} de {len(tabla)} filas)" if len(tabla) > MAX_FILAS_CONTEXTO else ""
            partes.append(f"## {nombre}{nota}\n{_csv(recorte)}")
    return "\n\n".join(partes)


def contexto_esquema(datos: dict) -> str:
    """Solo la estructura de las tablas: columnas, número de filas y ejemplos (R3.1)."""
    partes = []
    for nombre, tabla in tablas_para_ia(datos).items():
        if tabla.empty:
            partes.append(f"## {nombre}: sin registros")
            continue
        partes.append(
            f"## {nombre} ({len(tabla)} filas)\nColumnas: {', '.join(map(str, tabla.columns))}\n"
            f"Ejemplo:\n{_csv(tabla.head(FILAS_EJEMPLO))}"
        )
    return "\n\n".join(partes)


def _numero(tabla: pd.DataFrame, columna: str) -> pd.Series:
    if columna not in tabla.columns:
        return pd.Series(0.0, index=tabla.index)
    return pd.to_numeric(tabla[columna], errors="coerce").fillna(0)


def _lista(serie: pd.Series, formato) -> str:
    return "\n".join(f"  - {clave}: {formato(valor)}" for clave, valor in serie.items()) or "  (sin datos)"


def soles(valor) -> str:
    return f"S/. {valor:,.2f}"


def resumen_calculado(datos: dict) -> str:
    """Totales clave calculados en Python para que el modelo no tenga que sumar (R2.8)."""
    lineas = []
    inv = datos.get("inventario", pd.DataFrame())
    if not inv.empty:
        cantidad = _numero(inv, "CANTIDAD")
        lineas += [
            "INVENTARIO",
            f"- Productos registrados: {len(inv)}",
            f"- Unidades en stock: {int(cantidad.sum())}",
            f"- Valor del stock a costo: {soles((cantidad * _numero(inv, 'COSTO')).sum())}",
            f"- Valor del stock a precio de venta: {soles((cantidad * _numero(inv, 'PRECIO')).sum())}",
        ]
        bajos = inv[cantidad < UMBRAL_STOCK_BAJO]
        nombres_bajos = ", ".join(f"{n} ({int(c)})" for n, c in zip(bajos.get("NOMBRE", []), _numero(bajos, "CANTIDAD")))
        lineas.append(f"- Productos con stock bajo (menos de {UMBRAL_STOCK_BAJO}): {len(bajos)}"
                      + (f" -> {nombres_bajos}" if nombres_bajos else ""))
        if "CATEGORÍA" in inv.columns:
            lineas += ["- Unidades por categoría:", _lista(cantidad.groupby(inv["CATEGORÍA"]).sum().astype(int), str)]

    ventas = datos.get("ventas", pd.DataFrame())
    if not ventas.empty:
        total = _numero(ventas, "TOTAL")
        lineas += ["", "VENTAS", f"- Número de ventas: {len(ventas)}", f"- Monto total vendido: {soles(total.sum())}"]
        if "created_at" in ventas.columns:
            mes = pd.to_datetime(ventas["created_at"], utc=True, errors="coerce").dt.strftime("%Y-%m")
            lineas += ["- Ventas por mes:", _lista(total.groupby(mes).sum(), soles)]
        if "CANAL" in ventas.columns:
            lineas += ["- Ventas por canal:", _lista(total.groupby(ventas["CANAL"]).sum(), soles)]
        if "ESTADO" in ventas.columns:
            lineas += ["- Ventas por estado (cantidad de ventas):", _lista(ventas["ESTADO"].value_counts(), str)]

    detalle = datos.get("venta_detalle", pd.DataFrame())
    if not detalle.empty and "PRODUCTO" in detalle.columns:
        top = _numero(detalle, "CANTIDAD").groupby(detalle["PRODUCTO"]).sum().sort_values(ascending=False).head(5)
        lineas += ["- Productos más vendidos (unidades):", _lista(top.astype(int), str)]

    compras = datos.get("compras", pd.DataFrame())
    if not compras.empty:
        total = _numero(compras, "TOTAL")
        lineas += ["", "COMPRAS", f"- Número de compras: {len(compras)}", f"- Monto total comprado: {soles(total.sum())}"]
        if "PROVEEDOR" in compras.columns:
            lineas += ["- Compras por proveedor:", _lista(total.groupby(compras["PROVEEDOR"]).sum(), soles)]

    return "\n".join(lineas) or "(no hay datos registrados)"


# ----------------------------------------------------------------------------
# AGENTE DE RESPUESTAS (T8)
# ----------------------------------------------------------------------------
def agente_respuestas(cliente, datos: dict, historial: list) -> str:
    """Responde la última pregunta del historial usando los datos actuales (R2)."""
    sistema = (
        f"{PROMPT_AGENTE_RESPUESTAS}\n\n"
        f"RESUMEN CALCULADO:\n{resumen_calculado(datos)}\n\n"
        f"DATOS DETALLADOS (CSV):\n\n{contexto_completo(datos)}"
    )
    return cliente.chat(sistema, historial)


# ----------------------------------------------------------------------------
# AGENTE DE GRÁFICOS (T8)
# ----------------------------------------------------------------------------
def validar_spec(spec) -> dict:
    """Comprueba que la especificación cumpla el esquema; los modelos pequeños a veces se salen (R3.11)."""
    if not isinstance(spec, dict):
        raise ValueError("La IA no devolvió una especificación válida.")
    faltan = [c for c in ESQUEMA_GRAFICO["required"] if c not in spec]
    if faltan:
        raise ValueError(f"A la especificación le faltan campos: {', '.join(faltan)}.")
    for campo, regla in ESQUEMA_GRAFICO["properties"].items():
        if "enum" in regla and spec[campo] not in regla["enum"]:
            raise ValueError(f"Valor no permitido en '{campo}': {spec[campo]!r}.")
    try:
        spec["top_n"] = int(spec["top_n"])
    except (TypeError, ValueError):
        raise ValueError("'top_n' debe ser un número entero.") from None
    return spec


def agente_graficos(cliente, datos: dict, pedido: str) -> dict:
    """Convierte un pedido en una especificación de gráfico validada (R3.1, R3.2, R3.11)."""
    texto = cliente.chat(
        PROMPT_AGENTE_GRAFICOS,
        [{"role": "user", "content": f"TABLAS DISPONIBLES:\n\n{contexto_esquema(datos)}\n\nPEDIDO: {pedido}"}],
        formato=ESQUEMA_GRAFICO,
    )
    try:
        spec = json.loads(texto)
    except json.JSONDecodeError:
        raise ValueError("La IA no devolvió un JSON válido.") from None
    return validar_spec(spec)


# ----------------------------------------------------------------------------
# AGENTE DE CORREOS (T22, C3)
# ----------------------------------------------------------------------------
def filtrar_destinatarios(propuestos: list, pedido: str) -> list:
    """Conserva solo las direcciones que el usuario escribió en su pedido (R7.4)."""
    escritos = {c.lower() for c in correos_en_texto(pedido)}
    resultado = []
    for direccion in propuestos:
        direccion = str(direccion).strip()
        if direccion.lower() in escritos and direccion.lower() not in {r.lower() for r in resultado}:
            resultado.append(direccion)
    return resultado


def agente_correos(cliente, datos: dict, pedido: str, nombre_remitente: str = "") -> dict:
    """Redacta un borrador {para, asunto, cuerpo, nota}. Nunca envía (R7.2, R7.3)."""
    firma = f"Nombre del remitente para la firma: {nombre_remitente}\n\n" if nombre_remitente else ""
    texto = cliente.chat(
        PROMPT_AGENTE_CORREOS,
        [{"role": "user", "content": (
            f"RESUMEN CALCULADO:\n{resumen_calculado(datos)}\n\n"
            f"DATOS DETALLADOS (CSV):\n\n{contexto_completo(datos)}\n\n"
            f"{firma}PEDIDO DEL USUARIO: {pedido}"
        )}],
        formato=ESQUEMA_CORREO,
    )
    try:
        borrador = json.loads(texto)
    except json.JSONDecodeError:
        raise ValueError("La IA no devolvió un borrador válido.") from None
    if not isinstance(borrador, dict) or any(c not in borrador for c in ESQUEMA_CORREO["required"]):
        raise ValueError("La IA devolvió un borrador incompleto.")

    propuestos = borrador["para"] if isinstance(borrador["para"], list) else []
    para = filtrar_destinatarios(propuestos, pedido)
    nota = str(borrador["nota"] or "").strip()
    descartados = [d for d in propuestos if str(d).strip().lower() not in {p.lower() for p in para}]
    if descartados:
        aviso = f"Se quitaron direcciones que no escribiste en tu pedido: {', '.join(map(str, descartados))}."
        nota = f"{nota} {aviso}".strip()
    return {
        "para": para,
        "asunto": " ".join(str(borrador["asunto"]).split()),  # una sola línea (R7.7)
        "cuerpo": str(borrador["cuerpo"]).strip(),
        "nota": nota,
    }


def construir_grafico(spec: dict, datos: dict):
    """Dibuja el gráfico con código propio a partir de la especificación (R3.3–R3.8, R3.10).

    Devuelve (figura, tabla_resumen). Lanza ValueError si la especificación no es válida.
    """
    tabla = datos.get(spec["fuente"])
    if tabla is None or tabla.empty:
        raise ValueError(f"La tabla '{spec['fuente']}' no tiene datos.")
    tabla = tabla.copy()
    x, y, agregacion = spec["eje_x"], spec["eje_y"], spec["agregacion"]
    if x not in tabla.columns:
        raise ValueError(f"La columna '{x}' no existe en '{spec['fuente']}'.")
    if agregacion != "conteo" and y not in tabla.columns:
        raise ValueError(f"La columna '{y}' no existe en '{spec['fuente']}'.")

    if x == "created_at" or spec["agrupar_fecha"] != "ninguno":
        fechas = pd.to_datetime(tabla[x], utc=True, errors="coerce")
        periodo = {"dia": "D", "semana": "W", "mes": "M"}.get(spec["agrupar_fecha"], "D")
        tabla[x] = fechas.dt.tz_convert(None).dt.to_period(periodo).dt.start_time

    if agregacion == "ninguna":
        resumen = tabla[[x, y]].dropna()
    elif agregacion == "conteo":
        y = "Cantidad de registros"
        resumen = tabla.groupby(x).size().reset_index(name=y)
    else:
        tabla[y] = pd.to_numeric(tabla[y], errors="coerce")
        funcion = "sum" if agregacion == "suma" else "mean"
        resumen = tabla.groupby(x)[y].agg(funcion).reset_index()

    es_fecha = pd.api.types.is_datetime64_any_dtype(resumen[x])
    if es_fecha:
        resumen = resumen.sort_values(x)
    elif spec["orden"] != "ninguno":
        resumen = resumen.sort_values(y, ascending=spec["orden"] == "asc")
    if spec["top_n"] > 0:
        resumen = resumen.head(spec["top_n"])
    resumen = resumen.reset_index(drop=True)

    tipo = spec["tipo"]
    if tipo == "torta":
        traza = go.Pie(labels=resumen[x], values=resumen[y], hole=0.45, marker=dict(colors=PALETA_GRAFICOS))
    elif tipo == "linea":
        traza = go.Scatter(x=resumen[x], y=resumen[y], mode="lines+markers", line=dict(color=COLOR_PRINCIPAL, width=3))
    elif tipo == "dispersion":
        traza = go.Scatter(x=resumen[x], y=resumen[y], mode="markers", marker=dict(color=COLOR_PRINCIPAL, size=10))
    elif tipo == "barra_horizontal":
        traza = go.Bar(x=resumen[y], y=resumen[x].astype(str), orientation="h", marker_color=COLOR_PRINCIPAL)
    else:
        traza = go.Bar(x=resumen[x] if es_fecha else resumen[x].astype(str), y=resumen[y], marker_color=COLOR_PRINCIPAL)

    fig = go.Figure(data=[traza])
    fig.update_layout(
        title=spec["titulo"],
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#FFFFFF",
        font=dict(color=COLOR_PRINCIPAL),
        margin=dict(l=10, r=10, t=50, b=10),
        height=420,
    )
    if tipo == "barra_horizontal":
        fig.update_yaxes(autorange="reversed")
    return fig, resumen
