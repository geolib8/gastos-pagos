"""Datos de demo. Se cargan solos la primera vez que arranca la app con la
base vacía (ver create_app), o a mano con:  flask --app wsgi seed"""
import os
import secrets

from werkzeug.security import generate_password_hash

from . import services as sv
from .db import uno

PROVEEDORES = [
    ("Papelería La Moderna", "PMO010203AB1", "ventas@lamoderna.mx"),
    ("Servicios de Limpieza del Bajío", "SLB150611KJ2", "contacto@limpiezabajio.mx"),
    ("CFE Suministrador", "CSS160330CP7", None),
    ("Telmex", "TME840315KT6", None),
    ("Transportes Hernández", "THE990801QR4", "facturas@thernandez.com"),
    ("Soluciones TI Querétaro", "STQ201112MN8", "admin@stiqro.mx"),
    ("Inmobiliaria Centro Sur", "ICS080505HG3", None),
]
CATEGORIAS = ["Papelería", "Servicios", "Renta", "Transporte", "Tecnología", "Mantenimiento", "Honorarios"]

# (proveedor, categoría, descripción, monto, fecha, vencimiento, qué hacer)
GASTOS = [
    (7, 3, "Renta oficina mayo", 28500, "2026-05-01", "2026-05-05", "pagado"),
    (3, 2, "Luz abril-mayo", 4870.50, "2026-05-12", "2026-05-25", "pagado"),
    (1, 1, "Papelería trimestral", 3215.80, "2026-05-20", "2026-06-05", "pagado"),
    (7, 3, "Renta oficina junio", 28500, "2026-06-01", "2026-06-05", "pagado"),
    (6, 5, "Licencias Microsoft 365 (12 usuarios)", 21480, "2026-06-15", "2026-06-30", "pagado"),
    (5, 4, "Fletes junio", 12400, "2026-06-28", "2026-07-10", "cancelado"),
    (7, 3, "Renta oficina julio", 28500, "2026-07-01", "2026-07-05", "pagado"),
    (2, 6, "Limpieza julio-agosto", 9800, "2026-07-30", "2026-08-15", "pagado"),
    (4, 2, "Internet y telefonía agosto", 2150, "2026-08-05", "2026-08-20", "pagado"),
    (7, 3, "Renta oficina agosto", 28500, "2026-08-01", "2026-08-05", "pagado"),
    (6, 5, "Laptops (3) para equipo de ventas", 64500, "2026-09-10", "2026-10-10", "parcial"),
    (5, 4, "Fletes septiembre", 15750, "2026-09-25", "2026-10-15", "pagado"),
    (7, 3, "Renta oficina octubre", 28500, "2026-10-01", "2026-10-05", "pagado"),
    (3, 2, "Luz septiembre-octubre", 5320.40, "2026-10-14", "2026-10-30", "pago_aprobado"),
    (2, 6, "Limpieza octubre", 4900, "2026-10-28", "2026-11-10", "pago_pendiente"),
    (7, 3, "Renta oficina noviembre", 28500, "2026-11-01", "2026-11-05", "aprobado"),
    (1, 1, "Tóner y hojas", 1870, "2026-11-03", "2026-11-20", "pendiente"),
    (5, 4, "Fletes octubre", 13200, "2026-11-04", "2026-11-25", "pendiente"),
    (6, 7, "Consultoría implementación ERP (anticipo)", 45000, "2026-11-05", "2026-11-30", "pendiente"),
]


def usuarios_demo():
    return [
        ("admin", "Ana Martínez (Admin)", os.environ.get("ADMIN_PASSWORD") or "Rgv2026!admin", "admin"),
        ("capturista", "Luis Pérez (Capturista)", os.environ.get("CAPTURISTA_PASSWORD") or "Rgv2026!captura", "capturista"),
    ]


