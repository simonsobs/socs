#!/usr/bin/env python3
"""
Utility script for interacting with the suprsync db.
"""
import argparse
import os
import time

from tqdm.auto import trange

from socs.db.suprsync import SupRsyncFile, SupRsyncFilesManager


def check_func(args):
    srfm = SupRsyncFilesManager(args.db, create_all=False)
    session = srfm.Session()
    files = session.query(SupRsyncFile).filter(
        SupRsyncFile.local_path == args.file
    ).all()
    for file in files:
        print('-' * 80)
        print(file)
        print('-' * 80)


def next_func(args):
    srfm = SupRsyncFilesManager(args.db, create_all=False)

    files = srfm.get_copyable_files(args.archive_name, num_files=1)
    if not files:
        print("No more files left to be copied")
    else:
        print(files[0])


def list_func(args):
    srfm = SupRsyncFilesManager(args.db, create_all=False)
    files = srfm.get_copyable_files(args.archive_name)
    if not files:
        print("No files left to be copied")
        return

    for i, f in enumerate(files):
        print(f"{i}: {f.local_path}")


def add_local_files_func(args):
    srfm = SupRsyncFilesManager(args.db, create_all=args.create_db)

    args.local_root = os.path.abspath(args.local_root)

    known_files = srfm.get_known_files(args.archive_name)
    known_paths = [f.local_path for f in known_files]
    local_paths = []
    remote_paths = []
    now = time.time()

    for root, _, files in os.walk(args.local_root):
        for file in files:
            path = os.path.join(root, file)
            path = os.path.abspath(path)
            if path not in known_paths and now - os.stat(path).st_mtime >= args.last_edit:
                local_paths.append(path)
                remote_paths.append(os.path.relpath(path, args.local_root))

    if args.dry:
        print("Dry run\n" + 40 * '-')

        if len(local_paths) == 0:
            print("No files to add")
            return

        print(f"Would add {len(local_paths)} files, including:")
        n = min(len(local_paths), 10)
        for i in range(n):
            print(f"{i}: {local_paths[i]} --> {remote_paths[i]}")
        return

    print(f"Adding {len(local_paths)} files to the add to {args.db} from {args.local_root}")
    for i in trange(len(local_paths)):
        srfm.add_file(local_paths[i], remote_paths[i], args.archive_name)


def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()

    default_db = os.environ.get("SUPRSYNC_DB")

    check_parser = subparsers.add_parser(
        'check', help="Checks suprsync file entry for a given local file.")
    check_parser.set_defaults(func=check_func)
    check_parser.add_argument('file', type=str,
                              help="local path to check in the suprsync db")
    check_parser.add_argument('--db', default=default_db, help='db path')

    next_parser = subparsers.add_parser(
        'next',
        help="Returns file info for next file to be handled in the db"
    )
    next_parser.set_defaults(func=next_func)
    next_parser.add_argument('archive_name',
                             help='Name of archive to get next file')
    next_parser.add_argument('--db', default=default_db, help='db path')

    list_parser = subparsers.add_parser('list')
    list_parser.set_defaults(func=list_func)
    list_parser.add_argument('archive_name',
                             help='Name of archive to get next file')
    list_parser.add_argument('--db', default=default_db)

    add_local_files_parser = subparsers.add_parser(
        'add-local-files',
        help="Adds all files from a local directory to the suprsync db"
    )
    add_local_files_parser.set_defaults(func=add_local_files_func)
    add_local_files_parser.add_argument(
        'local_root', help="Root directory to search for files")
    add_local_files_parser.add_argument(
        'archive_name', help="Archive to add files to")
    add_local_files_parser.add_argument('--db', default=default_db)
    add_local_files_parser.add_argument('--last-edit', default=60,
                                        help="Only add files that were last edited more than some seconds ago. Default:60")
    add_local_files_parser.add_argument(
        '--create-db', action='store_true',
        help="Create the db if it doesn't exist"
    )
    add_local_files_parser.add_argument('--dry', action='store_true',
                                        help="Does a dry run and prints what files would be added")

    args = parser.parse_args()

    if not hasattr(args, 'func'):
        parser.print_help()
        return

    if args.db is None:
        raise FileNotFoundError("Suprsync DB must be specified either through the --db "
                                "cli-arg or the SUPRSYNC_DB env var")

    args.func(args)


if __name__ == '__main__':
    main()
