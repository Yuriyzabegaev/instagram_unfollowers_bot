import itertools
import logging
import time

from telegram import ParseMode, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CommandHandler, MessageHandler, Filters, CallbackQueryHandler

from instagram_unfollower.instagram import UnfollowersInspector
from instagram_unfollower.storage import UnfollowersStorage

logger = logging.getLogger('instagram_unsubscriber.controller')


def typing_text(func):
    def closure(self, update, context):
        update.effective_user.send_chat_action('typing')
        func(self, update, context)

    return closure


class BotController:
    REPLY_MARKUP_SHOW_OLD = '1'
    REPLY_MARKUP_RUSSIAN = 'set_lang_ru'
    REPLY_MARKUP_ENGLISH = 'set_lang_en'

    def __init__(self, bot, unfollowers_storage, unfollowers_inspector, localizer, notification_timeout: int):
        self.unfollowers_storage: UnfollowersStorage = unfollowers_storage
        self.unfollowers_inspector: UnfollowersInspector = unfollowers_inspector
        self.localizer = localizer
        self.bot = bot  # Reference cycle!
        self.notification_timeout = notification_timeout

    def initialize_dispatcher(self, dispatcher):
        dispatcher.add_handler(CommandHandler('start', self.start))
        dispatcher.add_handler(MessageHandler(Filters.regex(INSTA_USERNAME), self.update_instagram_id_with_username))
        dispatcher.add_handler(MessageHandler(Filters.entity('url'), self.update_instagram_id_with_url))
        dispatcher.add_handler(CommandHandler('unfollowers', self.get_unfollowers))
        dispatcher.add_handler(CallbackQueryHandler(self.get_all_unfollowers, pattern=self.REPLY_MARKUP_SHOW_OLD))
        dispatcher.add_handler(CallbackQueryHandler(self.set_locale, pattern=r'^set_lang_'))

        dispatcher.add_handler(CommandHandler('start_notifying', self.start_notifying))
        dispatcher.add_handler(CommandHandler('stop_notifying', self.stop_notifying))

    '''BOT COMMANDS'''

    @typing_text
    def start(self, update, context):
        _ = self.localizer.get_locale(update.effective_user.id)
        choose_language_reply_markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton('🇷🇺', callback_data=self.REPLY_MARKUP_RUSSIAN),
              InlineKeyboardButton('🇺🇸', callback_data=self.REPLY_MARKUP_ENGLISH)]])
        update.effective_message.reply_text(_('''Hello! 🙋‍♂️

Tell me your instagram username!

Commands:
/unfollowers
/start_notifying
'''), reply_markup=choose_language_reply_markup)

    @typing_text
    def set_locale(self, update, context):
        lang = update.callback_query.data.removeprefix('set_lang_')
        if lang == 'en':
            lang = None
        self.localizer.set_locale(update.effective_user.id, lang)
        return self.start(update, context)

    @typing_text
    def update_instagram_id_with_username(self, update, context):
        _ = self.localizer.get_locale(update.effective_user.id)
        instagram_username = update.message.text
        try:
            instagram_id = self.unfollowers_inspector.get_user_id(instagram_username)
        except Exception as e:
            print(e)
            update.effective_message.reply_text(
                _("Given Instagram account doesn't exist: {}").format(instagram_username))
            return

        self.unfollowers_storage.update_instagram_id(update.effective_message.from_user.id, instagram_id)
        update.effective_message.reply_text(_(OK_STRING))

    @typing_text
    def update_instagram_id_with_url(self, update, context):
        update.effective_message.reply_text('Not implemented')

    @typing_text
    def get_unfollowers(self, update, context):
        _ = self.localizer.get_locale(update.effective_user.id)
        instagram_id = self.unfollowers_storage.get_instagram_id(update.effective_user.id)
        if instagram_id is None:
            update.effective_message.reply_text(_(WRITE_ME_YOUR_INSTAGRAM_USERNAME_FIRST))
            return

        new_unfollowers_ids, actual_unfollowers_ids, followings_data = \
            self._get_new_unfollowers(update.effective_user.id, instagram_id)

        new_unfollowers_report = _('New unfollowers: {}\n').format(len(new_unfollowers_ids))
        new_unfollowers_report += self._make_unfollowers_report(update.effective_user.id,
                                                                new_unfollowers_ids,
                                                                followings_data)

        update.effective_message.reply_text(new_unfollowers_report,
                                            parse_mode=ParseMode.MARKDOWN,
                                            disable_web_page_preview=True,
                                            reply_markup=self._make_reply_markup_show_all(update.effective_user.id)),
        self.unfollowers_storage.update_known_unfollowers(update.effective_user.id,
                                                          instagram_id,
                                                          actual_unfollowers_ids)

    @typing_text
    def get_all_unfollowers(self, update, context):
        _ = self.localizer.get_locale(update.effective_user.id)
        update.callback_query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([]))
        update.callback_query.answer()

        instagram_id = self.unfollowers_storage.get_instagram_id(update.effective_user.id)
        if instagram_id is None:
            update.effective_message.reply_text(_(WRITE_ME_YOUR_INSTAGRAM_USERNAME_FIRST))
            return

        actual_unfollowers_ids, followings_data = self.unfollowers_inspector.inspect(instagram_id)

        report = _('All unfollowers: {}\n').format(len(actual_unfollowers_ids))
        report += self._make_unfollowers_report(update.effective_user.id, actual_unfollowers_ids, followings_data)

        update.callback_query.edit_message_text(report,
                                                parse_mode=ParseMode.MARKDOWN,
                                                disable_web_page_preview=True)
        self.unfollowers_storage.update_known_unfollowers(update.effective_user.id,
                                                          instagram_id,
                                                          actual_unfollowers_ids)

    @typing_text
    def start_notifying(self, update, context):
        _ = self.localizer.get_locale(update.effective_user.id)
        success = self.unfollowers_storage.start_notifying(update.effective_user.id)
        if success:
            update.effective_message.reply_text(_(OK_STRING))
        else:
            update.effective_message.reply_text(_(WRITE_ME_YOUR_INSTAGRAM_USERNAME_FIRST))

    @typing_text
    def stop_notifying(self, update, context):
        _ = self.localizer.get_locale(update.effective_user.id)
        success = self.unfollowers_storage.stop_notifying(update.effective_user.id)
        if success:
            update.effective_message.reply_text(_(OK_STRING))
        else:
            update.effective_message.reply_text(_(WRITE_ME_YOUR_INSTAGRAM_USERNAME_FIRST))

    def run_notification(self):
        t_start = time.time()

        telegram_ids = self.unfollowers_storage.get_notified_telegram_ids()
        for telegram_id in telegram_ids:
            _ = self.localizer.get_locale(telegram_id)

            instagram_id = self.unfollowers_storage.get_instagram_id(telegram_id)
            if instagram_id is None:
                logger.warning('Instagram id not found in database while notifying!')
                continue

            new_unfollowers_ids, actual_unfollowers_ids, followings_data = \
                self._get_new_unfollowers(telegram_id, instagram_id)
            report = _('New unfollowers: {}\n').format(len(new_unfollowers_ids))
            report += self._make_unfollowers_report(telegram_id, new_unfollowers_ids, followings_data)

            if len(new_unfollowers_ids) > 0:
                self.bot.send_message(
                    chat_id=telegram_id,
                    text=report,
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=True,
                    disable_notification=False,
                    reply_markup=self._make_reply_markup_show_all(telegram_id),
                )
                logger.info(f'Id {telegram_id} is notified: {len(new_unfollowers_ids)} new unfollowers')
                self.unfollowers_storage.update_known_unfollowers(telegram_id, instagram_id, actual_unfollowers_ids)
                time.sleep(NOTIFICATION_SLEEP_TIME_BETWEEN_USERS)
            else:
                logger.info(f'Id {telegram_id} has 0 new unfollowers')

        delta_t = time.time() - t_start
        sleep_time = max(self.notification_timeout - delta_t, HOUR)
        logger.info(f'Notifier sleeps {sleep_time} seconds')
        time.sleep(sleep_time)

    def _get_new_unfollowers(self, telegram_id, instagram_id):
        known_unfollower_ids = self.unfollowers_storage.get_known_unfollowers(telegram_id)
        actual_unfollowers_ids, followings_data = self.unfollowers_inspector.inspect(instagram_id)
        new_unfollowers_ids = actual_unfollowers_ids.difference(known_unfollower_ids)
        return new_unfollowers_ids, actual_unfollowers_ids, followings_data

    def _make_unfollowers_report(self, telegram_id: int, unfollower_ids: set, followings_data):
        _ = self.localizer.get_locale(telegram_id)
        # This limits telegram message size
        num_unfollowers_reached_limit = len(unfollower_ids) > SEND_MAX_UNFOLLOWERS

        new_unfollowers_names = (following['username'] for following in followings_data
                                 if following['pk'] in itertools.islice(unfollower_ids, SEND_MAX_UNFOLLOWERS))

        new_unfollowers_string = '\n'.join(f'[{name}](https://instagram.com/{name})' for name in new_unfollowers_names)

        report = ''
        if num_unfollowers_reached_limit:
            report += _('Showing only {} first\n').format(SEND_MAX_UNFOLLOWERS)

        report += '\n'
        report += new_unfollowers_string
        return report

    def _make_reply_markup_show_all(self, telegram_id):
        _ = self.localizer.get_locale(telegram_id)

        return InlineKeyboardMarkup([[
            InlineKeyboardButton(_('Show old unfollowers'), callback_data=f'{BotController.REPLY_MARKUP_SHOW_OLD}')
        ]])


INSTA_USERNAME = r'^(?!.*\.\.)(?!.*\.$)[^\W][\w.]{0,29}$'
SEND_MAX_UNFOLLOWERS = 100
HOUR = 60 * 60
WRITE_ME_YOUR_INSTAGRAM_USERNAME_FIRST = 'First write me your instagram username'
OK_STRING = 'Ok!'
NOTIFICATION_SLEEP_TIME_BETWEEN_USERS = 60
