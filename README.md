# SaaS Planillas

Sistema de planillas para Perú (Streamlit + PostgreSQL/Neon, desplegado en Cloud Run).

## Variables de entorno

| Variable | Obligatoria | Uso |
|---|---|---|
| `DATABASE_URL` | Sí | Conexión a PostgreSQL (Neon). |
| `ADMIN_INITIAL_PASSWORD` | Solo la primera vez | Si la tabla `usuarios` está vacía, crea el usuario `admin` con esta clave y lo obliga a cambiarla al ingresar. No hay claves por defecto en el código. |
| `APISPERU_TOKEN` | No | Token de APIsPERU para consultar DNI/RUC. Sin él se usa solo la API de respaldo. |
| `STREAMLIT_SERVER_COOKIE_SECRET` | Recomendada en Cloud Run | Secreto fijo para firmar la cookie XSRF entre instancias. |
| `SMTP_SERVER`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` | Para enviar boletas | Correo saliente. |

En Cloud Run, los valores secretos van en Secret Manager (`--set-secrets`).

## Pruebas

```bash
python -m pytest tests -q
```
