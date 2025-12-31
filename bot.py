import os
import time
import math
from telethon import TelegramClient, events
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
# --- CONFIGURATION ---
API_ID = '33165804'       # From my.telegram.org
API_HASH = '6f81146001e034c47b5362977e6bbb76'   # From my.telegram.org
BOT_TOKEN = '7832672061:AAHmkYSdBIRv6ScmzMpI2jof8FT9fL9QraQ' # From @BotFather
DRIVE_FOLDER_ID = '1be2ctX-gUrCbu3LeLL05ZClIVZgar5xg' # The ID part of your Drive Folder URL

TOKEN_FILE = 'token.json'
CREDENTIALS_FILE = 'credentials.json'

if os.path.exists(TOKEN_FILE):
    creds = Credentials.from_authorized_user_file(TOKEN_FILE, ['https://www.googleapis.com/auth/drive'])

if not creds or not creds.valid:
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())
    else:
        print("❌ Error: token.json is missing. Run get_token.py first.")
        exit()

drive_service = build('drive', 'v3', credentials=creds)

# --- BOT SETUP ---
bot = TelegramClient('bot_session', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# --- HELPERS FOR FORMATTING ---
def human_readable_size(size, decimal_places=2):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.{decimal_places}f}{unit}"
        size /= 1024.0
    return f"{size:.{decimal_places}f}PB"

def get_progress_bar_string(current, total):
    percentage = current / total
    finished_length = int(percentage * 10)
    # Using special block characters for the bar
    bar = "■" * finished_length + "□" * (10 - finished_length)
    return f"[{bar}]"

# --- PROGRESS CALLBACK ---
# Updates message only every 5 seconds to prevent flood errors
last_update_time = 0

async def progress_callback(current, total, event, title, status_type):
    global last_update_time
    now = time.time()
    
    if now - last_update_time >= 5 or current == total: # Update every 5s or when done
        percentage = (current / total) * 100
        bar = get_progress_bar_string(current, total)
        current_size = human_readable_size(current)
        total_size = human_readable_size(total)
        
        # Fancy Monospace Layout
        text = (
            f"**{status_type}**\n"
            f"`📂 {title}`\n"
            f"`{bar} {percentage:.2f}%`\n"
            f"`💾 {current_size} / {total_size}`"
        )
        
        try:
            await event.edit(text)
            last_update_time = now
        except:
            pass 

# --- START COMMAND ---
@bot.on(events.NewMessage(pattern='/start'))
async def start(event):
    await event.reply("👋 **Ready!**\nSend me a file to start uploading.")

# --- FILE HANDLER ---
@bot.on(events.NewMessage)
async def handle_file(event):
    if event.file and not event.text.startswith('/'):
        sender = await event.get_sender()
        user_id = sender.id

        # 1. Ask for Title
        async with bot.conversation(user_id) as conv:
            await conv.send_message("📝 **What should be the title?**")
            response = await conv.get_response()
            user_title = response.text.strip()
            
            # Auto-Extension Logic
            original_ext = event.file.ext if event.file.ext else ""
            if not user_title.lower().endswith(original_ext.lower()):
                final_filename = f"{user_title}{original_ext}"
            else:
                final_filename = user_title

            # Initial Status Message
            status_msg = await conv.send_message(f"⏳ Please wait...")

            # 2. Download Locally
            global last_update_time
            last_update_time = 0 
            
            file_path = await bot.download_media(
                event.message, 
                file=final_filename,
                progress_callback=lambda c, t: progress_callback(c, t, status_msg, final_filename, "⬇️ Downloading...")
            )
            
            # 3. Upload to Drive
            file_metadata = {
                'name': final_filename,
                'parents': [DRIVE_FOLDER_ID]
            }
            
            media = MediaFileUpload(file_path, resumable=True, chunksize=5*1024*1024)
            
            try:
                request = drive_service.files().create(
                    body=file_metadata,
                    media_body=media,
                    fields='id, webViewLink'
                )
                
                response = None
                while response is None:
                    status, response = request.next_chunk()
                    if status:
                        await progress_callback(status.resumable_progress, status.total_size, status_msg, final_filename, "⬆️ Uploading to Drive...")

                # 4. Success
                file_link = response.get('webViewLink')
                await status_msg.edit(
                    f"✅ **Mission Complete**\n\n"
                    f"📂 **File:** `{final_filename}`\n"
                    f"🔗 **Link:**\n`{file_link}`"
                )

            except Exception as e:
                await status_msg.edit(f"❌ **Error:**\n`{str(e)}`")
            
            finally:
                if os.path.exists(file_path):
                    os.remove(file_path)

print("Bot is running...")
bot.run_until_disconnected()