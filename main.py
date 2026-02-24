import os
import asyncio
import yt_dlp
import threading
import subprocess
import time
from flask import Flask
from pyrogram import Client, filters, idle
from pyrogram.types import Message
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

# --- Flask Server ---
web_app = Flask(__name__)
@web_app.route('/')
def health_check(): return "Bot is Alive!", 200

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

LAST_UPDATE_TIME = {}
ANIMATION = ["▰▱▱▱▱", "▰▰▱▱▱", "▰▰▰▱▱", "▰▰▰▰▱", "▰▰▰▰▰"]

# --- Utility Functions ---
def generate_thumbnail(video_path, thumb_path):
    try:
        # Added -update 1 and -frames:v 1 for single image capture
        subprocess.call(['ffmpeg', '-i', video_path, '-ss', '00:00:05.000', '-vframes', '1', '-update', '1', thumb_path])
        return thumb_path if os.path.exists(thumb_path) else None
    except: return None

async def progress_ui(current, total, message, status_type, task_id):
    now = time.time()
    if task_id in LAST_UPDATE_TIME and (now - LAST_UPDATE_TIME[task_id]) < 4:
        return
    LAST_UPDATE_TIME[task_id] = now
    
    # Handle cases where total might be None or 0 (Common in m3u8)
    if not total or total == 0:
        percent = 0
    else:
        percent = current * 100 / total
    
    task_data = await collection.find_one({"_id": task_id})
    idx = task_data.get("idx", 0) if task_data else 0
    bar = ANIMATION[idx % len(ANIMATION)]
    
    try:
        await message.edit_text(f"🚀 **{status_type}ing...**\n`{bar}` **{percent:.1f}%**")
        await collection.update_one({"_id": task_id}, {"$inc": {"idx": 1}})
    except: pass

def ytdl_hook(d, loop, msg, tid):
    if d['status'] == 'downloading':
        curr = d.get('downloaded_bytes', 0)
        # Check both total_bytes and estimate for m3u8
        total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
        asyncio.run_coroutine_threadsafe(progress_ui(curr, total, msg, "Download", tid), loop)

# --- Handlers ---
@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply_text("✅ **Bot is Online!**\nUse `/yt Link` or `/yt -n Name Link` to leech.")

@app.on_message(filters.command("yt"))
async def yt_leech(client, message: Message):
    text_parts = message.text.split(None, 1)
    if len(text_parts) < 2:
        return await message.reply("❌ Usage: `/yt -n Name Link` or `/yt Link`")
    
    raw_text = text_parts[1]
    custom_name, url = None, raw_text
    
    # Improved Parsing
    if "-n " in raw_text:
        try:
            cmd_data = raw_text.split("-n ", 1)[1]
            custom_name = cmd_data.split(None, 1)[0]
            url = cmd_data.split(None, 1)[1]
        except: pass

    status = await message.reply_text("⚡ Preparing...")
    loop = asyncio.get_event_loop()
    task = await collection.insert_one({"idx": 0})
    tid = task.inserted_id
    d_dir = f"downloads/{tid}/"
    if not os.path.exists(d_dir): os.makedirs(d_dir)

    try:
        ydl_opts = {
            'format': 'best', 
            'outtmpl': f'{d_dir}%(title)s.%(ext)s', 
            'progress_hooks': [lambda d: ytdl_hook(d, loop, status, tid)],
            'quiet': True,
            'noprogress': False # Ensure hooks are triggered
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            path = ydl.prepare_filename(info)
            if custom_name:
                ext = os.path.splitext(path)[1]
                new_path = os.path.join(d_dir, f"{custom_name}{ext}")
                os.rename(path, new_path)
                path = new_path

        thumb = generate_thumbnail(path, os.path.join(d_dir, "thumb.jpg"))
        await status.edit_text("📤 Uploading...")
        
        # FIX: Corrected progress_args structure
        sent = await message.reply_video(
            video=path, 
            thumb=thumb, 
            caption=f"✅ `{os.path.basename(path)}`", 
            progress=progress_ui, 
            progress_args=("Upload", tid)
        )
        
        await sent.copy(DUMP_CHAT_ID, caption=f"👤 {message.from_user.mention}\n🔗 {url}")
        await status.delete()

    except Exception as e:
        # FIX: Handle 'NoneType' write error by catching it or logging
        await status.edit_text(f"❌ Error: `{str(e)}`")
    finally:
        if tid in LAST_UPDATE_TIME: del LAST_UPDATE_TIME[tid]
        if os.path.exists(d_dir):
            import shutil
            shutil.rmtree(d_dir)
        await collection.delete_one({"_id": tid})

async def start_bot():
    threading.Thread(target=run_web_server, daemon=True).start()
    await app.start()
    await idle()
    await app.stop()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(start_bot())
