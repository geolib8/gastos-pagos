"""Reglas de negocio de gastos, pagos y cuentas.

Todo lo que cambia estatus o saldos pasa por aquí, para que las vistas y
los tests usen exactamente la misma lógica.
"""
from datetime import datetime

from .db import transaccion, uno, todos


class ReglaNegocio(Exception):
    pass


# estatus que todavía "apartan" monto del gasto
PAGOS_ACTIVOS = ("PENDIENTE", "APROBADO", "PAGADO")


def ahora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def a_cents(valor):
    """'1,234.50' -> 123450. Lanza ReglaNegocio si no es un monto válido."""
    try:
        txt = str(valor).replace(",", "").replace("$", "").strip()
        cents = round(float(txt) * 100)
    except (TypeError, ValueError):
        raise ReglaNegocio("El monto no es válido")
    if cents <= 0:
        raise ReglaNegocio("El monto debe ser mayor a cero")
    return cents


def _historial(con, entidad, entidad_id, antes, despues, usuario_id, comentario=None):
    con.execute(
        "INSERT INTO historial (entidad, entidad_id, estatus_anterior, estatus_nuevo, usuario_id, comentario, creado_en)"
        " VALUES (?,?,?,?,?,?,?)",
        (entidad, entidad_id, antes, despues, usuario_id, comentario, ahora()),
    )


def _siguiente_folio(con, tabla, prefijo):
    n = uno(con, f"SELECT COUNT(*) AS n FROM {tabla}")["n"] + 1
    return f"{prefijo}-{n:05d}"


def montos_gasto(con, gasto_id):
    """Regresa (monto, comprometido, pagado, pendiente) en centavos."""
    g = uno(con, "SELECT monto_cents FROM gastos WHERE id = ?", (gasto_id,))
    if g is None:
        raise ReglaNegocio("El gasto no existe")
    r = uno(con, """
        SELECT COALESCE(SUM(CASE WHEN estatus IN ('PENDIENTE','APROBADO','PAGADO') THEN monto_cents END), 0) AS comprometido,
               COALESCE(SUM(CASE WHEN estatus = 'PAGADO' THEN monto_cents END), 0) AS pagado
        FROM pagos WHERE gasto_id = ?""", (gasto_id,))
    monto = g["monto_cents"]
    return monto, r["comprometido"], r["pagado"], monto - r["comprometido"]


# ------------------------------------------------------------------ gastos
def crear_gasto(con, usuario_id, proveedor_id, categoria_id, descripcion, monto,
                fecha_gasto, fecha_vencimiento=None):
    cents = a_cents(monto)
    if not descripcion or not descripcion.strip():
        raise ReglaNegocio("La descripción es obligatoria")
    if uno(con, "SELECT 1 FROM proveedores WHERE id = ?", (proveedor_id,)) is None:
        raise ReglaNegocio("Proveedor no válido")
    if uno(con, "SELECT 1 FROM categorias WHERE id = ?", (categoria_id,)) is None:
        raise ReglaNegocio("Categoría no válida")
    with transaccion(con):
        folio = _siguiente_folio(con, "gastos", "G")
        cur = con.execute(
            "INSERT INTO gastos (folio, proveedor_id, categoria_id, descripcion, monto_cents, fecha_gasto,"
            " fecha_vencimiento, creado_por, creado_en) VALUES (?,?,?,?,?,?,?,?,?)",
            (folio, proveedor_id, categoria_id, descripcion.strip(), cents, fecha_gasto,
             fecha_vencimiento or None, usuario_id, ahora()),
        )
        gid = cur.lastrowid
        _historial(con, "gasto", gid, None, "PENDIENTE", usuario_id, "Gasto registrado")
    return gid


def aprobar_gasto(con, gasto_id, usuario_id):
    with transaccion(con):
        g = uno(con, "SELECT estatus FROM gastos WHERE id = ?", (gasto_id,))
        if g is None:
            raise ReglaNegocio("El gasto no existe")
        if g["estatus"] != "PENDIENTE":
            raise ReglaNegocio(f"Solo se aprueban gastos pendientes (estatus actual: {g['estatus']})")
        con.execute("UPDATE gastos SET estatus='APROBADO', aprobado_por=?, aprobado_en=? WHERE id=?",
                    (usuario_id, ahora(), gasto_id))
        _historial(con, "gasto", gasto_id, "PENDIENTE", "APROBADO", usuario_id)


