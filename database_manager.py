import json
import time
import random
import os
from custom_poll import Poll
from copy import deepcopy
DATA_FILE = "data.json"


class DataManager:
    def __init__(self, data_file: str = DATA_FILE):
        self.data_file = data_file
        if os.path.isfile(self.data_file): 
            self.read_json()
        else:
            self.data = {"last_poll_ts": 0, "questions": [], "active_polls": {}}
            self.update_json()
            
    def read_json(self):
        with open(self.data_file, "r") as f:
            self.data = json.loads(f.read())
            new_active_polls = {}
            for poll_id, info in self.data["active_polls"].items():
                new_active_polls[int(poll_id)] = {
                    "poll_data": Poll.from_dict(info["poll_data"]),
                    "result_message_id": info["result_message_id"]
                    }
            self.data["active_polls"] = new_active_polls

    def update_json(self):
        alt_data = deepcopy(self.data)
        with open(self.data_file, "w") as f:
            for _, info in alt_data["active_polls"].items():
                info["poll_data"] = info["poll_data"].to_dict()
            f.write(json.dumps(alt_data, indent=4))
        
    def update_last_poll(self):
        self.data["last_poll_ts"] = int(time.time())
        self.update_json()

    def get_last_poll(self) -> int:
        return self.data["last_poll_ts"]
    
    def add_active_poll(self, poll_data: Poll, poll_id: int, result_id: int):
        self.data["active_polls"][poll_id] = {
            "poll_data": poll_data,
            "result_message_id": result_id
            }
        self.update_json()
        
    def remove_active_poll(self, poll_id: int):
        try:
            self.data["active_polls"].pop(poll_id)
            self.update_json()
        except KeyError:
            print("Couldn't remove poll, poll not present")
        
    def get_random_question(self) -> str:
        availlable_questions = [question for question in self.data["questions"] if not question["asked"]]
        if not availlable_questions:
            return None
        question = random.choice(availlable_questions)
        question["asked"] = True
        question["asked_ts"] = int(time.time())
        self.update_json()
        return question["content"]
    
    def add_question(self, question: str, creator: str):
        self.data["questions"].append(
            {
                "content": question,
                "creator": creator,
                "asked": False,
                "asked_ts": 0,
            }
        )
        self.update_json()
        
    def reset_question(self):
        for question in self.data["questions"]:
            question["asked_ts"] = 0
            question["asked"] = False
        self.update_json()
        
    def remaining_questions(self) -> list:
        return [question for question in self.data["questions"] if not question["asked"]]
    
    def get_polls(self):
        return self.data["active_polls"].items()
    
    def close_polls(self):
        polls_to_close = []
        for poll_id, info in self.data["active_polls"].items():
            if time.time() >= info["poll_data"].close_ts:
                polls_to_close.append(poll_id)
        for poll_id in polls_to_close:
            self.data["active_polls"].pop(poll_id)
        self.update_json()
        

        
        
if __name__=="__main__":
    test = DataManager()
    test.data["actives_polls"] = {}
    test.reset_question()