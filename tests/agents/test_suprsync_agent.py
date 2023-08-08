import os
import time

import numpy as np
import txaio

from socs.db.suprsync import (SupRsyncFileHandler, SupRsyncFilesManager,
                              TimecodeDir)

txaio.use_twisted()


def test_suprsync_files_manager(tmp_path):
    """
    Tests table creation and the create_file / add_file functions of the
    SupRsyncFilesManager.
    """

    srfm = SupRsyncFilesManager(tmp_path / 'test.db')
    fpath = tmp_path / 'test.txt'
    fpath.write_text('test')
    srfm.add_file(str(fpath.absolute()), 'test.txt', 'test')


def test_timecode_dirs(tmp_path):
    txaio.start_logging(level='info')
    txaio.make_logger()
    db_path = str(tmp_path / 'test.db')
    dest = tmp_path / 'dest'
    dest.mkdir()
    dest = str(dest)

    data_dir = tmp_path / 'data'
    data_dir.mkdir()

    remote_basedir = dest
    archive_name = 'test'

    srfm = SupRsyncFilesManager(db_path)

    tc = time.time() // 1e5
    tcs = np.arange(tc - 5, tc + 1, dtype=int).tolist()
    print(tcs)

    file_data = np.zeros(10)
    files = []
    for tc in tcs:
        tc_dir = data_dir / str(tc)
        tc_dir.mkdir()

        for i in range(10):
            fname = tc_dir / f'{i}.npy'
            np.save(fname, file_data)
            remote_path = f'{tc}/{i}.npy'
            srfm.add_file(fname, remote_path, archive_name)

    # This is done in the suprsync run process
    handler = SupRsyncFileHandler(srfm, 'test', remote_basedir)
    handler.copy_files()

    sync_id = 'test_sync'
    srfm.update_all_timecode_dirs('test', data_dir, sync_id)

    handler.copy_files()

    session = srfm.Session()
    tcdirs = session.query(TimecodeDir).all()
    print("TCDirs:")
    for tcdir in tcdirs:
        print(tcdir.timecode, tcdir.completed, tcdir.synced, tcdir.finalized,
              tcdir.finalize_file_id)

    # Check that all but one timecode dirs have been successfully copied
    finalize_files = []
    for root, _, files in os.walk(remote_basedir):
        for f in files:
            if f.endswith('finalized.yaml'):
                finalize_files.append(os.path.join(root, f))

    print(f"Finalize timestamp: {srfm.get_finalized_until('test')}")
    print(srfm.get_archive_stats(archive_name))

    assert (len(finalize_files) == len(tcs) - 1)


def test_suprsync_handle_files(tmp_path):
    """
    Tests file handling
    """
    txaio.start_logging(level='info')
    txaio.make_logger()
    db_path = str(tmp_path / 'test.db')
    dest = tmp_path / 'dest'
    dest.mkdir()
    dest = str(dest)

    data_dir = tmp_path / 'data'
    data_dir.mkdir()

    remote_basedir = dest

    srfm = SupRsyncFilesManager(db_path)

    nfiles = 50
    file_data = np.zeros(10000)

    archive_name = 'test'
    for i in range(nfiles):
        fname = f"{i}.npy"
        path = str(data_dir / fname)
        np.save(path, file_data)
        srfm.add_file(path, f'test_remote/{fname}', archive_name,
                      deletable=True)

    fname = "dont_delete.npy"
    path = str(data_dir / fname)
    np.save(path, file_data)
    srfm.add_file(path, f'test_remote/{fname}', archive_name,
                  deletable=False)

    # This is done in the suprsync run process
    handler = SupRsyncFileHandler(srfm, 'test', remote_basedir)
    handler.copy_files()
    handler.delete_files(0)

    # Check data path is empty
    assert len(os.listdir(data_dir)) == 1

    ncopied = len(os.listdir(os.path.join(remote_basedir, 'test_remote')))
    assert ncopied == nfiles + 1
