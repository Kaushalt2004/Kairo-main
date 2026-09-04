import socket
s = socket.socket()
s.settimeout(3)
try:
    s.connect(('172.31.128.1', 2000))
    print('CARLA_REACHABLE')
    s.close()
except Exception as e:
    print(f'CARLA_UNREACHABLE: {e}')
