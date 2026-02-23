import os
import asyncio
import yt_dlp
import threading
from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import Message
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

web_app = Flask(__name__)

@web_app.route('/')
def health_check():
    return "Bot is running!", 200

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host='0.0.0.0', port=port)

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URL = os.getenv("MONGO_URL")

app = Client("leech_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client["leech_db"]
collection = db["tasks"]

DOWNLOAD_EMOJIS = ["▰▱▱▱▱▱▱▱▱▱", "▰▰▱▱▱▱▱▱▱▱", "▰▰▰▱▱▱▱▱▱▱", "▰▰▰▰▱▱▱▱▱▱", "▰▰▰▰▰▱▱▱▱▱",
                   "▰▰▰▰▰▰▱▱▱▱", "▰▰▰▰▰▰▰▱▱▱", "▰▰▰▰▰▰▰▰▱▱", "▰▰▰▰▰▰▰▰▰▱", "▰▰▰▰▰▰▰▰▰▰"]
UPLOAD_EMOJIS = ["■□□□□", "■■□□□", "■■■□□", "■■■■□", "■■■■■"]

# --- Helper for Progress Logic ---
async def update_progress_ui(current, total, message: Message, status_type: str, task_id):
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
        await collection.update_one({"_id": task_id}, {"$inc": {"frame_index": 1}})
    except:
        pass

# --- Sync Wrapper for yt-dlp ---
def yt_dlp_hook(d, loop, status_message, task_id):
    if d['status'] == 'downloading' and 'total_bytes' in d:
        # Async function ko sync hook se call karne ka sahi tarika
        asyncio.run_coroutine_threadsafe(
            update_progress_ui(d['downloaded_bytes'], d['total_bytes'], status_message, "Download", task_id), 
            loop
        )

# --- Pyrogram Progress Handler ---
async def pyrogram_progress(current, total, status_message, task_id):
    await update_progress_ui(current, total, status_message, "Upload", task_id)

@app.on_message(filters.command("start"))
async def start_command(client, message: Message):
    await message.reply_text("👋 Bot active! Send me an m3u8 link.")

@app.on_message(filters.text & ~filters.command(["start"]))
async def leech_handler(client, message: Message):
    url = message.text
    status_message = await message.reply_text("🔎 Processing...")
    loop = asyncio.get_event_loop()

    # DB Entry
    task = await collection.insert_one({"user_id": message.from_user.id, "frame_index": 0})
    task_id = task.inserted_id

    download_dir = f"downloads/{task_id}/"
    if not os.path.exists(download_dir): os.makedirs(download_dir)

    ydl_opts = {
        'format': 'best',
        'outtmpl': f'{download_dir}%(title)s.%(ext)s',
        'noplaylist': True,
        'progress_hooks': [lambda d: yt_dlp_hook(d, loop, status_message, task_id)],
    }
    
    file_path = None
    try:
        # DOWNLOAD
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            await status_message.edit_text("📥 Starting Download...")
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)
            
        # UPLOAD
        await status_message.edit_text("⬆️ Starting Upload...")
        await message.reply_video(
            video=file_path,
            caption=f"✅ **Leeched!**\n\n`{info.get('title')}`",
            progress=pyrogram_progress, # Correct coroutine pass
            progress_args=(status_message, task_id)
        )
        await status_message.delete()

    except Exception as e:
        await message.reply_text(f"❌ Error: {str(e)}")
    finally:
        if file_path and os.path.exists(file_path): os.remove(file_path)
        if os.path.exists(download_dir): os.rmdir(download_dir)
        await collection.delete_one({"_id": task_id})

if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()
    app.run()
