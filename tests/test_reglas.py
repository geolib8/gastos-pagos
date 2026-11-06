import pytest

from app import services as sv
from app.db import uno

ADMIN, CAPT = 1, 2


def nuevo_gasto(con, monto=1000):
    return sv.crear_gasto(con, CAPT, 1, 1, "Prueba", monto, "2026-11-01")


def cuenta_con(con, saldo):
    cid = sv.crear_cuenta(con, "Test", "Banco", f"T{saldo}{id(con)}")
    if saldo:
        sv.depositar(con, cid, saldo, ADMIN)
    return cid


def saldo(con, cid):
    return uno(con, "SELECT saldo_cents FROM cuentas_bancarias WHERE id=?", (cid,))["saldo_cents"]


def estatus_gasto(con, gid):
    return uno(con, "SELECT estatus FROM gastos WHERE id=?", (gid,))["estatus"]


def test_gasto_debe_estar_aprobado_para_pagar(con):
    gid, cid = nuevo_gasto(con), cuenta_con(con, 5000)
    with pytest.raises(sv.ReglaNegocio, match="aprobado"):
        sv.generar_pago(con, gid, cid, 1000, CAPT, "t1")


def test_pago_no_excede_saldo_de_la_cuenta(con):
    gid, cid = nuevo_gasto(con, 1000), cuenta_con(con, 500)
    sv.aprobar_gasto(con, gid, ADMIN)
    with pytest.raises(sv.ReglaNegocio, match="saldo"):
        sv.generar_pago(con, gid, cid, 1000, CAPT, "t1")


def test_saldo_se_revisa_otra_vez_al_efectuar(con):
    gid, cid = nuevo_gasto(con, 1000), cuenta_con(con, 1000)
    sv.aprobar_gasto(con, gid, ADMIN)
    pid, _ = sv.generar_pago(con, gid, cid, 1000, CAPT, "t1")
    sv.aprobar_pago(con, pid, ADMIN)
    # entre la creación y el pago la cuenta se queda sin fondos por otro gasto
    otro = nuevo_gasto(con, 600)
    sv.aprobar_gasto(con, otro, ADMIN)
    p2, _ = sv.generar_pago(con, otro, cid, 600, CAPT, "t2")
    sv.aprobar_pago(con, p2, ADMIN)
    sv.efectuar_pago(con, p2, ADMIN)
    with pytest.raises(sv.ReglaNegocio, match="Saldo insuficiente"):
        sv.efectuar_pago(con, pid, ADMIN)
    assert saldo(con, cid) == 40000


def test_pagos_parciales(con):
    gid, cid = nuevo_gasto(con, 1000), cuenta_con(con, 5000)
    sv.aprobar_gasto(con, gid, ADMIN)
    p1, _ = sv.generar_pago(con, gid, cid, 400, CAPT, "a")
    sv.aprobar_pago(con, p1, ADMIN); sv.efectuar_pago(con, p1, ADMIN)
    assert estatus_gasto(con, gid) == "PAGO_PARCIAL"
    p2, _ = sv.generar_pago(con, gid, cid, 600, CAPT, "b")
    sv.aprobar_pago(con, p2, ADMIN); sv.efectuar_pago(con, p2, ADMIN)
    assert estatus_gasto(con, gid) == "PAGADO"
    assert saldo(con, cid) == 400000


def test_no_se_paga_mas_que_el_gasto(con):
    gid, cid = nuevo_gasto(con, 1000), cuenta_con(con, 5000)
    sv.aprobar_gasto(con, gid, ADMIN)
    sv.generar_pago(con, gid, cid, 700, CAPT, "a")
    with pytest.raises(sv.ReglaNegocio, match="pendiente"):
        sv.generar_pago(con, gid, cid, 400, CAPT, "b")


