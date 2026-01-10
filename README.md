# Morpheus

Полноценный пример проекта для развертывания телеграм‑бота и API продаж ключей/билдов с оплатой через Anypay на VPS (Ubuntu).

## Кратко о стеке
- Python 3.11, FastAPI, aiogram 3
- PostgreSQL 15
- Nginx (reverse‑proxy + самоподписанный TLS)
- Docker Compose для сборки и запуска

## Установка на чистую Ubuntu
```bash
sudo ./deploy/install.sh
```
Скрипт:
1. Установит Docker/Compose.
2. Скопирует `env.sample` в `.env` (если нет).
3. Сгенерирует самоподписанные сертификаты в `deploy/certs/`.
4. Сформирует конфиг nginx.
5. Соберёт и запустит сервисы.

После первого старта в логах контейнера `api` появятся сгенерированные креды админа:
```
docker compose logs api | grep "Generated admin credentials"
```

## Что настроить в `.env`
- `TELEGRAM_BOT_TOKEN` — токен бота.
- `BOT_ADMINS` — id админов через запятую.
- `ANYPAY_*` — данные мерчанта (project_id, api_id, api_key, метод и валюту).
- `PUBLIC_BASE_URL` — https://IP (без домена допустимо, сертификат самоподписанный).

После правки перезапустите API:
```bash
sudo docker compose restart api
```

## Основные точки
- Админ API: `/admin/*` (OAuth2 Bearer). Вход — POST `/admin/login` (form: username/password), токен использовать в остальных вызовах.
- Каталог/покупки для бота: бот сам использует публичные эндпоинты `/api/*`.
- Проверка лицензии клиентом: `POST /api/{product}/auth` с `{"key": "...", "uuid": "..."}`.
- Вебхук Anypay: `POST /payments/anypay/webhook` (status=paid переводит заказ в оплачен и отправляет ключ + билд).
- Healthcheck: `/health`
- Входная точка, требуемая ТЗ: `https://<host>/Morpheus%20Private/` редиректит в Swagger (`/docs`).

## Минимальный порядок действий
1. Зайти в админ API (`/docs`) с токеном, создать продукты (`POST /admin/products`), добавить цены (`POST /admin/products/{id}/prices`).
2. Сгенерировать ключи (`POST /admin/keys/generate`), загрузить билд (`POST /admin/builds/{product_id}`).
3. Настроить бота (`PUT /admin/settings` → `bot_enabled=true`, при необходимости maintenance/off).
4. Запустить/перезапустить контейнер `api`.
5. Проверить ботом `/start`, купить товар — получите ссылку Anypay; после оплаты придёт билд+ключ.

## Где лежат файлы
- API и бот: `backend/app/*`
- Docker: `docker-compose.yml`, `backend/Dockerfile`
- Nginx + certs: `deploy/nginx/default.conf`, `deploy/certs/*`
- Загрузки билдов: `data/uploads/`

## Примечания
- Бот запускается в том же контейнере, опрашивает Telegram через long polling.
- TLS самоподписанный — браузер/Telegram примут, но покажут предупреждение; для боевого домена заменить сертификаты.
- Ключи генерируются в формате `MPH-XXXXX-XXXXX-XXXXX-XXXXX`.

