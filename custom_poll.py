import discord
from typing import List
from datetime import timedelta
import datetime
from dataclasses import dataclass

@dataclass
class Poll:
    def __init__(self, question: str, choices: List[str], duration: timedelta):
        self.question = question
        self.choices = {choice: chr(ord("\U0001F1E6") + i) for i, choice in enumerate(choices)}
        self.votes = {}
        self.close_ts = (datetime.datetime.now() + duration).timestamp()

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "choices": self.choices,
            "votes": self.votes,
            "close_ts": self.close_ts
        }

    def get_front_embed(self) -> discord.Embed:
        """Construct the nice and good looking discord Embed object that represent the poll choices
        """
        description = self.question + " \n"
        description += "\n".join(
            emoji + " " + choice
            for choice, emoji in self.choices.items()
        )
        embed = discord.Embed(
            description=description, color=discord.Color.dark_red()
        )
        return embed

    def get_thread_embed(self, username_map: dict) -> discord.Embed:
        results = {choice: [] for choice in self.choices.keys()}
        for votant, vote in self.votes.items():
            if vote not in self.choices.keys():
                continue
            results[vote].append(votant)
        sorting_key = lambda item: len(item[1])
        sorted_winners = sorted(results.items(), key=sorting_key, reverse=True)
        description = "\n".join(
            f"{choice} : {len(votants)}   |  " + ", ".join(username_map[votant_id] for votant_id in votants if votant_id in username_map.keys())
            for choice, votants in sorted_winners
        )
        embed = discord.Embed(
            description=description, color=discord.Color.dark_red()
        )
        return embed
    
    
    @staticmethod
    def from_dict(info: dict):
        new_poll = Poll(info["question"], choices=[], duration=timedelta(days=1))
        new_poll.choices = info["choices"]
        new_poll.close_ts = info["close_ts"]
        new_poll.votes = info["votes"]
        return new_poll
        