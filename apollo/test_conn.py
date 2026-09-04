import socket
ips = ["172.31.128.1", "127.0.0.1", "localhost", "0.0.0.0"]
for ip in ips:
    try:
        s = socket.socket()
        s.settimeout(3)
        s.connect((ip, 2000))
        print(f"OK: {ip}:2000")
        s.close()
    except Exception as e:
        print(f"FAIL: {ip}:2000 -> {e}")
