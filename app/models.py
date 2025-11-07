# app/models.py

from pydantic import BaseModel, Field
from typing import List, Dict, Any
from datetime import datetime
from asyncio import Task

# --- User Authentication Models (This is the missing part) ---
class UserCreate(BaseModel):
    username: str
    password: str
    confirmPassword: str
    email: str

class UserLogin(BaseModel):
    username: str
    password: str

# --- User Model for Database/Frontend ---
class User(BaseModel):
    username: str
    score: int = 0

# --- Game Logic Models ---
class PlayerStats(BaseModel):
    score: int = 0
    total_time: float = 0.0
    answered_mask: List[bool] = Field(default_factory=lambda: [False] * 5) # Assuming QUESTIONS_PER_GAME is 5
    current_question_index: int = -1
    question_start_time: datetime | None = None
    finished: bool = False
    timer_task: Task | None = None

    class Config:
        arbitrary_types_allowed = True

class GameSession(BaseModel):
    players: List[str]
    category: str
    puzzles: List[Dict[str, Any]]
    player_stats: Dict[str, PlayerStats]

    class Config:
        arbitrary_types_allowed = True # Needed for asyncio.Task if you ever add it back