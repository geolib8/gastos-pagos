import secrets
from datetime import date

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from . import services as sv
from .auth import login_requerido, solo_admin
from .db import get_db, todos, uno

bp = Blueprint("main", __name__)

ESTATUS_GASTO = ["PENDIENTE", "APROBADO", "PAGO_PARCIAL", "PAGADO", "CANCELADO"]
ESTATUS_PAGO = ["PENDIENTE", "APROBADO", "PAGADO", "CANCELADO"]

SQL_GASTOS = """
SELECT g.*, pr.nombre AS proveedor, c.nombre AS categoria,
       COALESCE((SELECT SUM(monto_cents) FROM pagos WHERE gasto_id = g.id AND estatus = 'PAGADO'), 0) AS pagado_cents,
       COALESCE((SELECT SUM(monto_cents) FROM pagos WHERE gasto_id = g.id
                 AND estatus IN ('PENDIENTE','APROBADO','PAGADO')), 0) AS comprometido_cents
FROM gastos g
JOIN proveedores pr ON pr.id = g.proveedor_id
JOIN categorias c ON c.id = g.categoria_id
"""

SQL_PAGOS = """
SELECT p.*, g.folio AS gasto_folio, g.descripcion AS gasto_desc, pr.nombre AS proveedor,
       cb.nombre AS cuenta, cb.banco
FROM pagos p
JOIN gastos g ON g.id = p.gasto_id
JOIN proveedores pr ON pr.id = g.proveedor_id
JOIN cuentas_bancarias cb ON cb.id = p.cuenta_id
"""


def _ejecutar(fn, *args, ok=None):
    """Corre una regla de negocio y convierte el error en mensaje."""
    try:
        r = fn(get_db(), *args)
        if ok:
            flash(ok, "success")
        return r
    except sv.ReglaNegocio as e:
        flash(str(e), "danger")
        return None


# ------------------------------------------------------------------ dashboard
@bp.route("/")
@login_requerido
def dashboard():
    db = get_db()
    kpi = {
        "saldo": uno(db, "SELECT COALESCE(SUM(saldo_cents),0) s FROM cuentas_bancarias WHERE activa=1")["s"],
        "por_aprobar": uno(db, "SELECT COUNT(*) n, COALESCE(SUM(monto_cents),0) s FROM gastos WHERE estatus='PENDIENTE'"),
        "pagos_por_efectuar": uno(db, "SELECT COUNT(*) n, COALESCE(SUM(monto_cents),0) s FROM pagos WHERE estatus='APROBADO'"),
        "pagado_mes": uno(db, "SELECT COALESCE(SUM(monto_cents),0) s FROM pagos WHERE estatus='PAGADO'"
                              " AND substr(pagado_en,1,7) = ?", (date.today().strftime("%Y-%m"),))["s"],
    }
    abiertos = todos(db, SQL_GASTOS + " WHERE g.estatus IN ('APROBADO','PAGO_PARCIAL') ORDER BY g.fecha_vencimiento")
    kpi["por_pagar"] = sum(r["monto_cents"] - r["pagado_cents"] for r in abiertos)

    por_estatus = {r["estatus"]: r for r in todos(
        db, "SELECT estatus, COUNT(*) n, SUM(monto_cents) s FROM gastos GROUP BY estatus")}
    graf = {
        "estatus": {"labels": ESTATUS_GASTO,
                    "data": [por_estatus[e]["n"] if e in por_estatus else 0 for e in ESTATUS_GASTO]},
        "categorias": [dict(r) for r in todos(db, """
            SELECT c.nombre AS label, SUM(g.monto_cents)/100.0 AS valor FROM gastos g
            JOIN categorias c ON c.id = g.categoria_id WHERE g.estatus <> 'CANCELADO'
            GROUP BY c.nombre ORDER BY valor DESC""")],
        "meses": [dict(r) for r in todos(db, """
            SELECT substr(fecha_gasto,1,7) AS mes,
                   SUM(monto_cents)/100.0 AS registrado,
                   SUM(CASE WHEN estatus IN ('PAGADO','PAGO_PARCIAL') THEN monto_cents ELSE 0 END)/100.0 AS con_pago
            FROM gastos WHERE estatus <> 'CANCELADO' GROUP BY mes ORDER BY mes""")],
        "cuentas": [dict(r) for r in todos(db, "SELECT nombre AS label, saldo_cents/100.0 AS valor"
                                               " FROM cuentas_bancarias WHERE activa=1 ORDER BY nombre")],
    }
    ultimos_pagos = todos(db, SQL_PAGOS + " ORDER BY p.id DESC LIMIT 6")
    return render_template("dashboard.html", kpi=kpi, graf=graf, abiertos=abiertos[:8],
                           ultimos_pagos=ultimos_pagos, hoy=date.today().isoformat())


