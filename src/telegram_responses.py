# src/telegram_responses.py
"""Telegram response formatters for Tucuxi bot."""

from datetime import datetime, timezone, timedelta


def format_start_response() -> str:
    """Format welcome message."""
    return (
        "🤖 *Bem-vindo ao Tucuxi!*\n\n"
        "Comandos disponíveis:\n"
        "/start - Mensagem de boas-vindas\n"
        "/status - Status do sistema\n"
        "/snapshot <id|nome> - Captura da câmera\n"
        "/alarmhome - Armar casa\n"
        "/alarmaway - Armar viagem\n"
        "/alarmdisarm - Desarmar\n"
        "/events [N] - Últimos N eventos\n"
        "/cameras - Lista de câmeras\n"
        "/help - Ajuda detalhada"
    )


def format_status_response(cameras: list, alarm_mode: str, last_event: dict) -> str:
    """Format system status response."""
    mode_labels = {
        "armed_home": "🔒 Alarme armado",
        "armed_away": "🔒 Alarme Viagem armado",
        "disarmed": "🔓 Alarme desarmado",
    }
    
    mode_text = mode_labels.get(alarm_mode, f"Modo: {alarm_mode}")
    cameras_count = len(cameras)
    
    text = f"📊 *Status do Sistema*\n\n"
    text += f"*Câmeras:* {cameras_count} configurada(s)\n"
    text += f"*Alarme:* {mode_text}\n"
    
    if last_event:
        event_type = last_event.get("event_type", "desconhecido")
        camera_id = last_event.get("camera_id", "?")
        text += f"\n*Último evento:* {event_type} (câmera {camera_id})"
    else:
        text += f"\n*Último evento:* Nenhum"
    
    return text


def format_events_response(events: list) -> str:
    """Format events list response."""
    if not events:
        return "📋 *Eventos*\n\nNenhum evento registrado."
    
    text = f"📋 *Últimos {len(events)} eventos*\n\n"
    for i, event in enumerate(events, 1):
        event_type = event.get("event_type", "desconhecido")
        camera_id = event.get("camera_id", "?")
        timestamp = event.get("timestamp")
        
        if timestamp:
            try:
                # Handle both numeric epoch and string timestamps
                if isinstance(timestamp, (int, float)):
                    dt = datetime.fromtimestamp(timestamp, tz=timezone(timedelta(hours=-3)))
                else:
                    # Parse ISO string and convert to local timezone
                    dt = datetime.fromisoformat(str(timestamp)).astimezone(timezone(timedelta(hours=-3)))
                ts = dt.strftime("%d/%m %H:%M")
            except (ValueError, TypeError):
                ts = str(timestamp)[:16]
            text += f"{i}. {event_type} - Câmera {camera_id} ({ts})\n"
        else:
            text += f"{i}. {event_type} - Câmera {camera_id}\n"
    
    return text


def format_cameras_response(cameras: list) -> str:
    """Format cameras list response."""
    if not cameras:
        return "📷 *Câmeras*\n\nNenhuma câmera configurada."
    
    text = f"📷 *Câmeras*\n\n"
    for cam in cameras:
        name = cam.get("name", "Sem nome")
        zone = cam.get("zone", "Sem zona")
        cam_id = cam.get("id", "?")
        status = cam.get("status", "desconhecido")
        status_icon = "🟢" if status == "online" else "🔴"
        text += f"{status_icon} *{name}* - {zone}\n   /snapshot {cam_id}\n"
    
    return text


def format_help_response() -> str:
    """Format detailed help response."""
    return (
        "❓ *Ajuda - Comandos Tucuxi*\n\n"
        "/start - Mensagem de boas-vindas\n"
        "/status - Resumo do sistema (câmeras, alarme, último evento)\n"
        "/snapshot <id|nome> - Captura imagem da câmera especificada\n"
        "/alarmhome - Armar modo casa\n"
        "/alarmaway - Armar modo viagem\n"
        "/alarmdisarm - Desarmar alarme\n"
        "/events [N] - Lista os últimos N eventos (padrão: 10)\n"
        "/cameras - Lista todas as câmeras com status\n"
        "/help - Esta mensagem de ajuda"
    )


def format_alarm_response(mode: str, success: bool) -> str:
    """Format alarm mode change response."""
    if success:
        mode_labels = {
            "armed_home": "🔒 Alarme armado",
            "armed_away": "🔒 Alarme Viagem armado",
            "disarmed": "🔓 Alarme desarmado",
        }
        return f"✅ {mode_labels.get(mode, f'Modo alterado: {mode}')}"
    else:
        return "❌ Modo de alarme inválido. Use: armed_home, armed_away, ou disarmed"


def format_snapshot_error(error: str) -> str:
    """Format snapshot error response."""
    return f"❌ Erro ao capturar snapshot: {error}"


def format_access_denied() -> str:
    """Format access denied response."""
    return "🚫 Acesso negado. Chat ID não autorizado."
