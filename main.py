import discord
from discord.ext import tasks
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
from database_manager import DataManager
import pytz


load_dotenv()
timezone = pytz.timezone("Europe/Paris")
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_NAME = "test_bots"
CHANNEL_NAME = "questions-cringes"
POLL_DELTA = timedelta(days=1.0)

def incr_time(time: datetime) -> datetime:
    return time.replace( minute=0, second=0, microsecond=0) + timedelta(hours=1)

class MyClient(discord.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.data_base = DataManager()
        
    async def setup_hook(self) -> None:
        self.my_background_task.start()

    async def on_ready(self):
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print('------')

    async def send_poll(self, question: str ="nobody expects the spanish inquisition"):
        guild = discord.utils.get(self.guilds, name=GUILD_NAME)
        if not guild:
            print(f"No guild found with name {GUILD_NAME}")
            return
        channel: discord.guild.GuildChannel = discord.utils.get(guild.channels, name=CHANNEL_NAME)
        if not channel:
            print(f"No channel found with name {CHANNEL_NAME}")
            return
        poll = discord.Poll(question, POLL_DELTA)
        for member in channel.members:
            if member.bot:
                continue
            username = member.nick if member.nick else member.name
            poll = poll.add_answer(text=username)
        message = await channel.send("@everyone, il est venu l'heure d'un nouveau sondage", poll=poll)
        await message.create_thread(name="Réactions")
        next_time = incr_time(datetime.now()).strftime("%H:%M:%S - %m/%d/%Y")
        print(f"Successfuly sent poll ! next poll at {next_time}")
        
    @tasks.loop(seconds=60)
    async def my_background_task(self):
        last_poll_ts = self.data_base.get_last_poll()
        if datetime.now() < incr_time(datetime.fromtimestamp(last_poll_ts)):
            return
        question = self.data_base.get_random_question()
        if question is None:
            question = "Je n'ai plus de question à poser (c'est bien réel), qui doit régler ce problème ?"
        await self.send_poll(question=question)
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


def main():
    intents = discord.Intents.default()
    intents.members = True
    client = MyClient(intents=intents)
    client.run(TOKEN)



if __name__=="__main__":
    main()