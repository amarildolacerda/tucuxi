#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Build da imagem Tucuxi Monitor (via Docker) ==="

# Verificar pré-requisitos
if ! command -v docker &> /dev/null; then
    echo "ERRO: Docker não encontrado. Instale o Docker primeiro."
    exit 1
fi

# Verificar se Docker está rodando
if ! docker info &> /dev/null; then
    echo "ERRO: Docker não está rodando. Inicie o Docker primeiro."
    exit 1
fi

echo "Usando Docker para build (evita problemas de symlinks no WSL)..."
echo ""

# Build via Docker
docker run --rm --privileged \
    -v "${SCRIPT_DIR}:/pi-gen-tucuxi" \
    -v "${SCRIPT_DIR}/config:/config" \
    -v "${SCRIPT_DIR}/stage3:/stage3" \
    -v "${SCRIPT_DIR}/stage4:/stage4" \
    -v "${SCRIPT_DIR}/stage5:/stage5" \
    -w /pi-gen-tucuxi \
    rpirtc/pi-gen:latest \
    bash -c "
        # Instalar dependências
        apt-get update
        apt-get install -y quilt parted qemu-user-static debootstrap zerofree zip dosfstools libarchive-tools arch-test
        
        # Clonar pi-gen
        if [ ! -d pi-gen ]; then
            git clone --depth 1 https://github.com/RPi-Distro/pi-gen.git pi-gen
        fi
        
        # Copiar configurações
        cp -r /config pi-gen/
        cp -r /stage3 pi-gen/
        cp -r /stage4 pi-gen/
        cp -r /stage5 pi-gen/
        
        # Build
        cd pi-gen
        ./build.sh -c config/config
    "

echo ""
echo "=== Build concluído ==="
echo "Imagem gerada em: ${SCRIPT_DIR}/pi-gen/output/"
