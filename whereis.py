"""
whereis.py — Scaneia rede RTSP, gera preview e links de acesso.

Uso:
    python whereis.py                          # scan padrao 192.168.1.100-254
    python whereis.py --base 192.168.0. --start 1 --end 50
    python whereis.py --user admin --password 123456
    python whereis.py --timeout 1              # scan mais rapido
"""
import argparse
import io
import os
import socket
import sys
import time
from pathlib import Path

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

RTSP_PATHS = [
    "/stream", "/stream1", "/live", "/1", "/0",
    "/cam/realmonitor?channel=1&subtype=0",
    "/Streaming/Channels/101",
    "/h264Preview_01_main",
]

HTTP_SNAPSHOT_PATHS = [
    "/cgi-bin/snapshot.cgi", "/snapshot.jpg",
    "/ISAPI/Streaming/channels/101/picture",
    "/cgi-bin/currentpic", "/image.jpg",
]


def scan_rtsp_network(base_ip, start, end, port=554, timeout=2):
    dispositivos = []
    print(f"\n  Scaneando {base_ip}{start}-{end}:{port} ...\n")
    for i in range(start, end + 1):
        ip = f"{base_ip}{i}"
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            if sock.connect_ex((ip, port)) == 0:
                print(f"    {ip}:{port} -- RTSP detectado")
                dispositivos.append(ip)
            sock.close()
        except Exception:
            pass
    return dispositivos


