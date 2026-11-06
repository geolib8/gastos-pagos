import base64
import re


def basic(u, p):
    return {"Authorization": "Basic " + base64.b64encode(f"{u}:{p}".encode()).decode()}


def login(client, u="admin", p="Rgv2026!admin"):
    html = client.get("/login").get_data(as_text=True)
    csrf = re.search(r'name="csrf" value="([^"]+)"', html).group(1)
    r = client.post("/login", data={"username": u, "password": p, "csrf": csrf})
    return csrf, r


def test_paginas_requieren_login(client):
    r = client.get("/gastos")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_login_y_paginas(client):
    _, r = login(client)
    assert r.status_code == 302
    for url in ["/", "/gastos", "/gastos/1", "/gastos/nuevo", "/pagos", "/pagos/1", "/cuentas", "/cuentas/1",
                "/proveedores", "/api-docs"]:
        assert client.get(url).status_code == 200, url


def test_login_incorrecto(client):
    _, r = login(client, p="mala")
    assert r.status_code == 200 and "incorrectos" in r.get_data(as_text=True)


def test_api_sin_credenciales(client):
    r = client.get("/api/v1/gastos")
    assert r.status_code == 401 and "WWW-Authenticate" in r.headers


def test_api_endpoints(client):
    h = basic("admin", "Rgv2026!admin")
    for url in ["/api/v1/", "/api/v1/resumen", "/api/v1/gastos", "/api/v1/gastos/1", "/api/v1/pagos",
                "/api/v1/pagos/1", "/api/v1/cuentas", "/api/v1/cuentas/1", "/api/v1/cuentas/1/movimientos",
                "/api/v1/proveedores", "/api/v1/categorias"]:
        r = client.get(url, headers=h)
        assert r.status_code == 200, url
    r = client.get("/api/v1/gastos?estatus=PENDIENTE&per_page=2", headers=h).get_json()
    assert r["meta"]["per_page"] == 2 and all(x["estatus"] == "PENDIENTE" for x in r["data"])
    assert client.get("/api/v1/gastos?estatus=XX", headers=h).status_code == 400
    assert client.get("/api/v1/gastos/9999", headers=h).status_code == 404


def test_capturista_no_puede_aprobar(client):
    csrf, _ = login(client, "capturista", "Rgv2026!captura")
    gid = client.get("/api/v1/gastos?estatus=PENDIENTE").get_json()["data"][0]["id"]
    client.post(f"/gastos/{gid}/aprobar", data={"csrf": csrf})
    assert client.get(f"/api/v1/gastos/{gid}").get_json()["data"]["estatus"] == "PENDIENTE"


def test_flujo_completo_por_web(client):
    csrf, _ = login(client)
    gid = client.get("/api/v1/gastos?estatus=PENDIENTE").get_json()["data"][0]["id"]
    client.post(f"/gastos/{gid}/aprobar", data={"csrf": csrf})
    g = client.get(f"/api/v1/gastos/{gid}").get_json()["data"]
    assert g["estatus"] == "APROBADO"
    datos = {"csrf": csrf, "cuenta_id": 1, "monto": g["monto"], "token": "tok-web"}
    r = client.post(f"/gastos/{gid}/generar-pago", data=datos)
    client.post(f"/gastos/{gid}/generar-pago", data=datos)  # doble envío
    pagos = client.get(f"/api/v1/pagos?gasto_id={gid}").get_json()["data"]
    assert len(pagos) == 1
    pid = pagos[0]["id"]
    client.post(f"/pagos/{pid}/aprobar", data={"csrf": csrf})
    client.post(f"/pagos/{pid}/efectuar", data={"csrf": csrf})
    assert client.get(f"/api/v1/gastos/{gid}").get_json()["data"]["estatus"] == "PAGADO"


def test_post_sin_csrf_rechazado(client):
    login(client)
    assert client.post("/gastos/1/aprobar", data={}).status_code == 400
