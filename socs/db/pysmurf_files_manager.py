"""
Script to create, update, or drop the `pysmurf_files` database
"""
import argparse
import mysql.connector
import getpass


class Column:
    def __init__(self, name, type, opts=""):
        self.name, self.type, self.opts = name, type, opts

    def __str__(self):
        return " ".join([self.name, self.type, self.opts])


columns = [Column(*args) for args in [
    ("id", "INT", "NOT NULL AUTO_INCREMENT PRIMARY KEY"),
    ("path", "VARCHAR(260)", "UNIQUE NOT NULL"),
    ("timestamp", "TIMESTAMP"),
    ("format" ,"VARCHAR(32)"),
    ("type", "VARCHAR(32)"),
    ("site", "VARCHAR(32)"),
    ("instance_id", "VARCHAR(32)"),
    ("copied", "TINYINT(1)"),
    ("failed_copy_attempts", "INT"),
    ("md5sum", "BINARY(16)", "NOT NULL"),
    ("pysmurf_version", "VARCHAR(64)"),
    ("socs_version", "VARCHAR(64)"),
    ("script_path", "VARCHAR(64)")
]]


def create_table(cur, update=True):
    """
    Creates new pysmurf_files table from scratch.

    Args:
        cur (MySQL Cursor):
            cursor to files db
        update (optional, bool):
            Add additional columns if existing table is not up to date.
    """

    cur.execute("SHOW TABLES;")
    table_names = [x[0] for x in cur.fetchall()]

    if 'pysmurf_files' not in table_names:
        print("Creating pysmurf_files table...")
        col_strings = [str(c) for c in columns]
        query = "CREATE TABLE pysmurf_files ({});".format(", ".join(col_strings))

        try:
            cur.execute(query)
            print("Created table pysmurf_files")
        except mysql.connector.errors.ProgrammingError as e:
            print(e)
    elif update:
        print("Found pysmurf_files table. Calling update_columns")
        update_columns(cur)
    else:
        print("Found pysmurf_files table and not updating")


def update_columns(cur):
    """
    Makes sure columns of existing table are up to date, and adds any that are
    missing.
    """
    cur.execute("DESCRIBE pysmurf_files");
    existing_cols = [c[0] for c in cur.fetchall()]

    try:
        for c in columns:
            if c.name not in existing_cols:
                cur.execute("ALTER TABLE pysmurf_files ADD {}".format(str(c)))
                print("Added column {}".format(c.name))
    except mysql.connector.errors.ProgrammingError as e:
        print(e)


def drop_table(cur):
    """
    Drops pysmurf_files.
    """
    try:
        cur.execute("DROP TABLE pysmurf_files;")
        con.commit()
        print("pysmurf_files dropped.")
    except mysql.connector.errors.ProgrammingError as e:
        print(e)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('cmd', choices=['create', 'update', 'drop'])
    parser.add_argument('--password', '-p', type=str,
                        help="Password for development database")
    args = parser.parse_args()

    sql_config = {
        'user': 'development',
        'database': 'files',
        'passwd': args.password
    }
    if sql_config['passwd'] is None:
        sql_config['passwd'] = getpass.getpass("Password for development db: ")

    con = mysql.connector.connect(**sql_config)
    cur = con.cursor()
    try:
        if args.cmd == 'create':
            create_table(con)
            con.commit()
        elif args.cmd == 'update':
            update_columns(con)
            con.commit()
        elif args.cmd == 'drop':
            while True:
                resp = input("Are you sure you want to drop pysmurf_files? [y/n]: ")
                if resp.lower().strip() == 'y':
                    drop_table(con)
                    con.commit()
                    break
                elif resp.lower().strip() == 'n':
                    break
                else:
                    print("Could not recognize input")
    finally:
        print("Closing connection")
        con.close()

