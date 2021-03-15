import os

from InstagramAPI import InstagramAPI
from telegram.ext import Updater

from instagram_unfollower.bot import BotController
from instagram_unfollower.instagram import UnfollowersInspector
from instagram_unfollower.storage import UnfollowersStorage

api = InstagramAPI(username=os.environ['INSTAGRAM_USERNAME'], password=os.environ['INSTAGRAM_PASSWORD'])
unfollowers_inspector = UnfollowersInspector(api)
unfollowers_storage = UnfollowersStorage(os.environ['SQL_URL'])

updater = Updater(token=os.environ['TELEGRAM_BOT_TOKEN'])

day = 60 * 60 * 24

controller = BotController(
    bot=updater.bot,
    unfollowers_storage=unfollowers_storage,
    unfollowers_inspector=unfollowers_inspector,
    notification_timeout=day,
)


if __name__ == '__main__':
    dp = updater.dispatcher
    controller.initialize_dispatcher(dp)

    dp.run_async(controller.run_notification)
    updater.start_polling()
    updater.idle()
