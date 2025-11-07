# app/routers/auth.py
from fastapi import APIRouter, HTTPException, status
from datetime import datetime
import logging

from app.database import db, serialize_mongo_doc
from app.models import UserCreate, UserLogin
from app.security import PasswordHasher

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/api/signup", status_code=status.HTTP_201_CREATED)
async def signup(user: UserCreate):
    """Handles user registration."""
    # Check if passwords match
    if user.password != user.confirmPassword:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Passwords do not match",
        )
        
    # Check if user already exists
    existing_user = await db.users.find_one({"username": user.username})
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already exists",
        )

    # Hash the password before storing
    hashed_password = PasswordHasher.get_password_hash(user.password)

    user_dict = {
        "username": user.username,
        "email": user.email,
        "hashed_password": hashed_password,
        "score": 0,
        "created_at": datetime.utcnow(),
    }
    
    await db.users.insert_one(user_dict)

    # Don't send the password hash back to the client
    user_dict.pop("hashed_password")
    
    return {"message": "User created successfully", "user": serialize_mongo_doc(user_dict)}


@router.post("/api/login")
async def login(user: UserLogin):
    """Handles user authentication."""
    logger.info(f"Login attempt for user: {user.username}")
    
    # Find user in the database
    db_user = await db.users.find_one({"username": user.username})
    
    # 1. Check if the user exists
    # 2. Verify the provided password against the stored hash
    if not db_user or not PasswordHasher.verify_password(user.password, db_user.get("hashed_password", "")):
        logger.warning(f"Login failed for user: {user.username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )

    # Update last login time
    await db.users.update_one(
        {"username": user.username},
        {"$set": {"last_login": datetime.utcnow()}}
    )
    
    # Prepare user data to send back (without the password hash)
    user_to_return = db_user
    user_to_return.pop("hashed_password", None)
    
    return {"message": "Login successful", "user": serialize_mongo_doc(user_to_return)}