"""Utilitários compartilhados do projeto Tucuxi."""

import re
import unicodedata


def topic_slug(name: str) -> str:
    """Convert a camera/zone name to a safe MQTT topic segment.

    Rules: lowercase, no accents, alphanumeric + underscores only.
    Examples:
        "Sala de Servidores" -> "sala_de_servidores"
        "Sala de Servidores!" -> "sala_de_servidores"
        "Portão Entrada"     -> "portao_entrada"
        "Garagem"            -> "garagem"
    """
    # Normalize unicode and strip accents
    nfkd = unicodedata.normalize("NFKD", name)
    without_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
    # Lowercase, replace non-alphanumeric with underscore, collapse runs
    slug = without_accents.lower()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = slug.strip("_")
    return slug or "unknown"
