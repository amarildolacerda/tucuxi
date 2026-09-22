#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PI_GEN_DIR="${SCRIPT_DIR}/pi-gen"

echo "=== Build da imagem Tucuxi Monitor ==="

# Verificar se é WSL (filesystem Windows)
if grep -qi microsoft /proc/version 2>/dev/null; then
    IS_WSL=true
    echo "Detectado WSL - usando Docker para build"
else
    IS_WSL=false
    echo "Detectado Linux nativo - build direto"
fi

# Verificar pré-requisitos
if ! command -v docker &> /dev/null; then
    if [ "$IS_WSL" = true ]; then
        echo "ERRO: Docker não encontrado. Instale o Docker primeiro."
        exit 1
    fi
fi

# Verificar se Docker está rodando (se necessário)
if [ "$IS_WSL" = true ]; then
    if ! docker info &> /dev/null; then
        echo "ERRO: Docker não está rodando. Inicie o Docker primeiro."
        exit 1
    fi
fi

# Clonar pi-gen se não existir
if [ ! -d "$PI_GEN_DIR" ]; then
    echo "Clonando pi-gen..."
    git clone --depth 1 https://github.com/RPi-Distro/pi-gen.git "$PI_GEN_DIR"
fi

# Configurar diretórios seguros para Git
echo "Configurando diretórios seguros para Git..."
git config --global --add safe.directory "$PI_GEN_DIR"
git config --global --add safe.directory "$SCRIPT_DIR"

# Copiar configurações
echo "Copiando configurações customizadas..."
cp -r "${SCRIPT_DIR}/config" "$PI_GEN_DIR/"
cp -r "${SCRIPT_DIR}/stage3" "$PI_GEN_DIR/"
cp -r "${SCRIPT_DIR}/stage4" "$PI_GEN_DIR/"
cp -r "${SCRIPT_DIR}/stage5" "$PI_GEN_DIR/"

# Build
echo "Iniciando build..."
cd "$PI_GEN_DIR"

# Verificar se existe build anterior para continuar
if [ -d "work/tucuxi-monitor" ]; then
    echo "Build anterior detectado - continuando de onde parou..."
    CONTINUE=1
fi

if [ "$IS_WSL" = true ]; then
    # Build via Docker (WSL)
    sudo CONTINUE=${CONTINUE:-0} ./build-docker.sh -c config/config
else
    # Build direto (Linux nativo)
    sudo CONTINUE=${CONTINUE:-0} ./build.sh -c config/config
fi

echo ""
echo "=== Build concluído ==="
echo "Imagem gerada em: $PI_GEN_DIR/deploy/"
