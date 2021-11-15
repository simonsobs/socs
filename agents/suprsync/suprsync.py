import argparse
from socs.db.suprsync import SupRsyncFilesManager, SupRsyncFile
import os
import time
import subprocess
import txaio
import datetime as dt
import traceback

on_rtd = os.environ.get('READTHEDOCS') == 'True'
if not on_rtd:
    from ocs import ocs_agent, site_config

class SupRsync:
    def __init__(self, agent, args):
        self.agent = agent
        self.log = txaio.make_logger()
        self.archive_name = args.archive_name
        self.ssh_host = args.ssh_host
        self.ssh_key = args.ssh_key
        self.remote_basedir = args.remote_basedir
        self.db_path = args.db_path
        self.delete_after = args.delete_after
        self.stop_on_exception = args.stop_on_exception
        self.running = False

    def run_on_remote(self, cmd):
        _cmd = []
        if self.ssh_host is not None:
            _cmd += ['ssh', self.ssh_host]
        _cmd += cmd

        self.log.debug(f"Running: {' '.join(_cmd)}")
        res = subprocess.run(_cmd, capture_output=True, text=True)
        if res.stderr:
            self.log.error("stderr for cmd: {cmd}\n{err}",
                           cmd=_cmd, err=res.stderr)
        return res

    def copy_file(self, file):
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

        cmd = ['rsync', '-t', file.local_path, dest]
        self.log.debug("Running: " + ' '.join(cmd))
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            self.log.error("Rsync failed for file {path}!\nstderr: {err}", path=file.local_path)
            return False

        res = self.run_on_remote(['md5sum', remote_path])
        if res.returncode != 0:
            return False
        else:
            return res.stdout.split()[0]

    def _handle_file(self, file):
        if file.local_md5sum != file.remote_md5sum:
            md5sum = self.copy_file(file)
            if md5sum is False:  # Copy command failed with exit code != 0
                self.log.warn(
                    "Failed to copy {local} (attempts: {c})",
                    local=file.local_path, c=file.failed_copy_attempts
                )
                file.failed_copy_attempts += 1
                return

            file.remote_md5sum = md5sum
            file.copied = dt.datetime.utcnow()
            if md5sum != file.local_md5sum:
                self.log.warn(
                    "Copied {local} but md5sum does not match (attempts: {c})",
                    local=file.local_path, c=file.failed_copy_attempts
                )
                file.failed_copy_attempts += 1
            else:
                self.log.info("Successfully copied {local}",
                               local=file.local_path)

        if self.delete_after is None:
            return

        print(file.removed)
        if file.local_md5sum == file.remote_md5sum:
            if time.time() - file.timestamp.timestamp() > self.delete_after:
                self.log.info(f"Deleting {file.local_path}")
                print("HERE")
                os.remove(file.local_path)
                print("HERE")
                file.removed = dt.datetime.utcnow()


    def run(self, session, params=None):
        srfm = SupRsyncFilesManager(self.db_path, create_all=True)

        self.running = True
        session.set_status('running')
        while self.running:
            with srfm.Session.begin() as session:
                files = session.query(SupRsyncFile).filter(
                    SupRsyncFile.removed == None,
                    SupRsyncFile.archive_name == self.archive_name
                ).all()
                for file in files:
                    try:
                        self._handle_file(file)
                    except Exception as e:
                        if self.stop_on_exception:
                            raise e
                        else:
                            print(traceback.format_exc())

            time.sleep(2)

    def _stop(self, session, params=None):
        self.running = False
        session.set_status('stopping')


def make_parser(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--archive-name', required=True)
    pgroup.add_argument('--remote-basedir')
    pgroup.add_argument('--db-path')
    pgroup.add_argument('--ssh-host')
    pgroup.add_argument('--ssh-key')
    pgroup.add_argument('--delete-after', type=float)
    pgroup.add_argument('--max-copy-attempts', default=10)
    pgroup.add_argument('--stop-on-exception', action='store_true')
    return parser


if __name__ == '__main__':
    parser = make_parser()
    print("HERE")
    args = site_config.parse_args('SupRsync', parser=parser)
    txaio.start_logging(level='debug')

    agent, runner = ocs_agent.init_site_agent(args)
    suprsync = SupRsync(agent, args)
    agent.register_process('run', suprsync.run, suprsync._stop, startup=True)

    runner.run(agent, auto_reconnect=True)
