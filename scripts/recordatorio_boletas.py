"""
Recordatorio automático de boletas pendientes de autorizar.

Script STANDALONE — no pasa por Streamlit, no requiere un usuario conectado.
Pensado para correr como Cloud Run Job, disparado por Cloud Scheduler el día 1 y 2
de cada mes. Solo envía un correo de aviso a cada empresa con periodos pendientes
(desde 07-2026) — NUNCA envía boletas reales, eso sigue requiriendo la autorización
manual dentro de la app.

Uso local/manual: python scripts/recordatorio_boletas.py
"""
import os
import sys
import smtplib
from email.mime.text import MIMEText

# Igual patrón que presentation/app.py para poder importar el resto del proyecto
_ruta_raiz = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _ruta_raiz not in sys.path:
    sys.path.append(_ruta_raiz)

from infrastructure.database.connection import SessionLocal
from infrastructure.database.models import Empresa, PlanillaMensual
from presentation.views.autorizacion_boletas import _periodo_ordenable, UMBRAL_PERIODO, _periodo_legible


def _enviar_recordatorio(correo_destino: str, empresa_nombre: str, periodo_legible: str) -> bool:
    smtp_server   = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port     = int(os.getenv("SMTP_PORT", 587))
    smtp_user     = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    if not smtp_user or not smtp_password:
        print(f"⚠️  Configuración SMTP incompleta — no se pudo notificar a {empresa_nombre}.")
        return False

    msg = MIMEText(
        f"Estimado(a) responsable de {empresa_nombre},\n\n"
        f"El periodo {periodo_legible} tiene la planilla cerrada y sus boletas de pago "
        f"aún no han sido autorizadas para envío.\n\n"
        f"Ingrese al sistema de Planillas y revíselas para autorizar el envío a sus "
        f"trabajadores.\n\nAtentamente,\nLCK Business Advisors — Planillas",
        "plain",
    )
    msg['Subject'] = f"Recordatorio: boletas pendientes de autorizar - {empresa_nombre}"
    msg['From'] = f"LCK Planillas <{smtp_user}>"
    msg['To'] = correo_destino

    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"❌ Error notificando a {empresa_nombre}: {e}")
        return False


def main():
    db = SessionLocal()
    try:
        empresas = db.query(Empresa).all()
        notificadas = 0
        for empresa in empresas:
            planillas = db.query(PlanillaMensual).filter_by(
                empresa_id=empresa.id, estado='CERRADA'
            ).all()
            pendientes = [
                p for p in planillas
                if not getattr(p, 'boletas_autorizado', False)
                and _periodo_ordenable(p.periodo_key) >= UMBRAL_PERIODO
            ]
            if not pendientes:
                continue
            if not empresa.correo_electronico:
                print(f"⚠️  {empresa.razon_social} tiene boletas pendientes pero no tiene correo de contacto registrado.")
                continue

            pendientes.sort(key=lambda p: _periodo_ordenable(p.periodo_key))
            periodo_mas_antiguo = _periodo_legible(pendientes[0].periodo_key)
            if _enviar_recordatorio(empresa.correo_electronico, empresa.razon_social, periodo_mas_antiguo):
                print(f"✅ Recordatorio enviado a {empresa.razon_social} ({empresa.correo_electronico})")
                notificadas += 1

        print(f"\nProceso terminado. Empresas notificadas: {notificadas}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
