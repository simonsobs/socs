import os
import subprocess
import tempfile
import time

import txaio
import yaml
from sqlalchemy import (Boolean, Column, Float, ForeignKey, Integer, String,
                        asc, create_engine)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from socs.util import get_md5sum

TABLE_VERSION = 0
txaio.use_twisted()


Base = declarative_base()

# Number of days after which a timecode directory will be marked as complete if
# the subsequent timecode dir has not been created.
DAYS_TO_COMPLETE_TCDIR = 1


class TimecodeDir(Base):
    """
    Table for information about 'timecode' directories. These are directories
    in particular archives such as 'smurf' that we care about tracking whether
    or not they've completed syncing.

    Timecode directories must start with a 5-digit time-code.

    Attributes
    ---------------
    timecode: int
        Timecode for directory. Must be 5 digits, and will be roughly 1 a day.
    archive_name : str
        Archive the directory is in.
    completed : bool
        True if we expect no more files to be added to this directory.
    synced : bool
        True if all files in this directory have been synced to the remote.
    finalized : bool
        True if the 'finalization' file has been written and added to the db.
    finalize_file_id : int
        ID for the SupRsyncFile object that is the finalization file for this
        timecode dir.
    """
    __tablename__ = f"timecode_dirs_v{TABLE_VERSION}"
    id = Column(Integer, primary_key=True)
    timecode = Column(Integer, nullable=False)
    archive_name = Column(String, nullable=False)
    completed = Column(Boolean, default=False)
    synced = Column(Boolean, default=False)
    finalized = Column(Boolean, default=False)
    finalize_file_id = Column(Integer, ForeignKey(f"supersync_v{TABLE_VERSION}.id"))


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
        ignore : Bool
            If true, file will be ignored by SupRsync agent and not
            included in `finalized_until`.
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
    ignore = Column(Boolean, default=False)

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


def split_path(path):
    """Splits path into a list where each element is a subdirectory"""
    return os.path.normpath(path).strip('/').split('/')


