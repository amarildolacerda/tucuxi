"""
test_ptz.py — Valida se a câmera atual suporta controle PTZ.

Uso:
    python tests/test_ptz.py --ip 192.168.1.100 --user admin --password 123456
    python tests/test_ptz.py --ip 192.168.1.100 --user admin --password 123456 --move
"""
import argparse
import sys

try:
    from onvif import ONVIFCamera
except ImportError:
    print("ERRO: lib onvif-zeep não instalada.")
    print("Instale com: pip install onvif-zeep")
    sys.exit(1)


def test_ptz(ip, port, user, password, move=False):
    """Testa capacidades PTZ da câmera."""
    print(f"\n{'='*50}")
    print(f"  Teste PTZ — {ip}:{port}")
    print(f"{'='*50}\n")

    # 1. Conectar
    print("[1] Conectando via ONVIF...")
    try:
        cam = ONVIFCamera(ip, port, user, password)
        print("    OK")
    except Exception as e:
        print(f"    FALHA: {e}")
        return False

    # 2. Device Management — capabilities
    print("\n[2] Capabilities do device:")
    try:
        dev_mgmt = cam.create_devicemgmt_service()
        caps = dev_mgmt.GetCapabilities()

        media = caps.Media if caps.Media else None
        ptz = caps.PTZ if caps.PTZ else None

        print(f"    Media: {media}")
        print(f"    PTZ:   {ptz}")

        if not ptz:
            print("\n    ⚠️  PTZ NÃO DISPONÍVEL nesta câmera.")
            print("    A câmera não suporta movimento remoto.")
            return False
        else:
            print("\n    ✅ PTZ DETECTADO!")
    except Exception as e:
        print(f"    Erro ao obter capabilities: {e}")
        return False

    # 3. Profiles de mídia
    print("\n[3] Profiles de mídia:")
    profiles = []
    try:
        media_service = cam.create_media_service()
        profiles = media_service.GetProfiles()
        for p in profiles:
            print(f"    - {p.Name} (token: {p.token})")
    except Exception as e:
        print(f"    Erro: {e}")

    # 4. Configuração PTZ
    print("\n[4] Configuração PTZ:")
    ptz_service = None
    try:
        ptz_service = cam.create_ptz_service()

        # Nodes (mecanismos PTZ)
        try:
            nodes = ptz_service.GetNodes()
            for node in nodes:
                print(f"    Node: {node.Name}")
                print(f"      Token: {node.token}")
        except Exception as e:
            print(f"    Erro ao listar nodes: {e}")

        # Capacidades PTZ
        try:
            ptz_caps = ptz_service.GetServiceCapabilities()
            print(f"\n    Capacidades PTZ:")
            print(f"      ContinuousMove: {getattr(ptz_caps, 'ContinuousMove', 'N/A')}")
            print(f"      RelativeMove:   {getattr(ptz_caps, 'RelativeMove', 'N/A')}")
            print(f"      AbsoluteMove:   {getattr(ptz_caps, 'AbsoluteMove', 'N/A')}")
            print(f"      GetPresets:     {getattr(ptz_caps, 'GetPresets', 'N/A')}")
            print(f"      PresetPositions:{getattr(ptz_caps, 'PresetPositions', 'N/A')}")
        except Exception as e:
            print(f"    Erro capabilities: {e}")

        # Presets
        try:
            profile_token = profiles[0].token if profiles else None
            if profile_token:
                presets = ptz_service.GetPresets({"ProfileToken": profile_token})
                print(f"\n    Presets configurados: {len(presets)}")
                for preset in presets[:5]:
                    print(f"      - {preset.Name} (token: {preset.token})")
                if len(presets) > 5:
                    print(f"      ... e mais {len(presets) - 5}")
        except Exception as e:
            print(f"    Presets: {e}")

    except Exception as e:
        print(f"    Erro serviço PTZ: {e}")
        return False

    # 5. Teste de movimento (opcional)
    if move and ptz_service and profiles:
        print("\n[5] Teste de movimento:")
        profile_token = profiles[0].token
        directions = [
            ("esquerda",  {"x": -0.5, "y":  0.0}),
            ("direita",   {"x":  0.5, "y":  0.0}),
            ("cima",      {"x":  0.0, "y":  0.5}),
            ("baixo",     {"x":  0.0, "y": -0.5}),
            ("zoom +",    {"x":  0.0, "y":  0.0}, 0.3),
            ("zoom −",    {"x":  0.0, "y":  0.0}, -0.3),
        ]
        for item in directions:
            name, pan_tilt = item[0], item[1]
            zoom_x = item[2] if len(item) > 2 else 0.0
            try:
                print(f"    Movendo {name} por 0.5s...")
                req = {
                    "ProfileToken": profile_token,
                    "Velocity": {
                        "PanTilt": pan_tilt,
                        "Zoom": {"x": zoom_x}
                    }
                }
                ptz_service.ContinuousMove(req)
                import time
                time.sleep(0.5)
                ptz_service.Stop({"ProfileToken": profile_token})
                time.sleep(0.3)
                print(f"    ✅ {name} OK")
            except Exception as e:
                print(f"    ❌ {name} FALHA: {e}")
        print("    Todos os movimentos executados!")
    else:
        print("\n[5] Teste de movimento: OMITIDO (use --move para ativar)")

    print(f"\n{'='*50}")
    print("  CONCLUSÃO: Câmera suporta PTZ")
    print(f"{'='*50}\n")
    return True


def main():
    parser = argparse.ArgumentParser(description="Teste PTZ da câmera")
    parser.add_argument("--ip", required=True, help="IP da câmera")
    parser.add_argument("--port", type=int, default=80, help="Porta ONVIF (padrão: 80)")
    parser.add_argument("--user", default="admin", help="Usuário")
    parser.add_argument("--password", default="admin", help="Senha")
    parser.add_argument("--move", action="store_true", help="Executa teste de movimento real")
    args = parser.parse_args()

    success = test_ptz(args.ip, args.port, args.user, args.password, args.move)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
