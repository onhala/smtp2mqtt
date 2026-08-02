import socket
import urllib.request
import concurrent.futures

def check_ip(ip):
    url = f"http://{ip}/"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'LoxBerryScanner'})
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            body = resp.read(2048).decode('utf-8', errors='ignore')
            if 'loxberry' in body.lower() or 'loxone' in body.lower():
                return ip, body[:200]
    except Exception:
        pass
    return None

def scan_subnet(prefix):
    print(f"Scanning subnet {prefix}.0/24...")
    found = []
    ips = [f"{prefix}.{i}" for i in range(1, 255)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
        results = executor.map(check_ip, ips)
        for res in results:
            if res:
                print(f"🎉 FOUND LOXBERRY AT: {res[0]}")
                found.append(res)
    return found

if __name__ == '__main__':
    for p in ["10.0.10", "192.168.1", "192.168.0", "10.0.0", "172.16.0"]:
        scan_subnet(p)
