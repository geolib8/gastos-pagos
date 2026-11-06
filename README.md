# Gastos & Pagos

Aplicación web para registrar gastos de una empresa, generar y efectuar sus pagos, y llevar el saldo de las cuentas bancarias.

**Stack:** Python 3.12 · Flask 3 · SQLite · Jinja2 + Bootstrap 5 · Chart.js · Gunicorn (Render)

## Correr en local

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   |   Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
flask --app wsgi run --debug
```

Abre http://127.0.0.1:5000. La primera vez se crea la base (`instance/gastos.db`) con datos de demo.

| Usuario | Contraseña | Rol |
|---|---|---|
| admin | Rgv2026!admin | Aprueba, cancela y efectúa pagos; administra cuentas |
| capturista | Rgv2026!captura | Registra gastos y genera pagos |

Las contraseñas se pueden cambiar con las variables `ADMIN_PASSWORD` y `CAPTURISTA_PASSWORD`. Para reiniciar la base: `flask --app wsgi reset-db`.

## Tests

```bash
pip install pytest
pytest -q
```

Cubren las reglas de negocio (aprobación antes de pagar, saldo, parciales, duplicados, cancelación definitiva), la autenticación, CSRF y la API.

## Reglas de negocio

| Regla | Cómo se cumple |
|---|---|
| Gasto aprobado antes de pagar | `generar_pago` y `efectuar_pago` validan que el gasto esté en APROBADO o PAGO_PARCIAL |
| Pago no puede exceder saldo | Se valida al generar el pago y otra vez al efectuarlo, dentro de una transacción `BEGIN IMMEDIATE` (lock de escritura) |
| Pagos parciales | El monto es editable; el gasto pasa a PAGO_PARCIAL y luego a PAGADO cuando lo pagado = monto |
| Evitar pagos duplicados | (1) token único por formulario (`pagos.token UNIQUE`), (2) la suma de pagos activos no puede pasar el monto del gasto, (3) un pago solo se efectúa una vez (`movimientos.pago_id UNIQUE`), (4) el botón se deshabilita al enviar |
| Gastos cancelados no se reactivan | CANCELADO es estado final; ninguna transición sale de él. Al cancelar, sus pagos no efectuados también se cancelan |

## Despliegue en Render

1. Sube este repo a GitHub.
2. En Render: **New > Blueprint** y elige el repo (usa `render.yaml`).
3. Opcional: define `ADMIN_PASSWORD` y `CAPTURISTA_PASSWORD`.

En el plan gratuito el disco es efímero: si el servicio se reinicia, la base vuelve a los datos de demo.

## API

`GET /api/v1/...` con autenticación HTTP Basic. Ver `/api-docs` dentro de la app o el PDF de entrega.

```bash
curl -u admin:Rgv2026!admin https://TU-APP.onrender.com/api/v1/resumen
```
