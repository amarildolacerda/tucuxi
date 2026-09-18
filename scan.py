#!/usr/bin/env python3
import os
import re
import struct
import socket
import json
import argparse
import time
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.request import urlopen, Request
from urllib.error import URLError

def get_local_ip():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except:
        return None

def check_port(ip, port=80, timeout=2):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((ip, port))
        sock.close()
        return ip if result == 0 else None
    except:
        return None

def fetch_title(ip, port):
    try:
        req = Request(f"http://{ip}:{port}/", method="GET", headers={"User-Agent": "scan.py"})
        resp = urlopen(req, timeout=2)
        html = resp.read().decode("utf-8", errors="ignore")
        start = html.lower().find("<title>")
        end = html.lower().find("</title>")
        if start != -1 and end != -1:
            return html[start+7:end].strip()
        return None
    except:
        return None

def get_mac_via_arp(ip):
    try:
        import subprocess, re
        if os.name == "nt":
            out = subprocess.check_output(f"arp -a {ip}", shell=True, timeout=3).decode("utf-8", errors="ignore")
            m = re.search(r"([0-9A-Fa-f]{2}[-:][0-9A-Fa-f]{2}[-:][0-9A-Fa-f]{2}[-:][0-9A-Fa-f]{2}[-:][0-9A-Fa-f]{2}[-:][0-9A-Fa-f]{2})", out)
        else:
            out = subprocess.check_output(f"arp -n {ip}", shell=True, timeout=3).decode("utf-8", errors="ignore")
            m = re.search(r"([0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2})", out, re.I)
        if m: return m.group(1).replace("-", ":")
    except: pass
    return None

def detect_device_type(data):
    t = data.get("type")
    if t:
        return t
    keys = data.keys()
    if "temperature" in keys or "humidity" in keys:
        return "dht_gas"
    if "motion_detected" in keys:
        return "pir"
    if "state" in keys:
        return "lampada"
    if "repeater_supported" in keys:
        return "repeater"
    return "unknown"

def identify(ip, port):
    title = fetch_title(ip, port)
    mac = None

    # Try gateway /api/info (retry 1x)
    for attempt in range(2):
        try:
            req = Request(f"http://{ip}:{port}/api/info", method="GET", headers={"User-Agent": "scan.py"})
            resp = urlopen(req, timeout=4)
            data = json.loads(resp.read())
            gw_id = data.get("gateway_id", "")
            fw = data.get("fw_version", "")
            platform = data.get("platform", "")
            paired = data.get("paired_count", "?")
            online = data.get("online_count", "?")
            mac = data.get("gateway_mac") or data.get("mac") or data.get("sta_mac")
            
            # Only treat as gateway if response has meaningful data
            # (empty {} from nodes with /api/info endpoint should not be gateway)
            if not gw_id and not mac and paired == "?" and online == "?":
                # Empty response - not a gateway, fall through to /api/state
                raise Exception("Empty /api/info response")
            
            is_gateway = "gateway" in gw_id or "gateway" in str(mac) or mac is not None
            label = "GATEWAY" if is_gateway else "bridge"
            info = f"  [{label}] {ip}:{port}  type=gateway  FW={fw}  platform={platform}  paired={paired} online={online}  id={gw_id}"
            if mac: info += f"  MAC={mac}"
            if title: info += f"  title=\"{title}\""
            return (info, mac, "gateway", fw, ip, platform, gw_id)
        except:
            if attempt == 0:
                time.sleep(1)
            pass

    # Try client /api/state (retry 1x)
    for attempt in range(2):
        try:
            req = Request(f"http://{ip}:{port}/api/state", method="GET", headers={"User-Agent": "scan.py"})
            resp = urlopen(req, timeout=4)
            data = json.loads(resp.read())
            dev_id = data.get("device_id", "")
            dev_name = data.get("device_name", "")
            fw = data.get("fw_version", "")
            platform = data.get("platform", "")
            relay = data.get("state", None)
            gw_con = data.get("gateway_connected", False)
            dtype = detect_device_type(data)
            info = f"  [DEVICE] {ip}:{port}  name=\"{dev_name}\"  id={dev_id}  FW={fw}  platform={platform}  type={dtype}"
            if relay is not None: info += f"  relay={'ON' if relay else 'OFF'}"
            info += f"  gw={gw_con}"
            if title and title != dev_name: info += f"  title=\"{title}\""
            return (info, None, dtype, fw, ip, platform, dev_name)
        except:
            if attempt == 0:
                time.sleep(1)
            pass

    # Fallback: just show title
    mac = get_mac_via_arp(ip) if not mac else mac
    if title:
        info = f"  [HTTP] {ip}:{port}  title=\"{title}\""
        if mac: info += f"  MAC={mac}"
        return (info, mac, "unknown", None, ip, "", title)
    return None

