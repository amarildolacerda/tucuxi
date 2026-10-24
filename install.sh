#!/usr/bin/env bash
#
# Tucuxi Monitor — instalador de produção (bare metal + systemd)
#
# O que este script faz:
#   1. Instala dependências do sistema (git, curl, python3-venv)
#   2. Clona (ou atualiza) o repositório em /opt/tucuxi
#   3. Cria usuário de serviço dedicado (tucuxi) e ambiente virtual Python
#   4. Instala as dependências Python + Waitress (servidor de produção)
#   5. Gera .env de produção na primeira instalação (sem sobrescrever depois)
#   6. Cria e habilita o serviço systemd "tucuxi" (inicia no boot)
#   7. Cria o admin inicial e remove a câmera de exemplo
#
# Uso local:
#   sudo ./install.sh
#
# Uso via link (recomendado no servidor):
#   curl -fsSL https://raw.githubusercontent.com/amarildolacerda/tucuxi/main/install.sh | sudo bash
#   wget -qO- https://raw.githubusercontent.com/amarildolacerda/tucuxi/main/install.sh | sudo bash
#
# Opções:
#   -d, --dir DIR            Diretório de instalação (padrão: /opt/tucuxi)
#   -b, --branch BRANCH      Branch do git (padrão: main)
#   -p, --port PORT          Porta HTTP (padrão: 8000)
#   -u, --user USER          Usuário dono do serviço (padrão: tucuxi / dono do diretório)
#       --admin-user USER    Usuário admin inicial (padrão: admin)
#       --admin-password PWD Senha do admin inicial (padrão: gerada aleatoriamente)
#       --skip-admin         Não cria o admin inicial (deixa /setup aberto — inseguro)
#       --no-apt             Não instala pacotes do sistema via apt-get
#       --no-start           Prepara tudo, mas não inicia o serviço
#       --uninstall          Remove serviço, unit e sudoers (preserva /opt/tucuxi)
#   -y, --yes                Confirma ações destrutivas (--uninstall)
#   -h, --help               Mostra esta ajuda
#
# Variáveis de ambiente equivalentes: APP_DIR, BRANCH, SERVER_PORT, SERVICE_USER,
# ADMIN_USER, ADMIN_PASSWORD, TUCUXI_REPO_URL, TUCUXI_INSTALL_URL.
#
set -Eeuo pipefail

REPO_URL="${TUCUXI_REPO_URL:-https://github.com/amarildolacerda/tucuxi.git}"
INSTALL_URL="${TUCUXI_INSTALL_URL:-https://raw.githubusercontent.com/amarildolacerda/tucuxi/main/install.sh}"
SERVICE_NAME="tucuxi"
DEFAULT_DIR="/opt/tucuxi"
MIN_PY_MINOR=11

usage() {
  cat <<'TXT'
Tucuxi Monitor — instalador de produção (bare metal + systemd)

Uso local:
  sudo ./install.sh

Uso via link:
  curl -fsSL https://raw.githubusercontent.com/amarildolacerda/tucuxi/main/install.sh | sudo bash
  wget -qO- https://raw.githubusercontent.com/amarildolacerda/tucuxi/main/install.sh | sudo bash

Opções:
  -d, --dir DIR             Diretório de instalação (padrão: /opt/tucuxi)
  -b, --branch BRANCH       Branch do git (padrão: main)
  -p, --port PORT           Porta HTTP (padrão: 8000)
  -u, --user USER           Usuário dono do serviço (padrão: tucuxi)
      --admin-user USER     Usuário admin inicial (padrão: admin)
      --admin-password PWD  Senha do admin inicial (padrão: gerada aleatoriamente)
      --skip-admin          Não cria o admin inicial (deixa /setup aberto — inseguro)
      --no-apt              Não instala pacotes do sistema via apt-get
      --no-start            Prepara tudo, mas não inicia o serviço
      --uninstall           Remove serviço, unit e sudoers (preserva o código/dados)
  -y, --yes                 Confirma ações destrutivas (--uninstall)
  -h, --help                Mostra esta ajuda

Variáveis: APP_DIR, BRANCH, SERVER_PORT, SERVICE_USER, ADMIN_USER,
ADMIN_PASSWORD, TUCUXI_REPO_URL, TUCUXI_INSTALL_URL.
TXT
}

