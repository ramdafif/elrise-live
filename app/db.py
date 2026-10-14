from contextlib import contextmanager
from dataclasses import dataclass

import mysql.connector
from flask import current_app, g


@dataclass
class Result:
    lastrowid: int
    rowcount: int


def connect(database=True):
    config = current_app.config
    options = {
        "host": config["MYSQL_HOST"],
        "port": config["MYSQL_PORT"],
        "user": config["MYSQL_USER"],
        "password": config["MYSQL_PASSWORD"],
        "charset": "utf8mb4",
        "autocommit": True,
        "connection_timeout": 5,
        "time_zone": "+07:00",
    }
    if database:
        options["database"] = config["MYSQL_DATABASE"]
    if config["MYSQL_SSL_CA"]:
        options.update(ssl_ca=config["MYSQL_SSL_CA"], ssl_verify_cert=True, ssl_verify_identity=True)
    return mysql.connector.connect(**options)


def get_db():
    if "db" not in g:
        g.db = connect()
    return g.db


def query(sql, params=(), one=False):
    cursor = get_db().cursor(dictionary=True, buffered=True)
    try:
        cursor.execute(sql, params)
        return cursor.fetchone() if one else cursor.fetchall()
    finally:
        cursor.close()


def execute(sql, params=()):
    cursor = get_db().cursor(buffered=True)
    try:
        cursor.execute(sql, params)
        return Result(cursor.lastrowid, cursor.rowcount)
    finally:
        cursor.close()


@contextmanager
def transaction():
    connection = get_db()
    connection.start_transaction(isolation_level="READ COMMITTED")
    try:
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def close_db(error=None):
    connection = g.pop("db", None)
    if connection:
        connection.close()