def cancelar_gasto(con, gasto_id, usuario_id, motivo):
    if not motivo or not motivo.strip():
        raise ReglaNegocio("Indica el motivo de cancelación")
    with transaccion(con):
        g = uno(con, "SELECT estatus FROM gastos WHERE id = ?", (gasto_id,))
        if g is None:
            raise ReglaNegocio("El gasto no existe")
        if g["estatus"] == "CANCELADO":
            raise ReglaNegocio("El gasto ya está cancelado")
        if g["estatus"] in ("PAGO_PARCIAL", "PAGADO"):
            raise ReglaNegocio("No se puede cancelar un gasto que ya tiene pagos efectuados")
        # los pagos que no se han efectuado se cancelan junto con el gasto
        for p in todos(con, "SELECT id, estatus FROM pagos WHERE gasto_id=? AND estatus IN ('PENDIENTE','APROBADO')",
                       (gasto_id,)):
            con.execute("UPDATE pagos SET estatus='CANCELADO', cancelado_por=?, cancelado_en=?, motivo_cancelacion=?"
                        " WHERE id=?", (usuario_id, ahora(), "Gasto cancelado", p["id"]))
            _historial(con, "pago", p["id"], p["estatus"], "CANCELADO", usuario_id, "Gasto cancelado")
        con.execute("UPDATE gastos SET estatus='CANCELADO', cancelado_por=?, cancelado_en=?, motivo_cancelacion=?"
                    " WHERE id=?", (usuario_id, ahora(), motivo.strip(), gasto_id))
        _historial(con, "gasto", gasto_id, g["estatus"], "CANCELADO", usuario_id, motivo.strip())


# ------------------------------------------------------------------ pagos
def generar_pago(con, gasto_id, cuenta_id, monto, usuario_id, token, referencia=None):
    """Crea el pago ligado al gasto. Si `token` ya se usó (doble clic,
    refresh del formulario) regresa el pago existente en lugar de duplicarlo."""
    if not token:
        raise ReglaNegocio("Falta el token del formulario")
    cents = a_cents(monto)
    with transaccion(con):
        previo = uno(con, "SELECT id FROM pagos WHERE token = ?", (token,))
        if previo:
            return previo["id"], False

        g = uno(con, "SELECT estatus FROM gastos WHERE id = ?", (gasto_id,))
        if g is None:
            raise ReglaNegocio("El gasto no existe")
        if g["estatus"] not in ("APROBADO", "PAGO_PARCIAL"):
            raise ReglaNegocio("El gasto debe estar aprobado antes de generar un pago")

        cuenta = uno(con, "SELECT saldo_cents, activa FROM cuentas_bancarias WHERE id = ?", (cuenta_id,))
        if cuenta is None or not cuenta["activa"]:
            raise ReglaNegocio("Cuenta bancaria no válida")

        _, _, _, pendiente = montos_gasto(con, gasto_id)
        if pendiente <= 0:
            raise ReglaNegocio("El gasto ya tiene pagos por el total; no se pueden generar más")
        if cents > pendiente:
            raise ReglaNegocio(f"El pago excede lo pendiente del gasto (${pendiente / 100:,.2f})")
        if cents > cuenta["saldo_cents"]:
            raise ReglaNegocio(f"El pago excede el saldo de la cuenta (${cuenta['saldo_cents'] / 100:,.2f})")

        folio = _siguiente_folio(con, "pagos", "P")
        cur = con.execute(
            "INSERT INTO pagos (folio, gasto_id, cuenta_id, monto_cents, referencia, token, creado_por, creado_en)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (folio, gasto_id, cuenta_id, cents, referencia or None, token, usuario_id, ahora()),
        )
        pid = cur.lastrowid
        parcial = " (parcial)" if cents < pendiente else ""
        _historial(con, "pago", pid, None, "PENDIENTE", usuario_id, f"Pago generado desde el gasto{parcial}")
    return pid, True


def aprobar_pago(con, pago_id, usuario_id):
    with transaccion(con):
        p = uno(con, "SELECT p.estatus, g.estatus AS est_gasto FROM pagos p JOIN gastos g ON g.id = p.gasto_id"
                     " WHERE p.id = ?", (pago_id,))
        if p is None:
            raise ReglaNegocio("El pago no existe")
        if p["estatus"] != "PENDIENTE":
            raise ReglaNegocio(f"Solo se aprueban pagos pendientes (estatus actual: {p['estatus']})")
        if p["est_gasto"] == "CANCELADO":
            raise ReglaNegocio("El gasto de este pago está cancelado")
        con.execute("UPDATE pagos SET estatus='APROBADO', aprobado_por=?, aprobado_en=? WHERE id=?",
                    (usuario_id, ahora(), pago_id))
        _historial(con, "pago", pago_id, "PENDIENTE", "APROBADO", usuario_id)


