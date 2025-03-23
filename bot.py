import os
import sys
import asyncio
import signal
import psutil
import logging
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Configuration
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
ALLOWED_USERS = [int(uid) for uid in os.getenv('ALLOWED_USERS', '').split(',') if uid]
BOT_PASSWORD = os.getenv('BOT_PASSWORD')

# Store authenticated users and running processes
authenticated_users = set()
user_processes = {}

# Commands that run continuously
CONTINUOUS_COMMANDS = {
    'ping': {'timeout': 30, 'sample_size': 5},  # 30 seconds, show 5 pings
    'tail -f': {'timeout': 60, 'sample_size': 10},  # 60 seconds, show last 10 lines
    'top': {'timeout': 30, 'sample_size': 10},  # 30 seconds, show 10 updates
    'htop': {'timeout': 30, 'sample_size': 10},
    'watch': {'timeout': 30, 'sample_size': 5},
}

# Define signals based on platform
try:
    SIGKILL = signal.SIGKILL
    SIGTERM = signal.SIGTERM
except AttributeError:
    SIGKILL = 9
    SIGTERM = 15

def log(message):
    """Write directly to stderr for immediate feedback."""
    print(message, file=sys.stderr, flush=True)

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
        "4. For continuous commands (ping, tail -f, etc.):\n"
        "   - Output will be streamed every 5 seconds\n"
        "   - Use /stop to end the command\n"
        "5. Open multiple chats for different tasks"
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

def kill_process_tree(pid):
    """Kill a process and all its children."""
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        
        for child in children:
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
                
        parent.terminate()
        
        # Wait for processes to terminate
        _, alive = psutil.wait_procs([parent] + children, timeout=1)
        
        # Force kill if still alive
        for p in alive:
            try:
                p.kill()
            except psutil.NoSuchProcess:
                pass
    except psutil.NoSuchProcess:
        pass

def is_continuous_command(command: str) -> tuple[bool, dict]:
    """Check if a command is continuous and return its settings."""
    cmd_lower = command.lower()
    for cmd, settings in CONTINUOUS_COMMANDS.items():
        if cmd in cmd_lower:
            return True, settings
    return False, {}

async def run_with_timeout(command: str, timeout: int, update: Update) -> None:
    """Run a command with timeout and return periodic snapshots."""
    try:
        # Create process
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT
        )

        # Store process
        user_id = update.effective_user.id
        user_processes[user_id] = process

        # Send initial message
        await update.message.reply_text(
            f"Running command with {timeout}s timeout.\n"
            "Use /stop to end early."
        )

        output_lines = []
        start_time = datetime.now()
        
        while (datetime.now() - start_time).seconds < timeout:
            if process.returncode is not None:
                break

            try:
                line = await asyncio.wait_for(process.stdout.readline(), timeout=1.0)
                if line:
                    output_lines.append(line.decode().strip())
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                await update.message.reply_text(f"Error reading output: {str(e)}")
                break

            # Send periodic updates
            if len(output_lines) >= 5:
                await update.message.reply_text(
                    "```\n" + "\n".join(output_lines[-5:]) + "\n```",
                    parse_mode='Markdown'
                )
                output_lines = []

        # Send any remaining output
        if output_lines:
            await update.message.reply_text(
                "```\n" + "\n".join(output_lines) + "\n```",
                parse_mode='Markdown'
            )

        # Clean up
        try:
            process.terminate()
            await asyncio.sleep(1)
            if process.returncode is None:
                process.kill()
        except:
            pass

        if user_id in user_processes:
            del user_processes[user_id]

        await update.message.reply_text(
            "Command completed. Use the same command again for more output."
        )

    except Exception as e:
        await update.message.reply_text(f"Error executing command: {str(e)}")
        if update.effective_user.id in user_processes:
            del user_processes[update.effective_user.id]

async def execute_shell_command(update: Update, command: str) -> None:
    """Execute a shell command and return the output."""
    try:
        # Remove 'sudo' if user added it
        if command.startswith('sudo '):
            command = command[5:]

        # Convert first word to lowercase for case-insensitive commands
        parts = command.split(maxsplit=1)
        if not parts:
            return

        # Convert command to lowercase and handle paths
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        # Map of common commands to their full paths
        cmd_paths = {
            'ls': '/bin/ls',
            'tail': '/usr/bin/tail',
            'ps': '/usr/bin/ps',
            'df': '/usr/bin/df',
            'htop': '/usr/bin/htop',
            'cat': '/bin/cat',
            'head': '/usr/bin/head',
            'docker': '/usr/bin/docker',
            'systemctl': '/usr/bin/systemctl',
            'journalctl': '/usr/bin/journalctl',
            'ping': '/usr/bin/ping'
        }

        # Commands that need sudo
        sudo_commands = [
            'tail',
            'journalctl',
            'systemctl',
            'docker'
        ]

        # Build the command with proper path and sudo if needed
        if cmd in cmd_paths:
            if cmd in sudo_commands:
                command = f"sudo {cmd_paths[cmd]} {args}"
            else:
                command = f"{cmd_paths[cmd]} {args}"
        else:
            # For other commands, just use lowercase version
            if cmd in sudo_commands:
                command = f"sudo {cmd} {args}"
            else:
                command = f"{cmd} {args}"

        # Special handling for tail command with log files
        if cmd == 'tail' and '/var/log' in args:
            command = f"sudo {cmd_paths['tail']} {args}"

        # Check if this is a continuous command
        is_continuous, settings = is_continuous_command(command)
        if is_continuous:
            await run_with_timeout(
                command,
                settings['timeout'],
                update
            )
        else:
            # For regular commands, just run and return output
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT
            )
            
            stdout, _ = await process.communicate()
            
            output = stdout.decode() if stdout else "Command executed successfully (no output)"
            
            # Split long outputs into chunks
            for i in range(0, len(output), 4000):
                chunk = output[i:i+4000]
                await update.message.reply_text(f"```\n{chunk}\n```", parse_mode='Markdown')

    except Exception as e:
        await update.message.reply_text(f"Error executing command: {str(e)}")

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Stop running command for the user."""
    if not is_authenticated(update):
        return

    user_id = update.effective_user.id
    if user_id in user_processes:
        process = user_processes[user_id]
        try:
            process.terminate()
            await asyncio.sleep(1)
            if process.returncode is None:
                process.kill()
            del user_processes[user_id]
            await update.message.reply_text("Command stopped.")
        except Exception as e:
            await update.message.reply_text(f"Error stopping command: {str(e)}")
    else:
        await update.message.reply_text("No running command to stop.")

async def handle_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle commands that start with /."""
    if not is_authenticated(update):
        return

    command = update.message.text[1:]  # Remove the leading /
    if command.split()[0].lower() in ('start', 'auth', 'help', 'stop'):
        return

    # Log command execution
    log_command(update.effective_user, command)
    await execute_shell_command(update, command)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle regular text messages as commands."""
    if not is_authenticated(update):
        return

    command = update.message.text.strip()
    if not command:
        return

    # Log command execution
    log_command(update.effective_user, command)
    await execute_shell_command(update, command)

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
        asyncio.create_task(update.message.reply_text("Please authenticate first using /auth <password>"))
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

    # Add command handlers for specific commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("auth", auth))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("stop", stop_command))
    
    # Handle all other messages
    application.add_handler(MessageHandler(filters.COMMAND, handle_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Start the Bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main() 