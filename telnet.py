#!/usr/bin/env python3
import os
import sys
import socket
import select
import argparse
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.request import urlopen, Request
from urllib.error import URLError

TELNET_PORT = 23
HTTP_PORT = 80

def get_local_ip():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except:
        return None

def check_port(ip, port=HTTP_PORT, timeout=1):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((ip, port))
        sock.close()
        return ip if result == 0 else None
    except:
        return None

def fetch_title(ip, port=HTTP_PORT):
    try:
        req = Request(f"http://{ip}:{port}/", method="GET", headers={"User-Agent": "telnet.py"})
        resp = urlopen(req, timeout=2)
        html = resp.read().decode("utf-8", errors="ignore")
        start = html.lower().find("<title>")
        end = html.lower().find("</title>")
        if start != -1 and end != -1:
            return html[start+7:end].strip()
        return None
    except:
        return None

def identify(ip, port=HTTP_PORT):
    try:
        req = Request(f"http://{ip}:{port}/api/info", method="GET", headers={"User-Agent": "telnet.py"})
        resp = urlopen(req, timeout=2)
        import json
        data = json.loads(resp.read())
        dev_id = data.get("gateway_id") or data.get("device_id", "")
        fw = data.get("fw_version", "")
        return (dev_id, fw)
    except:
        pass
    try:
        req = Request(f"http://{ip}:{port}/api/state", method="GET", headers={"User-Agent": "telnet.py"})
        resp = urlopen(req, timeout=2)
        import json
        data = json.loads(resp.read())
        dev_id = data.get("device_id", "")
        fw = data.get("fw_version", "")
        return (dev_id, fw)
    except:
        pass
    title = fetch_title(ip, port)
    return (title or ip, "")

def scan_devices():
    local_ip = get_local_ip()
    if not local_ip:
        print("Could not detect local IP")
        return []
    subnet = ".".join(local_ip.split(".")[:3]) + "."
    ips = [f"{subnet}{i}" for i in range(1, 253)]

    print(f"Scanning {len(ips)} IPs on {subnet}0/24 for port 80...")
    found = []
    with ThreadPoolExecutor(max_workers=50) as executor:
        futures = {executor.submit(check_port, ip, HTTP_PORT): ip for ip in ips}
        for future in as_completed(futures):
            result = future.result()
            if result:
                found.append(result)

    if not found:
        print("No devices found")
        return []

    devices = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(identify, ip): ip for ip in found}
        for future in as_completed(futures):
            ip = future.result()
            if ip:
                dev_id, fw = identify(ip)
                devices.append((ip, dev_id, fw))

    devices.sort(key=lambda x: [int(o) for o in x[0].split(".")])
    return devices

def pick_device(devices):
    print("\nDispositivos encontrados:")
    for i, (ip, dev_id, fw) in enumerate(devices):
        print(f"  [{i}] {ip}  {dev_id}  FW={fw}")
    print()
    while True:
        try:
            idx = int(input(f"Escolha um dispositivo [0-{len(devices)-1}]: "))
            if 0 <= idx < len(devices):
                return devices[idx][0]
        except (ValueError, EOFError):
            pass
        print("Invalido")

def telnet_connect(host, port=TELNET_PORT):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10)
    try:
        sock.connect((host, port))
        sock.setblocking(False)
        print(f"Conectado a {host}:{port}")
        print("Console remoto. Ctrl+] para sair.\n")
        return sock
    except socket.timeout:
        print(f"Timeout conectando a {host}:{port}")
        sys.exit(1)
    except ConnectionRefusedError:
        print(f"Conexao recusada por {host}:{port}")
        sys.exit(1)
    except OSError as e:
        print(f"Erro: {e}")
        sys.exit(1)

def telnet_reader(sock):
    try:
        while True:
            try:
                data = sock.recv(4096)
                if not data:
                    print("\nConexao fechada pelo dispositivo")
                    os._exit(0)
                sys.stdout.buffer.write(data)
                sys.stdout.buffer.flush()
            except (ConnectionResetError, OSError):
                print("\nConexao perdida")
                os._exit(0)
    except:
        os._exit(0)

def telnet_loop(sock):
    sock.setblocking(True)
    t = threading.Thread(target=telnet_reader, args=(sock,), daemon=True)
    t.start()
    try:
        while True:
            data = sys.stdin.buffer.read(1)
            if not data:
                break
            sock.sendall(data)
    except (EOFError, KeyboardInterrupt):
        print("\nEncerrando...")
    except BrokenPipeError:
        pass

def main():
    parser = argparse.ArgumentParser(description="Conecta via telnet no console remoto dos dispositivos ESP-NOW")
    parser.add_argument("host", nargs="?", help="IP do dispositivo (omita para scan)")
    parser.add_argument("-p", "--port", type=int, default=TELNET_PORT, help=f"Porta telnet (default: {TELNET_PORT})")
    args = parser.parse_args()

    host = args.host
    if not host:
        devices = scan_devices()
        if not devices:
            return
        if len(devices) == 1:
            host = devices[0][0]
            print(f"  Unico dispositivo: {host}")
        else:
            host = pick_device(devices)

    sock = telnet_connect(host, args.port)
    telnet_loop(sock)

if __name__ == "__main__":
    main()