def detect_rtsp_server(ip, port=554, timeout=3):
    """Detecta o servidor RTSP (H264DVR, etc) via OPTIONS."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((ip, port))
        sock.send(f"OPTIONS rtsp://{ip}:{port}/ RTSP/1.0\r\nCSeq: 1\r\n\r\n".encode())
        time.sleep(0.3)
        resp = sock.recv(4096).decode("utf-8", errors="ignore")
        sock.close()
        for line in resp.split("\r\n"):
            if line.lower().startswith("server:"):
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return None


def try_rtsp_url(url, timeout=5):
    """Tenta RTSP via OpenCV."""
    try:
        import cv2
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, timeout * 1000)
        ret, frame = cap.read()
        cap.release()
        return ret, frame
    except Exception:
        return False, None


def try_http_snapshot(ip, port=80, timeout=3):
    import urllib.request
    for path in HTTP_SNAPSHOT_PATHS:
        url = f"http://{ip}:{port}{path}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Tucuxi/1.0"})
            resp = urllib.request.urlopen(req, timeout=timeout)
            data = resp.read()
            if len(data) > 1000:
                return url, data
        except Exception:
            continue
    return None, None


def generate_links(ip, port=554, user=None, password=None):
    auth = f"{user}:{password}@" if user and password else ""
    links = {"rtsp": [], "vlc": [], "ha_camera": []}
    for path in RTSP_PATHS:
        rtsp_url = f"rtsp://{auth}{ip}:{port}{path}"
        links["rtsp"].append(rtsp_url)
        links["vlc"].append(f'vlc "{rtsp_url}"')
        links["ha_camera"].append(
            f"  - platform: generic\n"
            f"    name: Tucuxi {ip}\n"
            f"    stream_source: {rtsp_url}\n"
            f"    still_image_url: {rtsp_url}\n"
        )
    return links


def save_preview(ip, frame, output_dir="previews"):
    if frame is None:
        return None
    try:
        import cv2
        Path(output_dir).mkdir(exist_ok=True)
        filename = f"{output_dir}/{ip.replace('.', '_')}.png"
        cv2.imwrite(filename, frame)
        return filename
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser(description="Scan RTSP + preview + links")
    parser.add_argument("--base", default="192.168.1.")
    parser.add_argument("--start", type=int, default=100)
    parser.add_argument("--end", type=int, default=254)
    parser.add_argument("--port", type=int, default=554)
    parser.add_argument("--timeout", type=float, default=2)
    parser.add_argument("--user", default=None)
    parser.add_argument("--password", default=None)
    parser.add_argument("--preview", action="store_true", default=True)
    parser.add_argument("--no-preview", dest="preview", action="store_false")
    args = parser.parse_args()

    dispositivos = scan_rtsp_network(args.base, args.start, args.end, args.port, args.timeout)
    if not dispositivos:
        print("\n  Nenhum dispositivo RTSP encontrado.")
        return

    print(f"\n  {len(dispositivos)} dispositivo(s) encontrado(s)\n")
    report = []

    for ip in dispositivos:
        print(f"--- {ip} ---")
        device_info = {"ip": ip, "rtsp_ok": False, "snapshot": None, "links": None}

        # Detect server type
        server = detect_rtsp_server(ip, args.port)
        if server:
            print(f"  Server: {server}")
            device_info["server"] = server

        is_h264dvr = server and "H264DVR" in server

        # Try RTSP
        print(f"  Testando RTSP stream...")
        auth = f"{args.user}:{args.password}@" if args.user and args.password else ""

        if is_h264dvr:
            print(f"  [H264DVR detectado] Digest auth nao suportado via Python/OpenCV.")
            print(f"  Use VLC ou instale ffmpeg para preview.")
            # Generate the correct URL for user to test in VLC
            if args.user and args.password:
                vlc_url = f"rtsp://{auth}{ip}:{args.port}/stream"
                print(f"  Teste no VLC: {vlc_url}")
                device_info["stream_url"] = vlc_url
                device_info["rtsp_ok"] = "vlc_required"
        else:
            # Try exact URL first
            if args.user and args.password:
                for path in ["/stream", "/stream1", "/live"]:
                    url = f"rtsp://{auth}{ip}:{args.port}{path}"
                    ok, frame = try_rtsp_url(url, timeout=5)
                    if ok:
                        print(f"  Stream OK: {url}")
                        device_info["rtsp_ok"] = True
                        device_info["stream_url"] = url
                        if args.preview and frame is not None:
                            saved = save_preview(ip, frame)
                            if saved:
                                print(f"  Preview: {saved}")
                                device_info["snapshot"] = saved
                        break

            # Try other paths
            if not device_info["rtsp_ok"]:
                for path in RTSP_PATHS:
                    url = f"rtsp://{auth}{ip}:{args.port}{path}"
                    ok, frame = try_rtsp_url(url, timeout=3)
                    if ok:
                        print(f"  Stream OK: {url}")
                        device_info["rtsp_ok"] = True
                        device_info["stream_url"] = url
                        if args.preview and frame is not None:
                            saved = save_preview(ip, frame)
                            if saved:
                                print(f"  Preview: {saved}")
                                device_info["snapshot"] = saved
                        break

        # HTTP snapshot
        if not device_info["snapshot"]:
            print(f"  Tentando HTTP snapshot...")
            snap_url, snap_data = try_http_snapshot(ip)
            if snap_url:
                Path("previews").mkdir(exist_ok=True)
                snap_file = f"previews/{ip.replace('.', '_')}_http.jpg"
                with open(snap_file, "wb") as f:
                    f.write(snap_data)
                print(f"  HTTP snapshot: {snap_url}")
                device_info["snapshot"] = snap_file

        # Links
        links = generate_links(ip, args.port, args.user, args.password)
        device_info["links"] = links

        print(f"  Links RTSP:")
        for url in links["rtsp"][:3]:
            print(f"    {url}")

        # H264DVR special instructions
        if is_h264dvr:
            print()
            print(f"  === H264DVR INSTRUCOES ===")
            print(f"  1. Abra VLC Media Player")
            print(f"  2. Media -> Open Network Stream")
            print(f"  3. Cole: rtsp://{auth}{ip}:{args.port}/stream")
            print(f"  4. Se funcionar, use o mesmo link no HA")
            print(f"  5. Para snapshot, use: http://{ip}/cgi-bin/snapshot.cgi")
            print(f"     (pode precisar de auth HTTP)")

        print()
        report.append(device_info)

    # Report
    report_file = f"previews/scan_{args.base.replace('.', '_')}.txt"
    Path("previews").mkdir(exist_ok=True)
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(f"Tucuxi Camera Scan -- {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Rede: {args.base}{args.start}-{args.end}:{args.port}\n\n")
        for dev in report:
            f.write(f"{'='*50}\n")
            f.write(f"IP: {dev['ip']}\n")
            f.write(f"Server: {dev.get('server', 'unknown')}\n")
            f.write(f"RTSP: {dev['rtsp_ok']}\n")
            if dev.get("stream_url"):
                f.write(f"Stream URL: {dev['stream_url']}\n")
            if dev.get("snapshot"):
                f.write(f"Preview: {dev['snapshot']}\n")
            f.write(f"\nRTSP URLs:\n")
            for url in dev["links"]["rtsp"]:
                f.write(f"  {url}\n")
            f.write(f"\nVLC:\n  {dev['links']['vlc'][0]}\n")
            f.write(f"\nHA Camera config:\n{dev['links']['ha_camera'][0]}\n")

    print(f"Relatorio: {report_file}\n")

    # Summary
    print("=== RESUMO ===")
    for dev in report:
        status = "OK" if dev["rtsp_ok"] is True else "VLC" if dev["rtsp_ok"] == "vlc_required" else "FAIL"
        snap = " [preview]" if dev.get("snapshot") else ""
        print(f"  [{status}] {dev['ip']}{snap}")


if __name__ == "__main__":
    main()
