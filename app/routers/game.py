# app/routers/game.py

from fastapi import APIRouter
from app.database import db
from app.puzzles import CATEGORY_PUZZLES
from .websocket import active_games, connected_players, waiting_rooms

router = APIRouter()

@router.get("/api/leaderboard")
async def get_leaderboard():
    """Returns the top 10 users by score."""
    users = await db.users.find(
        {},
        {"_id": 0, "username": 1, "score": 1}
    ).sort("score", -1).limit(10).to_list(10)
    return users

@router.get("/api/categories")
async def get_categories():
    """Returns all available categories and their question counts."""
    categories_info = {
        category: {
            "name": category.replace("_", " ").title(),
            "count": len(puzzles)
        } for category, puzzles in CATEGORY_PUZZLES.items()
    }
    return {"categories": categories_info}

@router.get("/api/stats")
async def get_stats():
    """Returns general statistics about the application."""
    # Calculate total waiting players from the new 'waiting_rooms' structure
    total_waiting = sum(len(room.get("players", [])) for room in waiting_rooms.values())
    
    total_users = await db.users.count_documents({})
    total_questions = sum(len(puzzles) for puzzles in CATEGORY_PUZZLES.values())
    return {
        "total_users": total_users,
        "active_games": len(active_games),
        "connected_players": len(connected_players),
        "waiting_players": total_waiting,
        "total_categories": len(CATEGORY_PUZZLES),
        "total_questions": total_questions
    }