def cargar(con):
    if uno(con, "SELECT COUNT(*) n FROM usuarios")["n"]:
        return False
    for username, nombre, pw, rol in usuarios_demo():
        con.execute("INSERT INTO usuarios (username, nombre, password_hash, rol) VALUES (?,?,?,?)",
                    (username, nombre, generate_password_hash(pw), rol))
    admin = uno(con, "SELECT id FROM usuarios WHERE username='admin'")["id"]
    capt = uno(con, "SELECT id FROM usuarios WHERE username='capturista'")["id"]

    for p in PROVEEDORES:
        con.execute("INSERT INTO proveedores (nombre, rfc, email) VALUES (?,?,?)", p)
    for c in CATEGORIAS:
        con.execute("INSERT INTO categorias (nombre) VALUES (?)", (c,))

    bbva = sv.crear_cuenta(con, "Operación", "BBVA", "0123456789")
    banorte = sv.crear_cuenta(con, "Nómina y proveedores", "Banorte", "0987654321")
    sv.crear_cuenta(con, "Reserva", "Santander", "5566778899")
    sv.depositar(con, bbva, 250000, admin, "Saldo inicial")
    sv.depositar(con, banorte, 180000, admin, "Saldo inicial")
    sv.depositar(con, 3, 60000, admin, "Saldo inicial")

    def pago(gid, cuenta, monto, aprobar=True, efectuar=True):
        pid, _ = sv.generar_pago(con, gid, cuenta, monto, capt, secrets.token_hex(8))
        if aprobar:
            sv.aprobar_pago(con, pid, admin)
        if efectuar:
            sv.efectuar_pago(con, pid, admin)
        return pid

    for i, (prov, cat, desc, monto, fecha, venc, accion) in enumerate(GASTOS):
        gid = sv.crear_gasto(con, capt, prov, cat, desc, monto, fecha, venc)
        if accion == "pendiente":
            continue
        if accion == "cancelado":
            sv.cancelar_gasto(con, gid, admin, "Factura duplicada del proveedor")
            continue
        sv.aprobar_gasto(con, gid, admin)
        cuenta = bbva if i % 2 == 0 else banorte
        if accion == "pagado":
            pago(gid, cuenta, monto)
        elif accion == "parcial":
            pago(gid, bbva, 30000)  # anticipo; quedan 34,500 por pagar
        elif accion == "pago_aprobado":
            pago(gid, cuenta, monto, efectuar=False)
        elif accion == "pago_pendiente":
            pago(gid, cuenta, monto, aprobar=False, efectuar=False)
    # un pago cancelado para que se vea el flujo en la lista
    gid = uno(con, "SELECT id FROM gastos WHERE descripcion='Renta oficina noviembre'")["id"]
    pid = pago(gid, banorte, 28500, aprobar=False, efectuar=False)
    sv.cancelar_pago(con, pid, admin, "Se pagará desde la cuenta de Operación")
    _fechas_realistas(con)
    return True


def _fechas_realistas(con):
    """El seed corre en un solo momento; aquí se reparten las fechas según la
    fecha de cada gasto para que historial, movimientos y gráficas tengan sentido."""
    con.executescript("""
    BEGIN;
    UPDATE gastos SET creado_en = fecha_gasto || ' 09:15:00',
        aprobado_en  = CASE WHEN aprobado_en  IS NOT NULL THEN fecha_gasto || ' 12:40:00' END,
        cancelado_en = CASE WHEN cancelado_en IS NOT NULL THEN date(fecha_gasto, '+2 day') || ' 10:05:00' END;
    UPDATE pagos SET
        creado_en    = (SELECT date(fecha_gasto, '+1 day') FROM gastos WHERE id = pagos.gasto_id) || ' 10:00:00',
        aprobado_en  = CASE WHEN aprobado_en IS NOT NULL THEN
                       (SELECT date(fecha_gasto, '+1 day') FROM gastos WHERE id = pagos.gasto_id) || ' 16:20:00' END,
        pagado_en    = CASE WHEN pagado_en IS NOT NULL THEN
                       (SELECT min(fecha_vencimiento, date('now','localtime')) FROM gastos WHERE id = pagos.gasto_id) || ' 11:30:00' END,
        cancelado_en = CASE WHEN cancelado_en IS NOT NULL THEN
                       (SELECT date(fecha_gasto, '+2 day') FROM gastos WHERE id = pagos.gasto_id) || ' 09:45:00' END;
    UPDATE movimientos SET creado_en = '2026-05-01 08:00:00' WHERE tipo = 'DEPOSITO';
    UPDATE movimientos SET creado_en = (SELECT pagado_en FROM pagos WHERE id = movimientos.pago_id) WHERE tipo = 'PAGO';
    UPDATE historial SET creado_en = CASE estatus_nuevo
            WHEN 'PENDIENTE' THEN (SELECT creado_en FROM gastos WHERE id = entidad_id)
            WHEN 'APROBADO'  THEN (SELECT aprobado_en FROM gastos WHERE id = entidad_id)
            WHEN 'CANCELADO' THEN (SELECT cancelado_en FROM gastos WHERE id = entidad_id)
            ELSE (SELECT max(pagado_en) FROM pagos WHERE gasto_id = entidad_id AND estatus = 'PAGADO') END
        WHERE entidad = 'gasto';
    UPDATE historial SET creado_en = CASE estatus_nuevo
            WHEN 'PENDIENTE' THEN (SELECT creado_en FROM pagos WHERE id = entidad_id)
            WHEN 'APROBADO'  THEN (SELECT aprobado_en FROM pagos WHERE id = entidad_id)
            WHEN 'PAGADO'    THEN (SELECT pagado_en FROM pagos WHERE id = entidad_id)
            ELSE (SELECT cancelado_en FROM pagos WHERE id = entidad_id) END
        WHERE entidad = 'pago';
    COMMIT;
    """)
    # con las fechas movidas, recalculo el saldo corrido de cada cuenta en orden cronológico
    for (cid,) in con.execute("SELECT id FROM cuentas_bancarias").fetchall():
        saldo = 0
        for m in con.execute("SELECT id, tipo, monto_cents FROM movimientos WHERE cuenta_id = ?"
                             " ORDER BY creado_en, id", (cid,)).fetchall():
            saldo += m["monto_cents"] if m["tipo"] == "DEPOSITO" else -m["monto_cents"]
            con.execute("UPDATE movimientos SET saldo_despues_cents = ? WHERE id = ?", (saldo, m["id"]))
