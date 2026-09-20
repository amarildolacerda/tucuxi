# src/telegram_commands.py
"""Telegram command parser for Tucuxi bot."""


def parse_command(text: str) -> dict:
    """Parse a Telegram message into command and arguments.
    
    Args:
        text: Raw message text from Telegram
        
    Returns:
        dict with 'command' (str or None) and 'args' (list of str)
    """
    if not text or not text.startswith("/"):
        return {"command": None, "args": []}
    
    parts = text.strip().split()
    command = parts[0][1:].split("@")[0].lower()  # Remove / and @botname
    args = parts[1:] if len(parts) > 1 else []
    
    return {"command": command, "args": args}
