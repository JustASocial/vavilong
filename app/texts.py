"""Длинные тексты интерфейса на двух языках."""

from __future__ import annotations

from app.i18n import tr


def welcome(lang: str) -> str:
    return tr(
        lang,
        "<b>Vavilong Tools</b>\n\n"
        "Скачивание медиа и стикер-студия в одном боте.\n\n"
        "<b>Скачивание</b>\n"
        "Пришли ссылку на видео, фото, аудио или плейлист. Бот покажет обложку, "
        "метаданные и доступные качества, затем пришлёт файл.\n\n"
        "<b>Стикер-студия</b>\n"
        "Паки из фото, видео, гиф, других стикеров и прямых ссылок. "
        "Нарезка, кадрирование и сжатие под лимиты Telegram выполняются автоматически.\n\n"
        "<b>Цитаты и текст</b>\n"
        "Карточка из сообщения или надпись на градиенте — сразу в стикер.\n\n"
        "<b>Inline</b>\n"
        "В любом чате: <code>@vavilong_bot ссылка</code> — видео в 720p. "
        "Качество и <code>+info</code> добавляются после ссылки.\n\n"
        "Пришли ссылку или выбери раздел ниже.",
        "<b>Vavilong Tools</b>\n\n"
        "Media downloads and a sticker studio in one bot.\n\n"
        "<b>Downloads</b>\n"
        "Send a link to a video, photo, audio track or playlist. The bot shows the cover, "
        "metadata and available qualities, then delivers the file.\n\n"
        "<b>Sticker studio</b>\n"
        "Packs from photos, videos, GIFs, existing stickers and direct links. "
        "Trimming, cropping and compression to Telegram limits happen automatically.\n\n"
        "<b>Quotes and text</b>\n"
        "A card from a message or a caption on a gradient, ready to become a sticker.\n\n"
        "<b>Inline</b>\n"
        "In any chat: <code>@vavilong_bot link</code> sends the video in 720p. "
        "Add a quality and <code>+info</code> after the link.\n\n"
        "Send a link or pick a section below.",
    )


def help_text(lang: str) -> str:
    return tr(
        lang,
        "<b>Команды</b>\n"
        "/start — меню\n"
        "/packs — мои стикер-паки\n"
        "/newpack — создать пак\n"
        "/import — копия чужого пака\n"
        "/quote — цитата из сообщения\n"
        "/text — текстовый стикер\n"
        "/history — последние загрузки\n"
        "/settings — язык и параметры\n"
        "/cancel — прервать действие\n\n"
        "<b>Скачивание</b>\n"
        "Ссылка распознаётся автоматически: видео, фото, аудио, плейлист или прямая ссылка на файл. "
        "Доступны отдельные кнопки для MP3, аудио без перекодирования, обложки и субтитров. "
        "Файлы больше лимита сжимаются.\n\n"
        "<b>Стикеры</b>\n"
        "Пак вмещает до 120 стикеров, тип (фото или видео) фиксируется при создании. "
        "Видео приводится к 512×512, 30 fps, до 3 секунд и до 256 КБ. "
        "Начало ролика выбирается кнопками, умное кадрирование находит лицо.\n\n"
        "<b>Inline-режим</b>\n"
        "В любом чате: <code>@vavilong_bot ссылка</code> — видео в 720p. "
        "Укажи качество: <code>@vavilong_bot ссылка 1080p</code>. "
        "Добавь <code>+info</code>, чтобы видеть просмотры и лайки.\n\n"
        "<b>Жёсткие лимиты Bot API</b>\n"
        "Скачивание файла из Telegram — 20 МБ, отправка — 50 МБ, "
        "фото-стикер — 512 КБ, видео-стикер — 256 КБ.",
        "<b>Commands</b>\n"
        "/start — menu\n"
        "/packs — your sticker packs\n"
        "/newpack — create a pack\n"
        "/import — copy someone else's pack\n"
        "/quote — quote from a message\n"
        "/text — text sticker\n"
        "/history — recent downloads\n"
        "/settings — language and defaults\n"
        "/cancel — abort the current step\n\n"
        "<b>Downloads</b>\n"
        "Links are recognised automatically: video, photo, audio, playlist or a direct file. "
        "Separate buttons cover MP3, untouched audio, the cover image and subtitles. "
        "Files above the limit are compressed.\n\n"
        "<b>Stickers</b>\n"
        "A pack holds up to 120 stickers and its type (photo or video) is fixed at creation. "
        "Video becomes 512×512, 30 fps, up to 3 seconds and 256 KB. "
        "The start point is chosen with buttons and smart crop finds faces.\n\n"
        "<b>Inline mode</b>\n"
        "In any chat: <code>@vavilong_bot link</code> sends the video in 720p. "
        "Request a quality: <code>@vavilong_bot link 1080p</code>. "
        "Append <code>+info</code> to see views and likes.\n\n"
        "<b>Hard Bot API limits</b>\n"
        "Telegram file download — 20 MB, upload — 50 MB, "
        "photo sticker — 512 KB, video sticker — 256 KB.",
    )


def limits(lang: str) -> str:
    return tr(
        lang,
        "Лимиты Telegram: стикер-фото до 512 КБ, видео-стикер до 256 КБ и 3 секунд, "
        "пак до 120 стикеров, отправка файла до 50 МБ.",
        "Telegram limits: photo sticker up to 512 KB, video sticker up to 256 KB and 3 seconds, "
        "a pack up to 120 stickers, file upload up to 50 MB.",
    )


def download_intro(lang: str) -> str:
    return tr(
        lang,
        "<b>Скачивание</b>\n\n"
        "Пришли ссылку. Поддерживаются YouTube, Shorts, TikTok, Instagram, X, VK, Vimeo, "
        "SoundCloud, Reddit и ещё около 1800 сайтов, а также прямые ссылки на файлы.\n\n"
        "В карточке будут обложка, название, автор, длительность и кнопки качества. "
        "Отдельно доступны MP3, аудио без перекодирования, обложка и субтитры. "
        "Плейлисты можно забрать первыми десятью файлами.",
        "<b>Downloads</b>\n\n"
        "Send a link. YouTube, Shorts, TikTok, Instagram, X, VK, Vimeo, SoundCloud, "
        "Reddit and about 1800 other sites are supported, plus direct file links.\n\n"
        "The card shows the cover, title, author, duration and quality buttons. "
        "MP3, untouched audio, the cover image and subtitles are separate actions. "
        "Playlists can be fetched as the first ten files.",
    )
