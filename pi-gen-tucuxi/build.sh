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

# Verificar se já é root
if [ "$EUID" -eq 0 ]; then
    echo "Rodando como root."
    IS_ROOT=true
else
    echo "Não está rodando como root."
    IS_ROOT=false
    
    # Verificar se sudo está disponível
    if ! command -v sudo &> /dev/null; then
        echo "ERRO: sudo não encontrado. Execute como root ou instale sudo."
        exit 1
    fi
    
    # Verificar se o usuário tem permissão de sudo
    echo "Verificando permissões de sudo..."
    if ! sudo -n true 2>/dev/null; then
        echo ""
        echo "ATENÇÃO: Você precisa de permissão de sudo para buildar a imagem."
        echo ""
        echo "Opções:"
        echo "  1. Execute: sudo ./build.sh"
        echo "  2. Ou execute: sudo -i  (depois rode ./build.sh)"
        echo ""
        exit 1
    fi
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

if [ "$IS_ROOT" = true ]; then
    ./build.sh -c config/config
else
    sudo ./build.sh -c config/config
fi

echo "=== Build concluído ==="
echo "Imagem gerada em: $PI_GEN_DIR/output/"