for arg in "$@"; do
  case "$arg" in
    -h|--help) usage; exit 0 ;;
  esac
done

# ── Saída ────────────────────────────────────────────────────────────────
if [[ -t 1 ]]; then
  C_RESET=$'\033[0m'; C_BLUE=$'\033[1;34m'; C_GREEN=$'\033[1;32m'
  C_YELLOW=$'\033[1;33m'; C_RED=$'\033[1;31m'
else
  C_RESET=""; C_BLUE=""; C_GREEN=""; C_YELLOW=""; C_RED=""
fi
log()  { printf '%s==>%s %s\n' "$C_BLUE" "$C_RESET" "$*"; }
ok()   { printf '%s  ✓%s %s\n' "$C_GREEN" "$C_RESET" "$*"; }
warn() { printf '%sAviso:%s %s\n' "$C_YELLOW" "$C_RESET" "$*" >&2; }
die()  { printf '%sErro:%s %s\n' "$C_RED" "$C_RESET" "$*" >&2; exit 1; }
trap 'die "falha na linha $LINENO (comando: $BASH_COMMAND)"' ERR

# Executa um comando demorado mostrando spinner, tempo decorrido e a última
# linha do log (para não parecer travado). Em caso de erro, mostra o log.
run_long() {
  local label="$1"; shift
  local logfile start rc=0
  logfile="$(mktemp)"
  start=$SECONDS

  if [[ -t 1 ]]; then
    "$@" >"$logfile" 2>&1 &
    local pid=$! frames='|/-\' i=0 last=""
    trap 'kill "$pid" 2>/dev/null || true' INT TERM
    while kill -0 "$pid" 2>/dev/null; do
      last="$(tail -n 1 "$logfile" 2>/dev/null | tr -d '\r' | cut -c1-64)"
      printf '\r    %s %s [%3ds] %s\033[K' "${frames:i%4:1}" "$label" "$((SECONDS-start))" "$last"
      i=$((i+1))
      sleep 0.25
    done
    wait "$pid" || rc=$?
    trap - INT TERM
    printf '\r\033[K'
  else
    printf '    %s...\n' "$label"
    "$@" >"$logfile" 2>&1 || rc=$?
  fi

  if ((rc != 0)); then
    printf '    %s✗%s %s (falhou após %ds)\n' "$C_RED" "$C_RESET" "$label" "$((SECONDS-start))" >&2
    tail -n 40 "$logfile" >&2 || true
    rm -f "$logfile"
    die "$label falhou (código $rc)"
  fi
  printf '    %s✓%s %s (%ds)\n' "$C_GREEN" "$C_RESET" "$label" "$((SECONDS-start))"
  rm -f "$logfile"
}

