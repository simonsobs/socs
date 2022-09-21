import os

import numpy as np
import txaio

from socs.db.suprsync import SupRsyncFileHandler, SupRsyncFilesManager

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
