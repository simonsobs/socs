import gclib

# Initial IP address
# ip0 = '192.168.1.100'
ip0 = '10.10.10.73'

ip1 = '10.10.10.73'
# ip1 = '192.168.1.100'


def main(initial_IPaddress=ip0, new_IPaddress=ip1):
    # make an instance of the gclib python class
    g = gclib.py()

    try:
        print('gclib version:', g.GVersion())

        #######################################################################
        # Network Utilities
        #######################################################################
        '''
        #Get Ethernet controllers requesting IP addresses
        print('Listening for controllers requesting IP addresses...')
        ip_requests = g.GIpRequests()
        for id in ip_requests.keys():
          print(id, 'at mac', ip_requests[id])

        #define a mapping of my hardware to ip addresses
        ips = {}
        ips['DMC4000-783'] = '192.168.0.42'
        ips['DMC4103-9998'] = '192.168.0.43'

        for id in ips.keys():
          if id in ip_requests: #if our controller needs an IP
            print("\nAssigning", ips[id], "to", ip_requests[id])
            g.GAssign(ips[id], ip_requests[id]) #send the mapping
            g.GOpen(ips[id]) #connect to it
            print(g.GInfo())
            g.GCommand('BN') #burn the IP
            g.GClose() #disconnect

        print('\nAvailable addresses:') #print ready connections
        available = g.GAddresses()
        for a in sorted(available.keys()):
          print(a, available[a])

        print('\n')
        '''
        #######################################################################
        #  Connect
        #######################################################################
        g.GOpen('{}'.format(initial_IPaddress))
        # g.GOpen('COM1')
        print(g.GInfo())

        #######################################################################
        # Programs
        #######################################################################
        # Disable DHCP
        if new_IPaddress != initial_IPaddress:
            g.GCommand('DH 0')
            # Change the IP address
            g.GCommand('IA {}'.format(new_IPaddress.replace('.', ',')))
        else:
            print('check IP')
        a = int(float(g.GCommand('MG @INT[(_IA0&($FF000000))/$1000000]&$FF')))
        b = int(float(g.GCommand('MG @INT[(_IA0&($00FF0000))/$10000]')))
        c = int(float(g.GCommand('MG @INT[(_IA0&($0000FF00))/$100]')))
        d = int(float(g.GCommand('MG @INT[(_IA0&($000000FF))')))
        print('New IP address = {}.{}.{}.{}'.format(a, b, c, d))

        #######################################################################
        # except handler
        #######################################################################
    except gclib.GclibError as e:
        print('Unexpected GclibError:', e)

    finally:
        # don't forget to close connections!
        g.GClose()

    return


# runs main() if example.py called from the console
if __name__ == '__main__':
    main()
