import argparse
import os
import time
import subprocess
import txaio

from ocs import ocs_agent, site_config

from socs.db.suprsync import (SupRsyncFilesManager, SupRsyncFileHandler)


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
    cmd_timeout : float
        Time (sec) for which cmds run on the remote will timeout
    copy_timeout : float
        Time (sec) after which a copy command will timeout
    """
    def __init__(self, agent, args):
        self.agent = agent
        self.log = txaio.make_logger()
        self.archive_name = args.archive_name
        self.ssh_host = args.ssh_host
        self.ssh_key = args.ssh_key
        self.remote_basedir = args.remote_basedir
        self.db_path = args.db_path
        self.delete_after = args.delete_local_after
        self.max_copy_attempts = args.max_copy_attempts
        self.running = False
        self.cmd_timeout = args.cmd_timeout
        self.copy_timeout = args.copy_timeout
        self.files_per_batch = args.files_per_batch
        self.sleep_time = args.sleep_time

    def run(self, session, params=None):
        """run()

        **Process** - Main run process for the SupRsync agent. Continuosly
        checks the suprsync db checking for files that need to be handled.
        """

        srfm = SupRsyncFilesManager(self.db_path, create_all=True)

        handler = SupRsyncFileHandler(
            srfm, self.archive_name, self.remote_basedir, ssh_host=self.ssh_host,
            ssh_key=self.ssh_key, cmd_timeout=self.cmd_timeout,
            copy_timeout=self.copy_timeout
        )

        self.running = True
        session.set_status('running')

        while self.running:
            try:
                handler.copy_files(max_copy_attempts=self.max_copy_attempts,
                                   num_files=self.files_per_batch)
            except subprocess.TimeoutExpired as e:
                self.log.error("Timeout when copying files! {e}", e=e)

            if self.delete_after is not None:
                handler.delete_files(self.delete_after)
            time.sleep(self.sleep_time)

        return True, "Stopped run process"

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
    pgroup.add_argument('--delete-local-after', type=float,
                        help="Time (sec) after which this agent will delete "
                             "local copies of successfully transfered files. "
                             "If None, will not delete files.")
    pgroup.add_argument('--max-copy-attempts', type=int,
                        help="Number of failed copy attempts before the agent "
                             "will stop trying to copy a file")
    pgroup.add_argument('--copy-timeout', type=float,
                        help="Time (sec) before the rsync command will timeout")
    pgroup.add_argument('--cmd-timeout', type=float,
                        help="Time (sec) before remote commands will timeout")
    pgroup.add_argument('--files-per-batch', type=int,
                        help="Number of files to copy over per batch. Default "
                        "is None, which will copy over all available files.")
    pgroup.add_argument('--sleep-time', type=float, default=60,
                        help="Time to sleep (sec) in between copy iterations")
    return parser


if __name__ == '__main__':
    parser = make_parser()
    args = site_config.parse_args('SupRsync', parser=parser)
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    agent, runner = ocs_agent.init_site_agent(args)
    suprsync = SupRsync(agent, args)
    agent.register_process('run', suprsync.run, suprsync._stop, startup=True)

    runner.run(agent, auto_reconnect=True)