# ── Elevação para root ───────────────────────────────────────────────────
# Funciona também quando o script é executado via pipe (curl ... | bash).
if [[ ${EUID} -ne 0 ]]; then
  args=("$@")
  if [[ -n "${BASH_SOURCE[0]:-}" && -f "${BASH_SOURCE[0]}" ]]; then
    self="$(realpath "${BASH_SOURCE[0]}")"
    exec sudo env \
      "ADMIN_USER=${ADMIN_USER:-}" "ADMIN_PASSWORD=${ADMIN_PASSWORD:-}" \
      "SERVICE_USER=${SERVICE_USER:-}" "APP_DIR=${APP_DIR:-}" \
      "TUCUXI_REPO_URL=${REPO_URL}" "TUCUXI_INSTALL_URL=${INSTALL_URL}" \
      bash "$self" "${args[@]}"
  fi
  qargs=""
  if ((${#args[@]})); then qargs="$(printf '%q ' "${args[@]}")"; fi
  exec sudo env \
    "ADMIN_USER=${ADMIN_USER:-}" "ADMIN_PASSWORD=${ADMIN_PASSWORD:-}" \
    "SERVICE_USER=${SERVICE_USER:-}" "APP_DIR=${APP_DIR:-}" \
    "TUCUXI_REPO_URL=${REPO_URL}" "TUCUXI_INSTALL_URL=${INSTALL_URL}" \
    bash -c "curl -fsSL $(printf '%q' "$INSTALL_URL") | bash -s -- $qargs"
fi

# ── Argumentos ───────────────────────────────────────────────────────────
APP_DIR="${APP_DIR:-}"
BRANCH="${BRANCH:-main}"
SERVER_PORT="${SERVER_PORT:-8000}"
SERVICE_USER="${SERVICE_USER:-}"
ADMIN_USER="${ADMIN_USER:-admin}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-}"
DO_APT=1
DO_START=1
SKIP_ADMIN=0
UNINSTALL=0
ASSUME_YES=0

while (($#)); do
  case "$1" in
    -d|--dir)            APP_DIR="${2:?--dir exige um valor}"; shift 2 ;;
    --dir=*)             APP_DIR="${1#*=}"; shift ;;
    -b|--branch)         BRANCH="${2:?--branch exige um valor}"; shift 2 ;;
    --branch=*)          BRANCH="${1#*=}"; shift ;;
    -p|--port)           SERVER_PORT="${2:?--port exige um valor}"; shift 2 ;;
    --port=*)            SERVER_PORT="${1#*=}"; shift ;;
    -u|--user)           SERVICE_USER="${2:?--user exige um valor}"; shift 2 ;;
    --user=*)            SERVICE_USER="${1#*=}"; shift ;;
    --admin-user)        ADMIN_USER="${2:?--admin-user exige um valor}"; shift 2 ;;
    --admin-user=*)      ADMIN_USER="${1#*=}"; shift ;;
    --admin-password)    ADMIN_PASSWORD="${2:?--admin-password exige um valor}"; shift 2 ;;
    --admin-password=*)  ADMIN_PASSWORD="${1#*=}"; shift ;;
    --skip-admin)        SKIP_ADMIN=1; shift ;;
    --no-apt)            DO_APT=0; shift ;;
    --no-start)          DO_START=0; shift ;;
    --uninstall)         UNINSTALL=1; shift ;;
    -y|--yes)            ASSUME_YES=1; shift ;;
    -h|--help)           usage; exit 0 ;;
    *)                   die "opção desconhecida: $1 (use --help)" ;;
  esac
done

[[ "$SERVER_PORT" =~ ^[0-9]+$ ]] || die "porta inválida: $SERVER_PORT"

# ── Desinstalação ────────────────────────────────────────────────────────
if ((UNINSTALL)); then
  if ((!ASSUME_YES)); then
    die "use --uninstall --yes para confirmar a remoção do serviço"
  fi
  log "Removendo serviço $SERVICE_NAME..."
  systemctl disable --now "$SERVICE_NAME" 2>/dev/null || true
  rm -f "/etc/systemd/system/${SERVICE_NAME}.service" "/etc/sudoers.d/${SERVICE_NAME}-ota"
  systemctl daemon-reload 2>/dev/null || true
  ok "Serviço removido. Dados e código permanecem em ${APP_DIR:-$DEFAULT_DIR}."
  exit 0
fi

APP_DIR="${APP_DIR:-$DEFAULT_DIR}"
APP_DIR="$(realpath -m "$APP_DIR")"
case "$APP_DIR" in
  /|/usr|/etc|/var|/bin|/sbin|/lib|/boot) die "diretório de instalação inválido: $APP_DIR" ;;
esac

log "Tucuxi Monitor — instalação de produção"
log "Diretório: $APP_DIR"
log "Branch:    $BRANCH"
log "Porta:     $SERVER_PORT"

