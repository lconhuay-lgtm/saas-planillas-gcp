import smtplib
import os
import io
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from PyPDF2 import PdfReader, PdfWriter

def encriptar_pdf_en_memoria(buffer_pdf_original, password):
    """Encripta un PDF en memoria usando el DNI como contraseña."""
    reader = PdfReader(buffer_pdf_original)
    writer = PdfWriter()

    for page in reader.pages:
        writer.add_page(page)

    writer.encrypt(password)
    
    output_buffer = io.BytesIO()
    writer.write(output_buffer)
    output_buffer.seek(0)
    return output_buffer

def enviar_boleta_por_correo(correo_destino, mes_anio, pdf_buffer, nombre_trabajador, empresa_nombre):
    """Envía la boleta por correo electrónico usando SMTP."""
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", 587))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")

    if not smtp_user or not smtp_password:
        return "Configuración SMTP incompleta (Secrets)."

    msg = MIMEMultipart()
    msg['From'] = f"{empresa_nombre} <{smtp_user}>"
    msg['To'] = correo_destino
    msg['Subject'] = f"Boleta de Pago - Periodo {mes_anio} - {empresa_nombre}"

    body = f"""
    <html>
    <body>
        <p>Estimado/a <b>{nombre_trabajador}</b>,</p>
        <p>Adjuntamos su boleta de pago correspondiente al periodo <b>{mes_anio}</b>.</p>
        <p>Por su seguridad y confidencialidad, el documento se encuentra encriptado.</p>
        <p><b>La contraseña para abrir el archivo es su número de DNI.</b></p>
        <br>
        <p>Atentamente,<br>Departamento de Recursos Humanos<br>{empresa_nombre}</p>
    </body>
    </html>
    """
    msg.attach(MIMEText(body, 'html'))

    part = MIMEApplication(pdf_buffer.read(), Name=f"Boleta_{mes_anio.replace(' ','_')}.pdf")
    part['Content-Disposition'] = f'attachment; filename="Boleta_{mes_anio.replace(" ","_")}.pdf"'
    msg.attach(part)

    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        return str(e)
