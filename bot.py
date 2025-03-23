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
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr
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
user_tasks = {}

def is_continuous_command(command: str) -> bool:
    """Check if a command is expected to run continuously."""
    continuous_commands = ['ping', 'tail -f', 'top', 'htop', 'watch']
    return any(cmd in command.lower() for cmd in continuous_commands)

async def read_stream(stream, callback):
    """Read from a stream and call callback for each line."""
    try:
        while True:
            line = await stream.readline()
            if not line:  # EOF
                break
            await callback(line.decode().strip())
    except asyncio.CancelledError:
        print("Stream reading was cancelled", file=sys.stderr, flush=True)
        raise

async def handle_continuous_command(command: str, update: Update) -> None:
    """Handle a continuous command with real-time output."""
    print(f"Starting continuous command: {command}", file=sys.stderr, flush=True)
    
    user_id = update.effective_user.id
    
    # Kill any existing process and task
    if user_id in user_processes:
        print(f"Killing existing process for user {user_id}", file=sys.stderr, flush=True)
        try:
            process = user_processes[user_id]
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            del user_processes[user_id]
        except:
            pass
        
    if user_id in user_tasks:
        print(f"Cancelling existing task for user {user_id}", file=sys.stderr, flush=True)
        try:
            task = user_tasks[user_id]
            task.cancel()
            await task  # Wait for task to be cancelled
            del user_tasks[user_id]
        except:
            pass

    try:
        # Create process
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            preexec_fn=os.setsid
        )
        print(f"Process created with PID: {process.pid}", file=sys.stderr, flush=True)
        
        user_processes[user_id] = process
        
        # Send initial message
        msg = await update.message.reply_text(
            "Running continuous command. Output will be streamed.\n"
            "Use /stop to end the command."
        )

        # Create callback for output
        async def handle_output(line):
            try:
                await update.message.reply_text(f"`{line}`", parse_mode='Markdown')
                print(f"Sent output: {line}", file=sys.stderr, flush=True)
            except Exception as e:
                print(f"Error sending message: {e}", file=sys.stderr, flush=True)

        # Start reading streams in the background
        stdout_task = asyncio.create_task(read_stream(process.stdout, handle_output))
        stderr_task = asyncio.create_task(read_stream(process.stderr, handle_output))
        
        # Store tasks
        combined_task = asyncio.gather(stdout_task, stderr_task)
        user_tasks[user_id] = combined_task
        
        try:
            # Wait for either process to complete or tasks to finish
            done, pending = await asyncio.wait(
                [process.wait(), combined_task],
                return_when=asyncio.FIRST_COMPLETED
            )
            
            # Cancel any pending tasks
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                
            print(f"Process completed with return code: {process.returncode}", file=sys.stderr, flush=True)
            
        except asyncio.CancelledError:
            print("Task was cancelled", file=sys.stderr, flush=True)
            raise
        
    except Exception as e:
        print(f"Error in continuous command: {str(e)}", file=sys.stderr, flush=True)
        await update.message.reply_text(f"Error: {str(e)}")
    finally:
        # Clean up
        if user_id in user_processes:
            try:
                process = user_processes[user_id]
                if process.returncode is None:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                print(f"Killed process for user {user_id}", file=sys.stderr, flush=True)
            except:
                pass
            del user_processes[user_id]
        
        if user_id in user_tasks:
            try:
                task = user_tasks[user_id]
                task.cancel()
                await task  # Wait for task to be cancelled
                print(f"Cancelled task for user {user_id}", file=sys.stderr, flush=True)
            except:
                pass
            del user_tasks[user_id]

async def execute_shell_command(update: Update, command: str) -> None:
    """Execute a shell command and return the output."""
    print(f"Executing command: {command}", file=sys.stderr, flush=True)
    
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
            if cmd in sudo_commands:
                command = f"sudo {cmd} {args}"
            else:
                command = f"{cmd} {args}"

        # Special handling for tail command with log files
        if cmd == 'tail' and '/var/log' in args:
            command = f"sudo {cmd_paths['tail']} {args}"

        print(f"Final command: {command}", file=sys.stderr, flush=True)

        # Check if this is a continuous command
        if is_continuous_command(command):
            print("Handling as continuous command", file=sys.stderr, flush=True)
            await handle_continuous_command(command, update)
            return

        # For regular commands, just run and return output
        print("Handling as regular command", file=sys.stderr, flush=True)
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
        print(f"Error executing command: {str(e)}", file=sys.stderr, flush=True)
        await update.message.reply_text(f"Error executing command: {str(e)}")

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Stop running command for the user."""
    if not is_authenticated(update):
        return

    user_id = update.effective_user.id
    stopped = False

    if user_id in user_processes:
        try:
            process = user_processes[user_id]
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            del user_processes[user_id]
            stopped = True
            print(f"Killed process for user {user_id}", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"Error killing process: {str(e)}", file=sys.stderr, flush=True)

    if user_id in user_tasks:
        try:
            task = user_tasks[user_id]
            task.cancel()
            del user_tasks[user_id]
            stopped = True
            print(f"Cancelled task for user {user_id}", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"Error cancelling task: {str(e)}", file=sys.stderr, flush=True)

    if stopped:
        await update.message.reply_text("Command stopped.")
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