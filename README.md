# Vavilong Tools

Telegram-бот и Mini App для скачивания медиа, стикеров и стикер-паков.

## Где что живёт

| Часть | Адрес |
| --- | --- |
| Mini App + API | https://vavilong-tools.jpjgho.workers.dev |
| Бот (Render) | https://vavilong-bot.onrender.com |
| Код | https://github.com/JustASocial/vavilong-bot |

Mini App — статика Vite/React в `web/dist`, отдаётся Cloudflare Worker
(`worker/src/index.js`). Worker проверяет `initData` по HMAC, проксирует файлы
Telegram и принимает `.tgspack`-архивы.

Бот — Python + aiogram + yt-dlp + системный ffmpeg. Запускается на Render как
Python web service: `pip install -r requirements.txt`, старт `python -m app`.
HTTP-порт нужен только для `/health`.

## Почему Cron Trigger в Cloudflare

Бесплатный инстанс Render засыпает после 15 минут без входящего трафика.
`[triggers] crons = ["*/5 * * * *"]` в `wrangler.toml` пингует
`/health` каждые 5 минут, поэтому бот не спит.

## Деплой

Mini App:

```bash
cd web && npm run build
cd .. && npx wrangler deploy
```

Бот: любой push в `master` + ручной деплой в Render (auto-deploy выключен,
чтобы не перезапускать бота на каждую мелочь). Перезапуск через API:

```bash
curl -X POST https://api.render.com/v1/services/$SERVICE_ID/deploys \
  -H "Authorization: Bearer $RENDER_API_KEY" \
  -H "Content-Type: application/json" -d '{"clearCache":"do_not_clear"}'
```

Переменные окружения бота: `BOT_TOKEN`, `WEBAPP_URL`, `PUBLIC_BASE_URL`,
`MAX_UPLOAD_MB`, `MAX_CONCURRENT_DOWNLOADS`, `PYTHONIOENCODING`.

## Ограничения бесплатного Render

- Диск эфемерный: `data/bot.sqlite3` сбрасывается при передеплое или рестарте.
  Стикер-паки живут в Telegram и не теряются, локальная история — теряется.
- 750 инстанс-часов в месяц на аккаунт: один круглосуточный сервис ≈ 744 ч.

## Локальный запуск

`run.bat` остаётся для отладки, но одновременно с Render его запускать нельзя:
Telegram отдаёт обновления только одному `getUpdates`-клиенту (409 Conflict).
