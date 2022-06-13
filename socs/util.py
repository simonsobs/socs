import hashlib


def get_md5sum(filename):
    m = hashlib.md5()

    for line in open(filename, 'rb'):
        m.update(line)
    return m.hexdigest()
