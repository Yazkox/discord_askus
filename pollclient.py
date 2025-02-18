import discord
from discord.ext import tasks
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
import json
from typing import List, Dict
from pymongo import MongoClient
import os

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
TZ = timezone.utc


class PollClient(discord.Client):

    AUTO = 0
    CUSTOM = 1
    DISCORD = 2
    COMMAND_PREFIX = "/poll"

    def __init__(
        self,
        *args,
        db_url: str = "mongodb://localhost:27017/",
        db_name: str = "poll_db",
        **kwargs,
    ):
        """Poll client for discord

        Args:
            db_url (_type_, optional): url of the mongo database. Defaults to "mongodb://localhost:27017/".
            poll_collection (str, optional): database page on which the data is stored. Defaults to "poll_db".
        """
        super().__init__(*args, **kwargs)
        self.db_url = db_url
        self.db_name = db_name
        self.db_client: MongoClient = None
        self.database = None
        self.active_poll_collection = None
        self.nickname_collection = None

    def setup_database(self) -> None:
        self.db_client: MongoClient = MongoClient(self.db_url)
        self.database = self.db_client.get_database(self.db_name)
        self.active_poll_collection = self.database.get_collection("active_polls")
        self.nickname_collection = self.database.get_collection("nicknames")

    def run(self, *args, **kwargs):
        self.setup_database()
        super().run(*args, **kwargs)

    async def setup_hook(self) -> None:
        self.my_background_task.start()

    async def on_ready(self):
        print(f"Logged in as {self.user} (ID: {self.user.id})")
        print("------")

    @tasks.loop(seconds=30)
    async def my_background_task(self):
        await self.close_polls()

    @my_background_task.before_loop
    async def before_my_task(self):
        await self.wait_until_ready()

    async def on_message(self, message: discord.Message):
        if message.author.id == self.user.id or message.author.bot:
            return
        if not message.content.startswith(self.COMMAND_PREFIX):
            return

        new_content = message.content.removeprefix(self.COMMAND_PREFIX).strip()
        if new_content.startswith("help"):
            await message.channel.send("Sent you help in DM !")
            if message.author.dm_channel is None:
                await message.author.create_dm()
            await message.author.dm_channel.send(self.get_help())
            return

        if new_content.startswith("create"):
            new_content = new_content.removeprefix("create").strip()
            try:
                print(json.loads(new_content).values())
                args, kwargs = json.loads(new_content).values()
                await self.send_poll(message.channel, *args, **kwargs)
            except Exception as e:
                await message.channel.send(f"There was an error in your inputs : \n {e}\n Try /poll help !")
                raise Exception(e)
            return

        if new_content.startswith("remove"):
            poll_id = new_content.removeprefix("remove").strip()
            doc = self.active_poll_collection.find_one({"_id": int(poll_id)})
            if doc is not None and doc["channel_id"] == message.channel.id:
                self.active_poll_collection.find_one_and_delete({"_id": int(poll_id)})
                poll_message = await message.channel.fetch_message(poll_id)
                await poll_message.delete()
            return

        if new_content.startswith("clear"):
            docs = self.active_poll_collection.find({"channel_id": message.channel.id})
            message_ids = [doc["_id"] for doc in docs]
            for message_id in message_ids:
                self.active_poll_collection.find_one_and_delete({"_id": message_id})
                message_to_delete = await message.channel.fetch_message(message_id)
                await message_to_delete.delete()
            return

        if new_content.startswith("close"):
            poll_id = new_content.removeprefix("close").strip()
            doc = self.active_poll_collection.find_one({"_id": int(poll_id)})
            if doc is not None and doc["channel_id"] == message.channel.id:
                self.active_poll_collection.find_one_and_delete({"_id": int(poll_id)})
            return
        
        if new_content.startswith("add_nick"):
            poll_id = new_content.removeprefix("add_nick").strip()
            member_id, nickname = new_content.split(" ", 1)
            self.add_nickname(message.channel.id, member_id, nickname)      

        if message.channel.type != discord.ChannelType.private:
            return

    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """Checks every event of reaction add to see if it corresponds to a vote and acts in consequence
        """
        if payload.member.bot:
            return
        doc = self.active_poll_collection.find_one({"_id": payload.message_id})
        if not doc:
            return
        channel = self.get_channel(payload.channel_id)
        poll_msg = channel.get_partial_message(payload.message_id)
        await poll_msg.remove_reaction(payload.emoji, payload.member)
        
        # checking emojis to see if it corresponds to a the one of a vote, returning if not
        answer = None
        for key, emoji in doc["emojis"].items():
            if discord.partial_emoji.PartialEmoji(name=emoji) == payload.emoji:
                answer = key
        if not answer:
            return
        # constructing the variable to get the new embed of the result, then edit the message with the new embed
        thread = poll_msg.thread
        result_msg = thread.get_partial_message(doc["results_id"])
        doc["results"][payload.user_id] = answer
        votes = {str(key): [] for key in doc["answers"].keys()}
        name_map = self.get_name_map(channel)
        for votant, vote in doc["results"].items():
            votes[vote].append(name_map[votant])
        await result_msg.edit(embed=self._get_results_embed(doc["answers"].values(), [value for _, value in votes.items()]))
        self.active_poll_collection.find_one_and_update({"_id": payload.message_id}, {"$set": {"results": votes}})
        return

    async def _send_discord_poll(
        self,
        channel: discord.abc.GuildChannel,
        question: str,
        answers: Dict[int, str],
        message: str,
        duration: timedelta,
        thread_name: str = "",
        multiple: bool = False,
    ) -> int:
        """Sends a regular discord poll and updates the database with the poll information (excepts for answers)

        Args:
            channel (discord.abc.GuildChannel): channel in which to send the poll
            question (str): question of the poll
            answers (Dict[int, str]): dictionnary containing all possible answers
            message (str): message preceeding the poll
            duration (timedelta): duration of the poll
            thread_name (str, optional): If provided, creates a thread with that name under the poll. Defaults to "".
            multiple (bool, optional): Wether to allow multiple answers . Defaults to False.

        Returns:
            int: id of the poll message
        """
        poll = discord.Poll(question, duration, multiple=multiple)
        for _, answer in answers.items():
            poll = poll.add_answer(text=answer)
        poll_message = await channel.send(message, poll=poll)
        await poll_message.create_thread(name=thread_name)
        self.active_poll_collection.insert_one(
            {
                "_id": poll_message.id,
                "channel_id": channel.id,
                "close_time": datetime.now(tz=TZ) + duration,
                "native": True,
                "question": question,
                "answers": {index: {"answer": question, "emoji": None} for index, question in answers.items()},
            }
        )
        print(f"Successfuly sent poll in {channel.name}!")
        return poll_message.id

    async def _send_homemade_poll(
        self,
        channel: discord.abc.GuildChannel,
        question: str,
        answers: Dict[int, str],
        message: str,
        duration: timedelta,
        thread_name: str = "",
        emojis: Dict[int, str] = None,
    ) -> int:
        """Creates and send an homemade version of discord polls, usefull when there is more than 10 answers. If more than 26 answers are provided, emojis is needed

        Args:
            channel (discord.abc.GuildChannel): discord channel
            question (str): question of the poll
            answers (Dict[int, str]): dictionnary containing all possible answers
            message (str): message of the poll
            duration (timedelta): duration of the poll
            thread_name (str, optional): name of the thread on which results are published. Defaults to "Résultats".
            emojis (Dict[int, str], optional): maping of keys (same as answers) to emojis to use for reactions, needed if more than 26 answers, defaults to A to Z. Defaults to None.

        Returns:
            int: message id of the poll
        """
        if emojis:
            assert len(emojis) == len(answers)
            assert all([(key in emojis.keys()) for key in answers.keys()])

        else:
            emojis = {key: emoji  for key, emoji in zip(answers.keys(),self.get_emoji_AtoZ(len(answers)))}
        poll_embed = self._get_poll_embed(question, answers.values(), emojis.values())
        poll_message = await channel.send(message, embed=poll_embed)
        for _, emoji in emojis.items():
            await poll_message.add_reaction(emoji)

        thread = await poll_message.create_thread(name=thread_name if thread_name else "Résultat")

        result_embed = self._get_results_embed(answers.values(), [[] for _ in answers])
        result_message = await thread.send("Résultats: ", embed=result_embed)
        

        self.active_poll_collection.insert_one(
            {
                "_id": poll_message.id,
                "results_id": result_message.id,
                "channel_id": channel.id,
                "close_time": datetime.now(tz=TZ) + duration,
                "native": False,
                "question": question,
                "answers": convert_dictkeys_str(answers),
                "emojis": convert_dictkeys_str(emojis),
                "results": {},
            }
        )
        print(f"Successfuly sent poll in {channel.name} !")
        return poll_message.id

    async def send_poll(
        self,
        channel: discord.abc.GuildChannel,
        question: str,
        answers: Dict[int, str],
        mode: int = 0,
        message: str = "",
        thread_name: str = "",
        duration: timedelta = timedelta(seconds=30),
        emojis: Dict[int, str] = None,
        multiple: bool = False,
    ) -> int:
        """Sends a poll (discord or custom) on a channel

        Args:
            channel (discord.guild.GuildChannel): channel of the poll
            question (str): question of the poll
            answers (Dict[int, str]): dictionnary containing all possible answers
            mode (int, optional): Type of poll, auto will choose based on number of answers PollClient.AUTO, PollClient.DISCORD or PollClient.CUSTOM. Defaults to PollClient.AUTO.
            message (str, optional): message of the poll. Defaults to "".
            thread_name (str, optional): thread name, if poll is discord and set to "", will not create thread. Defaults to "".
            duration (timedelta, optional): duration of the poll. Defaults to timedelta(days=1).
            emojis (Dict[int, str], optional): maping of keys (same as answers) to emojis to use for reactions, needed if more than 26 answers, defaults to A to Z. Only for AUTO or CUSTOM polls.Defaults to None.

        Raises:
            Exception: When giving more than 26 possible answers without specifying emojis or when giving more than 10 answers in DISCORD mode

        Returns:
            int: message id of the poll
        """
        if mode != self.DISCORD and not emojis and len(answers) > 26:
            raise Exception("Too much answers without specifying emojis, max is 26")
        elif mode == self.DISCORD and len(answers) > 10:
            raise Exception("Too much answers, max for discord native polls is 10")

        if mode == self.AUTO:
            if len(answers) >= 10:
                mode = self.CUSTOM
            else:
                mode = self.DISCORD

        if mode == self.DISCORD:
            return await self._send_discord_poll(
                channel, question, answers, message, duration, thread_name=thread_name, multiple=multiple
            )
        else:
            return await self._send_homemade_poll(
                channel, question, answers, message, duration, thread_name=thread_name, emojis=emojis
            )

    async def close_polls(self):
        """Removes closed custom polls from database and mark them as such in discord"""
        docs = self.active_poll_collection.find({"close_time": {"$lt": datetime.now(tz=TZ)}})
        for doc in docs:
            if not doc["native"]:
                channel = self.get_channel(doc["channel_id"])
                poll_msg = channel.get_partial_message(doc["_id"])
                poll_embed = self._get_poll_embed(
                    doc["question"] + "⚠️ SONDAGE CLOS ⚠️", doc["answers"].values(), doc["emojis"].values()
                )
                await poll_msg.edit(embed=poll_embed)
            self.active_poll_collection.find_one_and_delete({"_id": doc["_id"]})
    
    def get_name_map(self, channel: discord.TextChannel) -> Dict[int, str]:
        """Fill nickname maps of any missing member by their discord nickname
        """
        nickname_page = self.nickname_collection.find_one({"_id": channel.id})
        nickname_map = nickname_page["nicknames"] if nickname_page else {}
        filtered_members = [member for member in channel.members if not member.bot]
        nicknames = {
            member.id: nickname_map[str(member.id)] if str(member.id) in nickname_map.keys() else member.nick
            for member in filtered_members
        }
        return nicknames

    @staticmethod
    def get_emoji_AtoZ(length: int) -> List[str]:
        """Return a list of length emojis, maximum 26 (from A to Z)
        """
        assert length >= 0 and length <= 26
        return [chr(ord("\U0001F1E6") + i) for i in range(length)]

    @staticmethod
    def _get_poll_embed(question: str, answers: List[str], emojis: List[str]) -> discord.Embed:
        """Gets the embed of the poll message

        Args:
            question (str)
            answers (List[str]): List of the answers
            emojis (List[str]): List of the emojis of the reactions corresponding to each vote

        Returns:
            discord.Embed
        """
        assert len(answers) == len(emojis)
        description = question + " \n"
        description += "\n".join(emoji + " " + answer for answer, emoji in zip(answers, emojis))
        embed = discord.Embed(description=description)
        return embed

    @staticmethod
    def _get_results_embed(answers: List[str], votes: List[List[str]]) -> discord.Embed:
        """Gets the embed of the result of the poll

        Args:
            answers (List[str]): List of the possible answers
            votes (List[List[str]]): List, each item representing the list name of the votants of the answer of the same index

        Returns:
            discord.Embed: _description_
        """
        filtered_results = [pair for pair in zip(answers, votes) if len(pair[1]) >= 0]# removing answers with zero votes
        sorting_key = lambda item: len(item[1])
        sorted_results = sorted(filtered_results, key=sorting_key, reverse=True)
        description = "\n".join(
            f"{answer:11} : {len(votants):2} |  " + ", ".join(votant for votant in votants) for answer, votants in sorted_results
        )
        embed = discord.Embed(description=description)
        return embed

    def add_nickname(self, channel_id: int, member_id: str, nickname: str):
        """Adds a nickname to the nickname config for the channel
        """
        nicknames = self.nickname_collection.find_one({"_id": channel_id})
        if not nicknames:
            nicknames = {"_id": channel_id, "nicknames": {member_id: nickname}}
            self.nickname_collection.insert_one(nicknames)
        else:
            nicknames["nicknames"][member_id] = nickname
            self.nickname_collection.replace_one({"_id": channel_id}, nicknames)

    def get_help(self):
        return "Not implemented yet"


def convert_dictkeys_str(dictionnary: dict) -> dict:
    """Converts key of dictionnary to string
    """
    if not dictionnary:
        return {}
    return {str(key): nick for key, nick in dictionnary.items()}

def main():
    intents = discord.Intents.default()
    intents.members = True
    intents.message_content = True
    client = PollClient(intents=intents)
    client.run(TOKEN)


if __name__ == "__main__":
    main()
