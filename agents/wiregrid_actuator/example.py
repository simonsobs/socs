import sys
import string
import gclib


def main():
  g = gclib.py() #make an instance of the gclib python class
  
  try:
    print('gclib version:', g.GVersion())
    
    ###########################################################################
    # Network Utilities
    ###########################################################################
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
    ###########################################################################
    #  Connect
    ###########################################################################
    g.GOpen('192.168.0.42 -s ALL')
    #g.GOpen('COM1')
    print(g.GInfo())
        
    ###########################################################################
    # Programs
    ###########################################################################
    '''
    print('Programs')
    program = '#A;i=0;i=i+1;i=i+1;i=i+1;i=i+1;i=i+1;i=i+1;i=i+1;i=i+1;i=i+1;i=i+1;i=i+1;i=i+1;i=i+1;i=i+1;i=i+1;i=i+1;i=i+1;i=i+1;i=i+1;i=i+1;EN';
    #Program line above is too large to fit on any Galil controller, however it can easily fit if broken up with level 4 compression.
    #the value of i at the end of code execution is 20.
    try:
      g.GProgramDownload(program, '--max 3') #program won't fit at level 3
    except gclib.GclibError as e:
      print(' GProgramDownload() correctly errored. Can\'t fit with level 3 compression')
      
    g.GProgramDownload(program, '')
    g.GProgramUploadFile('temp.dmc')
    g.GProgramDownload('','') #erase program
    g.GProgramDownloadFile('temp.dmc', '')
    print(' Uploaded program:\n%s' % g.GProgramUpload())
    g.GCommand('XQ') #execute the code
    g.GSleep(10) #wait a brief interval for the code to complete.
    if (float(g.GCommand('i=?')) == 20): #python can convert '20.0000' to float
      print(' Downloaded program verified')
    else:
      print(' Unexpected program result')
    
    #g.timeout = 5000 #set longish timeout 
    #g.GCommand('BP') #burn program
    '''
    ###########################################################################
    # Arrays
    ###########################################################################
    '''
    print('Arrays')
    g.GCommand('DA *,*[]')
    g.GCommand('DM A[5], B[10]')
    array_a = [1, 2, 3.14, 4, 5]
    array_b = [30, 42, 50, 60, 70]
    g.GArrayDownload('A', 0, -1, array_a)
    g.GArrayDownload('B', 2, -1, array_b)
    g.GArrayUploadFile('arrays.csv', ['A','B'])
    g.GArrayDownloadFile('arrays.csv')
    array_b_up = g.GArrayUpload('B', 3, 5)
    if array_b_up[0] == 42:
      print(' Array element verified')
    else:
      print(' Unexpected aray element', array_b_up[0])
    '''
    ###########################################################################
    # Messages
    ###########################################################################
    '''
    print('Messages')
    g.GProgramDownload('WT100\rMGTIME\rEN')
    g.GCommand('XQ')
    print(g.GMessage())
    '''
    ###########################################################################
    #  Firmware
    ###########################################################################
    '''
    firmware = r'c:\temp\dmc-4000-r12c.hex'
    #firmware = r'~/temp/dmc-4000-r12c.hex'
    print('Loading firmware', firmware)
    g.GFirmwareDownload(firmware)
    print(g.GInfo())
    '''
    ###########################################################################
    # Misc
    ###########################################################################
    '''
    #Motion Complete
    print('Motion Complete')
    c = g.GCommand #alias the command callable
    c('AB') #abort motion and program
    c('MO') #turn off all motors
    c('SHA') #servo A
    c('SPA=1000') #speead, 1000 cts/sec
    c('PRA=3000') #relative move, 3000 cts
    print(' Starting move...')
    c('BGA') #begin motion
    g.GMotionComplete('A')
    print(' done.')
    del c #delete the alias
    '''
  ###########################################################################
  # except handler
  ###########################################################################  
  except gclib.GclibError as e:
    print('Unexpected GclibError:', e)
  
  finally:
    g.GClose() #don't forget to close connections!
  
  return
  
 
#runs main() if example.py called from the console
if __name__ == '__main__':
  main()