from socs.db.suprsync import SupRsyncFilesManager, SupRsyncFile
import sys
sys.path.insert(0, '../agents/suprsync/')
from suprsync import SupRsync
import os
from argparse import Namespace

from shutil import rmtree
from ocs.ocs_agent import OpSession

import pytest
from unittest import mock
import txaio
txaio.use_twisted()

@pytest.fixture
def agent(tmp_path):
    """Test fixture to setup a mocked OCSAgent."""

    mock_agent = mock.MagicMock()
    log = txaio.make_logger()
    txaio.start_logging(level='debug')
    mock_agent.log = log
    log.info('Initialized mock OCSAgent')

    dest = tmp_path / 'dest'
    dest.mkdir()
    db_path = str(tmp_path / 'test.db')

    args = Namespace(
        archive_name='test', ssh_host=None, ssh_key=None,
        remote_basedir=str(dest), db_path=db_path,
        delete_after=0., stop_on_exception=True
    )

    return SupRsync(mock_agent, args)

def test_suprsync_files_manager(tmp_path):
    """
    Tests table creation and the create_file / add_file functions of the
    SupRsyncFilesManager.
    """

    srfm = SupRsyncFilesManager(tmp_path / 'test.db')
    fpath = tmp_path / 'test.txt'
    fpath.write_text('test')
    srfm.add_file(str(fpath.absolute()), 'test.txt', 'test')

def test_suprsync_agent_handle_file(agent):
    srfm = SupRsyncFilesManager(agent.db_path)
    test_path = os.path.join(
        os.path.dirname(agent.db_path), 'test.txt'
    )
    with open(test_path, 'w') as f:
        f.write("test")
    archive_name = 'test'
    remote_relpath = 'test.txt'
    srfm.add_file(test_path, remote_relpath, archive_name)

    # This is done in the suprsync run process
    with srfm.Session.begin() as session:
        files = session.query(SupRsyncFile).filter(
            SupRsyncFile.removed == None,
            SupRsyncFile.archive_name == archive_name
        ).all()
        for file in files:
            agent.handle_file(file)

    # Check file was successfully copied and removed
    remote_abspath = os.path.join(agent.remote_basedir, remote_relpath)
    assert not os.path.exists(test_path)
    assert os.path.exists(remote_abspath)
    session = srfm.Session()
    remaining_files = session.query(SupRsyncFile).filter(
        SupRsyncFile.removed == None
    ).all()
    assert not len(remaining_files)