def efectuar_pago(con, pago_id, usuario_id):
    with transaccion(con):
        p = uno(con, "SELECT * FROM pagos WHERE id = ?", (pago_id,))
        if p is None:
            raise ReglaNegocio("El pago no existe")
        if p["estatus"] == "PAGADO":
            raise ReglaNegocio("Este pago ya se efectuó")
        if p["estatus"] != "APROBADO":
            raise ReglaNegocio("El pago debe estar aprobado para efectuarse")
        g = uno(con, "SELECT estatus FROM gastos WHERE id = ?", (p["gasto_id"],))
        if g["estatus"] not in ("APROBADO", "PAGO_PARCIAL"):
            raise ReglaNegocio("El gasto debe estar aprobado antes de pagar")

        cuenta = uno(con, "SELECT saldo_cents FROM cuentas_bancarias WHERE id = ?", (p["cuenta_id"],))
        if p["monto_cents"] > cuenta["saldo_cents"]:
            raise ReglaNegocio(f"Saldo insuficiente: la cuenta tiene ${cuenta['saldo_cents'] / 100:,.2f}")

        nuevo_saldo = cuenta["saldo_cents"] - p["monto_cents"]
        con.execute("UPDATE cuentas_bancarias SET saldo_cents = ? WHERE id = ?", (nuevo_saldo, p["cuenta_id"]))
        con.execute(
            "INSERT INTO movimientos (cuenta_id, tipo, monto_cents, saldo_despues_cents, pago_id, descripcion,"
            " creado_por, creado_en) VALUES (?,?,?,?,?,?,?,?)",
            (p["cuenta_id"], "PAGO", p["monto_cents"], nuevo_saldo, pago_id, f"Pago {p['folio']}",
             usuario_id, ahora()),
        )
        con.execute("UPDATE pagos SET estatus='PAGADO', pagado_por=?, pagado_en=? WHERE id=?",
                    (usuario_id, ahora(), pago_id))
        _historial(con, "pago", pago_id, "APROBADO", "PAGADO", usuario_id)

        monto, _, pagado, _ = montos_gasto(con, p["gasto_id"])
        nuevo_est = "PAGADO" if pagado >= monto else "PAGO_PARCIAL"
        if nuevo_est != g["estatus"]:
            con.execute("UPDATE gastos SET estatus = ? WHERE id = ?", (nuevo_est, p["gasto_id"]))
            _historial(con, "gasto", p["gasto_id"], g["estatus"], nuevo_est, usuario_id, f"Por pago {p['folio']}")


def cancelar_pago(con, pago_id, usuario_id, motivo):
    if not motivo or not motivo.strip():
        raise ReglaNegocio("Indica el motivo de cancelación")
    with transaccion(con):
        p = uno(con, "SELECT estatus FROM pagos WHERE id = ?", (pago_id,))
        if p is None:
            raise ReglaNegocio("El pago no existe")
        if p["estatus"] not in ("PENDIENTE", "APROBADO"):
            raise ReglaNegocio(f"No se puede cancelar un pago {p['estatus'].lower()}")
        con.execute("UPDATE pagos SET estatus='CANCELADO', cancelado_por=?, cancelado_en=?, motivo_cancelacion=?"
                    " WHERE id=?", (usuario_id, ahora(), motivo.strip(), pago_id))
        _historial(con, "pago", pago_id, p["estatus"], "CANCELADO", usuario_id, motivo.strip())


# ------------------------------------------------------------------ cuentas
def crear_cuenta(con, nombre, banco, numero, moneda="MXN"):
    if not (nombre and banco and numero):
        raise ReglaNegocio("Nombre, banco y número son obligatorios")
    if uno(con, "SELECT 1 FROM cuentas_bancarias WHERE numero = ?", (numero.strip(),)):
        raise ReglaNegocio("Ya existe una cuenta con ese número")
    with transaccion(con):
        cur = con.execute("INSERT INTO cuentas_bancarias (nombre, banco, numero, moneda, creado_en) VALUES (?,?,?,?,?)",
                          (nombre.strip(), banco.strip(), numero.strip(), moneda, ahora()))
    return cur.lastrowid


def depositar(con, cuenta_id, monto, usuario_id, descripcion=None):
    cents = a_cents(monto)
    with transaccion(con):
        c = uno(con, "SELECT saldo_cents FROM cuentas_bancarias WHERE id = ?", (cuenta_id,))
        if c is None:
            raise ReglaNegocio("La cuenta no existe")
        nuevo = c["saldo_cents"] + cents
        con.execute("UPDATE cuentas_bancarias SET saldo_cents = ? WHERE id = ?", (nuevo, cuenta_id))
        con.execute("INSERT INTO movimientos (cuenta_id, tipo, monto_cents, saldo_despues_cents, descripcion,"
                    " creado_por, creado_en) VALUES (?,?,?,?,?,?,?)",
                    (cuenta_id, "DEPOSITO", cents, nuevo, descripcion or "Depósito", usuario_id, ahora()))
    return nuevo
