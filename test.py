addr = 'localhost:12345'
host, port = addr.split('//')[-1].split(':')
port = int(port)
print(f"({host}, {port})")
