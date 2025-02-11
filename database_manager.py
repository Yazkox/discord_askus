import json
import time
import random
import os
DATA_FILE = "data.json"


class DataManager:
    def __init__(self, data_file: str = DATA_FILE):
        self.data_file = data_file
        if os.path.isfile(self.data_file): 
            with open(self.data_file, "r") as f:
                self.data = json.loads(f.read())
        else:
            self.data = {"last_poll_ts": 0, "questions": []}
            self.update_json()
            
    def update_json(self):
        with open(self.data_file, "w") as f:
            f.write(json.dumps(self.data, indent=4))
        
    def update_last_poll(self):
        self.data["last_poll_ts"] = int(time.time())
        self.update_json()

    def get_last_poll(self) -> int:
        return self.data["last_poll_ts"]
    
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
        
        
        
test = DataManager()