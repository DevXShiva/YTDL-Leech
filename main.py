import os
import asyncio
import yt_dlp
import threading
import subprocess
import time
from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import Message
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

# --- Flask Server ---
web_app = Flask(__name__)
@web_app.route('/')
def health_check(): return "Speed Leech Bot Active", 200
def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host='0.0.0.0', port=port)

# --- Configs ---
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URL = os.getenv("MONGO_URL")
DUMP_CHAT_ID = int(os.getenv("DUMP_CHAT_ID"))

app = Client("leech_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, workers=20)
mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client["leech_db"]
collection = db["tasks"]

# Throttling dictionary to prevent FloodWait
LAST_UPDATE_TIME = {}

# Animations
ANIMATION = ["▰▱▱▱▱", "▰▰▱▱▱", "▰▰▰▱▱", "▰▰▰▰▱", "▰▰▰▰▰"]

# --- Thumbnail Generator ---
def generate_thumbnail(video_path, thumb_path):
    try:
        subprocess.call(['ffmpeg', '-i', video_path, '-ss', '00:00:05.000', '-vframes', '1', thumb_path])
        return thumb_path if os.path.exists(thumb_path) else None
    except: return None

# --- Improved Progress Handler ---
async def progress_ui(current, total, message, status_type, task_id):
    now = time.time()
    # Sirf har 3 second mein message update karein taaki speed fast rahe
    if task_id in LAST_UPDATE_TIME and (now - LAST_UPDATE_TIME[task_id]) < 3:
        return
    
    LAST_UPDATE_TIME[task_id] = now
    
    if total <= 0: return
    percent = current * 100 / total
    
    task_data = await collection.find_one({"_id": task_id})
    idx = task_data.get("idx", 0) if task_data else 0
    
    bar = ANIMATION[idx % len(ANIMATION)]
    text = f"🚀 **{status_type}ing...**\n`{bar}` **{percent:.1f}%**"
    
    try:
        await message.edit_text(text)
        await collection.update_one({"_id": task_id}, {"$inc": {"idx": 1}})
    except: pass

# --- yt-dlp Hook Fix ---
def ytdl_hook(d, loop, msg, tid):
    if d['status'] == 'downloading':
        curr = d.get('downloaded_bytes', 0)
        total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
        # Use run_coroutine_threadsafe to bridge sync hook to async UI
        asyncio.run_coroutine_threadsafe(progress_ui(curr, total, msg, "Download", tid), loop)

@app.on_message(filters.command("yt"))
async def yt_leech(client, message: Message):
    text = message.text.split(None, 1)
    if len(text) < 2:
        return await message.reply("❌ Usage: `/yt -n Name Link` or `/yt Link`")

    content = text[1]
    custom_name = None
    url = content

    if "-n " in content:
        try:
            # Better parsing for -n
            parts = content.split("-n ", 1)[1].split(None, 1)
            custom_name = parts[0]
            url = parts[1]
        except: pass

    status = await message.reply_text("⚡ Initializing Speed Leech...")
    loop = asyncio.get_event_loop()
    task = await collection.insert_one({"idx": 0})
    tid = task.inserted_id

    d_dir = f"downloads/{tid}/"
    if not os.path.exists(d_dir): os.makedirs(d_dir)

    ydl_opts = {
        'format': 'best',
        'outtmpl': f'{d_dir}%(title)s.%(ext)s',
        # Progress hook with loop access
        'progress_hooks': [lambda d: ytdl_hook(d, loop, status, tid)],
        'quiet': True,
        'no_warnings': True
    }

    file_path = None
    try:
        # Step 1: Download
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            original_path = ydl.prepare_filename(info)
            
            if custom_name:
                ext = os.path.splitext(original_path)[1]
                file_path = os.path.join(d_dir, f"{custom_name}{ext}")
                os.rename(original_path, file_path)
            else:
                file_path = original_path

        # Step 2: Thumbnail
        thumb_path = os.path.join(d_dir, "thumb.jpg")
        thumb = generate_thumbnail(file_path, thumb_path)

        # Step 3: Upload
        await status.edit_text("📤 **Uploading to Cloud...**")
        sent_video = await message.reply_video(
            video=file_path,
            thumb=thumb,
            caption=f"✅ **File:** `{os.path.basename(file_path)}`",
            progress=progress_ui,
            progress_args=("Upload", tid)
        )
        
        # Dump to Channel
        await sent_video.copy(DUMP_CHAT_ID, caption=f"👤 **User:** {message.from_user.mention}\n🔗 **Source:** {url}")
        await status.delete()

    except Exception as e:
        await status.edit_text(f"❌ **Error:** `{str(e)}`")
    finally:
        # Clear throttle and cleanup
        if tid in LAST_UPDATE_TIME: del LAST_UPDATE_TIME[tid]
        if file_path and os.path.exists(file_path): os.remove(file_path)
        if os.path.exists(d_dir):
            import shutil
            shutil.rmtree(d_dir)
        await collection.delete_one({"_id": tid})

if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()
    app.run()
