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
    def __init__(self, db_path, create_all=True, echo=False):
        if not os.path.exists(os.path.dirname(db_path)):
            os.makedirs(os.path.dirname(db_path))

        self._engine = create_engine(f'sqlite:///{db_path}', echo=echo)
        self.Session = sessionmaker(bind=self._engine)

        if create_all:
            Base.metadata.create_all(self._engine)

    def add_file(local_path, remote_path, archive_name, local_md5sum=None):
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
        return self._sessionmaker()


if __name__ == '__main__':
    ss = SupRsyncFilesManager('/data/so/databases/suprsync.db')
    parser = argparse.ArgumentParser()