SSDP_MULTICAST = "239.255.255.250"
SSDP_PORT = 1900
SSDP_TIMEOUT = 4

def ssdp_discover(timeout=SSDP_TIMEOUT):
    """Envia M-SEARCH multicast (SSDP) na porta 1900 e retorna os devices que responderam.
    Qualquer Espalexa (emulacao Philips Hue) responde a 'urn:schemas-upnp-org:device:basic:1',
    entao isto descobre lamps independentemente da versao do Espalexa instalada."""
    import struct
    msg = (
        "M-SEARCH * HTTP/1.1\r\n"
        "HOST: 239.255.255.250:1900\r\n"
        "MAN: \"ssdp:discover\"\r\n"
        "MX: 3\r\n"
        "ST: urn:schemas-upnp-org:device:basic:1\r\n"
        "\r\n"
    )
    found = []
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(timeout)
        mreq = struct.pack("4sl", socket.inet_aton(SSDP_MULTICAST), socket.INADDR_ANY)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        sock.sendto(msg.encode(), (SSDP_MULTICAST, SSDP_PORT))
        start = time.time()
        while time.time() - start < timeout:
            try:
                data, addr = sock.recvfrom(4096)
                raw = data.decode("utf-8", errors="ignore")
                found.append({"ip": addr[0], "port": addr[1], "raw": raw})
            except socket.timeout:
                break
            except Exception:
                break
        sock.close()
    except Exception:
        pass
    # dedup por IP
    seen = {}
    for d in found:
        seen[d["ip"]] = d
    return list(seen.values())

HUB_DISCOVERY_PORT = 5000
HUB_DISCOVERY_SERVICE = "esp-bridge"

def hub_discover(timeout=3):
    """Descobre o hub (ESP-NOW/TCP) na porta 5000.
    Protocolo binario (shared/src/tcp_protocol.h): envia MSG_GW_DISCOVER (0x0A) e o
    hub responde com MSG_GW_ANNOUNCE (0x09) contendo hub_ip e hub_port.
    Observacao: o hub responde apenas a pacotes UNICAST (broadcast do PC e bloqueado
    por muitos APs/roteadores), entao varremos a sub-rede em unicast na porta 5000."""
    MSG_GW_DISCOVER = 0x0A
    MSG_GW_ANNOUNCE = 0x09
    local_ip = get_local_ip()
    subnet = ".".join(local_ip.split(".")[:3]) + "."
    found = []
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(0.05)
        pkt = bytes([MSG_GW_DISCOVER])
        for i in range(1, 255):
            ip = f"{subnet}{i}"
            if ip == local_ip:
                continue
            try:
                sock.sendto(pkt, (ip, HUB_DISCOVERY_PORT))
            except Exception:
                pass
        # tambem tenta broadcast (funciona em alguns ambientes)
        try:
            bs = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            bs.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            bs.sendto(pkt, ("255.255.255.255", HUB_DISCOVERY_PORT))
            bs.close()
        except Exception:
            pass
        start = time.time()
        while time.time() - start < timeout:
            try:
                data, addr = sock.recvfrom(4096)
                if not data or data[0] != MSG_GW_ANNOUNCE:
                    continue
                if len(data) < 1 + 4 + 16 + 2:
                    continue
                fw = data[1:5]
                ip = data[5:21].split(b"\x00")[0].decode("utf-8", "ignore").strip()
                port = struct.unpack("<H", data[21:23])[0]
                fw_str = ".".join(str(b) for b in fw) if any(fw) else "?"
                found.append({"ip": ip or addr[0], "port": port or 80, "fw_version": fw_str})
            except socket.timeout:
                break
            except Exception:
                break
        sock.close()
    except Exception:
        pass
    # dedup
    seen = {}
    for d in found:
        seen[d["ip"]] = d
    return list(seen.values())

def fetch_description_xml(location, timeout=4):
    """Baixa o /description.xml (LOCATION do SSDP) e extrai campos que identificam o device."""
    if not location:
        return None
    try:
        req = Request(location, headers={"User-Agent": "scan.py"})
        resp = urlopen(req, timeout=timeout)
        xml = resp.read().decode("utf-8", errors="ignore")
        out = {}
        for tag in ("friendlyName", "modelName", "modelNumber", "serialNumber",
                    "manufacturer", "deviceType", "UDN", "modelDescription"):
            m = re.search(r"<%s>(.*?)</%s>" % (tag, tag), xml, re.S | re.I)
            if m:
                out[tag] = m.group(1).strip()
        return out
    except Exception:
        return None