def test_mismo_token_no_duplica_el_pago(con):
    gid, cid = nuevo_gasto(con, 1000), cuenta_con(con, 5000)
    sv.aprobar_gasto(con, gid, ADMIN)
    p1, nuevo1 = sv.generar_pago(con, gid, cid, 1000, CAPT, "mismo")
    p2, nuevo2 = sv.generar_pago(con, gid, cid, 1000, CAPT, "mismo")
    assert p1 == p2 and nuevo1 and not nuevo2
    assert uno(con, "SELECT COUNT(*) n FROM pagos WHERE gasto_id=?", (gid,))["n"] == 1


def test_un_pago_no_se_efectua_dos_veces(con):
    gid, cid = nuevo_gasto(con, 1000), cuenta_con(con, 5000)
    sv.aprobar_gasto(con, gid, ADMIN)
    pid, _ = sv.generar_pago(con, gid, cid, 1000, CAPT, "a")
    sv.aprobar_pago(con, pid, ADMIN); sv.efectuar_pago(con, pid, ADMIN)
    with pytest.raises(sv.ReglaNegocio, match="ya se efectuó"):
        sv.efectuar_pago(con, pid, ADMIN)
    assert saldo(con, cid) == 400000


def test_gasto_cancelado_no_se_reactiva(con):
    gid = nuevo_gasto(con)
    sv.cancelar_gasto(con, gid, ADMIN, "error")
    for accion in (lambda: sv.aprobar_gasto(con, gid, ADMIN),
                   lambda: sv.cancelar_gasto(con, gid, ADMIN, "otra vez")):
        with pytest.raises(sv.ReglaNegocio):
            accion()
    assert estatus_gasto(con, gid) == "CANCELADO"


def test_cancelar_gasto_cancela_pagos_no_efectuados(con):
    gid, cid = nuevo_gasto(con), cuenta_con(con, 5000)
    sv.aprobar_gasto(con, gid, ADMIN)
    pid, _ = sv.generar_pago(con, gid, cid, 1000, CAPT, "a")
    sv.cancelar_gasto(con, gid, ADMIN, "ya no aplica")
    assert uno(con, "SELECT estatus FROM pagos WHERE id=?", (pid,))["estatus"] == "CANCELADO"
    with pytest.raises(sv.ReglaNegocio):
        sv.generar_pago(con, gid, cid, 100, CAPT, "b")


def test_no_se_cancela_gasto_con_pagos_efectuados(con):
    gid, cid = nuevo_gasto(con, 1000), cuenta_con(con, 5000)
    sv.aprobar_gasto(con, gid, ADMIN)
    pid, _ = sv.generar_pago(con, gid, cid, 500, CAPT, "a")
    sv.aprobar_pago(con, pid, ADMIN); sv.efectuar_pago(con, pid, ADMIN)
    with pytest.raises(sv.ReglaNegocio, match="pagos efectuados"):
        sv.cancelar_gasto(con, gid, ADMIN, "x")


def test_pago_cancelado_libera_el_monto(con):
    gid, cid = nuevo_gasto(con, 1000), cuenta_con(con, 5000)
    sv.aprobar_gasto(con, gid, ADMIN)
    pid, _ = sv.generar_pago(con, gid, cid, 1000, CAPT, "a")
    sv.cancelar_pago(con, pid, ADMIN, "cuenta equivocada")
    pid2, nuevo = sv.generar_pago(con, gid, cid, 1000, CAPT, "b")
    assert nuevo and pid2 != pid


def test_pago_requiere_aprobacion_para_efectuarse(con):
    gid, cid = nuevo_gasto(con), cuenta_con(con, 5000)
    sv.aprobar_gasto(con, gid, ADMIN)
    pid, _ = sv.generar_pago(con, gid, cid, 1000, CAPT, "a")
    with pytest.raises(sv.ReglaNegocio, match="aprobado"):
        sv.efectuar_pago(con, pid, ADMIN)


def test_montos_invalidos(con):
    for m in ("0", "-5", "abc", ""):
        with pytest.raises(sv.ReglaNegocio):
            sv.a_cents(m)
    assert sv.a_cents("1,234.56") == 123456
