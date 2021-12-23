import gclib

ip = '10.10.10.73'


def main(IPaddress=ip):
    g = gclib.py()
    g.GOpen('{}'.format(IPaddress))
    print(g.GInfo())
    g.GCommand('MO')
    g.GClose()
    del g
    return 0


if __name__ == '__main__':
    main(ip)