# ------------------------------------------------------------------ gastos
@bp.route("/gastos")
@login_requerido
def gastos():
    estatus = request.args.get("estatus", "")
    q = request.args.get("q", "").strip()
    sql, params = SQL_GASTOS + " WHERE 1=1", []
    if estatus in ESTATUS_GASTO:
        sql += " AND g.estatus = ?"; params.append(estatus)
    if q:
        sql += " AND (g.folio LIKE ? OR g.descripcion LIKE ? OR pr.nombre LIKE ?)"
        params += [f"%{q}%"] * 3
    filas = todos(get_db(), sql + " ORDER BY g.id DESC", params)
    return render_template("gastos/lista.html", gastos=filas, estatus=estatus, q=q, opciones=ESTATUS_GASTO)


@bp.route("/gastos/nuevo", methods=["GET", "POST"])
@login_requerido
def gasto_nuevo():
    db = get_db()
    if request.method == "POST":
        f = request.form
        gid = _ejecutar(sv.crear_gasto, g.usuario["id"], f.get("proveedor_id", type=int),
                        f.get("categoria_id", type=int), f.get("descripcion"), f.get("monto"),
                        f.get("fecha_gasto") or date.today().isoformat(), f.get("fecha_vencimiento"),
                        ok="Gasto registrado. Queda pendiente de aprobación.")
        if gid:
            return redirect(url_for("main.gasto_detalle", gasto_id=gid))
    return render_template("gastos/nuevo.html",
                           proveedores=todos(db, "SELECT * FROM proveedores ORDER BY nombre"),
                           categorias=todos(db, "SELECT * FROM categorias ORDER BY nombre"),
                           hoy=date.today().isoformat())


@bp.route("/gastos/<int:gasto_id>")
@login_requerido
def gasto_detalle(gasto_id):
    db = get_db()
    gasto = uno(db, SQL_GASTOS + " WHERE g.id = ?", (gasto_id,))
    if gasto is None:
        flash("El gasto no existe", "warning")
        return redirect(url_for("main.gastos"))
    monto, comprometido, pagado, pendiente = sv.montos_gasto(db, gasto_id)
    return render_template(
        "gastos/detalle.html", gasto=gasto, pendiente=pendiente, pagado=pagado, comprometido=comprometido,
        pagos=todos(db, SQL_PAGOS + " WHERE p.gasto_id = ? ORDER BY p.id", (gasto_id,)),
        historial=todos(db, "SELECT h.*, u.nombre AS usuario FROM historial h JOIN usuarios u ON u.id=h.usuario_id"
                            " WHERE entidad='gasto' AND entidad_id=? ORDER BY h.id", (gasto_id,)),
        cuentas=todos(db, "SELECT * FROM cuentas_bancarias WHERE activa=1 ORDER BY nombre"),
        token=secrets.token_urlsafe(16),
    )


@bp.post("/gastos/<int:gasto_id>/aprobar")
@solo_admin
def gasto_aprobar(gasto_id):
    _ejecutar(sv.aprobar_gasto, gasto_id, g.usuario["id"], ok="Gasto aprobado")
    return redirect(url_for("main.gasto_detalle", gasto_id=gasto_id))


@bp.post("/gastos/<int:gasto_id>/cancelar")
@solo_admin
def gasto_cancelar(gasto_id):
    _ejecutar(sv.cancelar_gasto, gasto_id, g.usuario["id"], request.form.get("motivo"), ok="Gasto cancelado")
    return redirect(url_for("main.gasto_detalle", gasto_id=gasto_id))


@bp.post("/gastos/<int:gasto_id>/generar-pago")
@login_requerido
def gasto_generar_pago(gasto_id):
    f = request.form
    r = _ejecutar(sv.generar_pago, gasto_id, f.get("cuenta_id", type=int), f.get("monto"),
                  g.usuario["id"], f.get("token"), f.get("referencia"))
    if r:
        pid, nuevo = r
        flash("Pago generado, queda pendiente de aprobación." if nuevo
              else "Ese pago ya se había generado (envío duplicado), no se creó otro.", "success" if nuevo else "warning")
        return redirect(url_for("main.pago_detalle", pago_id=pid))
    return redirect(url_for("main.gasto_detalle", gasto_id=gasto_id))


# ------------------------------------------------------------------ pagos
@bp.route("/pagos")
@login_requerido
def pagos():
    estatus = request.args.get("estatus", "")
    sql, params = SQL_PAGOS, []
    if estatus in ESTATUS_PAGO:
        sql += " WHERE p.estatus = ?"; params.append(estatus)
    filas = todos(get_db(), sql + " ORDER BY p.id DESC", params)
    return render_template("pagos/lista.html", pagos=filas, estatus=estatus, opciones=ESTATUS_PAGO)


@bp.route("/pagos/<int:pago_id>")
@login_requerido
def pago_detalle(pago_id):
    db = get_db()
    pago = uno(db, SQL_PAGOS + " WHERE p.id = ?", (pago_id,))
    if pago is None:
        flash("El pago no existe", "warning")
        return redirect(url_for("main.pagos"))
    cuenta = uno(db, "SELECT * FROM cuentas_bancarias WHERE id = ?", (pago["cuenta_id"],))
    hist = todos(db, "SELECT h.*, u.nombre AS usuario FROM historial h JOIN usuarios u ON u.id=h.usuario_id"
                     " WHERE entidad='pago' AND entidad_id=? ORDER BY h.id", (pago_id,))
    return render_template("pagos/detalle.html", pago=pago, cuenta=cuenta, historial=hist)


