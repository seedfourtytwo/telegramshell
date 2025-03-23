import os
import asyncio
import signal
import psutil
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

# Commands that are known to run continuously
CONTINUOUS_COMMANDS = [
    'ping',           # Network connectivity testing
    'tail -f',        # File monitoring
    'top',           # Process monitoring
    'htop',          # Interactive process monitoring
    'watch',         # Periodic command execution
    'tcpdump',       # Network packet capture
    'iotop',         # I/O monitoring
    'iostat',        # I/O statistics
    'vmstat',        # Virtual memory statistics
    'netstat',       # Network statistics
    'ss',            # Socket statistics
    'nload',         # Network load monitor
    'iftop',         # Network bandwidth monitor
    'nethogs',       # Per-process network monitor
    'atop',          # System and process monitor
    'powertop',      # Power consumption monitor
    'journalctl -f', # System log monitoring
    'dstat',         # System resource statistics
    'mpstat',        # Processor statistics
    'perf',          # Performance monitoring
    'strace',        # System call tracing
    'docker logs -f', # Docker container log following
    'kubectl logs -f', # Kubernetes pod log following
    'docker stats',   # Docker container statistics
    'kubectl top',    # Kubernetes resource usage
]

# Define signals based on platform
try:
    SIGKILL = signal.SIGKILL
    SIGTERM = signal.SIGTERM
except AttributeError:
    SIGKILL = 9
    SIGTERM = 15

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

def is_continuous_command(command: str) -> bool:
    """Check if a command is expected to run continuously."""
    return any(cont_cmd in command.lower() for cont_cmd in CONTINUOUS_COMMANDS)

