import socket
import urllib.request
import concurrent.futures

def check_ip(i):
    ip = f"10.0.10.{i}"
    url = f"http://{ip}/"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=0.8) as resp:
            body = resp.read(4096).decode('utf-8', errors='ignore')
            title = "NO TITLE"
            if '<title>' in body.lower():
                start = body.lower().find('<title>') + 7
                end = body.lower().find('</title>', start)
                title = body[start:end].strip()
            print(f"FOUND HTTP: {ip} -> Title: {title}", flush=True)
            return ip, title
    except Exception:
        pass
    return None

if __name__ == '__main__':
    print("Scanning 10.0.10.1 to 10.0.10.254...", flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=100) as executor:
        results = list(executor.map(check_ip, range(1, 255)))
    found = [r for r in results if r]
    print(f"Scan complete. Found {len(found)} HTTP servers.", flush=True)
