import discord
from discord.ext import tasks
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
import json
from typing import Dict
from pollclient import PollClient
import random
import os

load_dotenv()
TOKEN =  os.getenv("DISCORD_TOKEN")
TZ = timezone.utc


class AskUsClient(PollClient):

    COMMAND_PREFIX = "/askus"

    def __init__(
        self,
        *args,
        **kwargs,
    ):
        """Poll client for discord

        Args:
            db_url (_type_, optional): url of the mongo database. Defaults to "mongodb://localhost:27017/".
        """
        super().__init__(*args, **kwargs)
        self.askus_collection = None
        self.question_collection = None

    def setup_database(self):
        super().setup_database()
        self.askus_collection = self.database.get_collection("askus")
        self.question_collection = self.database.get_collection("questions")

    async def setup_hook(self) -> None:
        self.my_background_task.start()

    async def on_ready(self):
        print(f"Logged in as {self.user} (ID: {self.user.id})")
        print("------")

    @tasks.loop(seconds=30)
    async def my_background_task(self):
        await self.close_polls()
        await self.check_askus()

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
        if new_content.startswith("question"):
            new_content = new_content.removeprefix("question").strip()
            parts = new_content.split("|")
            question = parts[0]
            answers = []
            if len(parts) > 1:
                answers = parts[1].split(",")
            self.add_question(question, answers=answers)
            await message.channel.send("J'ai bien ajouté ta question !")
            return

        if message.channel.type != discord.ChannelType.text:
            return
        if new_content.startswith("start"):
            new_content = new_content.removeprefix("start").strip()
            try:
                args, kwargs = json.loads(new_content).values()
                self.start_askus(message.channel.id, *args, **kwargs)
            except Exception as e:
                await message.channel.send(f"There was an error in your inputs : \n {e}\n Try /poll help !")
                raise Exception(e.with_traceback())
            return

        if new_content.startswith("stop"):
            self.stop_askus(message.channel.id)
            return

        if new_content.startswith("pause"):
            self.pause_askus(message.channel.id)
            return

        if new_content.startswith("nickname"):
            new_content = new_content.removeprefix("nickname").strip()
            member_id, nickname = new_content.split(" ", 1)
            try:
                member_id = int(member_id)
            except:
                await message.channel.send("Member id is not an integer")
                return
            page = self.nickname_collection.find_one({"_id": message.channel.id})
            if not page:
                page = {"_id": message.channel.id, "nicknames": {}}
                self.nickname_collection.insert_one(page)
            new_nicknames = page["nicknames"]
            new_nicknames[str(member_id)] = nickname
            self.nickname_collection.find_one_and_update({"_id": message.channel.id}, {"$set": {"nicknames": new_nicknames}})
            await message.channel.send("J'ai bien ajouté le nickname")

        
    async def check_askus(self):
        """Checks to see if new polls needs to be posted and poss them
        """
        sessions = self.askus_collection.find({"next_poll_time": {"$lt": datetime.now(tz=TZ)}})
        if not sessions:
            return
        for session in sessions:
            if session["paused"]:
                continue
            channel: discord.guild.GuildChannel = self.get_channel(session["_id"])
            if not channel:
                continue

            questions = self.question_collection.find()
            remaining_questions = [
                page for page in questions if page["_id"] not in session["asked_questions"]
            ]
            if not remaining_questions:
                self.pause_askus(channel.id)
                await channel.send("Je n'ai plus de question à poser, j'ai pausé la session, n'hésitez pas à en rajouter en tapant /askus question 'question' en DM !")
                continue

            question = random.choice(remaining_questions)
            duration = timedelta(
                **session["poll_duration"]
            )  # py mongo supports datetime so we have to store timedelta as dict or params
            closing_time = (datetime.now(tz=TZ) + duration).strftime("%H:%M - %d/%m/%Y")
            thread_name = "Résultats - " + datetime.now(tz=TZ).strftime("%d/%m/%Y")
            message = f"<@&1342105732463460392>, il est venu le temps des questions génantes ! Il me reste {len(remaining_questions) - 1} question(s) en stock. Le sondage ferme à {closing_time}"
            
            if "answers" in question and question["answers"]:
                answers = question["answers"]
            else:
                answers = self.get_name_map(channel)
            message_id = await self.send_poll(
                channel,
                question["question"],
                answers,
                message=message,
                thread_name=thread_name,
                duration=duration,
                mode=self.CUSTOM
            )
            if not message_id:
                continue
            session["asked_questions"].append(question["_id"])
            next_poll_time = datetime.now(tz=TZ).replace(**session["poll_time"]) + timedelta(**session["poll_period"])
            self.askus_collection.find_one_and_update(
                {"_id": session["_id"]},
                {
                    "$set": {
                        "next_poll_time": next_poll_time,
                        "asked_questions": session["asked_questions"],
                    }
                },
            )
        return

    def start_askus(
        self,
        channel_id: int,
        poll_time: Dict[str, int] = {"hour": 12, "minute": 0, "second": 0},
        poll_duration: Dict[str, int] = {"hours": 20, "minutes": 0, "seconds": 0},
        poll_period: Dict[str, int] = {"days": 1}
    ):
        """Starts a askus session on a channel. there can be only one session per channel. If there is already one, it will just unpause and modify
        the parameters of the session

        Args:
            channel_id (int)
            poll_time (Dict[str, int], optional): time at which to send the poll (will replace current time with those value and add poll period to determine next poll time). Defaults to {"hours": 21, "minutes": 0, "seconds": 0}, regardless of the day, at 21pm.
            poll_duration (Dict[str, int], optional): duration of the poll. Defaults to {"hours": 14, "minutes": 0, "seconds": 0}.
            poll_period (Dict[str, int], optional): period at which to send polls on the session. Defaults to {"days": 1}.
        """
        possible_session = self.askus_collection.find_one_and_update(
            {"_id": channel_id}, {"$set": {"paused": False, "poll_time": poll_time, "poll_duration": poll_duration}}
        )
        # If there was a session, we unpaused it and updated poll time and duration
        if possible_session:
            return
        # If not we create it
        self.askus_collection.insert_one(
            {
                "_id": channel_id,
                "poll_time": poll_time,
                "poll_period": poll_period,
                "poll_duration": poll_duration,
                "paused": False,
                "asked_questions": [],
                "next_poll_time": datetime.now(tz=TZ),
            }
        )

    def stop_askus(self, channel_id: int):
        """Stops askus session
        """
        self.askus_collection.find_one_and_delete({"_id": channel_id})

    def pause_askus(self, channel_id: int):
        """Pauses askus session
        """
        self.askus_collection.find_one_and_update({"_id": channel_id}, {"$set": {"paused": True}})

    def add_question(self, question: str, answers: list = []):
        return self.question_collection.insert_one({"question": question, "answers": answers})


def main():
    intents = discord.Intents.default()
    intents.members = True
    intents.message_content = True
    client = AskUsClient(intents=intents)
    client.run(TOKEN)


if __name__ == "__main__":
    main()
