# mindmaze-backend/app/routers/websocket_helpers.py

import asyncio
from asyncio import Task, CancelledError
from fastapi import WebSocket
from typing import Dict, List
import json
import random
from datetime import datetime
import logging
from pymongo import ReturnDocument

from app.database import db
from app.models import GameSession, PlayerStats
from app.puzzles import CATEGORY_PUZZLES

logger = logging.getLogger(__name__)

# --- Game Constants ---
MIN_PLAYERS = 2
MAX_PLAYERS = 8
WAITING_TIME = 10
QUESTIONS_PER_GAME = 5
TIME_PER_QUESTION = 30


# --- Utility Functions ---

async def broadcast_stats(connected_players: Dict, active_games: Dict):
    """Broadcasts live server stats to all connected players."""
    try:
        total_users = await db.users.count_documents({})
        stats = {
            "total_users": total_users,
            "active_games": len(active_games),
            "connected_players": len(connected_players)
        }
        for websocket in list(connected_players.values()):
            try:
                await websocket.send_text(json.dumps({"type": "stats_update", "stats": stats}))
            except Exception:
                pass
    except Exception as e:
        logger.error(f"Error broadcasting stats: {e}")


# --- Core Game Logic ---

async def finalize_game(game_id: str, active_games: Dict, connected_players: Dict):
    """Finalizes the game, calculates ranks, awards points to the winner, and notifies players."""
    if game_id not in active_games:
        return
    
    try:
        game = active_games.pop(game_id, None)
        if not game:
            return
        
        logger.info(f"Finalizing game '{game_id}' with winner-takes-all scoring.")
        
        final_results = sorted(
            game.player_stats.items(),
            key=lambda item: (-item[1].score, item[1].total_time)
        )
        
        winner_username = final_results[0][0] if final_results and final_results[0][1].score > 0 else "No one"
        WINNER_POINTS = 50
        
        results_with_points = []
        
        player_usernames = list(game.player_stats.keys())
        player_docs = await db.users.find({"username": {"$in": player_usernames}}).to_list(length=len(player_usernames))
        current_scores = {doc['username']: doc['score'] for doc in player_docs}

        for username, stats in final_results:
            points_awarded = 0
            new_total_score = current_scores.get(username, 0)

            if username == winner_username:
                points_awarded = WINNER_POINTS
                updated_user = await db.users.find_one_and_update(
                    {"username": username},
                    {"$inc": {"score": points_awarded}},
                    return_document=ReturnDocument.AFTER
                )
                if updated_user:
                    new_total_score = updated_user['score']
                logger.info(f"Awarded {points_awarded} points to winner: {username}. New score: {new_total_score}")

            results_with_points.append({
                "username": username,
                "score": stats.score,
                "time": round(stats.total_time, 2),
                "points_awarded": points_awarded,
                "new_total_score": new_total_score
            })

        results_payload = {
            "type": "game_end",
            "winner": winner_username,
            "results": results_with_points
        }
        
        for player_name in list(game.player_stats.keys()):
            if player_name in connected_players:
                try:
                    await connected_players[player_name].send_text(json.dumps(results_payload))
                except Exception as e:
                    logger.warning(f"Could not send game_end to {player_name}: {e}")

    except Exception as e:
        logger.error(f"An error occurred during finalize_game for game_id {game_id}: {e}", exc_info=True)
    finally:
        await broadcast_stats(connected_players, active_games)


