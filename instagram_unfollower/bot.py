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

    def __init__(self, bot, unfollowers_storage, unfollowers_inspector, notification_timeout: int):
        self.unfollowers_storage: UnfollowersStorage = unfollowers_storage
        self.unfollowers_inspector: UnfollowersInspector = unfollowers_inspector
        self.bot = bot  # Reference cycle!
        self.notification_timeout = notification_timeout

    def initialize_dispatcher(self, dispatcher):
        dispatcher.add_handler(CommandHandler('start', self.start))
        dispatcher.add_handler(MessageHandler(Filters.regex(INSTA_USERNAME), self.update_instagram_id_with_username))
        dispatcher.add_handler(MessageHandler(Filters.entity('url'), self.update_instagram_id_with_url))
        dispatcher.add_handler(CommandHandler('unfollowers', self.get_unfollowers))
        dispatcher.add_handler(CallbackQueryHandler(self.get_all_unfollowers, pattern=self.REPLY_MARKUP_SHOW_OLD))

        dispatcher.add_handler(CommandHandler('start_notifying', self.start_notifying))
        dispatcher.add_handler(CommandHandler('stop_notifying', self.stop_notifying))

    '''BOT COMMANDS'''

    @staticmethod
    def start(update, context):
        update.effective_message.reply_text('''Hello! 🙋‍♂️

Tell me your instagram username!

Commands:
/unfollowers
/start_notifying
''')

    @typing_text
    def update_instagram_id_with_username(self, update, context):
        instagram_username = update.message.text
        try:
            instagram_id = self.unfollowers_inspector.get_user_id(instagram_username)
        except Exception as e:
            print(e)
            update.effective_message.reply_text(f'Instagram id for username: {instagram_username} not found')
            return

        self.unfollowers_storage.update_instagram_id(update.effective_message.from_user.id, instagram_id)
        update.effective_message.reply_text('Ok!')

    @typing_text
    def update_instagram_id_with_url(self, update, context):
        update.effective_message.reply_text('Not implemented')

    @typing_text
    def get_unfollowers(self, update, context):
        instagram_id = self.unfollowers_storage.get_instagram_id(update.effective_user.id)
        if instagram_id is None:
            update.effective_message.reply_text(WRITE_ME_YOUR_INSTAGRAM_USERNAME_FIRST)
            return

        new_unfollowers_ids, actual_unfollowers_ids, followings_data = self._get_new_unfollowers(instagram_id)

        new_unfollowers_report = f'New unfollowers: {len(new_unfollowers_ids)}\n'
        new_unfollowers_report += _make_unfollowers_report(new_unfollowers_ids, followings_data)

        update.effective_message.reply_text(new_unfollowers_report,
                                            parse_mode=ParseMode.MARKDOWN,
                                            disable_web_page_preview=True,
                                            reply_markup=REPLY_MARKUP_SHOW_ALL)
        self.unfollowers_storage.update_known_unfollowers(instagram_id, actual_unfollowers_ids)

    @typing_text
    def get_all_unfollowers(self, update, context):
        update.callback_query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([]))
        update.callback_query.answer()

        instagram_id = self.unfollowers_storage.get_instagram_id(update.effective_user.id)
        if instagram_id is None:
            update.effective_message.reply_text('First write me your instagram username')
            return

        actual_unfollowers_ids, followings_data = self.unfollowers_inspector.inspect(instagram_id)

        report = f'All unfollowers: {len(actual_unfollowers_ids)}\n'
        report += _make_unfollowers_report(actual_unfollowers_ids, followings_data)

        update.callback_query.edit_message_text(report,
                                                parse_mode=ParseMode.MARKDOWN,
                                                disable_web_page_preview=True)
        self.unfollowers_storage.update_known_unfollowers(instagram_id, actual_unfollowers_ids)

    @typing_text
    def start_notifying(self, update, context):
        success = self.unfollowers_storage.start_notifying(update.effective_user.id)
        if success:
            update.effective_message.reply_text('Ok!')
        else:
            update.effective_message.reply_text(WRITE_ME_YOUR_INSTAGRAM_USERNAME_FIRST)

    @typing_text
    def stop_notifying(self, update, context):
        success = self.unfollowers_storage.stop_notifying(update.effective_user.id)
        if success:
            update.effective_message.reply_text('Ok!')
        else:
            update.effective_message.reply_text(WRITE_ME_YOUR_INSTAGRAM_USERNAME_FIRST)

    def run_notification(self):
        t_start = time.time()

        telegram_ids = self.unfollowers_storage.get_notified_telegram_ids()
        for telegram_id in telegram_ids:
            instagram_id = self.unfollowers_storage.get_instagram_id(telegram_id)
            if instagram_id is None:
                logger.warning('Instagram id not found in database while notifying!')
                continue

            new_unfollowers_ids, actual_unfollowers_ids, followings_data = self._get_new_unfollowers(instagram_id)
            report = f'New unfollowers: {len(new_unfollowers_ids)}\n'
            report += _make_unfollowers_report(new_unfollowers_ids, followings_data)

            if len(new_unfollowers_ids) > 0:
                self.bot.send_message(
                    chat_id=telegram_id,
                    text=report,
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=True,
                    disable_notification=False,
                    reply_markup=REPLY_MARKUP_SHOW_ALL,
                )
                logger.info(f'Id {telegram_id} is notified: {len(new_unfollowers_ids)} new unfollowers')
                self.unfollowers_storage.update_known_unfollowers(instagram_id, actual_unfollowers_ids)
                time.sleep(NOTIFICATION_SLEEP_TIME_BETWEEN_USERS)
            else:
                logger.info(f'Id {telegram_id} has 0 new unfollowers')

        delta_t = time.time() - t_start
        sleep_time = max(self.notification_timeout - delta_t, HOUR)
        logger.info(f'Notifier sleeps {sleep_time} seconds')
        time.sleep(sleep_time)

    def _get_new_unfollowers(self, instagram_id):
        known_unfollower_ids = self.unfollowers_storage.get_known_unfollowers(instagram_id)
        actual_unfollowers_ids, followings_data = self.unfollowers_inspector.inspect(instagram_id)
        new_unfollowers_ids = actual_unfollowers_ids.difference(known_unfollower_ids)
        return new_unfollowers_ids, actual_unfollowers_ids, followings_data


def _make_unfollowers_report(unfollower_ids: set, followings_data):
    # This limits telegram message size
    num_unfollowers_reached_limit = len(unfollower_ids) > SEND_MAX_UNFOLLOWERS

    new_unfollowers_names = (following['username'] for following in followings_data
                             if following['pk'] in itertools.islice(unfollower_ids, SEND_MAX_UNFOLLOWERS))

    new_unfollowers_string = '\n'.join(f'[{name}](https://instagram.com/{name})' for name in new_unfollowers_names)

    report = ''
    if num_unfollowers_reached_limit:
        report += f'Showing only {SEND_MAX_UNFOLLOWERS} first\n'

    report += '\n'
    report += new_unfollowers_string
    return report


INSTA_USERNAME = r'^(?!.*\.\.)(?!.*\.$)[^\W][\w.]{0,29}$'
SEND_MAX_UNFOLLOWERS = 100
HOUR = 60 * 60
WRITE_ME_YOUR_INSTAGRAM_USERNAME_FIRST = 'First write me your instagram username'
NOTIFICATION_SLEEP_TIME_BETWEEN_USERS = 60
REPLY_MARKUP_SHOW_ALL = InlineKeyboardMarkup([[
    InlineKeyboardButton('Show old unfollowers', callback_data=f'{BotController.REPLY_MARKUP_SHOW_OLD}')
]])