def main():
    parser = argparse.ArgumentParser(description="Scan for ESP-NOW gateway on local network")
    parser.add_argument("-p", "--port", type=int, default=80, help="Port to scan (default: 80)")
    parser.add_argument("--mac", action="store_true", help="Show only gateway MAC (for repeater config)")
    parser.add_argument("--ssdp", action="store_true", help="Descovery via SSDP multicast (porta 1900) - acha devices Espalexa")
    parser.add_argument("--hub", action="store_true", help="Descobre o hub via UDP porta 5000 (MSG_GW_DISCOVER 0x0A) - varre a sub-rede em unicast e mostra so o hub")
    parser.add_argument("--json", action="store_true", help="Output JSON for consumption by other tools")
    args = parser.parse_args()

    local_ip = get_local_ip()
    if not local_ip:
        print("Could not detect local IP")
        return

    # --ssdp e --hub fazem discovery dedicado e nao varrem a sub-rede em port 80
    do_port_scan = not (args.ssdp or args.hub)

    found_gateway_mac = None
    devices = []

    if do_port_scan:
        subnet = ".".join(local_ip.split(".")[:3]) + "."
        ips = [f"{subnet}{i}" for i in range(1, 253)]

        if not args.json:
            print(f"Scanning {len(ips)} IPs on {subnet}0/24 for port {args.port}...")
            print(f"Local IP: {local_ip}")
        found = []

        with ThreadPoolExecutor(max_workers=50) as executor:
            futures = {executor.submit(check_port, ip, args.port): ip for ip in ips}
            for future in as_completed(futures):
                result = future.result()
                if result:
                    if not args.json:
                        marker = "  <--" if result == local_ip else ""
                        print(f"  Found: {result}:{args.port}{marker}")
                    found.append(result)
                else:
                    pass

        if not found:
            if not args.json:
                print(f"\nNo devices found with port {args.port} open")
            else:
                print("[]")
            return

        if not args.json:
            print(f"\nIdentificando dispositivos...")
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(identify, ip, args.port): ip for ip in found}
            for future in as_completed(futures):
                result = future.result()
                if result:
                    info, mac, dtype, fw, ip, platform, name = result
                    if not args.json:
                        print(info)
                    else:
                        devices.append({"ip": ip, "port": args.port, "type": dtype, "fw_version": fw, "platform": platform, "name": name})
                    if mac and not found_gateway_mac:
                        found_gateway_mac = mac

    if args.ssdp:
        if not args.json:
            print(f"\nSSDP discovery (porta 1900)...")
        ssdp = ssdp_discover()
        if not ssdp:
            if not args.json:
                print("  Nenhum device respondeu ao SSDP.")
        else:
            for d in ssdp:
                loc = ""
                for line in d.get("raw", "").split("\r\n"):
                    if line.lower().startswith("location:"):
                        loc = line.split(":", 1)[1].strip()
                        break
                dxml = fetch_description_xml(loc) if loc else None
                res = identify(d["ip"], 80)
                if not args.json:
                    if dxml:
                        print(f"  [SSDP] {d['ip']}:1900  name={dxml.get('friendlyName','?')}  "
                              f"model={dxml.get('modelName','?')}  serial={dxml.get('serialNumber','?')}  "
                              f"LOCATION={loc}")
                    elif res:
                        info, mac, dtype, fw, ip, platform, name = res
                        print(f"  [SSDP] {info}")
                    else:
                        extra = f"  LOCATION={loc}" if loc else ""
                        print(f"  [SSDP] {d['ip']}:1900  (sem /api/state nem /description.xml){extra}")
                else:
                    entry = {"ip": d["ip"], "port": 1900, "type": "ssdp-only", "ssdp": True, "location": loc}
                    if dxml:
                        entry.update(dxml)
                    devices.append(entry)
                if res and res[1] and not found_gateway_mac:
                    found_gateway_mac = res[1]

    if args.hub:
        if not args.json:
            print(f"\nHub discovery (UDP porta {HUB_DISCOVERY_PORT}, unicast sweep MSG_GW_DISCOVER 0x0A)...")
        hubs = hub_discover()
        if not hubs:
            if not args.json:
                print("  Nenhum hub/bridge respondeu na porta 5000.")
        else:
            for h in hubs:
                if not args.json:
                    print(f"  [HUB] {h['ip']}:{h.get('port', 80)}  fw={h.get('fw_version','?')}  (respondeu como TCP hub via 5000)")
                else:
                    devices.append({"ip": h["ip"], "port": h.get("port", 80), "type": "gateway", "fw_version": h.get("fw_version"), "hub_discovery": True})

    if args.json:
        print(json.dumps(devices, indent=2))
        return

    if args.mac:
        if found_gateway_mac:
            print(f"\n{found_gateway_mac}")
        else:
            print("\nGateway MAC nao encontrado")

if __name__ == "__main__":
    main()