@bp.post("/pagos/<int:pago_id>/aprobar")
@solo_admin
def pago_aprobar(pago_id):
    _ejecutar(sv.aprobar_pago, pago_id, g.usuario["id"], ok="Pago aprobado")
    return redirect(url_for("main.pago_detalle", pago_id=pago_id))


@bp.post("/pagos/<int:pago_id>/efectuar")
@solo_admin
def pago_efectuar(pago_id):
    _ejecutar(sv.efectuar_pago, pago_id, g.usuario["id"], ok="Pago efectuado y descontado de la cuenta")
    return redirect(url_for("main.pago_detalle", pago_id=pago_id))


@bp.post("/pagos/<int:pago_id>/cancelar")
@solo_admin
def pago_cancelar(pago_id):
    _ejecutar(sv.cancelar_pago, pago_id, g.usuario["id"], request.form.get("motivo"), ok="Pago cancelado")
    return redirect(url_for("main.pago_detalle", pago_id=pago_id))


# ------------------------------------------------------------------ cuentas
@bp.route("/cuentas", methods=["GET", "POST"])
@login_requerido
def cuentas():
    db = get_db()
    if request.method == "POST":
        if g.usuario["rol"] != "admin":
            flash("Solo un admin puede dar de alta cuentas", "danger")
        else:
            f = request.form
            _ejecutar(sv.crear_cuenta, f.get("nombre"), f.get("banco"), f.get("numero"), f.get("moneda") or "MXN",
                      ok="Cuenta creada")
        return redirect(url_for("main.cuentas"))
    filas = todos(db, """
        SELECT cb.*,
               COALESCE((SELECT SUM(monto_cents) FROM pagos WHERE cuenta_id = cb.id AND estatus='APROBADO'),0) AS comprometido_cents,
               (SELECT COUNT(*) FROM movimientos WHERE cuenta_id = cb.id) AS n_mov
        FROM cuentas_bancarias cb ORDER BY cb.nombre""")
    return render_template("cuentas/lista.html", cuentas=filas)


@bp.route("/cuentas/<int:cuenta_id>")
@login_requerido
def cuenta_detalle(cuenta_id):
    db = get_db()
    cuenta = uno(db, "SELECT * FROM cuentas_bancarias WHERE id = ?", (cuenta_id,))
    if cuenta is None:
        flash("La cuenta no existe", "warning")
        return redirect(url_for("main.cuentas"))
    movs = todos(db, """SELECT m.*, p.folio AS pago_folio, u.nombre AS usuario FROM movimientos m
                        LEFT JOIN pagos p ON p.id = m.pago_id JOIN usuarios u ON u.id = m.creado_por
                        WHERE m.cuenta_id = ? ORDER BY m.creado_en DESC, m.id DESC""", (cuenta_id,))
    serie = [dict(fecha=m["creado_en"][:10], saldo=m["saldo_despues_cents"] / 100) for m in reversed(movs)]
    return render_template("cuentas/detalle.html", cuenta=cuenta, movimientos=movs, serie=serie)


@bp.post("/cuentas/<int:cuenta_id>/depositar")
@solo_admin
def cuenta_depositar(cuenta_id):
    _ejecutar(sv.depositar, cuenta_id, request.form.get("monto"), g.usuario["id"], request.form.get("descripcion"),
              ok="Depósito registrado")
    return redirect(url_for("main.cuenta_detalle", cuenta_id=cuenta_id))


# ------------------------------------------------------------------ proveedores
@bp.route("/proveedores", methods=["GET", "POST"])
@login_requerido
def proveedores():
    db = get_db()
    if request.method == "POST":
        nombre = (request.form.get("nombre") or "").strip()
        rfc = (request.form.get("rfc") or "").strip().upper() or None
        if not nombre:
            flash("El nombre es obligatorio", "danger")
        elif rfc and uno(db, "SELECT 1 FROM proveedores WHERE rfc = ?", (rfc,)):
            flash("Ya existe un proveedor con ese RFC", "danger")
        else:
            db.execute("INSERT INTO proveedores (nombre, rfc, email) VALUES (?,?,?)",
                       (nombre, rfc, request.form.get("email") or None))
            flash("Proveedor agregado", "success")
        return redirect(url_for("main.proveedores"))
    filas = todos(db, """SELECT pr.*, COUNT(g.id) AS n_gastos,
                                COALESCE(SUM(CASE WHEN g.estatus <> 'CANCELADO' THEN g.monto_cents END),0) AS total_cents
                         FROM proveedores pr LEFT JOIN gastos g ON g.proveedor_id = pr.id
                         GROUP BY pr.id ORDER BY pr.nombre""")
    return render_template("proveedores/lista.html", proveedores=filas)


@bp.route("/api-docs")
@login_requerido
def api_docs():
    return render_template("api_docs.html")
