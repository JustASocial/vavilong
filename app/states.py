"""Состояния FSM."""

from aiogram.fsm.state import State, StatesGroup


class Flow(StatesGroup):
    pack_title = State()
    pack_kind = State()
    pack_emoji = State()
    pack_crop = State()
    pack_media = State()
    sticker_emoji = State()
    import_confirm = State()
    quote_text = State()
    quote_theme = State()
    text_sticker = State()
    text_theme = State()
