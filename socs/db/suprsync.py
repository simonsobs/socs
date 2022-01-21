import os
import time
import subprocess
import tempfile
import txaio

from sqlalchemy import (Column, create_engine, Integer, String, Float, Boolean)
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base

from socs.util import get_md5sum

TABLE_VERSION = 0
txaio.use_twisted()


Base = declarative_base()


class SupRsyncFile(Base):
    """
    Files table utilized by the SupRsync agent.

    Attributes
    ----------
        local_path : String
            Absolute path of the local file to be copied
        local_md5sum : String
            locally calculated checksum
        archive_name : String
            Name of the archive, i.e. `timestreams` or `smurf`. Each archive
            is managed by its own SupRsync instance, so they can be copied to
            different base-dirs or hosts.
        remote_path : String
            Path of the file on the remote server relative to the base-dir.
            specified in the SupRsync agent config.
        remote_md5sum : String, optional
            Md5sum calculated on remote machine
        timestamp : Float
            Timestamp that file was added to db
        copied : Float, optional
            Time at which file was transfered
        removed : Float, optional
            Time at which file was removed from local server.
        failed_copy_attempts : Int
            Number of failed copy attempts
        deletable : Bool
            Whether file should be deleted after copying
    """
    __tablename__ = f"supersync_v{TABLE_VERSION}"

    id = Column(Integer, primary_key=True)
    local_path = Column(String, nullable=False)
    local_md5sum = Column(String, nullable=False)
    archive_name = Column(String, nullable=False)
    remote_path = Column(String, nullable=False)
    timestamp = Column(Float, nullable=False)
    remote_md5sum = Column(String)
    copied = Column(Float)
    removed = Column(Float)
    failed_copy_attempts = Column(Integer, default=0)
    deletable = Column(Boolean, default=True)

    def __str__(self):
        excl = ('_sa_adapter', '_sa_instance_state')
        d = {
            k: v for k, v in vars(self).items()
            if not k.startswith('_') and not any(hasattr(v, a) for a in excl)
        }

        s = "SupRsyncFile:\n"
        s += "\n".join([
            f"    {k}: {v}"
            for k, v in d.items()
        ])
        return s


def create_file(local_path, remote_path, archive_name, local_md5sum=None,
                timestamp=None, deletable=True):
    """
    Creates SupRsyncFiles object.

    Args
    ----
        local_path : String or Path
            Absolute path of the local file to be copied
        remote_path : String
            Path of the file on the remote server relative to the base-dir.
            specified in the SupRsync agent config.
        archive_name : String
            Name of the archive, i.e. `timestreams` or `smurf`. Each archive
            is managed by its own SupRsync instance, so they can be copied to
            different base-dirs or hosts.
        local_md5sum : String, optional
            locally calculated checksum. If not specified, will calculate
            md5sum automatically.
        timestamp:
            Timestamp of file. If None is specified, will use the current
            time.
        deletable : bool
            If true, can be deleted by suprsync agent
    """
    local_path = str(local_path)
    remote_path = str(remote_path)

    if local_md5sum is None:
        local_md5sum = get_md5sum(local_path)

    if timestamp is None:
        timestamp = time.time()

    file = SupRsyncFile(
        local_path=local_path, local_md5sum=local_md5sum,
        remote_path=remote_path, archive_name=archive_name,
        timestamp=timestamp
    )

    if deletable is not None:
        file.deletable = deletable

    return file


class SupRsyncFilesManager:
    """
    Helper class for accessing and adding entries to the SupRsync
    files database.

    Args
    -----
        db_path : path
            path to sqlite db
        create_all : bool
            Create table if it hasn't been generated yet.
        echo : bool
            If true, writes sql statements to stdout
    """
    def __init__(self, db_path, create_all=True, echo=False):
        db_path = os.path.abspath(db_path)
        if not os.path.exists(os.path.dirname(db_path)):
            os.makedirs(os.path.dirname(db_path))

        self._engine = create_engine(f'sqlite:///{db_path}', echo=echo)
        self.Session = sessionmaker(bind=self._engine)

        if create_all:
            Base.metadata.create_all(self._engine)

    def add_file(self, local_path, remote_path, archive_name,
                 local_md5sum=None, timestamp=None, session=None,
                 deletable=True):
        """
        Adds file to the SupRsyncFiles table.

        Args
        ----
            local_path : String
                Absolute path of the local file to be copied
            remote_path : String
                Path of the file on the remote server relative to the base-dir.
                specified in the SupRsync agent config.
            archive_name : String
                Name of the archive, i.e. `timestreams` or `smurf`. Each archive
                is managed by its own SupRsync instance, so they can be copied to
                different base-dirs or hosts.
            local_md5sum : String, optional
                locally calculated checksum. If not specified, will calculate
                md5sum automatically.
            session : sqlalchemy session
                Session to use to add the SupRsyncFile. If None, will create
                a new session and commit afterwards.
            deletable : bool
                If true, can be deleted by suprsync agent
        """
        file = create_file(local_path, remote_path, archive_name,
                           local_md5sum=local_md5sum, timestamp=timestamp,
                           deletable=deletable)
        if session is None:
            with self.Session.begin() as session:
                session.add(file)
        else:
            session.add(file)

    def get_copyable_files(self, archive_name, session=None,
                           max_copy_attempts=None, num_files=None):
        """
        Gets all SupRsyncFiles that are copyable, meaning they satisfy:
         - local and remote md5sums do not match
         - Failed copy attempts is below the max number of attempts

        Args
        ----
            archive_name : string
                Name of archive to get files from
            session : sqlalchemy session
                Session to use to get files. If none is specified, one will
                be created. You need to specify this if you wish to change
                file data and commit afterwards.
            max_copy_attempts : int
                Max number of failed copy atempts
            num_files : int
                Number of files to return
        """
        if session is None:
            session = self.Session()

        query = session.query(SupRsyncFile).filter(
            SupRsyncFile.removed == None,
            SupRsyncFile.archive_name == archive_name,
        )

        if max_copy_attempts is not None:
            query.filter(SupRsyncFile.failed_copy_attempts < max_copy_attempts)

        files = []
        for f in query.all():
            if f.local_md5sum != f.remote_md5sum:
                files.append(f)
            if num_files is not None:
                if len(files) == num_files:
                    break

        return files

    def get_deletable_files(self, archive_name, delete_after, session=None):
        """
        Gets all files that are deletable, meaning that the local and remote
        md5sums match, and they have existed longer than ``delete_after``
        seconds.

        Args
        -----
            archive_name : str
                Name of archive to pull files from
            delete_after : float
                Time since creation (in seconds) for which it's ok to delete
                files.
            session : sqlalchemy session
                Session to use to query files.
        """
        if session is None:
            session = self.Session()

        query = session.query(SupRsyncFile).filter(
            SupRsyncFile.removed == None,
            SupRsyncFile.archive_name == archive_name,
            SupRsyncFile.deletable,
        )

        files = []
        now = time.time()
        for f in query.all():
            if f.local_md5sum == f.remote_md5sum:
                print(f.local_path, f.timestamp)
                if now > f.timestamp + delete_after:
                    files.append(f)

        return files


