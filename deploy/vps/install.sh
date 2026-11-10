#!/usr/bin/env bash
set -euo pipefail
umask 077

if [[ $EUID != 0 || $# != 2 ]]; then
  echo 'Использование: sudo bash deploy/vps/install.sh aion.example.com ops.example.com' >&2
  exit 2
fi

app_host=$1
panel_host=$2
domain='^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{0,62}$'
if [[ ! $app_host =~ $domain || ! $panel_host =~ $domain || $app_host == "$panel_host" ]]; then
  echo 'Укажите два разных DNS-имени в нижнем регистре.' >&2
  exit 2
fi
if (( ${#app_host} > 253 || ${#panel_host} > 253 )); then
  echo 'DNS-имя не должно превышать 253 символа.' >&2
  exit 2
fi

for program in python3 systemctl sudo visudo curl caddy flock; do
  command -v "$program" >/dev/null || { echo "Требуется $program" >&2; exit 2; }
done
[[ -d /run/systemd/system && -x /usr/bin/systemctl && -x /usr/bin/sudo && -x /usr/bin/curl ]] || {
  echo 'Требуется Linux с systemd и стандартным расположением системных команд.' >&2
  exit 2
}
getent passwd caddy >/dev/null || { echo 'Установите Caddy как системную службу с пользователем caddy.' >&2; exit 2; }
python3 -c 'import sys; sys.exit(sys.version_info < (3, 12))' || { echo 'Требуется Python 3.12+' >&2; exit 2; }

source_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
assets="$source_dir/deploy/vps"
[[ -f "$source_dir/frontend/dist/index.html" ]] || {
  echo 'Сначала выполните npm ci и npm run build в frontend либо используйте архив с готовой сборкой.' >&2
  exit 2
}

exec 9>/run/aion-vps-install.lock
flock -n 9 || { echo 'Установка Aion уже выполняется.' >&2; exit 1; }
for account in aion-web aion-panel; do
  if ! getent passwd "$account" >/dev/null; then
    useradd --system --user-group --no-create-home --shell /usr/sbin/nologin "$account"
  fi
done

install -d -m 0755 /opt/aion /opt/aion/releases
release=$(mktemp -d /opt/aion/releases/release.XXXXXXXX)
chmod 0755 "$release"
(
  umask 022
  tar --exclude=__pycache__ --exclude=.tmp --exclude=tests -C "$source_dir" -cf - backend control |
    tar --no-same-owner --no-same-permissions -C "$release" -xf -
  install -d -m 0755 "$release/frontend"
  cp -r "$source_dir/frontend/dist" "$release/frontend/"
  find "$release/backend" "$release/control" "$release/frontend" -type d -exec chmod 0755 {} +
  find "$release/backend" "$release/control" "$release/frontend" -type f -exec chmod 0644 {} +
  python3 -m venv "$release/.venv"
  "$release/.venv/bin/python" -m pip install --disable-pip-version-check \
    -r "$release/backend/requirements.lock" psutil==7.2.2
)

install -d -m 0755 /etc/aion
install -d -m 0700 /etc/aion/credentials
for name in bootstrap_password operator panel_password; do
  if [[ ! -s /etc/aion/credentials/$name ]]; then
    python3 -c 'import secrets; print(secrets.token_urlsafe(36))' > "/etc/aion/credentials/$name"
  fi
done
if [[ ! -e /etc/aion/credentials/telegram ]]; then
  touch /etc/aion/credentials/telegram
fi
chmod 0600 /etc/aion/credentials/{bootstrap_password,operator,panel_password,telegram}

panel_hash=$("$release/.venv/bin/python" -c '
from pathlib import Path
import bcrypt
password = Path("/etc/aion/credentials/panel_password").read_bytes().strip()
print(bcrypt.hashpw(password, bcrypt.gensalt(rounds=12)).decode())
')
sed -e "s|@AION_HOST@|$app_host|g" -e "s|@OUROBOROS_HOST@|$panel_host|g" \
  -e "s|@PANEL_HASH@|$panel_hash|g" "$assets/Caddyfile.template" > "$release/Caddyfile"
caddy validate --config "$release/Caddyfile" --adapter caddyfile
install -m 0640 -o root -g caddy "$release/Caddyfile" /etc/aion/Caddyfile
rm -f -- "$release/Caddyfile"
printf 'AION_HOST=%s\nOUROBOROS_HOST=%s\nAPP_PUBLIC_URL=https://%s\n' \
  "$app_host" "$panel_host" "$app_host" > /etc/aion/web.env

visudo -c -f "$assets/aion-ouroboros.sudoers"
install -m 0440 "$assets/aion-ouroboros.sudoers" /etc/sudoers.d/aion-ouroboros
install -m 0644 "$assets/aion-web.service" "$assets/aion-ouroboros.service" \
  "$assets/aion-ouroboros.socket" /etc/systemd/system/
install -D -m 0644 "$assets/caddy-aion-group.conf" /etc/systemd/system/caddy.service.d/aion.conf

ln -s "$release" "$release/current-link"
mv -Tf "$release/current-link" /opt/aion/current
systemctl daemon-reload
systemctl enable aion-web.service aion-ouroboros.socket
systemctl start aion-ouroboros.socket
systemctl try-restart aion-ouroboros.service
systemctl restart aion-web.service

echo 'Добавьте строку import /etc/aion/Caddyfile в /etc/caddy/Caddyfile.'
echo 'Проверьте конфигурацию и перезапустите Caddy по инструкции deploy/vps/README.md.'
echo 'Пароли доступны через sudo cat /etc/aion/credentials/bootstrap_password и panel_password.'