async def stream_output(process, update: Update, first_message=None):
    """Stream output from a process back to Telegram."""
    print("Debug - Stream output started")
    buffer = ""
    last_send_time = 0
    message_to_update = first_message

    try:
        while True:
            # Check if process is still running
            try:
                if process.returncode is not None:
                    print(f"Debug - Process ended with return code: {process.returncode}")
                    break
            except Exception as e:
                print(f"Debug - Error checking process status: {str(e)}")
                break

            try:
                # Read output line by line
                line = await process.stdout.readline()
                if not line:
                    print("Debug - No more output to read")
                    # Check if process is still running despite no output
                    if process.returncode is None:
                        await asyncio.sleep(1)  # Wait a bit before next read
                        continue
                    break

                print(f"Debug - Read line: {line.decode().strip()}")
                buffer += line.decode()

                # Send update every 5 seconds or when buffer gets large
                current_time = datetime.now().timestamp()
                if current_time - last_send_time >= 5 or len(buffer) > 3000:
                    if buffer:
                        print(f"Debug - Sending buffer of size: {len(buffer)}")
                        # Truncate buffer if too long
                        if len(buffer) > 4000:
                            buffer = buffer[-4000:]

                        # Update existing message or send new one
                        try:
                            if message_to_update:
                                await message_to_update.edit_text(f"```\n{buffer}\n```", parse_mode='Markdown')
                                print("Debug - Updated existing message")
                            else:
                                message_to_update = await update.message.reply_text(f"```\n{buffer}\n```", parse_mode='Markdown')
                                print("Debug - Sent new message")
                        except Exception as e:
                            print(f"Debug - Error sending message: {str(e)}")
                            # If edit fails, send as new message
                            message_to_update = await update.message.reply_text(f"```\n{buffer}\n```", parse_mode='Markdown')

                        buffer = ""
                        last_send_time = current_time

            except Exception as e:
                print(f"Debug - Error reading output: {str(e)}")
                break

    except Exception as e:
        print(f"Debug - Stream error: {str(e)}")
        await update.message.reply_text(f"Error streaming output: {str(e)}")
    finally:
        print("Debug - Stream output ended")
        # Send any remaining buffer
        if buffer:
            try:
                await update.message.reply_text(f"```\n{buffer}\n```", parse_mode='Markdown')
            except Exception as e:
                print(f"Debug - Error sending final buffer: {str(e)}")

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Stop running command for the user."""
    if not is_authenticated(update):
        return

    user_id = update.effective_user.id
    if user_id in user_processes:
        process = user_processes[user_id]
        try:
            # Get process and all children
            parent = psutil.Process(process.pid)
            children = parent.children(recursive=True)
            
            # Terminate them all
            for child in children:
                child.terminate()
            parent.terminate()
            
            # Wait briefly for graceful termination
            await asyncio.sleep(1)
            
            # Force kill any remaining processes
            for child in children:
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    pass
            try:
                parent.kill()
            except psutil.NoSuchProcess:
                pass
            
            del user_processes[user_id]
            await update.message.reply_text("Command stopped successfully.")
        except Exception as e:
            await update.message.reply_text(f"Error stopping command: {str(e)}")
            if user_id in user_processes:
                del user_processes[user_id]
    else:
        await update.message.reply_text("No running command to stop.")

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

        # Debug logging
        print(f"Debug - Command received: {command}")
        print(f"Debug - Command parts: cmd='{cmd}', args='{args}'")

        # Map of common commands to their full paths
        cmd_paths = {
            # File and system commands
            'ls': '/bin/ls',
            'cat': '/bin/cat',
            'head': '/usr/bin/head',
            'tail': '/usr/bin/tail',
            
            # Process monitoring
            'ps': '/usr/bin/ps',
            'top': '/usr/bin/top',
            'htop': '/usr/bin/htop',
            'atop': '/usr/bin/atop',
            'iotop': '/usr/bin/iotop',
            'powertop': '/usr/bin/powertop',
            
            # System monitoring
            'df': '/usr/bin/df',
            'vmstat': '/usr/bin/vmstat',
            'iostat': '/usr/bin/iostat',
            'mpstat': '/usr/bin/mpstat',
            'dstat': '/usr/bin/dstat',
            'perf': '/usr/bin/perf',
            
            # Network monitoring
            'ping': '/usr/bin/ping',
            'tcpdump': '/usr/bin/tcpdump',
            'netstat': '/usr/bin/netstat',
            'ss': '/usr/bin/ss',
            'nload': '/usr/bin/nload',
            'iftop': '/usr/bin/iftop',
            'nethogs': '/usr/bin/nethogs',
            
            # Container and service management
            'docker': '/usr/bin/docker',
            'kubectl': '/usr/bin/kubectl',
            'systemctl': '/usr/bin/systemctl',
            'journalctl': '/usr/bin/journalctl',
            
            # Other utilities
            'watch': '/usr/bin/watch',
            'strace': '/usr/bin/strace'
        }

        # Debug - Check if command is continuous
        is_continuous = is_continuous_command(command)
        print(f"Debug - Is continuous command: {is_continuous}")

        # Commands that need sudo
        sudo_commands = [
            'tail',
            'journalctl',
            'systemctl',
            'docker',
            'tcpdump',
            'iotop',
            'nethogs',
            'iftop',
            'powertop',
            'perf',
            'strace'
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

        # Log the actual command being executed
        print(f"Debug - Final command to execute: {command}")

        # Check for existing process and stop it
        user_id = update.effective_user.id
        if user_id in user_processes:
            print("Debug - Stopping existing process")
            try:
                process = user_processes[user_id]
                parent = psutil.Process(process.pid)
                parent.terminate()
                await asyncio.sleep(1)
                if parent.is_running():
                    parent.kill()
            except (psutil.NoSuchProcess, Exception) as e:
                print(f"Debug - Error stopping existing process: {str(e)}")
            finally:
                del user_processes[user_id]

        # Create new process with line buffering
        print("Debug - Creating new process")
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,  # Redirect stderr to stdout
            bufsize=1  # Line buffering
        )

        print(f"Debug - Process created with PID: {process.pid}")
        user_processes[user_id] = process

        # Check if this is a continuous command
        if is_continuous:
            print("Debug - Starting continuous command handling")
            await update.message.reply_text(
                "⚠️ This is a continuous command. Output will be streamed every 5 seconds.\n"
                "Use /stop to end the command."
            )
            # Start streaming output
            print("Debug - Starting output streaming")
            await stream_output(process, update)
            print("Debug - Stream output completed")
        else:
            print("Debug - Handling as regular command")
            stdout, stderr = await process.communicate()
            
            # Clear process from storage
            if user_id in user_processes and user_processes[user_id] == process:
                del user_processes[user_id]

            output = stdout.decode() if stdout else stderr.decode()
            if not output:
                output = "Command executed successfully (no output)"

            # Split long outputs into chunks
            for i in range(0, len(output), 4000):
                chunk = output[i:i+4000]
                await update.message.reply_text(f"```\n{chunk}\n```", parse_mode='Markdown')

    except Exception as e:
        print(f"Debug - Error executing command: {str(e)}")
        await update.message.reply_text(f"Error executing command: {str(e)}")
        if update.effective_user.id in user_processes:
            del user_processes[update.effective_user.id]

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