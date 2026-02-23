import os
import asyncio
import yt_dlp
import threading
from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import Message
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# --- Flask Server for Render Health Check ---
web_app = Flask(__name__)

@web_app.route('/')
def health_check():
    return "Bot is running perfectly!", 200

def run_web_server():
    # Render default port 10000 use karta hai
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host='0.0.0.0', port=port)

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

async def progress_callback(current, total, message: Message, status_type: str, task_id):
    if total == 0: return
    percent = current * 100 / total
    
    task_data = await collection.find_one({"_id": task_id})
    if not task_data: return

    frame_index = task_data.get("frame_index", 0)
    emoji_list = DOWNLOAD_EMOJIS if status_type == "Download" else UPLOAD_EMOJIS
    prefix = "⬇️" if status_type == "Download" else "⬆️"
    
    current_emoji = emoji_list[frame_index % len(emoji_list)]
    text = f"{prefix} **{status_type}ing:** {current_emoji} `{percent:.1f}%`"
    
    try:
        await message.edit_text(text)
        await collection.update_one({"_id": task_id}, {"$set": {"frame_index": (frame_index + 1)}})
    except:
        pass

@app.on_message(filters.command("start"))
async def start_command(client, message: Message):
    await message.reply_text("👋 Hello! Send me a link to leech. I'll handle the rest.")

@app.on_message(filters.text & ~filters.command(["start"]))
async def leech_handler(client, message: Message):
    url = message.text
    status_message = await message.reply_text("🔎 Processing link...")

    # DB Entry
    task = await collection.insert_one({"user_id": message.from_user.id, "frame_index": 0})
    task_id = task.inserted_id

    download_dir = f"downloads/{task_id}/"
    if not os.path.exists(download_dir): os.makedirs(download_dir)

    ydl_opts = {
        'format': 'best',
        'outtmpl': f'{download_dir}%(title)s.%(ext)s',
        'noplaylist': True,
        'progress_hooks': [lambda d: asyncio.create_task(
            progress_callback(d['downloaded_bytes'], d['total_bytes'], status_message, "Download", task_id)
            if d['status'] == 'downloading' and 'total_bytes' in d else None
        )],
    }
    
    file_path = None
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            await status_message.edit_text("📥 Starting Download...")
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)
            
        await status_message.edit_text("⬆️ Starting Upload...")
        await message.reply_video(
            video=file_path,
            caption=f"✅ **Leeched Successfully!**\n\n`{info.get('title')}`",
            progress=progress_callback,
            progress_args=(status_message, "Upload", task_id)
        )
        await status_message.delete()

    except Exception as e:
        await message.reply_text(f"❌ Error: {str(e)}")
    finally:
        if file_path and os.path.exists(file_path): os.remove(file_path)
        if os.path.exists(download_dir): os.rmdir(download_dir)
        await collection.delete_one({"_id": task_id})

if __name__ == "__main__":
    # Web server ko background thread mein chalana zaroori hai
    threading.Thread(target=run_web_server, daemon=True).start()
    print("Bot is starting...")
    app.run()
