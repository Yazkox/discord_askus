import discord
from discord.ext import tasks
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
from database_manager import DataManager
from custom_poll import Poll


load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = 1012323355346608198
CHANNEL_NAME = "askus"
POLL_DELTA = timedelta(hours=14)

USER_MAP = {
    165132116344963072: "François",
    266305722076102657: "Loïc",
    298081860230184960: "Timothée",
    308191958319497216: "Jade",
    334632744745435137: "Chammings",
    380327586779234334: "Alexis",
    389476905830711320: "Chakma",
    407171886221361153: "Rémi",
    411610859324833793: "Noë",
    582631508523745282: "Sixtine",
    639416249985794078: "Corentin",
}

def incr_time(time: datetime) -> datetime:
    return time.replace(hour=21, minute=0, second=0, microsecond=0) + timedelta(days=1)


class MyClient(discord.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.data_base = DataManager()

    async def setup_hook(self) -> None:
        self.my_background_task.start()

    async def on_ready(self):
        print(f"Logged in as {self.user} (ID: {self.user.id})")
        print("------")

    async def send_poll(self, channel: discord.abc.GuildChannel, question: str, remaining: int = None):
        poll = discord.Poll(question, POLL_DELTA)
        choices = [self.get_nickname_map(channel).values()]
        for choice in choices:
            poll = poll.add_answer(text=choices)
        message_str = "@everyone, il est venu l'heure d'un nouveau sondage !"
        if remaining is not None:
            message_str += f" Il me reste {remaining} questions en stock"
        message = await channel.send(message_str, poll=poll)
        await message.create_thread(name="Réactions")
        next_time = incr_time(datetime.now()).strftime("%H:%M:%S - %m/%d/%Y")
        message.remove_reaction()
        print(f"Successfuly sent poll! Next poll at {next_time}")

    async def send_homemade_poll(self, channel: discord.abc.GuildChannel, question, remaining: int = None):
        choices = list(self.get_nickname_map(channel).values())
        poll_data = Poll(question, choices, POLL_DELTA)

        message_str = "@everyone, il est venu l'heure d'un nouveau sondage !"
        if remaining is not None:
            message_str += f" Il me reste {remaining} questions en stock"

        poll_message: discord.Message = await channel.send(message_str, embed=poll_data.get_front_embed())
        for _, reaction in poll_data.choices.items():
            await poll_message.add_reaction(reaction)
        thread = await poll_message.create_thread(name="Réactions et résultats - " + datetime.now().strftime("%m/%d/%Y"))
        result_message = await thread.send("Résultats: ", embed=poll_data.get_thread_embed({}))
        next_time = incr_time(datetime.now()).strftime("%H:%M:%S - %m/%d/%Y")
        self.data_base.add_active_poll(poll_data, poll_message.id, result_message.id)
        print(f"Successfuly sent poll! Next poll at {next_time}")

    @tasks.loop(seconds=30)
    async def my_background_task(self):
        self.data_base.close_polls()

        last_poll_ts = self.data_base.get_last_poll()
        if datetime.now() < incr_time(datetime.fromtimestamp(last_poll_ts)):
            return
        guild = discord.utils.get(self.guilds, id=GUILD_ID)
        if not guild:
            print(f"No guild found with id {GUILD_ID}")
            return
        channel: discord.abc.GuildChannel = discord.utils.get(guild.channels, name=CHANNEL_NAME)
        if not channel:
            print(f"No channel found with name {CHANNEL_NAME}")
            return
        question = self.data_base.get_random_question()
        if question is None:
            question = "Je n'ai plus de question à poser (c'est bien réel), qui doit régler ce problème ?\n"
        await self.send_homemade_poll(channel, question, remaining=len(self.data_base.remaining_questions()))
        self.data_base.update_last_poll()

    @my_background_task.before_loop
    async def before_my_task(self):
        await self.wait_until_ready()

    async def on_message(self, message: discord.Message):
        if message.author.id == self.user.id:
            return
        if message.channel.type != discord.ChannelType.private:
            return
        if message.content.startswith("/add"):
            self.data_base.add_question(message.content[5:], message.author.display_name)
            await message.channel.send("J'ai bien ajouté ta question")
        elif message.content.startswith("/remaining"):
            n = len(self.data_base.remaining_questions())
            await message.channel.send(f"Il reste {n} questions")

    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        for poll_message_id, info in self.data_base.get_polls():
            if payload.message_id != poll_message_id:
                continue
            if payload.user_id == self.user.id or payload.member.bot:
                return
            channel = self.get_channel(payload.channel_id)
            poll_msg = channel.get_partial_message(payload.message_id)
            await poll_msg.remove_reaction(payload.emoji, payload.member)
            choice = None
            for ch, emoji in info["poll_data"].choices.items():
                if discord.partial_emoji.PartialEmoji(name=emoji) == payload.emoji:
                    choice = ch
            if choice is None:
                return
            thread = poll_msg.thread
            result_msg = thread.get_partial_message(info["result_message_id"])
            info["poll_data"].votes[payload.member.id] = choice
            await result_msg.edit(embed=info["poll_data"].get_thread_embed(self.get_nickname_map(channel)))
            return

    def get_nickname_map(self, channel):

        nick_map = {}
        for member in channel.members:
            if member.bot:
                continue
            nick_map[member.id] = USER_MAP[member.id] if member.id in USER_MAP.keys() else member.name
        return nick_map


def main():
    intents = discord.Intents.default()
    intents.members = True
    client = MyClient(intents=intents)
    client.run(TOKEN)


if __name__ == "__main__":
    main()
