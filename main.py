from mastodon import Mastodon
import os
import sqlite3
from mastodon import StreamListener
import time
import sys
import json

with open(sys.argv[1]) as f:
    parsed_config = json.load(f)    

BOT_ID = parsed_config["bot_id"]
BOT_SECRET_FILE = parsed_config["bot_secret_file"]
API_BASE_URL = parsed_config["api_base_url"]
MASTODON_USER_NAME = parsed_config["mastodon_user_name"]
MASTODON_LOCAL_USER_NAME = parsed_config['mastodon_local_user_name']
MASTODON_POSSIBLE_SERVER_PART = parsed_config['mastodon_possible_server_part']
MASTODON_PASSWORD_FILE = parsed_config['mastodon_password_file']
mastodon_password_reader = open(MASTODON_PASSWORD_FILE, "r")
MASTODON_PASSWORD = mastodon_password_reader.read()
POLL_INTERVAL = parsed_config['poll_interval']
DB_PATH = parsed_config['db_path']

class MastoBotListener(StreamListener):
    def __init__(self, mastobot):
        StreamListener.__init__(self)
        self.mastobot = mastobot
    
    def on_notification(self, notif):
        print(notif)
        if notif["type"] == "mention":
            self.mastobot.handle_message(notif["status"])
    
    def on_conversation(self, conversation):
        print(conversation)
    
    def handle_heartbeat(self):
        print("heartbeat")
    
    def on_abort(self, err):
        print(err)

class MastoBot:
    def __init__(self):
        self.listener = None
        if not os.path.isfile(BOT_SECRET_FILE):
            Mastodon.create_app(
                BOT_ID,
                api_base_url = API_BASE_URL,
                to_file = BOT_SECRET_FILE
            )

        self.mastodon = Mastodon(
            client_id = BOT_SECRET_FILE,
            api_base_url = API_BASE_URL
        )
        self.mastodon.log_in(
            MASTODON_USER_NAME,
            MASTODON_PASSWORD
        )
        self.con = sqlite3.connect(DB_PATH)
        self.check_database()
    
    def check_database(self):
        cur = self.con.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        all_tables = map(lambda x: x[0], cur.fetchall())
        if "data" not in all_tables:
            cur.execute("CREATE TABLE data(key PRIMARY KEY, value)")
            cur.fetchall()
        cur.execute("SELECT key FROM data")
        all_keys = map(lambda x: x[0], cur.fetchall())
        if "min_id_notification" not in all_keys:
            cur.execute("INSERT INTO data (key, value) VALUES (\"min_id_notification\", 0)")
            cur.fetchall()
        
        if "retooted" not in all_tables:
            cur.execute("CREATE TABLE retooted(original_id PRIMARY KEY, retoot_id)")
            cur.fetchall()
        self.con.commit()
    
    def retoot_message(self, message):
        id = str(message["id"])
        cur = self.con.cursor()
        cur.execute("SELECT COUNT(*) FROM retooted WHERE original_id = ?", [id])
        if cur.fetchone()[0] != 0:
            print("The toot with id " + id + " has already been retooted, skipping it...")
            return
        if message["visibility"] == "private" or message["visibility"] == "direct":
            self.mastodon.status_post("@" + message["account"]["username"] + " This bot only retoot message that are public or unlisted", in_reply_to_id=message["id"], visibility="unlisted")
            new_id = str(-1)
        else:
            new_toot = self.mastodon.status_reblog(id)
            new_id = new_toot["id"]
        cur.execute("INSERT INTO retooted(original_id, retoot_id) VALUES (?, ?)", (id, new_id))
        print("handled the message with the id " + id)
        self.con.commit()
    
    def get_min_id_notification(self):
        cur = self.con.cursor()
        cur.execute("SELECT value FROM data WHERE key=\"min_id_notification\"")
        r = cur.fetchone()[0]
        cur.close()
        return r
    
    def set_min_id_notification(self, new_value):
        cur = self.con.cursor()
        cur.execute("UPDATE data SET value = ? WHERE key=\"min_id_notification\"", [new_value])
        cur.close()
        self.con.commit()

    def check_command(self, message):
        normalized_content = message["content"]
        to_remove = [
            "<p>",
            "</p>",
            "</span>",
            "<span>",
            "</a>",
            "<a>"
        ]
        for e in to_remove:
            normalized_content = normalized_content.replace(e, "")
        sections = normalized_content.split(MASTODON_LOCAL_USER_NAME)
        if len(sections) == 0 or len(sections) == 1:
            return None
        for section in sections[1:]:
            section = section.strip()
            for possible_server_part in MASTODON_POSSIBLE_SERVER_PART:
                if section.startswith(possible_server_part):
                    section = section[len(possible_server_part):]
                    section = section.strip()
            if len(section) >= 4:
                if section[:4].lower() == "this":
                    return "retoot"
            if section.startswith("RT") or section.startswith("Rt") or section.startswith("rt") or section.startswith("rT"):
                return "retoot"
            if len(section) >= 6:
                if section[:6].lower() == "parent":
                    return "parent"
        return None
        # TODO: a command to retoot the parent message

    
    def handle_message(self, message):
        command = self.check_command(message)
        if command == None:
            pass
        elif command == "retoot":
            self.retoot_message(message)
        elif command == "parent":
            if message["in_reply_to_id"] == None:
                #TODO: a function to ping someone with a message
                self.mastodon.status_post("@" + message["account"]["username"] + " You seems to want to share the parent message, but your message doesn’t be to be a reply to someone.", in_reply_to_id=message["id"], visibility="unlisted")
            else:
                new_message = self.mastodon.status(message["in_reply_to_id"])
                self.retoot_message(new_message)
        else:
            print("unrecognized command returned by check_message: " + command)
    
    def poll_update(self):
        min_notification_id = self.get_min_id_notification()
        notifications = self.mastodon.notifications(min_id=min_notification_id)
        max_encountered_notification_id = min_notification_id
        for notif in notifications:
            if notif["id"] > max_encountered_notification_id:
                max_encountered_notification_id = notif["id"]
            if notif["type"] == "mention":
                self.handle_message(notif["status"])
        self.set_min_id_notification(max_encountered_notification_id)
    
    # def configure_background_listener(self):
    #    if self.listener == None:
    #        self.listener = MastoBotListener(self)
    #        self.mastodon.stream_user(self.listener)





a = MastoBot()
#doesn’t seems to work
#a.configure_background_listener()
while True:
    a.poll_update()
    time.sleep(POLL_INTERVAL)