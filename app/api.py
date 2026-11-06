"""API REST de solo lectura (GET). Autenticación HTTP Basic."""
from flask import Blueprint, jsonify, request

from .auth import basic_auth
from .db import get_db, todos, uno
from .services import montos_gasto
from .views import ESTATUS_GASTO, ESTATUS_PAGO, SQL_GASTOS, SQL_PAGOS

bp = Blueprint("api", __name__, url_prefix="/api/v1")


def pesos(cents):
    return round((cents or 0) / 100, 2)


def paginar(sql, params):
    page = max(request.args.get("page", 1, type=int), 1)
    per_page = min(max(request.args.get("per_page", 20, type=int), 1), 100)
    db = get_db()
    total = uno(db, f"SELECT COUNT(*) AS n FROM ({sql})", params)["n"]
    filas = todos(db, f"{sql} LIMIT ? OFFSET ?", (*params, per_page, (page - 1) * per_page))
    meta = {"page": page, "per_page": per_page, "total": total, "pages": (total + per_page - 1) // per_page}
    return filas, meta


def gasto_json(r):
    return {
        "id": r["id"], "folio": r["folio"], "descripcion": r["descripcion"],
        "proveedor": {"id": r["proveedor_id"], "nombre": r["proveedor"]},
        "categoria": r["categoria"], "monto": pesos(r["monto_cents"]),
        "pagado": pesos(r["pagado_cents"]), "saldo_pendiente": pesos(r["monto_cents"] - r["pagado_cents"]),
        "estatus": r["estatus"], "fecha_gasto": r["fecha_gasto"], "fecha_vencimiento": r["fecha_vencimiento"],
        "creado_en": r["creado_en"], "aprobado_en": r["aprobado_en"], "cancelado_en": r["cancelado_en"],
        "motivo_cancelacion": r["motivo_cancelacion"],
    }


def pago_json(r):
    return {
        "id": r["id"], "folio": r["folio"], "monto": pesos(r["monto_cents"]), "estatus": r["estatus"],
        "gasto": {"id": r["gasto_id"], "folio": r["gasto_folio"]},
        "cuenta": {"id": r["cuenta_id"], "nombre": r["cuenta"], "banco": r["banco"]},
        "proveedor": r["proveedor"], "referencia": r["referencia"],
        "creado_en": r["creado_en"], "aprobado_en": r["aprobado_en"], "pagado_en": r["pagado_en"],
        "cancelado_en": r["cancelado_en"], "motivo_cancelacion": r["motivo_cancelacion"],
    }


def cuenta_json(r):
    return {"id": r["id"], "nombre": r["nombre"], "banco": r["banco"], "numero": r["numero"],
            "moneda": r["moneda"], "saldo": pesos(r["saldo_cents"]), "activa": bool(r["activa"])}


def no_encontrado(que):
    return jsonify(error=f"{que} no encontrado"), 404


@bp.get("/")
@basic_auth
def indice():
    return jsonify(version="1.0", endpoints=[
        "GET /api/v1/resumen",
        "GET /api/v1/gastos?estatus=&proveedor_id=&page=&per_page=",
        "GET /api/v1/gastos/<id>",
        "GET /api/v1/pagos?estatus=&gasto_id=&cuenta_id=&page=&per_page=",
        "GET /api/v1/pagos/<id>",
        "GET /api/v1/cuentas",
        "GET /api/v1/cuentas/<id>",
        "GET /api/v1/cuentas/<id>/movimientos?page=&per_page=",
        "GET /api/v1/proveedores",
        "GET /api/v1/categorias",
    ])


@bp.get("/resumen")
@basic_auth
def resumen():
    db = get_db()
    gastos = {e: {"cantidad": 0, "monto": 0.0} for e in ESTATUS_GASTO}
    for r in todos(db, "SELECT estatus, COUNT(*) n, SUM(monto_cents) s FROM gastos GROUP BY estatus"):
        gastos[r["estatus"]] = {"cantidad": r["n"], "monto": pesos(r["s"])}
    pagos = {e: {"cantidad": 0, "monto": 0.0} for e in ESTATUS_PAGO}
    for r in todos(db, "SELECT estatus, COUNT(*) n, SUM(monto_cents) s FROM pagos GROUP BY estatus"):
        pagos[r["estatus"]] = {"cantidad": r["n"], "monto": pesos(r["s"])}
    saldo = uno(db, "SELECT COALESCE(SUM(saldo_cents),0) s FROM cuentas_bancarias WHERE activa=1")["s"]
    return jsonify(gastos=gastos, pagos=pagos, saldo_total_cuentas=pesos(saldo))


@bp.get("/gastos")
@basic_auth
def gastos():
    sql, params = SQL_GASTOS + " WHERE 1=1", []
    est = request.args.get("estatus", "").upper()
    if est:
        if est not in ESTATUS_GASTO:
            return jsonify(error=f"estatus inválido, usa uno de {ESTATUS_GASTO}"), 400
        sql += " AND g.estatus = ?"; params.append(est)
    if request.args.get("proveedor_id", type=int):
        sql += " AND g.proveedor_id = ?"; params.append(request.args.get("proveedor_id", type=int))
    filas, meta = paginar(sql + " ORDER BY g.id DESC", params)
    return jsonify(data=[gasto_json(r) for r in filas], meta=meta)


@bp.get("/gastos/<int:gasto_id>")
@basic_auth
def gasto(gasto_id):
    db = get_db()
    r = uno(db, SQL_GASTOS + " WHERE g.id = ?", (gasto_id,))
    if r is None:
        return no_encontrado("Gasto")
    data = gasto_json(r)
    _, comprometido, _, pendiente = montos_gasto(db, gasto_id)
    data["comprometido_en_pagos"] = pesos(comprometido)
    data["disponible_para_pagar"] = pesos(pendiente)
    data["pagos"] = [pago_json(p) for p in todos(db, SQL_PAGOS + " WHERE p.gasto_id = ? ORDER BY p.id", (gasto_id,))]
    data["historial"] = [dict(h) for h in todos(
        db, "SELECT h.estatus_anterior, h.estatus_nuevo, h.comentario, h.creado_en, u.username AS usuario"
            " FROM historial h JOIN usuarios u ON u.id = h.usuario_id WHERE entidad='gasto' AND entidad_id=?"
            " ORDER BY h.id", (gasto_id,))]
    return jsonify(data=data)


@bp.get("/pagos")
@basic_auth
def pagos():
    sql, params = SQL_PAGOS + " WHERE 1=1", []
    est = request.args.get("estatus", "").upper()
    if est:
        if est not in ESTATUS_PAGO:
            return jsonify(error=f"estatus inválido, usa uno de {ESTATUS_PAGO}"), 400
        sql += " AND p.estatus = ?"; params.append(est)
    for campo in ("gasto_id", "cuenta_id"):
        v = request.args.get(campo, type=int)
        if v:
            sql += f" AND p.{campo} = ?"; params.append(v)
    filas, meta = paginar(sql + " ORDER BY p.id DESC", params)
    return jsonify(data=[pago_json(r) for r in filas], meta=meta)


@bp.get("/pagos/<int:pago_id>")
@basic_auth
def pago(pago_id):
    r = uno(get_db(), SQL_PAGOS + " WHERE p.id = ?", (pago_id,))
    if r is None:
        return no_encontrado("Pago")
    return jsonify(data=pago_json(r))


@bp.get("/cuentas")
@basic_auth
def cuentas():
    filas = todos(get_db(), "SELECT * FROM cuentas_bancarias ORDER BY id")
    return jsonify(data=[cuenta_json(r) for r in filas])


@bp.get("/cuentas/<int:cuenta_id>")
@basic_auth
def cuenta(cuenta_id):
    r = uno(get_db(), "SELECT * FROM cuentas_bancarias WHERE id = ?", (cuenta_id,))
    if r is None:
        return no_encontrado("Cuenta")
    return jsonify(data=cuenta_json(r))


@bp.get("/cuentas/<int:cuenta_id>/movimientos")
@basic_auth
def movimientos(cuenta_id):
    if uno(get_db(), "SELECT 1 FROM cuentas_bancarias WHERE id = ?", (cuenta_id,)) is None:
        return no_encontrado("Cuenta")
    sql = ("SELECT m.*, p.folio AS pago_folio FROM movimientos m LEFT JOIN pagos p ON p.id = m.pago_id"
           " WHERE m.cuenta_id = ? ORDER BY m.creado_en DESC, m.id DESC")
    filas, meta = paginar(sql, (cuenta_id,))
    data = [{"id": r["id"], "tipo": r["tipo"], "monto": pesos(r["monto_cents"]),
             "saldo_despues": pesos(r["saldo_despues_cents"]), "pago_folio": r["pago_folio"],
             "descripcion": r["descripcion"], "fecha": r["creado_en"]} for r in filas]
    return jsonify(data=data, meta=meta)


@bp.get("/proveedores")
@basic_auth
def proveedores():
    filas = todos(get_db(), "SELECT id, nombre, rfc, email FROM proveedores ORDER BY nombre")
    return jsonify(data=[dict(r) for r in filas])


@bp.get("/categorias")
@basic_auth
def categorias():
    return jsonify(data=[dict(r) for r in todos(get_db(), "SELECT id, nombre FROM categorias ORDER BY nombre")])