def check_timecode(file: SupRsyncFile):
    """
    Tries to extract timecode from the remote path. If it fails, returns
    None.
    """
    split = split_path(file.remote_path)
    try:
        timecode = int(split[0])
        if len(str(timecode)) != 5:  # Timecode must be 5 digits
            raise ValueError("Timecode not 5 digits")
        return timecode
    except ValueError:
        return None


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

    def __init__(
        self, db_path: str, create_all: bool = True, echo: bool = False,
        pool_size: int = 5, max_overflow: int = 10
    ) -> None:
        db_path = os.path.abspath(db_path)
        if not os.path.exists(os.path.dirname(db_path)):
            os.makedirs(os.path.dirname(db_path))

        self._engine = create_engine(
            f'sqlite:///{db_path}', echo=echo,
            pool_size=pool_size, max_overflow=max_overflow,
        )
        self.Session = sessionmaker(bind=self._engine)

        if create_all:
            Base.metadata.create_all(self._engine)

    def get_archive_stats(self, archive_name, session=None):
        if session is None:
            session = self.Session()

        files = session.query(SupRsyncFile).filter(
            SupRsyncFile.archive_name == archive_name,
        ).order_by(asc(SupRsyncFile.timestamp)).all()

        finalized_until = None
        num_files_to_copy = 0
        last_file_added = ''
        last_file_copied = ''

        for f in files:
            last_file_added = f.local_path
            if (f.local_md5sum == f.remote_md5sum):
                last_file_copied = f.local_path

            if (not f.ignore) and (f.local_md5sum != f.remote_md5sum):
                num_files_to_copy += 1

            if finalized_until is None and not (f.ignore):
                if f.local_md5sum != f.remote_md5sum:
                    finalized_until = f.timestamp - 1

        # There are no more uncopied files that aren't ignored
        if finalized_until is None:
            finalized_until = time.time()

        stats = {
            'finalized_until': finalized_until,
            'num_files': len(files),
            'uncopied_files': num_files_to_copy,
            'last_file_added': last_file_added,
            'last_file_copied': last_file_copied,
        }

        return stats

    def get_finalized_until(self, archive_name, session=None):
        """
        Returns a timetamp for which all files preceding are either successfully
        copied, or ignored. If all files are copied, returns the current time.

        Args
        ------
            archive_name : String
                Archive name to get finalized_until for
            session : sqlalchemy session
                SQLAlchemy session to use. If none is passed, will create a new
                session
        """
        if session is None:
            session = self.Session()

        query = session.query(SupRsyncFile).filter(
            SupRsyncFile.archive_name == archive_name,
        ).order_by(asc(SupRsyncFile.timestamp))

        for file in query.all():
            if file.ignore:
                continue
            if file.local_md5sum != file.remote_md5sum:
                return file.timestamp - 1
        else:
            return time.time()

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
                self._add_file_tcdir(file, session)
                session.add(file)
        else:
            self._add_file_tcdir(file, session)
            session.add(file)

        return file

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

        if max_copy_attempts is None:
            max_copy_attempts = 2**10

        query = session.query(SupRsyncFile).filter(
            SupRsyncFile.removed == None,  # noqa: E711
            SupRsyncFile.archive_name == archive_name,
            SupRsyncFile.failed_copy_attempts < max_copy_attempts,
            SupRsyncFile.ignore == False,  # noqa: E712
        )

        files = []
        for f in query.all():
            if f.local_md5sum != f.remote_md5sum:
                files.append(f)
            if num_files is not None:
                if len(files) >= num_files:
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
            SupRsyncFile.removed == None,  # noqa: E711
            SupRsyncFile.archive_name == archive_name,
            SupRsyncFile.deletable,
        )

        files = []
        now = time.time()
        for f in query.all():
            if f.local_md5sum == f.remote_md5sum:
                if now > f.timestamp + delete_after:
                    files.append(f)

        return files

    def get_known_files(self, archive_name, session=None, min_ctime=None):
        """Gets all files.  This can be used to help avoid
        double-registering files.

        Args
        -----
            archive_name : str
                Name of archive to pull files from
            session : sqlalchemy session
                Session to use to query files.
            min_ctime : float, optional
                minimum ctime to use when querying files.

        """
        if session is None:
            session = self.Session()

        if min_ctime is None:
            min_ctime = 0

        query = session.query(SupRsyncFile).filter(
            SupRsyncFile.archive_name == archive_name,
            SupRsyncFile.timestamp > min_ctime,
        ).order_by(asc(SupRsyncFile.timestamp))

        return list(query.all())

    def _add_file_tcdir(self, file: SupRsyncFile, session):
        """
        Creates and adds a TimecodeDir for a file if possible.  This will
        attempt to extract the timecode from the remote filename, and will
        create a new TimecodeDir if it doesn't already exist.
        """
        # print(file.remote_path)
        tc = check_timecode(file)
        if tc is None:
            return None

        tcdir = session.query(TimecodeDir).filter(
            TimecodeDir.timecode == tc,
            TimecodeDir.archive_name == file.archive_name,
        ).one_or_none()

        if tcdir is not None:
            return tcdir

        tcdir = TimecodeDir(timecode=tc, archive_name=file.archive_name)
        session.add(tcdir)
        return tcdir

    def create_all_timecode_dirs(self, archive_name, min_ctime=None):
        with self.Session.begin() as session:
            files = self.get_known_files(
                archive_name, session=session, min_ctime=min_ctime)
            for file in files:
                self._add_file_tcdir(file, session)

    def update_all_timecode_dirs(self, archive_name, file_root, sync_id):
        with self.Session.begin() as session:
            tcdirs = session.query(TimecodeDir).filter(
                TimecodeDir.archive_name == archive_name,
            ).all()
            for tcdir in tcdirs:
                self._update_tcdir(tcdir, session, file_root, sync_id)

    def _update_tcdir(self, tcdir, session, file_root, sync_id):
        """
        Takes the next series of actions for a timecode dir object.
        - If we expect no more files to be added to the tc dir, marks it as
          complete
        - If all files in the tc dir have been synced, marks it as synced
        - If the tc dir is synced and not finalized, creates the finalization
          file and marks as finalized.
        """
        if tcdir.finalized:
            return

        now = time.time()

        if not tcdir.completed:
            all_tcs = session.query(TimecodeDir.timecode).all()
            for tc, in all_tcs:
                if tc > tcdir.timecode:
                    # Mark as complete if there's a timecode after this one
                    tcdir.completed = True
                    break
            else:
                # No timecodes after this one. Mark after complete if we are
                # over a full day away.
                if (now // 1e5 - tcdir.timecode) > DAYS_TO_COMPLETE_TCDIR:
                    tcdir.completed = True

        # Gets all files in this tcdir
        files = session.query(SupRsyncFile).filter(
            SupRsyncFile.remote_path.like(f'{tcdir.timecode}/%')
        ).all()

        if tcdir.completed and not tcdir.synced:
            for f in files:
                if f.local_md5sum != f.remote_md5sum:
                    break  # File is not synced properly
            else:
                tcdir.synced = True

        if tcdir.synced and not tcdir.finalized:  # Finalize file
            # Get subdirs this suprsync instance is responsible for
            subdirs = set()
            for f in files:
                split = split_path(f.remote_path)
                if len(split) > 2:
                    subdirs.add(split[1])

            tcdir_summary = {
                'timecode': tcdir.timecode,
                'num_files': len(files),
                'subdirs': list(subdirs),
                'finalized_at': now,
                'finalized_until': self.get_finalized_until(tcdir.archive_name),
                'archive_name': tcdir.archive_name,
                'instance_id': sync_id
            }

            tc = int(now // 1e5)
            timestamp = int(now)
            fname = f'{timestamp}_{tcdir.archive_name}_{tcdir.timecode}_finalized.yaml'
            finalize_local_path = os.path.join(
                file_root, str(tc), sync_id, fname,
            )
            finalize_remote_path = os.path.join(
                str(tc), 'suprsync', sync_id, fname
            )
            os.makedirs(os.path.dirname(finalize_local_path), exist_ok=True)
            with open(finalize_local_path, 'w') as f:
                yaml.dump(tcdir_summary, f)

            file = self.add_file(
                finalize_local_path, finalize_remote_path, tcdir.archive_name,
                session=session, timestamp=now
            )
            session.add(file)
            session.flush()

            tcdir.finalized = True
            tcdir.finalize_file_id = file.id


class SupRsyncFileHandler:
    """
    Helper class to handle files in the suprsync db and copy them to their
    dest / delete them if enough time has passed.
    """

    def __init__(self, file_manager, archive_name, remote_basedir,
                 ssh_host=None, ssh_key=None, cmd_timeout=None,
                 copy_timeout=None, compression=None, bwlimit=None,
                 chmod=None):
        self.srfm = file_manager
        self.archive_name = archive_name
        self.ssh_host = ssh_host
        self.ssh_key = ssh_key
        self.remote_basedir = remote_basedir
        self.log = txaio.make_logger()
        self.cmd_timeout = cmd_timeout
        self.copy_timeout = copy_timeout
        self.compression = compression
        self.bwlimit = bwlimit
        self.chmod = chmod

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

        Returns
        -------
            copy_attempts : list of (str, bool)
                Each entry of the list provides the path to the copied file,
                and a bool indicating wheter the remote md5sum matched.
        """
        output = []
        with self.srfm.Session.begin() as session:
            files = self.srfm.get_copyable_files(
                self.archive_name, max_copy_attempts=max_copy_attempts,
                num_files=num_files, session=session
            )

            if not files:
                return []

            if self.ssh_host is not None:
                dest = self.ssh_host + ':' + self.remote_basedir
            else:
                dest = self.remote_basedir

            # Creates temp directory with remote dir structure of symlinks for
            # rsync to copy.
            file_map = {}
            remote_paths = []
            with tempfile.TemporaryDirectory() as tmp_dir:
                self.log.info("Copying files:")
                for file in files:
                    self.log.info(f"- {file.local_path}")
                    tmp_path = os.path.join(tmp_dir, file.remote_path)
                    os.makedirs(os.path.dirname(tmp_path), exist_ok=True)

                    if not os.path.exists(file.local_path):
                        self.log.warn("Cannot find file {path}", path=file.local_path)
                        file.failed_copy_attempts += 1
                        continue

                    if os.path.exists(tmp_path):
                        self.log.warn("Temp file {path} already exists!", path=tmp_path)
                        file.failed_copy_attempts += 1
                        continue

                    os.symlink(file.local_path, tmp_path)

                    remote_path = os.path.normpath(
                        os.path.join(self.remote_basedir, file.remote_path)
                    )
                    remote_paths.append(remote_path)
                    file_map[remote_path] = file

                cmd = ['rsync', '-Lrt']
                if self.chmod:
                    cmd += ['-p', f'--chmod={self.chmod}']
                if self.compression:
                    cmd.append('-z')
                if self.bwlimit:
                    cmd.append(f'--bwlimit={self.bwlimit}')
                if self.ssh_key is not None:
                    cmd.extend(['--rsh', f'ssh -i {self.ssh_key}'])
                cmd.extend([tmp_dir + '/', dest])

                subprocess.run(cmd, check=True, timeout=self.copy_timeout)

            for file in files:
                file.copied = time.time()

            self.log.info("Checksumming on remote.")
            res = self.run_on_remote(['md5sum'] + remote_paths)
            for line in res.stdout.decode().split('\n'):
                split = line.split()

                # If file cannot be found, line will say:
                # "md5sum: file: No such file or directory
                if len(split) != 2:
                    continue

                md5sum, path = line.split()
                key = os.path.normpath(path)
                if key in file_map:
                    file_map[key].remote_md5sum = md5sum

            for file in files:
                md5_ok = (file.remote_md5sum == file.local_md5sum)
                output.append((file.local_path, md5_ok))
                if not md5_ok:
                    file.failed_copy_attempts += 1
                    self.log.info(
                        f"Copy failed for file {file.local_path}! "
                        f"(copy attempts: {file.failed_copy_attempts})"
                    )
                    self.log.info(f"Local md5: {file.local_md5sum}, "
                                  f"remote_md5: {file.remote_md5sum}")

            self.log.info("Copy session complete.")

        return output

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
                        f"File {file.local_path} no longer exists! "
                        "Updating remove time to be 0"
                    )
                    file.removed = 0
