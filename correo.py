"""Envío de correos por SMTP (especificación: specs/asistente-ia/, R7).

No usa IA: los agentes solo redactan borradores. Este módulo envía únicamente
cuando la interfaz lo llama después de que el usuario pulsa "Enviar correo" (R7.3).
"""
import re
import smtplib
from email.message import EmailMessage
from email.utils import formataddr

SMTP_HOST_POR_DEFECTO = "smtp.gmail.com"
SMTP_PUERTO_POR_DEFECTO = 587
MAX_DESTINATARIOS = 10
TIEMPO_MAXIMO_S = 30
PATRON_CORREO = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
PATRON_BUSCAR_CORREOS = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


class ErrorCorreo(RuntimeError):
    """Error base del envío de correos."""


class CredencialesCorreoInvalidas(ErrorCorreo):
    """El remitente o la contraseña de aplicación son incorrectos (R7.10)."""


class DestinatarioRechazado(ErrorCorreo):
    """El servidor rechazó uno o más destinatarios (R7.10)."""


class ErrorEnvioCorreo(ErrorCorreo):
    """Sin conexión o error del servidor de correo (R7.10)."""


def correos_en_texto(texto: str) -> list:
    """Direcciones de correo que aparecen escritas en un texto."""
    return PATRON_BUSCAR_CORREOS.findall(texto or "")


def separar_destinatarios(texto: str) -> list:
    """Convierte 'a@x.com, b@y.com; c@z.com' en una lista sin duplicados."""
    vistos, resultado = set(), []
    for parte in re.split(r"[,;\s]+", texto or ""):
        if parte and parte.lower() not in vistos:
            vistos.add(parte.lower())
            resultado.append(parte)
    return resultado


def es_clave_app_gmail(clave: str) -> bool:
    """Las contraseñas de aplicación de Google son 16 letras (R7.14)."""
    limpia = (clave or "").replace(" ", "")
    return len(limpia) == 16 and limpia.isascii() and limpia.isalpha()


def validar_correo(para: list, asunto: str, cuerpo: str) -> None:
    """Lanza ValueError si el correo no se puede enviar (R7.5–R7.7)."""
    if not para:
        raise ValueError("Agrega al menos un destinatario.")
    if len(para) > MAX_DESTINATARIOS:
        raise ValueError(f"Máximo {MAX_DESTINATARIOS} destinatarios por correo.")
    invalidos = [d for d in para if not PATRON_CORREO.match(d)]
    if invalidos:
        raise ValueError(f"Dirección no válida: {', '.join(invalidos)}")
    if not (asunto or "").strip():
        raise ValueError("El asunto está vacío.")
    if "\n" in asunto or "\r" in asunto:
        raise ValueError("El asunto no puede tener saltos de línea.")
    if not (cuerpo or "").strip():
        raise ValueError("El cuerpo del correo está vacío.")


def construir_mensaje(remitente, nombre_remitente, para, asunto, cuerpo) -> EmailMessage:
    mensaje = EmailMessage()
    mensaje["From"] = formataddr((nombre_remitente, remitente)) if nombre_remitente else remitente
    mensaje["To"] = ", ".join(para)
    mensaje["Subject"] = asunto.strip()
    mensaje.set_content(cuerpo)
    return mensaje


def enviar_correo(config: dict, para: list, asunto: str, cuerpo: str, smtp=smtplib.SMTP) -> None:
    """Envía el correo por SMTP con STARTTLS (R7.9).

    config: remitente, clave_app y, opcionalmente, nombre, host y puerto.
    smtp: fábrica de conexiones (se reemplaza en las pruebas).
    """
    validar_correo(para, asunto, cuerpo)
    host = config.get("host") or SMTP_HOST_POR_DEFECTO
    clave = (config.get("clave_app") or "").replace(" ", "")
    if host == SMTP_HOST_POR_DEFECTO and not es_clave_app_gmail(clave):
        raise CredencialesCorreoInvalidas(
            "EMAIL_CLAVE_APP no es una contraseña de aplicación de Google (deben ser 16 letras)."
        )
    mensaje = construir_mensaje(config["remitente"], config.get("nombre"), para, asunto, cuerpo)
    puerto = int(config.get("puerto") or SMTP_PUERTO_POR_DEFECTO)
    etapa = "conexión"
    try:
        with smtp(host, puerto, timeout=TIEMPO_MAXIMO_S) as servidor:
            servidor.starttls()
            etapa = "inicio de sesión"
            servidor.login(config["remitente"], clave)
            etapa = "envío"
            servidor.send_message(mensaje)
    except smtplib.SMTPAuthenticationError as e:
        raise CredencialesCorreoInvalidas("El correo remitente o la contraseña de aplicación son incorrectos.") from e
    except smtplib.SMTPServerDisconnected as e:
        if etapa == "inicio de sesión":  # Gmail corta así ciertas credenciales inválidas (R7.15)
            raise CredencialesCorreoInvalidas("Gmail cerró la conexión al iniciar sesión.") from e
        raise ErrorEnvioCorreo(f"El servidor cerró la conexión durante la {etapa}.") from e
    except smtplib.SMTPRecipientsRefused as e:
        rechazados = ", ".join(e.recipients)
        raise DestinatarioRechazado(f"El servidor rechazó: {rechazados}") from e
    except (smtplib.SMTPException, OSError) as e:
        raise ErrorEnvioCorreo(f"No se pudo enviar el correo: {e}") from e
