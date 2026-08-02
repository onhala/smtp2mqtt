import socket
import urllib.request
import concurrent.futures

ports = [80, 8080, 8081, 8888, 8000, 8088]

def check_ip_port(args):
    ip, port = args
    url = f"http://{ip}:{port}/"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=0.6) as resp:
            body = resp.read(2048).decode('utf-8', errors='ignore')
            title = "NO TITLE"
            if '<title>' in body.lower():
                start = body.lower().find('<title>') + 7
                end = body.lower().find('</title>', start)
                title = body[start:end].strip()
            print(f"FOUND HTTP: {ip}:{port} -> {title}", flush=True)
            return ip, port, title
    except Exception:
        pass
    return None

if __name__ == '__main__':
    targets = [(f"10.0.10.{i}", p) for i in range(1, 255) for p in ports]
    print(f"Scanning {len(targets)} targets...", flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=100) as executor:
        results = list(executor.map(check_ip_port, targets))
    found = [r for r in results if r]
    print(f"Scan complete. Found {len(found)} services.", flush=True)
