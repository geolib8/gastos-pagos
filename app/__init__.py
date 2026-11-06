import os
from pathlib import Path

import click
from flask import Flask, jsonify, request

from . import db as dbmod


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-cambiar-en-produccion"),
        DATABASE=os.environ.get("DATABASE_PATH", os.path.join(app.instance_path, "gastos.db")),
        SEED_DEMO=os.environ.get("SEED_DEMO", "1") == "1",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        JSON_SORT_KEYS=False,
    )
    if config:
        app.config.update(config)
    app.json.sort_keys = False

    dbmod.init_app(app)
    from . import api, auth, views
    from .auth import csrf_token, revisar_csrf
    app.register_blueprint(auth.bp)
    app.register_blueprint(views.bp)
    app.register_blueprint(api.bp)
    app.before_request(revisar_csrf)

    @app.template_filter("dinero")
    def dinero(cents):
        return f"${(cents or 0) / 100:,.2f}"

    @app.context_processor
    def globales():
        return {"csrf_token": csrf_token}

    @app.errorhandler(404)
    def no_existe(e):
        if request.path.startswith("/api/"):
            return jsonify(error="Recurso no encontrado"), 404
        return e

    with app.app_context():
        con = dbmod.conectar(app.config["DATABASE"])
        dbmod.crear_tablas(con)
        if app.config["SEED_DEMO"]:
            from .seed import cargar
            cargar(con)
        con.close()

    @app.cli.command("seed")
    def seed_cmd():
        """Carga datos de demo si la base está vacía."""
        from .seed import cargar
        con = dbmod.conectar(app.config["DATABASE"])
        click.echo("Datos cargados" if cargar(con) else "La base ya tenía datos")
        con.close()

    @app.cli.command("reset-db")
    def reset_cmd():
        """Borra la base y la vuelve a crear con datos de demo."""
        Path(app.config["DATABASE"]).unlink(missing_ok=True)
        con = dbmod.conectar(app.config["DATABASE"])
        dbmod.crear_tablas(con)
        from .seed import cargar
        cargar(con)
        con.close()
        click.echo("Base reiniciada")

    return app