# ── Dependências do sistema ──────────────────────────────────────────────
if ((DO_APT)); then
  command -v apt-get >/dev/null || die "apt-get não encontrado; use --no-apt e instale git/curl/python3-venv manualmente"
  missing=()
  command -v git   >/dev/null || missing+=(git)
  command -v curl  >/dev/null || missing+=(curl)
  python3 -c 'import venv, ensurepip' >/dev/null 2>&1 || missing+=(python3-venv)
  if ((${#missing[@]})); then
    log "Instalando pacotes do sistema: ${missing[*]}"
    export DEBIAN_FRONTEND=noninteractive
    run_long "Atualizando índices do apt" apt-get update -qq
    run_long "Instalando pacotes do sistema" \
      apt-get install -y -qq --no-install-recommends "${missing[@]}"
  fi
fi

command -v git  >/dev/null || die "git não encontrado"
command -v curl >/dev/null || die "curl não encontrado"
command -v python3 >/dev/null || die "python3 não encontrado"

python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
  || die "Python 3.${MIN_PY_MINOR}+ é obrigatório (encontrado: $(python3 -V 2>&1))"

# ── Usuário do serviço ───────────────────────────────────────────────────
if [[ -z "$SERVICE_USER" ]]; then
  if [[ -d "$APP_DIR" ]] && [[ "$(stat -c %U "$APP_DIR")" != "root" ]]; then
    SERVICE_USER="$(stat -c %U "$APP_DIR")"
  elif [[ -n "${SUDO_USER:-}" && "$APP_DIR" == "/home/${SUDO_USER}"/* ]]; then
    SERVICE_USER="$SUDO_USER"
  else
    SERVICE_USER="tucuxi"
  fi
fi

if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
  log "Criando usuário de serviço: $SERVICE_USER"
  useradd --system --user-group --home-dir "$APP_DIR" --no-create-home \
          --shell /usr/sbin/nologin "$SERVICE_USER"
fi
SERVICE_GROUP="$(id -gn "$SERVICE_USER")"
[[ "$SERVICE_USER" != "root" ]] || warn "o serviço rodará como root; recomenda-se um usuário dedicado"

# ── Código (clone / atualização) ─────────────────────────────────────────
export GIT_TERMINAL_PROMPT=0
mkdir -p "$(dirname "$APP_DIR")"
if [[ -d "$APP_DIR/.git" ]]; then
  log "Atualizando código existente (git)..."
  warn "sincronizando com origin/$BRANCH — alterações locais no código serão descartadas"
  git config --global --add safe.directory "$APP_DIR"
  run_long "Buscando código no GitHub" \
    git -C "$APP_DIR" fetch --tags --prune --progress origin
  git -C "$APP_DIR" checkout -B "$BRANCH" "origin/$BRANCH"
  git -C "$APP_DIR" reset --hard "origin/$BRANCH"
elif [[ -f "$APP_DIR/run.py" ]]; then
  log "Usando código já presente em $APP_DIR (sem repositório git)"
elif [[ -d "$APP_DIR" && -n "$(ls -A "$APP_DIR" 2>/dev/null)" ]]; then
  die "$APP_DIR existe e não está vazio (nem é um clone do Tucuxi)"
else
  log "Clonando $REPO_URL..."
  run_long "Clonando repositório do GitHub" \
    git clone --progress --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi
[[ -f "$APP_DIR/run.py" ]] || die "run.py não encontrado em $APP_DIR"

# Para uma instalação anterior antes de atualizar dependências
systemctl stop "$SERVICE_NAME" 2>/dev/null || true

# ── Ambiente virtual + dependências Python ───────────────────────────────
VENV_DIR="$APP_DIR/.venv"
if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  log "Criando ambiente virtual em $VENV_DIR"
  run_long "Criando ambiente virtual Python" python3 -m venv "$VENV_DIR"
fi
if ! "$VENV_DIR/bin/python" -m pip --version >/dev/null 2>&1; then
  log "Instalando pip no ambiente virtual..."
  if ! "$VENV_DIR/bin/python" -m ensurepip --upgrade >/dev/null 2>&1; then
    TMP_GETPIP="$(mktemp)"
    run_long "Baixando get-pip.py" \
      curl -4 -fsSL --retry 5 --connect-timeout 15 \
        https://bootstrap.pypa.io/get-pip.py -o "$TMP_GETPIP"
    run_long "Instalando pip" "$VENV_DIR/bin/python" "$TMP_GETPIP" --no-cache-dir
    rm -f "$TMP_GETPIP"
  fi
fi

log "Instalando dependências Python (pode levar vários minutos)..."
case "$(uname -m)" in
  arm*|aarch64)
    warn "em ARM, se o pip falhar ao compilar algo, instale: build-essential libxml2-dev libxslt1-dev" ;;
esac
export PIP_DISABLE_PIP_VERSION_CHECK=1
PIP=("$VENV_DIR/bin/python" -m pip)
run_long "Atualizando pip, setuptools e wheel" \
  "${PIP[@]}" install --no-cache-dir --timeout 60 --retries 5 --prefer-binary \
  --upgrade pip setuptools wheel
run_long "Instalando Flask, OpenCV, NumPy, Waitress e demais pacotes" \
  "${PIP[@]}" install --no-cache-dir --timeout 60 --retries 5 --prefer-binary \
  -r "$APP_DIR/requirements.txt" waitress

# ── Arquivo .env ─────────────────────────────────────────────────────────
ENV_FILE="$APP_DIR/.env"
set_env() {
  local key="$1" value="${2-}"
  ENV_FILE="$ENV_FILE" ENV_KEY="$key" ENV_VALUE="$value" python3 - <<'PY'
import os
path = os.environ["ENV_FILE"]
key = os.environ["ENV_KEY"]
value = os.environ["ENV_VALUE"]
try:
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
except FileNotFoundError:
    lines = []
out = []
found = False
for line in lines:
    if line.startswith(key + "="):
        out.append(f"{key}={value}")
        found = True
    else:
        out.append(line)
if not found:
    out.append(f"{key}={value}")
with open(path, "w", encoding="utf-8") as fh:
    fh.write("\n".join(out).rstrip("\n") + "\n")
PY
}

if [[ -f "$ENV_FILE" ]]; then
  log "Preservando .env existente"
  env_port="$(grep -E '^SERVER_PORT=' "$ENV_FILE" | tail -n1 | cut -d= -f2- || true)"
  if [[ -n "$env_port" ]]; then
    SERVER_PORT="$env_port"
  fi
else
  log "Gerando .env de produção"
  if [[ -f "$APP_DIR/.env_default" ]]; then
    cp "$APP_DIR/.env_default" "$ENV_FILE"
  else
    : > "$ENV_FILE"
  fi
  set_env SERVER_HOST "0.0.0.0"
  set_env SERVER_PORT "$SERVER_PORT"
  set_env DETECTOR_MODEL_PATH ""
  set_env PREDICTOR_ENABLED "false"
  # Canais externos ficam desligados até serem configurados (evita erros/spam)
  set_env TELEGRAM_BOT_TOKEN ""
  set_env TELEGRAM_CHAT_ID ""
  set_env MQTT_BROKER_URL ""
  set_env MQTT_USERNAME ""
  set_env MQTT_PASSWORD ""
  set_env HOME_ASSISTANT_URL ""
  set_env HOME_ASSISTANT_TOKEN ""
  if [[ -f "$APP_DIR/data/models/detector.onnx" ]]; then
    set_env DETECTOR_MODEL_PATH "$APP_DIR/data/models/detector.onnx"
  fi
fi
chmod 600 "$ENV_FILE"

# ── Launcher WSGI de produção ────────────────────────────────────────────
WSGI_FILE="$APP_DIR/deploy/wsgi.py"
if [[ ! -f "$WSGI_FILE" ]]; then
  log "Criando launcher WSGI de produção (Waitress)"
  mkdir -p "$(dirname "$WSGI_FILE")"
  cat > "$WSGI_FILE" <<'PY'
"""Launcher de produção do Tucuxi Monitor.

Executa o wiring completo de src.main.main() (câmeras, alertas, MQTT,
Telegram, predictor e dashboard) mas substitui o servidor de desenvolvimento
do Flask (app.run(debug=True)) por Waitress, um servidor WSGI de produção
multi-thread e sem debugger interativo.

Uso: .venv/bin/python deploy/wsgi.py
"""

import importlib
import os
import runpy
import sys

import flask
from waitress import serve

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

os.chdir(ROOT_DIR)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# Produção: não cria a câmera de exemplo rtsp://admin:123456@192.168.1.104.
# Sem isso, o app re-semeia a câmera fake sempre que não há câmeras no banco.
importlib.import_module("src.main").DEFAULT_CAMERAS = []


def _run_waitress(self, host=None, port=None, debug=None, load_dotenv=True, **options):
    host = host or os.getenv("SERVER_HOST", "0.0.0.0")
    port = int(port or os.getenv("SERVER_PORT", "8000"))
    threads = int(os.getenv("WAITRESS_THREADS", "16"))
    serve(self, host=host, port=port, threads=threads, ident="Tucuxi")


flask.Flask.run = _run_waitress

runpy.run_path(os.path.join(ROOT_DIR, "run.py"), run_name="__main__")
PY
fi

# Mantém o repositório limpo para o updater (OTA) e para futuros pulls
if [[ -d "$APP_DIR/.git" ]]; then
  touch "$APP_DIR/.git/info/exclude"
  for entry in ".venv/" "data/"; do
    grep -qxF "$entry" "$APP_DIR/.git/info/exclude" || echo "$entry" >> "$APP_DIR/.git/info/exclude"
  done
fi

# ── Serviço systemd ──────────────────────────────────────────────────────
log "Configurando serviço systemd: $SERVICE_NAME"

cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=Tucuxi Monitor (produção)
Documentation=https://github.com/amarildolacerda/tucuxi
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_GROUP}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${ENV_FILE}
Environment=PATH=${VENV_DIR}/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
Environment=PYTHONUNBUFFERED=1
Environment=WAITRESS_THREADS=16
ExecStart=${VENV_DIR}/bin/python ${APP_DIR}/deploy/wsgi.py
Restart=always
RestartSec=5
TimeoutStopSec=20
KillMode=mixed
ProtectSystem=full
PrivateTmp=true
ReadWritePaths=${APP_DIR}
SyslogIdentifier=${SERVICE_NAME}

[Install]
WantedBy=multi-user.target
EOF

# Permite que o OTA (rodando como usuário do serviço) reinicie o serviço
if [[ "$SERVICE_USER" != "root" ]]; then
  cat > "/etc/sudoers.d/${SERVICE_NAME}-ota" <<EOF
${SERVICE_USER} ALL=(root) NOPASSWD: /usr/bin/systemctl restart ${SERVICE_NAME}, /usr/bin/systemctl start ${SERVICE_NAME}, /usr/bin/systemctl stop ${SERVICE_NAME}
EOF
  chmod 440 "/etc/sudoers.d/${SERVICE_NAME}-ota"
  visudo -cf "/etc/sudoers.d/${SERVICE_NAME}-ota" >/dev/null || die "regra sudoers inválida"
fi

# ── Propriedade e permissões ─────────────────────────────────────────────
if [[ "$SERVICE_USER" != "root" ]]; then
  run_long "Ajustando permissões de $APP_DIR" \
    chown -R "$SERVICE_USER:$SERVICE_GROUP" "$APP_DIR"
fi
chmod 600 "$ENV_FILE"
mkdir -p "$APP_DIR/data"
if [[ "$SERVICE_USER" != "root" ]]; then
  chown -R "$SERVICE_USER:$SERVICE_GROUP" "$APP_DIR/data"
fi

systemctl daemon-reload
systemctl enable "$SERVICE_NAME" >/dev/null

# ── Firewall (opcional) ──────────────────────────────────────────────────
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
  log "Liberando porta ${SERVER_PORT}/tcp no ufw"
  ufw allow "${SERVER_PORT}/tcp" >/dev/null || warn "não foi possível liberar a porta no ufw"
fi

# ── Início ───────────────────────────────────────────────────────────────
BASE_URL="http://127.0.0.1:${SERVER_PORT}"
if ((DO_START)); then
  log "Iniciando serviço..."
  if ! systemctl restart "$SERVICE_NAME"; then
    journalctl -u "$SERVICE_NAME" -n 60 --no-pager 2>/dev/null || true
    die "falha ao iniciar o serviço (veja: journalctl -u ${SERVICE_NAME} -n 100)"
  fi

  log "Aguardando o servidor responder em ${BASE_URL}/health..."
  healthy=0
  for i in $(seq 1 60); do
    if curl -fsS --max-time 2 "${BASE_URL}/health" >/dev/null 2>&1; then
      healthy=1; break
    fi
    if ! systemctl is-active --quiet "$SERVICE_NAME"; then break; fi
    if [[ -t 1 ]]; then
      printf '\r    Aguardando /health... %ds' "$i"
    fi
    sleep 1
  done
  if [[ -t 1 ]]; then printf '\r\033[K'; fi
  if ((!healthy)); then
    journalctl -u "$SERVICE_NAME" -n 60 --no-pager 2>/dev/null || true
    die "o serviço não respondeu em ${BASE_URL}/health (veja: journalctl -u ${SERVICE_NAME} -n 100)"
  fi
  ok "Serviço saudável em ${BASE_URL}"

  # ── Admin inicial ──────────────────────────────────────────────────────
  JAR="$(mktemp)"
  trap 'rm -f "$JAR"' EXIT
  setup_code="$(curl -s -o /dev/null -w '%{http_code}' "${BASE_URL}/setup" || true)"
  if [[ "$setup_code" == "200" ]]; then
    if ((SKIP_ADMIN)); then
      warn "Nenhum admin criado (--skip-admin). O painel está ABERTO em ${BASE_URL}/setup."
      warn "Crie o admin agora para não expor o sistema na rede."
    else
      generated=0
      if [[ -z "$ADMIN_PASSWORD" ]]; then
        ADMIN_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_hex(12))')"
        generated=1
      fi
      juser="$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$ADMIN_USER")"
      jpass="$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$ADMIN_PASSWORD")"
      curl -fsS -c "$JAR" -H 'Content-Type: application/json' \
        -d "{\"username\":${juser},\"password\":${jpass}}" \
        "${BASE_URL}/api/setup" -o /dev/null \
        || die "falha ao criar o admin inicial"

      # Remove a câmera de exemplo (rtsp://admin:123456@192.168.1.104)
      cams_json="$(curl -sS -b "$JAR" "${BASE_URL}/api/cameras" || echo '[]')"
      mapfile -t demo_ids < <(python3 - "$cams_json" <<'PY'
import json, sys
try:
    cams = json.loads(sys.argv[1])
except Exception:
    cams = []
for cam in cams:
    if "192.168.1.104" in str(cam.get("source", "")):
        print(cam["id"])
PY
)
      for cid in "${demo_ids[@]:-}"; do
        [[ -n "$cid" ]] || continue
        curl -sS -b "$JAR" -X DELETE "${BASE_URL}/cameras/${cid}" >/dev/null || \
          warn "não foi possível remover a câmera de exemplo #$cid"
      done
      if ((${#demo_ids[@]})); then
        ok "Câmera de exemplo removida"
      fi

      if ((generated)); then
        CRED_FILE="$APP_DIR/.admin-credentials"
        umask 077
        printf 'usuario=%s\nsenha=%s\n' "$ADMIN_USER" "$ADMIN_PASSWORD" > "$CRED_FILE"
        chmod 600 "$CRED_FILE"
      fi
      ok "Admin criado: ${ADMIN_USER}"
    fi
  elif [[ "$setup_code" == "403" ]]; then
    log "Sistema já configurado (admin existente preservado)"
  else
    warn "não foi possível verificar o estado do setup (HTTP ${setup_code})"
  fi
fi

# ── Resumo ───────────────────────────────────────────────────────────────
HOST_IP="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
printf '\n'
log "Instalação concluída"
printf '  Painel:      http://%s:%s/\n' "${HOST_IP:-127.0.0.1}" "$SERVER_PORT"
printf '  Local:       %s/\n' "$BASE_URL"
printf '  Código:      %s\n' "$APP_DIR"
printf '  Config:      %s\n' "$ENV_FILE"
printf '  Serviço:     systemctl status %s\n' "$SERVICE_NAME"
printf '  Logs:        journalctl -u %s -f\n' "$SERVICE_NAME"
if ((DO_START)) && [[ -f "${CRED_FILE:-}" ]]; then
  printf '\n  %sCredenciais iniciais:%s %s / %s\n' "$C_YELLOW" "$C_RESET" "$ADMIN_USER" "$ADMIN_PASSWORD"
  printf '  (salvas em %s — apague após o primeiro login)\n' "$CRED_FILE"
fi
printf '\n  Próximos passos:\n'
printf '   1. Acesse o painel e cadastre suas câmeras IP\n'
printf '   2. Configure Telegram/MQTT/Home Assistant em %s (e reinicie o serviço)\n' "$ENV_FILE"
printf '   3. Coloque atrás de HTTPS (proxy reverso) se exposto fora da LAN\n'
printf '\n'
warn "OTA: o updater do app detecta docker-compose.yml e assume modo Docker."
warn "Neste deploy bare metal, use 'git -C $APP_DIR pull && systemctl restart $SERVICE_NAME'"
warn "para atualizar até que o detect_deploy_mode seja corrigido no projeto."
