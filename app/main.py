# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging
from dotenv import load_dotenv

from app.database import client, db
from app.routers import auth, game, websocket

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="MindMaze API", version="1.1.0")

# ✅ Updated CORS Allowed Origins
origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "https://frontend-wx0b.onrender.com",  # ✅ Render Frontend URL
]

# ✅ Apply CORS Globally
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ Corrected Router Prefixes
app.include_router(auth.router)
app.include_router(game.router)
app.include_router(websocket.router)

# Application Lifecycle Events
@app.on_event("startup")
async def startup_event():
    """Actions to perform on application startup."""
    try:
        await client.admin.command('ping')
        logger.info("✅ Successfully connected to MongoDB Atlas!")
        await db.users.create_index("username", unique=True)
        logger.info("✅ Database indexes have been ensured.")
    except Exception as e:
        logger.error(f"❌ Failed to connect to MongoDB Atlas: {e}")
        raise

@app.on_event("shutdown")
async def shutdown_event():
    """Actions to perform on application shutdown."""
    client.close()
    logger.info("✅ MongoDB connection has been closed.")

# Root Endpoint
@app.get("/")
async def root():
    """Root endpoint to check if the API is running."""
    return {"message": "Welcome to the MindMaze API!", "status": "online"}


