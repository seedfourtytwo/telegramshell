import os
import asyncio
import signal
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

# Load environment variables
load_dotenv()

# Configuration
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
ALLOWED_USERS = [int(uid) for uid in os.getenv('ALLOWED_USERS', '').split(',') if uid]
BOT_PASSWORD = os.getenv('BOT_PASSWORD')

# Store authenticated users and running processes
authenticated_users = set()
user_processes = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
    if update.effective_user.id not in ALLOWED_USERS:
        await update.message.reply_text("Unauthorized access denied.")
        return
    
    await update.message.reply_text(
        "Welcome to Secure Shell Bot!\n"
        "Please authenticate using /auth <password>\n\n"
        "Tips:\n"
        "1. Just type commands directly: ls -la\n"
        "2. Commands are case-insensitive\n"
        "3. Use /stop to end running commands\n"
        "4. Open multiple chats for different tasks"
    )

async def auth(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle authentication."""
    if update.effective_user.id not in ALLOWED_USERS:
        await update.message.reply_text("Unauthorized access denied.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /auth <password>")
        return

    if context.args[0] == BOT_PASSWORD:
        authenticated_users.add(update.effective_user.id)
        await update.message.reply_text("Authentication successful! You can now run commands directly.")
    else:
        await update.message.reply_text("Invalid password.")

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Stop running command for the user."""
    if not is_authenticated(update):
        return

    user_id = update.effective_user.id
    if user_id in user_processes:
        process = user_processes[user_id]
        try:
            process.terminate()
            process.kill()  # Force kill if terminate doesn't work
            del user_processes[user_id]
            await update.message.reply_text("Command stopped.")
        except Exception as e:
            await update.message.reply_text(f"Error stopping command: {str(e)}")
    else:
        await update.message.reply_text("No running command to stop.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle any message as a potential command."""
    if not is_authenticated(update):
        return

    text = update.message.text
    if not text:
        return

    # Convert first word to lowercase to handle phone capitalization
    parts = text.split(maxsplit=1)
    if len(parts) > 0:
        # Convert first word to lowercase
        parts[0] = parts[0].lower()
        # Remove leading / if present
        if parts[0].startswith('/'):
            parts[0] = parts[0][1:]
        text = ' '.join(parts)

    # Skip actual commands
    if text.lower().startswith(('start', 'auth', 'help', 'stop')):
        return

    # Log command execution
    log_command(update.effective_user, text)
    
    try:
        process = await asyncio.create_subprocess_shell(
            text,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        # Store process for potential stopping
        user_id = update.effective_user.id
        user_processes[user_id] = process
        
        stdout, stderr = await process.communicate()
        
        # Clear process from storage after it's done
        if user_id in user_processes:
            del user_processes[user_id]
        
        output = stdout.decode() if stdout else stderr.decode()
        if not output:
            output = "Command executed successfully (no output)"
            
        # Split long outputs into chunks to avoid Telegram message length limits
        for i in range(0, len(output), 4000):
            chunk = output[i:i+4000]
            await update.message.reply_text(f"```\n{chunk}\n```", parse_mode='Markdown')
            
    except Exception as e:
        await update.message.reply_text(f"Error executing command: {str(e)}")
        if update.effective_user.id in user_processes:
            del user_processes[update.effective_user.id]

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show help message."""
    if not is_authenticated(update):
        return
        
    await update.message.reply_text(
        "Usage Examples:\n"
        "- List files: ls -la\n"
        "- Monitor log: tail -f /var/log/syslog\n"
        "- System info: htop\n"
        "- Stop command: /stop\n"
        "\nTips:\n"
        "- Commands are case-insensitive\n"
        "- Use /stop to end running commands\n"
        "- Open multiple chats for different tasks"
    )

def is_authenticated(update: Update) -> bool:
    """Check if user is authenticated."""
    if update.effective_user.id not in authenticated_users:
        update.message.reply_text("Please authenticate first using /auth <password>")
        return False
    return True

def log_command(user, command: str) -> None:
    """Log command execution to file."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] User {user.id} ({user.username}): {command}\n"
    
    with open("command_log.txt", "a") as log_file:
        log_file.write(log_entry)

def main() -> None:
    """Start the bot."""
    # Create the Application
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("auth", auth))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("stop", stop_command))
    
    # Handle all messages (with or without /)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.COMMAND, handle_message))

    # Start the Bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main() 