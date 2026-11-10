# Aion и Ouroboros на Linux VPS

Aion и веб-панель Ouroboros работают как службы systemd. Caddy принимает HTTPS на двух DNS-именах. Для связи со службами используются закрытые Unix-сокеты.

## Перед установкой

- VPS с systemd и Python 3.12+ с модулем `venv`. Подойдёт Ubuntu 24.04.
- Системная служба Caddy 2.8+ с пользователем `caddy`, а также `curl` и `sudo`.
- Два DNS-имени, например `aion.example.com` и `ops.example.com`. Направьте их A-записи на публичный IP VPS. Добавляйте AAAA-записи только при доступном IPv6.
- Откройте входящие TCP-порты 80 и 443 в правилах VPS для получения сертификатов и доступа через HTTPS.

[Установка Caddy](https://caddyserver.com/docs/install) · [Условия автоматического HTTPS](https://caddyserver.com/docs/automatic-https)

## Установка

Распакуйте архив на VPS и войдите в папку `aion-vps`. В архиве есть готовый `frontend/dist`. Если разворачиваете исходный checkout, сначала соберите интерфейс с Node.js 22.

```bash
npm --prefix frontend ci
npm --prefix frontend run build
```

Запустите установщик, подставив свои DNS-имена.

```bash
sudo bash deploy/vps/install.sh aion.example.com ops.example.com
```

Добавьте в конец `/etc/caddy/Caddyfile` строку импорта один раз. Уберите повторные блоки с теми же DNS-именами, если они уже есть.

```caddyfile
import /etc/aion/Caddyfile
```

Проверьте конфигурацию и запустите Caddy. Первый перезапуск применяет группу доступа к сокету Aion.

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl enable caddy
sudo systemctl restart caddy
```

Откройте `https://aion.example.com` и войдите как `admin`. Для панели по адресу `https://ops.example.com` используйте логин `operator`. Установщик генерирует разные случайные пароли и сохраняет их в файлах, доступных root.

```bash
sudo cat /etc/aion/credentials/bootstrap_password
sudo cat /etc/aion/credentials/panel_password
```

Первый пароль действует для новой базы. Подключённая база сохраняет свои аккаунты. Перед публикацией перенесённой базы проверьте пароль её администратора.

## Управление

В Ouroboros видны состояние systemd, готовность Aion по `/health`, нагрузка, память и свободное место. Кнопки запуска, остановки и перезапуска отправляют команду для `aion-web.service`. После остановки Aion панель остаётся доступной. При загрузке VPS systemd запускает Aion и поднимает сокет панели. Если Aion должен оставаться остановленным после перезагрузки, используйте `sudo systemctl disable --now aion-web.service`.

Для диагностики с VPS:

```bash
sudo systemctl status aion-web.service aion-ouroboros.socket
sudo journalctl -u aion-web.service -u aion-ouroboros.service -n 100 --no-pager
curl --fail https://aion.example.com/health
curl --fail --user operator https://ops.example.com/api/status
```

Последняя команда запросит пароль панели. При обращении без пароля Caddy возвращает 401. HTTPS-сайт Aion использует свои аккаунты, а запросы записи привязаны к настроенному адресу через заголовок `Origin`. Панель принимает команды только со своего адреса.

## Данные и обновления

Данные Aion находятся в `/var/lib/aion-web`, конфигурация и ключи в `/etc/aion`, установленный код в `/opt/aion/releases`. Повторный запуск установщика с новым архивом устанавливает новую версию и перезапускает службу. Сохраните копию данных и ключей перед обновлением. Для файловой копии остановите Aion и скопируйте оба каталога в закрытое хранилище. Управление архивами в этой поставке выполняет оператор на сервере.

Если нужно перенести существующий проект, подготовьте согласованную копию SQLite и папки документов. Управляемый режим рассчитан на одну базу с одним проектом. Подключайте копию на остановленной службе и передайте владение файлами пользователю `aion-web`. Ключ `/etc/aion/credentials/operator` используется для шифрования защитной копии перед миграцией схемы. Храните его отдельно от архива.

Для Telegram впишите токен в `/etc/aion/credentials/telegram` через `sudoedit`, настройте `telegram_chat` в `/var/lib/aion-web/.hub-settings.json` и перезапустите Aion. Файл настроек должен быть JSON-объектом, например `{"telegram_chat":"-1001234567890"}`, доступным на чтение пользователю `aion-web`. Маршруты событий задаются в интерфейсе Aion. Ссылки в новых уведомлениях используют HTTPS-адрес VPS.
