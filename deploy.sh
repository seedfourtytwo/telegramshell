#!/bin/bash

# Exit on any error
set -e

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "Please run as root"
    exit 1
fi

# Get the absolute path of the script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Create telegram_bot user if it doesn't exist
if ! id "telegram_bot" &>/dev/null; then
    adduser --disabled-password --gecos "" telegram_bot
    echo "Created telegram_bot user"
fi

# Set up project directory
BOT_DIR=/home/telegram_bot/telegramShell
mkdir -p $BOT_DIR

# Copy files from current directory
echo "Copying files from $SCRIPT_DIR to $BOT_DIR"
cp -r "$SCRIPT_DIR"/{bot.py,requirements.txt,telegram-shell-bot.service,.env,.env.example} $BOT_DIR/
chown -R telegram_bot:telegram_bot $BOT_DIR

# Set up Python virtual environment
echo "Setting up Python virtual environment..."
su - telegram_bot -c "python3 -m venv $BOT_DIR/venv"
su - telegram_bot -c "$BOT_DIR/venv/bin/pip install -r $BOT_DIR/requirements.txt"

# Set up systemd service
echo "Setting up systemd service..."
cp $BOT_DIR/telegram-shell-bot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable telegram-shell-bot
systemctl restart telegram-shell-bot

# Set up sudo permissions
echo "Setting up sudo permissions..."
cat > /etc/sudoers.d/telegram_bot << EOF
# Allow telegram_bot to run specific commands without password
telegram_bot ALL=(ALL) NOPASSWD: /usr/bin/tail, /bin/ls, /usr/bin/df, /usr/bin/ps, /usr/bin/htop, /usr/bin/systemctl, /usr/bin/journalctl, /usr/bin/docker, /bin/cat, /usr/bin/head
EOF
chmod 0440 /etc/sudoers.d/telegram_bot

echo "Deployment complete! Checking service status..."
systemctl status telegram-shell-bot

echo "You can check logs with: sudo journalctl -u telegram-shell-bot -f"

echo "Please set up your .env file with:"
echo "TELEGRAM_TOKEN=your_bot_token"
echo "ALLOWED_USERS=your_telegram_user_id"
echo "BOT_PASSWORD=your_secure_password" 