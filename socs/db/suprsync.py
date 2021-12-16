import argparse
import os
from sqlalchemy import (Column, create_engine, Integer, String, BLOB, DateTime,
                        Boolean)
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from socs.util import get_md5sum

import argparse

TABLE_VERSION = 0
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
        timestamp : datetime
            Timestamp that file was added to db
        copied : Datetime, optional
            Time at which file was transfered
        removed : Datetime, optional
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
    timestamp = Column(DateTime, nullable=False)
    remote_md5sum = Column(String)
    copied = Column(DateTime)
    removed = Column(DateTime)
    failed_copy_attempts = Column(Integer, default=0)


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
        if not os.path.exists(os.path.dirname(db_path)):
            os.makedirs(os.path.dirname(db_path))

        self._engine = create_engine(f'sqlite:///{db_path}', echo=echo)
        self.Session = sessionmaker(bind=self._engine)

        if create_all:
            Base.metadata.create_all(self._engine)

    def add_file(local_path, remote_path, archive_name, local_md5sum=None):
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
        if local_md5sum is None:
            local_md5sum = get_md5sum(local_path)
        session = self.Session()

        file = SupRsyncFile(
            local_path=local_path,
            local_md5sum=local_md5sum,
        )
        session.add(file)
        session.commit()


    def get_session(self):
        """
        Returns database session
        """
        return self._sessionmaker()


if __name__ == '__main__':
    ss = SupRsyncFilesManager('/data/so/databases/suprsync.db')
    parser = argparse.ArgumentParser()


