#!/usr/bin/env python3
'''Common utility for elread
'''
from pathlib import Path
from stat import filemode

def get_latest_path(path, suffix=None):
    ''' Obtain the latest path (according to the name) in
    the child of the given path
    Parameters
    ----------
    path: str or Path
        Path to the parent directory

    exteinsion: str on None
        extension of the file

    Returns
    -------
    path_latest: Path
        The latest path in the child of the given path
    '''
    path = Path(path)
    globstr = '*' if suffix is None else '*' + suffix
    glob_result = sorted(path.glob(globstr))
    if len(glob_result) == 0:
        return None
    if not glob_result[-1].is_dir():
        return glob_result[-1]

    for _p in glob_result[::-1]:
        glp = get_latest_path(_p)
        if glp:
            return glp

    return None


def get_oldest_path(path, suffix=None):
    ''' Obtain the oldest path (according to the name) in the child of
    the given path

    Parameters
    ----------
    path: str or Path
        Path to the parent directory

    exteinsion: str on None
        extension of the file

    Returns
    -------
    path_oldest: Path
        The latest path in the child of the given path
    '''
    path = Path(path)
    globstr = '*' if suffix is None else '*' + suffix
    glob_result = sorted(path.glob(globstr))
    if len(glob_result) == 0:
        return None
    if not glob_result[0].is_dir():
        return glob_result[0]

    for _p in glob_result:
        glp = get_oldest_path(_p)
        if glp:
            return glp

    return None


def get_previous_path(path, suffix=None):
    ''' Get previous path of the given data

    Parameters
    ----------
    path: str or Path
        Path

    Returns
    -------
    path_prev: Path
        Path to the previous data
    '''
    path = Path(path)
    p_dir = path.parent
    glob_result = sorted(p_dir.glob('*' + path.suffix))
    lp_ind = glob_result.index(path)
    if lp_ind == 0:
        return get_previous_path(p_dir, suffix=path.suffix)

    if glob_result[lp_ind - 1].is_dir():
        glp = get_latest_path(glob_result[lp_ind - 1], suffix=suffix)
        if glp:
            return glp

        return get_previous_path(glob_result[lp_ind - 1], suffix=suffix)

    return glob_result[lp_ind - 1]


def get_next_path(path, suffix=None):
    ''' Get previous path of the given data

    Parameters
    ----------
    path: str or Path
        Path

    Returns
    -------
    path_prev: Path
        Path to the previous data
    '''
    path = Path(path)
    p_dir = path.parent
    glob_result = sorted(p_dir.glob('*' + path.suffix))
    lp_ind = glob_result.index(path)
    if lp_ind == len(glob_result) - 1:
        return get_next_path(p_dir, suffix=path.suffix)

    if glob_result[lp_ind + 1].is_dir():
        glp = get_oldest_path(glob_result[lp_ind + 1], suffix=suffix)
        if glp:
            return glp

        return get_next_path(glob_result[lp_ind + 1], suffix=suffix)

    return glob_result[lp_ind + 1]

def is_writable(path):
    '''Check whethere the user has a write access to the `path`.
    Parameters
    ----------
    path: pathlib.Path
        path to the file

    Returns
    -------
    is_writable: bool
        True iff the user have write access to the file
    '''
    from os import getuid, getgroups

    p_st = path.stat()
    fm_str = filemode(p_st.st_mode)

    if fm_str[2] == 'w':# Write access to the owner
        uid = getuid()
        if uid == p_st.st_uid:
            return True

    if fm_str[5] == 'w':# Write access to the group
        if p_st.st_gid in getgroups():
            return True

    if fm_str[8] == 'w':# Write access to everyone
        return True

    return False
