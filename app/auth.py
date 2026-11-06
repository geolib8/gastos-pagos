import secrets
from functools import wraps

from flask import (Blueprint, abort, flash, g, jsonify, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash

from .db import get_db, uno

bp = Blueprint("auth", __name__)


def verificar(username, password):
    u = uno(get_db(), "SELECT * FROM usuarios WHERE username = ? AND activo = 1", (username or "",))
    if u and check_password_hash(u["password_hash"], password or ""):
        return u
    return None


@bp.before_app_request
def cargar_usuario():
    uid = session.get("uid")
    g.usuario = uno(get_db(), "SELECT * FROM usuarios WHERE id = ?", (uid,)) if uid else None


def login_requerido(vista):
    @wraps(vista)
    def envuelta(*a, **kw):
        if g.usuario is None:
            return redirect(url_for("auth.login", next=request.path))
        return vista(*a, **kw)
    return envuelta


def solo_admin(vista):
    @wraps(vista)
    def envuelta(*a, **kw):
        if g.usuario is None:
            return redirect(url_for("auth.login", next=request.path))
        if g.usuario["rol"] != "admin":
            flash("Tu usuario no tiene permiso para esta acción (requiere rol admin).", "danger")
            return redirect(request.referrer or url_for("main.dashboard"))
        return vista(*a, **kw)
    return envuelta


def basic_auth(vista):
    """HTTP Basic para la API. También acepta la sesión del navegador para
    poder abrir los endpoints desde la misma app."""
    @wraps(vista)
    def envuelta(*a, **kw):
        if g.usuario is None:
            cred = request.authorization
            u = verificar(cred.username, cred.password) if cred else None
            if u is None:
                resp = jsonify(error="No autorizado", detalle="Usa autenticación HTTP Basic")
                resp.status_code = 401
                resp.headers["WWW-Authenticate"] = 'Basic realm="api-gastos"'
                return resp
            g.usuario = u
        return vista(*a, **kw)
    return envuelta


# --- CSRF sencillo: un token por sesión que va en cada formulario POST
def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def revisar_csrf():
    if request.method == "POST" and not request.path.startswith("/api/"):
        enviado, esperado = request.form.get("csrf"), session.get("csrf")
        if not enviado or not esperado or not secrets.compare_digest(enviado, esperado):
            abort(400, "Token CSRF inválido, recarga la página")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = verificar(request.form.get("username"), request.form.get("password"))
        if u:
            csrf = session.get("csrf")
            session.clear()
            session["uid"] = u["id"]
            if csrf:
                session["csrf"] = csrf
            destino = request.args.get("next") or ""
            if not destino.startswith("/") or destino.startswith("//"):
                destino = url_for("main.dashboard")
            return redirect(destino)
        flash("Usuario o contraseña incorrectos", "danger")
    return render_template("login.html")


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
