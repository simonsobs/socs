import hashlib
from typing import ContextManager
from contextlib import contextmanager
import os

on_rtd = os.environ.get('READTHEDOCS') == 'True'
if not on_rtd:
    import mysql.connector


def get_md5sum(filename):
    m = hashlib.md5()

    for line in open(filename, 'rb'):
        m.update(line)
    return m.hexdigest()


@contextmanager
def get_db_connection(**config):
    """
    Mysql connection context manager.

    Same args as mysql.connector:
    https://dev.mysql.com/doc/connector-python/en/connector-python-connectargs.html
    """
    con = mysql.connector.connect(**config)
    try:
        yield con
    finally:
        con.close()
