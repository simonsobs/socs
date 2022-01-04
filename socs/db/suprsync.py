import argparse
import os
from sqlalchemy import (Column, create_engine, Integer, String, BLOB, DateTime,
                        Float, Boolean)
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from socs.util import get_md5sum
import time
import txaio

import argparse
import subprocess

TABLE_VERSION = 0


def todict(obj):
    """ Return the object's dict excluding private attributes,
    sqlalchemy state and relationship attributes.
    """
    excl = ('_sa_adapter', '_sa_instance_state')
    return {k: v for k, v in vars(obj).items() if not k.startswith('_') and
            not any(hasattr(v, a) for a in excl)}


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

    def __str__(self):
        d = todict(self)
        s = "SupRsyncFile:\n"
        s += "\n".join([
            f"    {k}: {v}"
            for k, v in d.items()
        ])
        return s


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

    def create_file(self, local_path, remote_path, archive_name,
                    local_md5sum=None, timestamp=None):
        """
        Creates SupRsyncFiles object.

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
            timestamp:
                Timestamp of file. If None is specified, will use the current
                time.
        """

        if local_md5sum is None:
            local_md5sum = get_md5sum(local_path)

        if timestamp is None:
            timestamp = time.time()

        file = SupRsyncFile(
            local_path=local_path, local_md5sum=local_md5sum,
            remote_path=remote_path, archive_name=archive_name,
            timestamp=timestamp
        )

        return file

    def add_file(self, local_path, remote_path, archive_name,
                 local_md5sum=None, timestamp=None):
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
        """
        file = self.create_file(local_path, remote_path, archive_name,
                    local_md5sum=local_md5sum, timestamp=timestamp)

        session = self.Session()
        session.add(file)
        session.commit()

    def get_next_file(self, archive_name, session=None, delete_after=None,
                      max_copy_attempts=None):
        if session is None:
            session = self.Session()
        query = session.query(SupRsyncFile).filter(
            SupRsyncFile.removed == None,
            SupRsyncFile.archive_name == archive_name
        )
        if max_copy_attempts is not None:
            query.filter(SupRsyncFile.failed_copy_attempts < max_copy_attempts)

        files = query.all()
        for f in files:
            if f.local_md5sum == f.remote_md5sum:
                if delete_after is None:
                    continue
                if time.time() - f.timestamp > delete_after:
                    # This file needs to be removed
                    return f
                else:
                    continue
            return f

    def get_session(self):
        """
        Returns database session
        """
        return self.Session()


class SupRsyncFileHandler:
    """
    Helper class to handle files in the suprsync db and copy them to their
    dest / delete them if enough time has passed.
    """
    def __init__(self, file_manager, remote_basedir, delete_after=None,
                 ssh_host=None, ssh_key=None, cmd_timeout=5, copy_timeout=30):
        self.ssh_host = ssh_host
        self.ssh_key = ssh_key
        self.remote_basedir = remote_basedir
        self.delete_after = delete_after
        self.log = txaio.make_logger()
        self.cmd_timeout = cmd_timeout
        self.copy_timeout = copy_timeout


    def run_on_remote(self, cmd):
        """
        Runs a command on the remote server (or locally if none is set)

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

        self.log.debug(f"Running: {' '.join(_cmd)}")
        res = subprocess.run(_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             timeout=self.cmd_timeout)
        if res.stderr:
            self.log.error("stderr for cmd: {cmd}\n{err}",
                           cmd=_cmd, err=res.stderr.decode())
        # To many ssh commands in to short a period will break things
        time.sleep(1)
        return res

    def copy_file(self, file):
        """
        Attempts to copy a file to its dest.

        Args
        ----
        file : SupRsyncFile
            file to be copied

        Returns
        --------
        res : str or bool
            Returns False if unsuccessful, and the md5sum calculated on the
            remote server if successful.
        """
        remote_path = os.path.join(self.remote_basedir, file.remote_path)

        # Creates directory on dest server:
        res = self.run_on_remote(['mkdir', '-p', os.path.dirname(remote_path)])
        if res.returncode != 0:
            self.log.error("remote mkdir failed:\n{e}", e=res.stderr)
            return False

        if self.ssh_host is not None:
            dest = self.ssh_host + ':' + remote_path
        else:
            dest = remote_path

        cmd = ['rsync', '-t']
        if self.ssh_key is not None:
            cmd.extend(['--rsh', f'ssh -i {self.ssh_key}'])

        cmd.extend([file.local_path, dest])
        self.log.debug("Running: " + ' '.join(cmd))
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             timeout=self.copy_timeout)
        time.sleep(1)


        if res.returncode != 0:
            self.log.error("Rsync failed for file {path}!\nstderr: {err}",
                           path=file.local_path, err=res.stderr.decode())
            return False

        res = self.run_on_remote(['md5sum', remote_path])
        if res.returncode != 0:
            return False
        else:
            return res.stdout.decode().split()[0]

    def handle_file(self, file, session):
        """
        Handles operation of an un-removed SupRsyncFile. Will attempt to copy,
        calculate the remote md5sum, and remove from the local host if enough
        time has passed.

        Args
        ----
        file : SupRsyncFile
            file to be copied
        """
        # File must have been removed for some reason
        if not os.path.exists(file.local_path):
            self.log.warn(
                "File {path} does not exist! Setting removed time to 0.",
                path=file.local_path
            )
            file.removed = 0
            return

        # Check that file md5sum matches whatever it was before
        current_md5sum = get_md5sum(file.local_path)
        if current_md5sum != file.local_md5sum:
            self.log.warn(
                "Md5sum of {path} has changed! Resetting it in the db and "
                "trying to copy", path=file.local_path)
            file.local_md5sum = current_md5sum

        if file.local_md5sum != file.remote_md5sum:
            self.log.info("Copying file: {path}", path=file.local_path)
            md5sum = self.copy_file(file)
            if md5sum is False:  # Copy command failed with exit code != 0
                self.log.warn(
                    "Failed to copy {local} (attempts: {c})",
                    local=file.local_path, c=file.failed_copy_attempts
                )
                file.failed_copy_attempts += 1
                return

            file.remote_md5sum = md5sum
            file.copied = time.time()
            if md5sum != file.local_md5sum:
                self.log.warn(
                    "Copied {local} but md5sum does not match (attempts: {c})",
                    local=file.local_path, c=file.failed_copy_attempts
                )
                file.failed_copy_attempts += 1
            else:
                dest = os.path.join(self.remote_basedir, file.remote_path)
                if self.ssh_host is not None:
                    dest = self.ssh_host + ':' + dest
                self.log.info("Successfully copied {local} to {dest}",
                               local=file.local_path, dest=dest)

        if self.delete_after is None:
            return

        if file.local_md5sum == file.remote_md5sum:
            if time.time() - file.timestamp > self.delete_after:
                self.log.info(f"Deleting {file.local_path}")
                os.remove(file.local_path)
                file.removed = time.time()

