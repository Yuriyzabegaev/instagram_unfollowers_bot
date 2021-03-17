import gettext
from typing import Optional


class Localizer:

    def __init__(self, storage, languages: tuple):
        self.storage = storage
        self.languages = {lang: gettext.translation('base', localedir='locale', languages=[lang]).gettext
                          for lang in languages}
        self.languages[None] = gettext.gettext  # Default text

    def get_locale(self, telegram_id: int):
        lang = self.storage.get_language(telegram_id)
        return self.languages[lang]

    def set_locale(self, telegram_id: int, locale: Optional[str]):
        self.storage.set_language(telegram_id, locale)
