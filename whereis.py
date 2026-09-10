"""
whereis.py — Scaneia rede RTSP, gera preview e links de acesso.

Uso:
    python whereis.py                          # scan padrão 192.168.1.100-254
    python whereis.py --base 192.168.0. --start 1 --end 50
    python whereis.py --timeout 1              # scan mais rápido
"""
import argparse
import os
import socket
import sys
import time
from pathlib import Path

# ── RTSP URL patterns comuns ──────────────────────────────────────
RTSP_PATHS = [
    "/",
    "/stream1",
    "/stream",
    "/live",
    "/1",
    "/0",
    "/cam/realmonitor?channel=1&subtype=0",
    "/Streaming/Channels/101",
    "/h264Preview_01_main",
    "/VideoConfigure?channel=1",
    "/media/video1",
]

# ── HTTP snapshot paths ───────────────────────────────────────────
HTTP_SNAPSHOT_PATHS = [
    "/cgi-bin/snapshot.cgi",
    "/snapshot.jpg",
    "/ISAPI/Streaming/channels/101/picture",
    "/cgi-bin/currentpic",
    "/tmp/snap.jpg",
    "/image.jpg",
    "/snapshot",
    "/onvif-http/snapshot",
]


def scan_rtsp_network(base_ip="192.168.1.", start=100, end=254, port=554, timeout=2):
    """Scaneia rede por dispositivos com porta RTSP aberta."""
    dispositivos = []
    print(f"\n🔍 Scaneando {base_ip}{start}-{end}:{port} ...\n")
    for i in range(start, end + 1):
        ip = f"{base_ip}{i}"
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((ip, port))
            if result == 0:
                print(f"  ✅ {ip}:{port} — RTSP detectado")
                dispositivos.append(ip)
            sock.close()
        except Exception:
            pass
    return dispositivos


def try_rtsp_url(url, timeout=5):
    """Tenta conectar ao stream RTSP e retorna True se bem-sucedido."""
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
    """Tenta HTTP snapshot em paths comuns."""
    import urllib.request
    for path in HTTP_SNAPSHOT_PATHS:
        url = f"http://{ip}:{port}{path}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Tucuxi/1.0"})
            resp = urllib.request.urlopen(req, timeout=timeout)
            data = resp.read()
            if len(data) > 1000:  # imagem válida tem >1KB
                return url, data
        except Exception:
            continue
    return None, None


def generate_links(ip, port=554):
    """Gera links de acesso para o dispositivo."""
    links = {
        "rtsp": [],
        "http_snapshot": [],
        "vlc": [],
        "ha_camera": [],
    }
    for path in RTSP_PATHS:
        rtsp_url = f"rtsp://{ip}:{port}{path}"
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
    """Salva snapshot como PNG."""
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
    parser.add_argument("--base", default="192.168.1.", help="Base IP (default: 192.168.1.)")
    parser.add_argument("--start", type=int, default=100, help="Start IP (default: 100)")
    parser.add_argument("--end", type=int, default=254, help="End IP (default: 254)")
    parser.add_argument("--port", type=int, default=554, help="RTSP port (default: 554)")
    parser.add_argument("--timeout", type=float, default=2, help="Scan timeout (default: 2s)")
    parser.add_argument("--preview", action="store_true", default=True, help="Gerar preview PNG")
    parser.add_argument("--no-preview", dest="preview", action="store_false")
    args = parser.parse_args()

    # 1. Scan
    dispositivos = scan_rtsp_network(args.base, args.start, args.end, args.port, args.timeout)

    if not dispositivos:
        print("\n❌ Nenhum dispositivo RTSP encontrado.")
        return

    print(f"\n📋 {len(dispositivos)} dispositivo(s) encontrado(s)\n")

    # 2. Para cada dispositivo, tentar preview e gerar links
    report = []
    for ip in dispositivos:
        print(f"━━━ {ip} ━━━")
        device_info = {"ip": ip, "rtsp_ok": False, "snapshot": None, "links": None}

        # Tentar RTSP stream
        print(f"  📡 Testando RTSP stream...")
        for path in RTSP_PATHS:
            url = f"rtsp://{ip}:{args.port}{path}"
            ok, frame = try_rtsp_url(url, timeout=3)
            if ok:
                print(f"  ✅ Stream OK: {url}")
                device_info["rtsp_ok"] = True
                device_info["stream_url"] = url

                if args.preview and frame is not None:
                    saved = save_preview(ip, frame)
                    if saved:
                        print(f"  🖼️  Preview salvo: {saved}")
                        device_info["snapshot"] = saved
                break

        # Tentar HTTP snapshot
        if not device_info["snapshot"]:
            print(f"  🌐 Tentando HTTP snapshot...")
            snap_url, snap_data = try_http_snapshot(ip)
            if snap_url:
                Path("previews").mkdir(exist_ok=True)
                snap_file = f"previews/{ip.replace('.', '_')}_http.jpg"
                with open(snap_file, "wb") as f:
                    f.write(snap_data)
                print(f"  🖼️  HTTP snapshot: {snap_url} → {snap_file}")
                device_info["snapshot"] = snap_file

        # Gerar links
        links = generate_links(ip, args.port)
        device_info["links"] = links

        print(f"  🔗 Links RTSP:")
        for i, url in enumerate(links["rtsp"][:3]):  # mostrar só os 3 principais
            print(f"     {url}")
        if len(links["rtsp"]) > 3:
            print(f"     ... +{len(links['rtsp'])-3} outras URLs")

        print()
        report.append(device_info)

    # 3. Gerar relatório
    print("━━━ RELATÓRIO ━━━\n")

    report_file = f"previews/scan_{args.base.replace('.', '_')}.txt"
    Path("previews").mkdir(exist_ok=True)
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(f"Tucuxi Camera Scan — {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Rede: {args.base}{args.start}-{args.end}:{args.port}\n\n")

        for dev in report:
            f.write(f"{'='*50}\n")
            f.write(f"IP: {dev['ip']}\n")
            f.write(f"RTSP: {'✅ OK' if dev['rtsp_ok'] else '❌ Falhou'}\n")
            if dev.get("stream_url"):
                f.write(f"Stream URL: {dev['stream_url']}\n")
            if dev.get("snapshot"):
                f.write(f"Preview: {dev['snapshot']}\n")
            f.write(f"\nRTSP URLs:\n")
            for url in dev["links"]["rtsp"]:
                f.write(f"  {url}\n")
            f.write(f"\nVLC:\n")
            f.write(f"  {dev['links']['vlc'][0]}\n")
            f.write(f"\nHA Camera config:\n")
            f.write(dev["links"]["ha_camera"][0])
            f.write("\n")

    print(f"📄 Relatório salvo em: {report_file}")
    print(f"📁 Previews em: previews/\n")

    # Resumo
    print("━━━ RESUMO ━━━")
    for dev in report:
        status = "✅" if dev["rtsp_ok"] else "⚠️"
        snap = "📸" if dev.get("snapshot") else ""
        print(f"  {status} {dev['ip']} {snap}")


if __name__ == "__main__":
    main()
