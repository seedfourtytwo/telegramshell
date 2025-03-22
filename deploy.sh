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

# Create the installation directory
mkdir -p /opt/telegram-shell-bot

# Copy all necessary files
cp -r * /opt/telegram-shell-bot/
cp .env /opt/telegram-shell-bot/ 2>/dev/null || true

# Set ownership
chown -R telegram_bot:telegram_bot /opt/telegram-shell-bot

# Create and configure the service file
cat > /etc/systemd/system/telegram-shell-bot.service << EOL
[Unit]
Description=Telegram Shell Bot
After=network.target

[Service]
Type=simple
User=telegram_bot
WorkingDirectory=/opt/telegram-shell-bot
ExecStart=/usr/bin/python3 bot.py
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