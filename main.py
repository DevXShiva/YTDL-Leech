import os
import asyncio
import yt_dlp
from pyrogram import Client, filters
from pyrogram.types import Message
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

# Load environment variables for local testing
load_dotenv()

# --- Environment Variables ---
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URL = os.getenv("MONGO_URL")

# --- Clients ---
app = Client("leech_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client["leech_db"]
collection = db["tasks"]

# --- Progress Bar Animation ---
DOWNLOAD_EMOJIS = ["▰▱▱▱▱▱▱▱▱▱", "▰▰▱▱▱▱▱▱▱▱", "▰▰▰▱▱▱▱▱▱▱", "▰▰▰▰▱▱▱▱▱▱", "▰▰▰▰▰▱▱▱▱▱",
                   "▰▰▰▰▰▰▱▱▱▱", "▰▰▰▰▰▰▰▱▱▱", "▰▰▰▰▰▰▰▰▱▱", "▰▰▰▰▰▰▰▰▰▱", "▰▰▰▰▰▰▰▰▰▰"]
UPLOAD_EMOJIS = ["■□□□□", "■■□□□", "■■■□□", "■■■■□", "■■■■■"]

# This function will update the progress message
async def progress_callback(current, total, message: Message, status_type: str, task_id):
    percent = current * 100 / total
    
    # Get the current animation frame from MongoDB
    task_data = await collection.find_one({"_id": task_id})
    if not task_data: # If task is deleted, stop updating
        return

    frame_index = task_data.get("frame_index", 0)
    
    if status_type == "Download":
        emoji_list = DOWNLOAD_EMOJIS
        prefix_emoji = "⬇️"
    else: # Upload
        emoji_list = UPLOAD_EMOJIS
        prefix_emoji = "⬆️"
    
    current_emoji = emoji_list[frame_index % len(emoji_list)]
    
    text = f"{prefix_emoji} **{status_type}ing:** {current_emoji} `{percent:.1f}%`"
    
    try:
        await message.edit_text(text)
        # Update frame index in MongoDB for next iteration
        await collection.update_one({"_id": task_id}, {"$set": {"frame_index": (frame_index + 1) % len(emoji_list)}})
    except Exception as e:
        # Avoid flood waits or deleted messages
        if "MESSAGE_NOT_MODIFIED" not in str(e):
            print(f"Error updating progress message: {e}")
        pass # Silently pass if message can't be edited

@app.on_message(filters.command("start"))
async def start_command(client, message: Message):
    await message.reply_text("Hello! Send me a link to leech. I support m3u8, YouTube, etc.")

@app.on_message(filters.text & ~filters.command(["start"]))
async def leech_handler(client, message: Message):
    url = message.text
    status_message = await message.reply_text("🔎 Processing link...")

    # MongoDB entry for tracking and animation
    task_data = {"user_id": message.from_user.id, "url": url, "status": "pending", "frame_index": 0}
    task = await collection.insert_one(task_data)
    task_id = task.inserted_id # MongoDB's ObjectId

    # Create a unique download directory for each task
    download_dir = f"downloads/{task_id}/"
    if not os.path.exists(download_dir):
        os.makedirs(download_dir)

    # yt-dlp Options
    ydl_opts = {
        'format': 'best',
        'outtmpl': f'{download_dir}%(title)s.%(ext)s',
        'noplaylist': True,
        'progress_hooks': [lambda d: asyncio.create_task(
            progress_callback(d['downloaded_bytes'], d['total_bytes'], status_message, "Download", task_id)
            if d['status'] == 'downloading' and 'total_bytes' in d else None
        )],
    }
    
    file_path = None # Initialize file_path
    
    try:
        # Download
        await collection.update_one({"_id": task_id}, {"$set": {"status": "downloading"}})
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)
            title = info.get('title', 'Video')
            
        # Upload
        await collection.update_one({"_id": task_id}, {"$set": {"status": "uploading", "frame_index": 0}}) # Reset frame index for upload animation
        await status_message.edit_text("⬆️ **Uploading to Telegram:** `0.0%`") # Initial upload message
        
        await message.reply_video(
            video=file_path,
            caption=f"✅ **Leeched:** `{title}`\n\n**Source:** `{url}`",
            progress=progress_callback,
            progress_args=(status_message, "Upload", task_id)
        )

        await status_message.delete() # Delete the animated status message

    except Exception as e:
        error_message = f"❌ Error: {str(e)}"
        print(error_message) # Log the error
        try:
            await status_message.edit_text(error_message)
        except:
            await message.reply_text(error_message) # If status_message already deleted

    finally:
        # Cleanup: Delete files and database entry
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
        if os.path.exists(download_dir):
            os.rmdir(download_dir)
        
        await collection.delete_one({"_id": task_id})
