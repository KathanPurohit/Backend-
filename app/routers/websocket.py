import asyncio
from asyncio import Task, CancelledError
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import Dict, List
import json
import random
from datetime import datetime
import logging

from app.database import db
from app.models import GameSession
from app.puzzles import CATEGORY_PUZZLES
from .websocket_helpers import (
    broadcast_stats, handle_matchmaking, handle_answer, cleanup_player,
    MIN_PLAYERS 
)

router = APIRouter()
logger = logging.getLogger(__name__)

# --- Data Structures & Game State ---
MAX_PLAYERS = 8

active_games: Dict[str, GameSession] = {}
connected_players: Dict[str, WebSocket] = {}
waiting_rooms: Dict[str, Dict] = {}
player_to_room: Dict[str, str] = {}


# --- Main WebSocket Endpoint ---
@router.websocket("/ws/{username}")
async def websocket_endpoint(websocket: WebSocket, username: str):
    await websocket.accept()
    if username in connected_players:
        logger.warning(f"User '{username}' already has a connection. Closing the old one.")
        old_websocket = connected_players.get(username)
        if old_websocket: await old_websocket.close(code=1008)
    
    connected_players[username] = websocket
    logger.info(f"WebSocket connected for: {username}")
    await broadcast_stats(connected_players, active_games)
    
    try:
        await websocket.send_text(json.dumps({"type": "connected", "message": f"Welcome, {username}!"}))
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            msg_type = message.get("type")

            if msg_type == "find_match":
                await handle_matchmaking(username, websocket, message.get("category"), waiting_rooms, player_to_room, connected_players, active_games, MAX_PLAYERS)
            elif msg_type == "submit_answer":
                await handle_answer(username, message.get("answer"), active_games, connected_players)
            elif msg_type == "cancel_search":
                if username in player_to_room:
                    category = player_to_room[username]
                    del player_to_room[username]
                    room = waiting_rooms.get(category)
                    if room and username in room["players"]:
                        room["players"].remove(username)
                        if not room["players"]:
                            if "task" in room: room["task"].cancel()
                            del waiting_rooms[category]
                await websocket.send_text(json.dumps({"type": "search_cancelled"}))

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for: {username}")
    finally:
        if connected_players.get(username) == websocket:
            await cleanup_player(username, connected_players, player_to_room, waiting_rooms, active_games, MIN_PLAYERS)