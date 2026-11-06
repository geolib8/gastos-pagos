-- Montos en centavos (INTEGER) para no arrastrar errores de punto flotante.

CREATE TABLE IF NOT EXISTS usuarios (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT    NOT NULL UNIQUE,
    nombre          TEXT    NOT NULL,
    password_hash   TEXT    NOT NULL,
    rol             TEXT    NOT NULL CHECK (rol IN ('admin', 'capturista')),
    activo          INTEGER NOT NULL DEFAULT 1,
    creado_en       TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS cuentas_bancarias (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre          TEXT    NOT NULL,
    banco           TEXT    NOT NULL,
    numero          TEXT    NOT NULL UNIQUE,
    moneda          TEXT    NOT NULL DEFAULT 'MXN',
    saldo_cents     INTEGER NOT NULL DEFAULT 0 CHECK (saldo_cents >= 0),
    activa          INTEGER NOT NULL DEFAULT 1,
    creado_en       TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS proveedores (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre          TEXT    NOT NULL,
    rfc             TEXT    UNIQUE,
    email           TEXT,
    creado_en       TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS categorias (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre          TEXT    NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS gastos (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    folio               TEXT    NOT NULL UNIQUE,
    proveedor_id        INTEGER NOT NULL REFERENCES proveedores(id),
    categoria_id        INTEGER NOT NULL REFERENCES categorias(id),
    descripcion         TEXT    NOT NULL,
    monto_cents         INTEGER NOT NULL CHECK (monto_cents > 0),
    fecha_gasto         TEXT    NOT NULL,
    fecha_vencimiento   TEXT,
    estatus             TEXT    NOT NULL DEFAULT 'PENDIENTE'
                        CHECK (estatus IN ('PENDIENTE','APROBADO','PAGO_PARCIAL','PAGADO','CANCELADO')),
    creado_por          INTEGER NOT NULL REFERENCES usuarios(id),
    creado_en           TEXT    NOT NULL DEFAULT (datetime('now')),
    aprobado_por        INTEGER REFERENCES usuarios(id),
    aprobado_en         TEXT,
    cancelado_por       INTEGER REFERENCES usuarios(id),
    cancelado_en        TEXT,
    motivo_cancelacion  TEXT
);

CREATE TABLE IF NOT EXISTS pagos (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    folio               TEXT    NOT NULL UNIQUE,
    gasto_id            INTEGER NOT NULL REFERENCES gastos(id),
    cuenta_id           INTEGER NOT NULL REFERENCES cuentas_bancarias(id),
    monto_cents         INTEGER NOT NULL CHECK (monto_cents > 0),
    estatus             TEXT    NOT NULL DEFAULT 'PENDIENTE'
                        CHECK (estatus IN ('PENDIENTE','APROBADO','PAGADO','CANCELADO')),
    referencia          TEXT,
    -- token del formulario: si llega dos veces el mismo, no se crea otro pago
    token               TEXT    NOT NULL UNIQUE,
    creado_por          INTEGER NOT NULL REFERENCES usuarios(id),
    creado_en           TEXT    NOT NULL DEFAULT (datetime('now')),
    aprobado_por        INTEGER REFERENCES usuarios(id),
    aprobado_en         TEXT,
    pagado_por          INTEGER REFERENCES usuarios(id),
    pagado_en           TEXT,
    cancelado_por       INTEGER REFERENCES usuarios(id),
    cancelado_en        TEXT,
    motivo_cancelacion  TEXT
);

CREATE TABLE IF NOT EXISTS movimientos (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    cuenta_id           INTEGER NOT NULL REFERENCES cuentas_bancarias(id),
    tipo                TEXT    NOT NULL CHECK (tipo IN ('DEPOSITO','PAGO')),
    monto_cents         INTEGER NOT NULL CHECK (monto_cents > 0),
    saldo_despues_cents INTEGER NOT NULL,
    -- UNIQUE: un pago solo puede generar un cargo en la cuenta
    pago_id             INTEGER UNIQUE REFERENCES pagos(id),
    descripcion         TEXT,
    creado_por          INTEGER NOT NULL REFERENCES usuarios(id),
    creado_en           TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS historial (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    entidad             TEXT    NOT NULL CHECK (entidad IN ('gasto','pago')),
    entidad_id          INTEGER NOT NULL,
    estatus_anterior    TEXT,
    estatus_nuevo       TEXT    NOT NULL,
    usuario_id          INTEGER NOT NULL REFERENCES usuarios(id),
    comentario          TEXT,
    creado_en           TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_gastos_estatus ON gastos(estatus);
CREATE INDEX IF NOT EXISTS idx_pagos_gasto ON pagos(gasto_id);
CREATE INDEX IF NOT EXISTS idx_pagos_estatus ON pagos(estatus);
CREATE INDEX IF NOT EXISTS idx_mov_cuenta ON movimientos(cuenta_id);
CREATE INDEX IF NOT EXISTS idx_hist_entidad ON historial(entidad, entidad_id);
