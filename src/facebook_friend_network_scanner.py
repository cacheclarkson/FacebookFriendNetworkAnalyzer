import json
import re
import time
import urllib

import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait

from src.friend import Friend


class FacebookFriendNetworkScanner(object):
    DOC_IDS = dict(
        mutual_friends_page_1=5488968171176172,
        mutual_friends_next_pages=4236371019740591,
    )

    TIME_TO_LOGIN = 3

    def __init__(self, user, password):
        self.friends = []
        self.mutual_friends = {}

        self._friend_list_page_info = dict(has_next_page=True, end_cursor=None)
        self._mutual_friends_list_page_info = {}

        self.driver = self._create_driver()
        self._log_into_facebook(self.driver, user, password)
        time.sleep(self.TIME_TO_LOGIN)
        self.driver.get("https://www.facebook.com/friends/list")

        self.session = requests.session()
        self.session.cookies.update({cookie["name"]: cookie["value"] for cookie in self.driver.get_cookies()})
        self._fb_dtsg_token = self._get_fb_dtsg_token()

        print("Facebook Friend Network initialized")

    @staticmethod
    def _create_driver(get_logs=False):  # pragma: no cover
        if not get_logs:
            return webdriver.Chrome()  # if your chromedriver.exe inside root. Otherwise, insert the file path as the first argument

        caps = DesiredCapabilities.CHROME
        caps['goog:loggingPrefs'] = {'performance': 'ALL'}
        return webdriver.Chrome(desired_capabilities=caps)

    @staticmethod
    def _log_into_facebook(driver, user, password):  # pragma: no cover
        def accept_all_cookies():
            accept_cookies_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, "button[data-testid='cookie-policy-dialog-accept-button']")
                )
            )

            accept_cookies_button.click()

        def insert_user_and_password():
            user_css_selector = "input[name='email']"
            password_css_selector = "input[name='pass']"

            username_input = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, user_css_selector)))
            password_input = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, password_css_selector)))

            username_input.clear()
            username_input.send_keys(user)
            password_input.clear()
            password_input.send_keys(password)

        def click_login_button():
            WebDriverWait(driver, 2).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "button[type='submit']"))).click()

        driver.get("https://www.facebook.com/")
        accept_all_cookies()
        insert_user_and_password()
        click_login_button()

    def _get_fb_dtsg_token(self):
        pattern = r'\["DTSGInitData",\[\],{"token":"\S+","async_get_token":"\S+?"},\d+\]'
        match = re.search(pattern, self.driver.page_source)
        return json.loads(match.group())[2]["token"]

    def scan_network(self):
        self.read_all_friends_from_graphql_api()

        for i, friend in enumerate(self.friends, start=1):
            print(f"Reading mutual friends with {friend.name}. ({i} of {len(self.friends)})")
            self.read_mutual_friends_from_friend_profile(friend.user_id)
            print(f"  Number of mutual friends: {len(self.mutual_friends[friend.user_id])}")

    def save_network(self, output_file_name):
        with open(output_file_name, "w") as outfile:
            json.dump(
                dict(
                    friend_list=[vars(friend) for friend in self.friends],
                    mutual_friends={
                        friend: [vars(mutual_friend) for mutual_friend in mutual_friends]
                        for friend, mutual_friends in self.mutual_friends.items()
                    }
                ),
                outfile
            )

    def read_all_friends_from_graphql_api(self):
        while self._friend_list_page_info["has_next_page"]:
            self._read_next_batch_of_friends()

    def _read_next_batch_of_friends(self):
        api_info = self._get_next_batch_of_friends_api_info()
        api_info_dict = json.loads(api_info)

        self.friends += self._friends_api_info_to_friend_list(api_info_dict)

        self._friend_list_page_info = api_info_dict["data"]["viewer"]["all_friends"]["page_info"]

    def _get_next_batch_of_friends_api_info(self):
        url = 'https://www.facebook.com/api/graphql/'
        headers = {
            "accept": "*/*",
            "accept-language": "es-ES,es;q=0.9",
            "content-type": "application/x-www-form-urlencoded",
            "sec-ch-ua": "\" Not;A Brand\";v=\"99\", \"Google Chrome\";v=\"91\", \"Chromium\";v=\"91\"",
            "sec-ch-ua-mobile": "?0",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "x-fb-friendly-name": "FriendingCometFriendsListPaginationQuery",
            "referrer": "https://www.facebook.com/friends/list",
            "referrerPolicy": "strict-origin-when-cross-origin",
        }

        session = requests.session()
        session.cookies.update({cookie["name"]: cookie["value"] for cookie in self.driver.get_cookies()})

        response = session.post(
            url,
            headers=headers,
            data=urllib.parse.urlencode(
                {
                    "fb_dtsg": self._fb_dtsg_token,
                    "fb_api_req_friendly_name": "FriendingCometFriendsListPaginationQuery",
                    "variables": json.dumps(
                        {
                            "count": 30,
                            "cursor": self._friend_list_page_info["end_cursor"],
                            "name": None,
                            "scale": 1,
                        }
                    ).replace(" ", ""),
                    "doc_id": 4577965845578736,
                }
            )
        )

        return response.content

    @staticmethod
    def _friends_api_info_to_friend_list(api_info: dict):
        friend_objects = api_info["data"]["viewer"]["all_friends"]["edges"]
        return [
            Friend(
                user_id=str(friend["node"]["id"]),
                name=friend['node']['name'],
                link=friend['node']['url'],
                gender=friend['node']['gender']
            )
            for friend in friend_objects
            if friend["node"]["__typename"] == "User"
        ]

    def read_mutual_friends_from_friend_profile(self, friend_id):
        self.driver.get(self._get_mutual_friends_link(friend_id))
        self._wait_until_all_mutual_friends_are_loaded()
        self.mutual_friends[friend_id] = self._get_mutual_friends_from_mutual_friends_html(self.driver)

    def _get_mutual_friends_link(self, friend_id):
        friend = self._get_friend_by_id(friend_id)
        profile_link = friend.link

        url_parsed = urllib.parse.urlparse(profile_link)
        if url_parsed.path != "/profile.php":
            return f"{profile_link}/friends_mutual"

        return f"{profile_link}&sk=friends_mutual"

    def _wait_until_all_mutual_friends_are_loaded(self):
        time.sleep(1.5)

        while self._mutual_friends_page_is_loading():
            self.driver.find_element_by_xpath('//body').send_keys(Keys.END)
            time.sleep(0.5)

    def _mutual_friends_page_is_loading(self):
        return self._mutual_friends_page_is_loading_from_html(self.driver)

    @staticmethod
    def _mutual_friends_page_is_loading_from_html(driver):
        loading_mutual_friends_panel_class = "lzcic4wl j83agx80 btwxx1t3 lhclo0ds i1fnvgqd"
        element = driver.find_elements_by_css_selector(
            f"div[class='{loading_mutual_friends_panel_class}'][aria-busy='true']"
        )
        return len(element) > 0

    @staticmethod
    def _get_mutual_friends_from_mutual_friends_html(driver):
        mutual_friends_pannel = driver.find_element_by_css_selector(
            "div[data-pagelet='ProfileAppSection_0']"
        )

        mutual_friend_card_link_class = (
            "oajrlxb2 g5ia77u1 qu0x051f esr5mh6w e9989ue4 r7d6kgcz rq0escxv"
            " nhd2j8a9 nc684nl6 p7hjln8o kvgmc6g5 cxmmr5t8 oygrvhab hcukyx3x"
            " jb3vyjys rz4wbd8a qt6c0cv9 a8nywdso i1ao9s8h esuyzwwr f1sip0of lzcic4wl gmql0nx0 gpro0wi8"
        )
        cards = mutual_friends_pannel.find_elements_by_css_selector(f"a[class='{mutual_friend_card_link_class}']")

        friend_cards = [FriendCard(card) for card in cards]

        return [
            Friend(
                name=friend_card.name,
                link=friend_card.link
            )
            for friend_card in friend_cards
        ]

    def _get_friend_by_id(self, friend_id):
        return [friend for friend in self.friends if friend.user_id == friend_id][0]


class FriendCard(object):
    def __init__(self, card):
        self.card = card

    @property
    def link(self):
        return self.card.get_attribute("href")

    @property
    def name(self):
        return self.card.text.split("\n")[0]
