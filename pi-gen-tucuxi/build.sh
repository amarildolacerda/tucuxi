#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PI_GEN_DIR="${SCRIPT_DIR}/pi-gen"

echo "=== Build da imagem Tucuxi Monitor ==="

# Verificar pré-requisitos
if ! command -v docker &> /dev/null; then
    echo "ERRO: Docker não encontrado. Instale o Docker primeiro."
    exit 1
fi

# Clonar pi-gen se não existir
if [ ! -d "$PI_GEN_DIR" ]; then
    echo "Clonando pi-gen..."
    git clone --depth 1 https://github.com/RPi-Distro/pi-gen.git "$PI_GEN_DIR"
fi

# Copiar configurações
echo "Copiando configurações customizadas..."
cp -r "${SCRIPT_DIR}/config" "$PI_GEN_DIR/"
cp -r "${SCRIPT_DIR}/stage3" "$PI_GEN_DIR/"
cp -r "${SCRIPT_DIR}/stage4" "$PI_GEN_DIR/"
cp -r "${SCRIPT_DIR}/stage5" "$PI_GEN_DIR/"

# Build da imagem
echo "Iniciando build da imagem..."
cd "$PI_GEN_DIR"
sudo ./build.sh -c config/config

echo "=== Build concluído ==="
echo "Imagem gerada em: $PI_GEN_DIR/output/"