async def send_question_to_player(username: str, game_id: str, active_games: Dict, connected_players: Dict):
    if game_id not in active_games or username not in connected_players:
        return

    game = active_games[game_id]
    player_stats = game.player_stats[username]
    player_stats.current_question_index += 1
    
    q_index = player_stats.current_question_index
    
    if q_index >= QUESTIONS_PER_GAME:
        player_stats.finished = True
        logger.info(f"Player {username} has finished all questions in game {game_id}.")
        await connected_players[username].send_text(json.dumps({
            "type": "player_finished",
            "message": "You've finished! Waiting for other players..."
        }))
        
        all_finished = all(ps.finished for ps in game.player_stats.values())
        if all_finished:
            logger.info(f"All players finished in game {game_id}. Finalizing.")
            await finalize_game(game_id, active_games, connected_players)
        return

    puzzle = game.puzzles[q_index]
    player_stats.question_start_time = datetime.utcnow()

    # Cancel any existing timer task before creating a new one
    if player_stats.timer_task and not player_stats.timer_task.done():
        player_stats.timer_task.cancel()

    # Create a new timer task for the question timeout
    player_stats.timer_task = asyncio.create_task(
        question_timeout_handler(username, game_id, active_games, connected_players)
    )
    
    question_payload = json.dumps({
        "type": "new_question",
        "question": puzzle["question"],
        "question_index": q_index + 1,
        "total_questions": QUESTIONS_PER_GAME,
        "duration": TIME_PER_QUESTION
    })
    
    await connected_players[username].send_text(question_payload)


async def question_timeout_handler(username: str, game_id: str, active_games: Dict, connected_players: Dict):
    try:
        await asyncio.sleep(TIME_PER_QUESTION)
        await handle_timeout(username, game_id, active_games, connected_players)
    except asyncio.CancelledError:
        # Timer was cancelled because player answered in time
        pass


async def handle_timeout(username: str, game_id: str, active_games: Dict, connected_players: Dict):
    if game_id not in active_games or username not in connected_players:
        return

    game = active_games[game_id]
    player_stats = game.player_stats[username]
    q_index = player_stats.current_question_index

    if player_stats.finished or not (0 <= q_index < QUESTIONS_PER_GAME) or player_stats.answered_mask[q_index]:
        return
    player_stats.answered_mask[q_index] = True

    correct_answer = game.puzzles[q_index]["answer"]
    await connected_players[username].send_text(json.dumps({"type": "answer_result", "correct": False, "message": f"Time's up! The answer was: {correct_answer}"}))

    await send_question_to_player(username, game_id, active_games, connected_players)


async def handle_answer(username: str, answer: str, active_games: Dict, connected_players: Dict):
    game_id, game = next(((gid, g) for gid, g in active_games.items() if username in g.players), (None, None))
    if not game: return

    websocket = connected_players.get(username)
    if not websocket: return

    player_stats = game.player_stats[username]
    q_index = player_stats.current_question_index

    if player_stats.finished or not (0 <= q_index < QUESTIONS_PER_GAME) or player_stats.answered_mask[q_index]:
        return
    player_stats.answered_mask[q_index] = True

    # Cancel the timer task if it exists
    if player_stats.timer_task and not player_stats.timer_task.done():
        player_stats.timer_task.cancel()

    correct_answer = game.puzzles[q_index]["answer"]
    is_correct = answer.lower().strip() == correct_answer.lower()

    if is_correct:
        time_taken = (datetime.utcnow() - player_stats.question_start_time).total_seconds()
        player_stats.score += 1
        player_stats.total_time += time_taken
        await websocket.send_text(json.dumps({"type": "answer_result", "correct": True, "message": "Correct!"}))
    else:
        await websocket.send_text(json.dumps({"type": "answer_result", "correct": False, "message": f"Wrong! The answer was: {correct_answer}"}))

    await send_question_to_player(username, game_id, active_games, connected_players)


# --- Matchmaking Logic ---

