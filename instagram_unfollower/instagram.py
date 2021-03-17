import time

from InstagramAPI import InstagramAPI

REQUEST_SLEEP_TIME = 1


class UnfollowersInspector:

    def __init__(self, api: InstagramAPI):
        self.api = api
        api.login()

    def get_user_id(self, instagram_username: str):
        success = self.api.searchUsername(instagram_username)
        user_id = self.api.LastJson['user']['pk']
        if success is True:
            return int(user_id)
        else:
            raise RuntimeError('Instagram API failed')

    def inspect(self, instagram_id: int):
        self.api.login(force=True)

        time.sleep(REQUEST_SLEEP_TIME)
        followers = self.api.getTotalFollowers(usernameId=instagram_id)
        follower_ids = {int(user['pk']) for user in followers}

        time.sleep(REQUEST_SLEEP_TIME)
        followings = self.api.getTotalFollowings(usernameId=instagram_id)
        following_ids = {int(user['pk']) for user in followings}

        unfollowers_ids = following_ids.difference(follower_ids)
        return unfollowers_ids, followings
