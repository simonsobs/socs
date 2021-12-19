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
    """
    Agent to rsync files to a remote (or local) destination, verify successful
    transfer, and delete local files after a specified amount of time.

    Parameters
    --------------
    agent : OCSAgent
        OCS agent object
    args : Namespace
        Namespace with parsed arguments

    Attributes
    ------------
    agent : OCSAgent
        OCS agent object
    log : txaio.tx.Logger
        txaio logger object, created by the OCSAgent
    archive_name : string
        Name of the managed archive. Sets which files in the suprsync db should
        be copied.
    ssh_host : str, optional
        Remote host to copy data to. If None, will copy data locally.
    ssh_key : str, optional
        ssh-key to use to access the ssh host.
    remote_basedir : path
        Base directory on the destination server to copy files to
    db_path : path
        Path of the sqlite db to monitor
    delete_after : float
        Seconds after which this agent will delete successfully copied files.
    stop_on_exception : bool
        If True, will stop the run process if a file cannot be copied
    """
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
        res = subprocess.run(_cmd, capture_output=True, text=True)
        if res.stderr:
            self.log.error("stderr for cmd: {cmd}\n{err}",
                           cmd=_cmd, err=res.stderr)
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
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            self.log.error("Rsync failed for file {path}!\nstderr: {err}", path=file.local_path)
            return False

        res = self.run_on_remote(['md5sum', remote_path])
        if res.returncode != 0:
            return False
        else:
            return res.stdout.split()[0]

    def handle_file(self, file):
        """
        Handles operation of an un-removed SupRsyncFile. Will attempt to copy,
        calculate the remote md5sum, and remove from the local host if enough
        time has passed.

        Args
        ----
        file : SupRsyncFile
            file to be copied
        """
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

    def run(self, session, params=None):
        """run()

        **Process** - Main run process for the SupRsync agent. Continuosly
        checks the suprsync db checking for files that need to be handled.
        """

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
                        self.handle_file(file)
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
    pgroup.add_argument('--archive-name', required=True, type=str,
                        help="Name of managed archive. Determines which files "
                             "should be copied")
    pgroup.add_argument('--remote-basedir', required=True, type=str,
                        help="Base directory on the remote server where files "
                             "will be copied")
    pgroup.add_argument('--db-path', required=True, type=str,
                        help="Path to the suprsync sqlite db")
    pgroup.add_argument('--ssh-host', type=str, default=None,
                        help="Remote host to copy files to (e.g. "
                             "'<user>@<host>'). If None, will copy files locally")
    pgroup.add_argument('--ssh-key', type=str,
                        help="Path to ssh-key needed to access remote host")
    pgroup.add_argument('--delete-after', type=float,
                        help="Time (sec) after which this agent will delete "
                             "local copies of successfully transfered files. "
                             "If None, will not delete files.")
    pgroup.add_argument('--max-copy-attempts', default=10, type=int,
                        help="Number of failed copy attempts before the agent "
                             "will stop trying to copy a file")
    pgroup.add_argument('--stop-on-exception', action='store_true',
                        help="If true will stop the run process on an exception")
    return parser


if __name__ == '__main__':
    parser = make_parser()
    args = site_config.parse_args('SupRsync', parser=parser)
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    agent, runner = ocs_agent.init_site_agent(args)
    suprsync = SupRsync(agent, args)
    agent.register_process('run', suprsync.run, suprsync._stop, startup=True)

    runner.run(agent, auto_reconnect=True)