class SupRsyncFileHandler:
    """
    Helper class to handle files in the suprsync db and copy them to their
    dest / delete them if enough time has passed.
    """
    def __init__(self, file_manager, archive_name, remote_basedir,
                 ssh_host=None, ssh_key=None, cmd_timeout=None,
                 copy_timeout=None):
        self.srfm = file_manager
        self.archive_name = archive_name
        self.ssh_host = ssh_host
        self.ssh_key = ssh_key
        self.remote_basedir = remote_basedir
        self.log = txaio.make_logger()
        self.cmd_timeout = cmd_timeout
        self.copy_timeout = copy_timeout

    def run_on_remote(self, cmd, timeout=None):
        """
        Runs a command on the remote server or locally if ssh_host is None.

        Parameters
        -----------
        cmd : list
            Command to be run
        """
        _cmd = []
        if self.ssh_host is not None:
            _cmd += ['ssh', self.ssh_host]
            if self.ssh_key is not None:
                _cmd.extend(['-i', self.ssh_key])
        _cmd += cmd

        if timeout is None:
            timeout = self.cmd_timeout
        self.log.debug(f"Running: {' '.join(_cmd)}")
        res = subprocess.run(_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             timeout=timeout, check=True)
        if res.stderr:
            self.log.error("stderr for cmd: {cmd}\n{err}",
                           cmd=_cmd, err=res.stderr.decode())
        return res

    def copy_files(self, max_copy_attempts=None, num_files=None):
        """
        Copies a batch of files, and computes remote md5sums.

        Args
        ----
            max_copy_attempts : int
                Max number of failed copy atempts
            num_files : int
                Number of files to return
        """
        with self.srfm.Session.begin() as session:
            files = self.srfm.get_copyable_files(
                self.archive_name, max_copy_attempts=max_copy_attempts,
                num_files=num_files, session=session
            )

            if not files:
                return

            if self.ssh_host is not None:
                dest = self.ssh_host + ':' + self.remote_basedir
            else:
                dest = self.remote_basedir

            # Creates temp directory with remote dir structure of symlinks for
            # rsync to copy.
            file_map = {}
            with tempfile.TemporaryDirectory() as tmp_dir:
                self.log.info("Copying files:")
                for file in files:
                    self.log.info(f"- {file.local_path}")
                    tmp_path = os.path.join(tmp_dir, file.remote_path)
                    os.makedirs(os.path.dirname(tmp_path), exist_ok=True)
                    os.symlink(file.local_path, tmp_path)

                    remote_path = os.path.normpath(
                        os.path.join(self.remote_basedir, file.remote_path)
                    )
                    file_map[remote_path] = file

                cmd = ['rsync', '-Lrt', tmp_dir+'/', dest]
                subprocess.run(cmd, check=True, timeout=self.copy_timeout)

            for file in files:
                file.copied = time.time()

            remote_paths = [
                os.path.join(self.remote_basedir, f.remote_path)
                for f in files
            ]

            res = self.run_on_remote(['md5sum'] + remote_paths)
            for line in res.stdout.decode().split('\n'):
                split = line.split()

                # If file cannot be found, line will say:
                # "md5sum: file: No such file or directory
                if len(split) != 2:
                    continue

                md5sum, path = line.split()
                file_map[os.path.normpath(path)].remote_md5sum = md5sum

    def delete_files(self, delete_after):
        """
        Gets deletable files, deletes them, and updates file info

        Args
        -----
            delete_after : float
                Time since creation (in seconds) for which it's ok to delete
                files.
        """
        with self.srfm.Session.begin() as session:
            files = self.srfm.get_deletable_files(
                self.archive_name, delete_after, session=session
            )
            for file in files:
                if os.path.exists(file.local_path):
                    try:
                        self.log.info(f"Removing file {file.local_path}")
                        os.remove(file.local_path)
                        file.removed = time.time()
                    except PermissionError:
                        self.log.error(
                            f"Permission error: Could not remove {file.local_path}"
                        )
                else:
                    self.log.warn(
                        "File {file.local_path} no longer exists! "
                        "Updating remove time to be 0"
                    )
                    file.removed = 0
