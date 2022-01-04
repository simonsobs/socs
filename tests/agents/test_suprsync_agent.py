from socs.db.suprsync import SupRsyncFilesManager, SupRsyncFile, SupRsyncFileHandler
import sys
sys.path.insert(0, '../agents/suprsync/')
from suprsync import SupRsync
import os
from argparse import Namespace

from shutil import rmtree
from ocs.ocs_agent import OpSession

import pytest
from unittest import mock


def test_suprsync_files_manager(tmp_path):
    """
    Tests table creation and the create_file / add_file functions of the
    SupRsyncFilesManager.
    """

    srfm = SupRsyncFilesManager(tmp_path / 'test.db')
    fpath = tmp_path / 'test.txt'
    fpath.write_text('test')
    srfm.add_file(str(fpath.absolute()), 'test.txt', 'test')


def test_suprsync_handle_file(tmp_path):
    """
    Tests file handling
    """
    db_path = str(tmp_path / 'test.db')
    dest = tmp_path / 'dest'
    dest.mkdir()
    dest = str(dest)
    remote_basedir = dest

    srfm = SupRsyncFilesManager(db_path)
    test_path = str(tmp_path / 'test.txt')

    with open(test_path, 'w') as f:
        f.write("test")

    archive_name = 'test'
    remote_relpath = 'test.txt'
    srfm.add_file(test_path, remote_relpath, archive_name)

    # This is done in the suprsync run process
    handler = SupRsyncFileHandler(srfm, remote_basedir, delete_after=0)
    with srfm.Session.begin() as session:
        file = srfm.get_next_file(archive_name, session=session)
        handler.handle_file(file, session)

    # Check file was successfully copied and removed
    remote_abspath = os.path.join(remote_basedir, remote_relpath)
    assert not os.path.exists(test_path)
    assert os.path.exists(remote_abspath)
    # Checks that there are no more files left to handle
    assert srfm.get_next_file(archive_name) is None