async def create_and_start_match(category: str, waiting_rooms: Dict, player_to_room: Dict, connected_players: Dict, active_games: Dict):
    if category not in waiting_rooms: return
    room = waiting_rooms.pop(category)
    players_in_room = list(room["players"])
    for p_name in players_in_room:
        if p_name in player_to_room: del player_to_room[p_name]
        
    if len(players_in_room) >= MIN_PLAYERS:
        game_id = f"game_{datetime.now().strftime('%Y%m%d%H%M%S')}_{random.randint(100, 999)}"
        puzzles = random.sample(CATEGORY_PUZZLES.get(category, []), QUESTIONS_PER_GAME)
        if len(puzzles) < QUESTIONS_PER_GAME: 
            logger.error(f"Not enough puzzles for category {category}! Required: {QUESTIONS_PER_GAME}, Found: {len(puzzles)}")
            for p_name in players_in_room:
                if p_name in connected_players: await connected_players[p_name].send_text(json.dumps({ "type": "match_failed", "message": f"Not enough questions in the '{category}' category to start a game." }))
            return

        player_stats = {name: PlayerStats() for name in players_in_room}
        active_games[game_id] = GameSession(players=players_in_room, category=category, puzzles=puzzles, player_stats=player_stats)
        
        logger.info(f"Starting game {game_id} for players: {players_in_room}")
        
        for player_name in players_in_room:
            await send_question_to_player(player_name, game_id, active_games, connected_players)

        await broadcast_stats(connected_players, active_games)
    else:
        for p_name in players_in_room:
            if p_name in connected_players: await connected_players[p_name].send_text(json.dumps({ "type": "match_failed", "message": "Not enough players joined in time." }))


async def start_match_timer(category: str, waiting_rooms: Dict, player_to_room: Dict, connected_players: Dict, active_games: Dict):
    try:
        await asyncio.sleep(WAITING_TIME)
        if category in waiting_rooms:
            await create_and_start_match(category, waiting_rooms, player_to_room, connected_players, active_games)
    except CancelledError:
        logger.info(f"Match timer for '{category}' was cancelled (likely because the room filled up).")
    except Exception as e:
        logger.error(f"Error in match timer for '{category}': {e}", exc_info=True)


async def handle_matchmaking(username: str, websocket: WebSocket, category: str, waiting_rooms: Dict, player_to_room: Dict, connected_players: Dict, active_games: Dict, max_players: int):
    if username in player_to_room: return
    
    room = waiting_rooms.get(category)
    if not room:
        task = asyncio.create_task(start_match_timer(category, waiting_rooms, player_to_room, connected_players, active_games))
        waiting_rooms[category] = {"players": [username], "task": task}
    else:
        if len(room["players"]) < max_players:
            room["players"].append(username)
        else:
            await websocket.send_text(json.dumps({"type": "error", "message": "This room is full."})); return

    player_to_room[username] = category
    current_room_players = waiting_rooms[category]["players"]
    update_payload = json.dumps({ "type": "waiting_update", "player_count": len(current_room_players), "max_players": max_players })
    
    for p_name in current_room_players:
        if p_name in connected_players:
            await connected_players[p_name].send_text(update_payload)
            
    if len(current_room_players) == max_players:
        if "task" in waiting_rooms[category]:
            waiting_rooms[category]["task"].cancel()
        await create_and_start_match(category, waiting_rooms, player_to_room, connected_players, active_games)


# --- Player Cleanup ---

async def cleanup_player(username: str, connected_players: Dict, player_to_room: Dict, waiting_rooms: Dict, active_games: Dict, min_players: int):
    player_was_connected = username in connected_players
    if player_was_connected:
        del connected_players[username]
    
    if username in player_to_room:
        category = player_to_room[username]
        del player_to_room[username]
        if category in waiting_rooms and username in waiting_rooms[category]["players"]:
            room = waiting_rooms[category]
            room["players"].remove(username)
            if not room["players"]:
                if "task" in room: room["task"].cancel()
                del waiting_rooms[category]
            else:
                update_payload = json.dumps({"type": "waiting_update", "player_count": len(room["players"]), "max_players": MAX_PLAYERS})
                for p_name in room["players"]:
                    if p_name in connected_players:
                        await connected_players[p_name].send_text(update_payload)

    for game_id, game in list(active_games.items()):
        if username in game.player_stats:
            game.player_stats[username].finished = True
            if username in game.players:
                game.players.remove(username)
            logger.info(f"Player {username} disconnected from game {game_id}. Marking as finished.")
            
            all_remaining_finished = all(ps.finished for name, ps in game.player_stats.items() if name in game.players)
            
            if len(game.players) < min_players or all_remaining_finished:
                logger.info(f"Game {game_id} ending due to player disconnect or all others finishing.")
                await finalize_game(game_id, active_games, connected_players)

    if player_was_connected:
        await broadcast_stats(connected_players, active_games)