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
    useradd -m -s /bin/bash telegram_bot
fi

# Set up project directory
BOT_DIR=/home/telegram_bot/telegramShell
mkdir -p $BOT_DIR

# Copy files from current directory
echo "Copying files to $BOT_DIR"
cp -r "$SCRIPT_DIR"/{bot.py,requirements.txt,.env} $BOT_DIR/
chown -R telegram_bot:telegram_bot $BOT_DIR

# Install system dependencies
apt-get update
apt-get install -y python3-venv

# Set up Python virtual environment
echo "Setting up Python virtual environment..."
su - telegram_bot -c "python3 -m venv $BOT_DIR/venv"
su - telegram_bot -c "$BOT_DIR/venv/bin/pip install python-telegram-bot python-dotenv"

# Create and configure the service file
cat > /etc/systemd/system/telegram-shell-bot.service << EOL
[Unit]
Description=Telegram Shell Bot
After=network.target

[Service]
Type=simple
User=telegram_bot
WorkingDirectory=$BOT_DIR
ExecStart=$BOT_DIR/venv/bin/python bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOL

# Configure sudoers for telegram_bot user
cat > /etc/sudoers.d/telegram_bot << EOL
# Allow telegram_bot to execute specific commands without password
telegram_bot ALL=(ALL) NOPASSWD: /usr/bin/tail -f /var/log/syslog
telegram_bot ALL=(ALL) NOPASSWD: /usr/bin/tail -f /var/log/*
telegram_bot ALL=(ALL) NOPASSWD: /usr/bin/journalctl
telegram_bot ALL=(ALL) NOPASSWD: /usr/bin/systemctl status *
telegram_bot ALL=(ALL) NOPASSWD: /usr/bin/docker ps
telegram_bot ALL=(ALL) NOPASSWD: /usr/bin/docker logs *
EOL

# Set proper permissions for sudoers file
chmod 0440 /etc/sudoers.d/telegram_bot

# Reload systemd and start the service
systemctl daemon-reload
systemctl enable telegram-shell-bot
systemctl restart telegram-shell-bot

echo "Deployment completed successfully!"
echo "You can check logs with: sudo journalctl -u telegram-shell-bot -f"

echo "Please set up your .env file with:"
echo "TELEGRAM_TOKEN=your_bot_token"
echo "ALLOWED_USERS=your_telegram_user_id"
echo "BOT_PASSWORD=your_secure_password" 