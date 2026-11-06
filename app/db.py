import sqlite3
from contextlib import contextmanager
from pathlib import Path

from flask import current_app, g

SCHEMA = Path(__file__).with_name("schema.sql")


def conectar(ruta):
    con = sqlite3.connect(ruta, timeout=10, isolation_level=None)  # autocommit; las transacciones las abro yo
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def get_db():
    if "db" not in g:
        g.db = conectar(current_app.config["DATABASE"])
    return g.db


def cerrar_db(_=None):
    con = g.pop("db", None)
    if con is not None:
        con.close()


@contextmanager
def transaccion(con):
    """BEGIN IMMEDIATE toma el lock de escritura desde el inicio, así dos
    requests no pueden leer el mismo saldo y descontarlo dos veces."""
    con.execute("BEGIN IMMEDIATE")
    try:
        yield con
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise


def crear_tablas(con):
    con.executescript(SCHEMA.read_text(encoding="utf-8"))


def uno(con, sql, params=()):
    return con.execute(sql, params).fetchone()


def todos(con, sql, params=()):
    return con.execute(sql, params).fetchall()


def init_app(app):
    app.teardown_appcontext(cerrar_db)
