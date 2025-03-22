#!/bin/bash

# Exit on any error
set -e

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "Please run as root"
    exit 1
fi

# Create telegram_bot user if it doesn't exist
if ! id "telegram_bot" &>/dev/null; then
    adduser --disabled-password --gecos "" telegram_bot
    echo "Created telegram_bot user"
fi

# Set up project directory
BOT_DIR=/home/telegram_bot/telegramShell
mkdir -p $BOT_DIR
cd $BOT_DIR

# Copy files
cp -r ./* $BOT_DIR/
chown -R telegram_bot:telegram_bot $BOT_DIR

# Set up Python virtual environment
su - telegram_bot -c "python3 -m venv $BOT_DIR/venv"
su - telegram_bot -c "$BOT_DIR/venv/bin/pip install -r $BOT_DIR/requirements.txt"

# Set up systemd service
cp telegram-shell-bot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable telegram-shell-bot
systemctl start telegram-shell-bot

# Set up sudo permissions
cat > /etc/sudoers.d/telegram_bot << EOF
telegram_bot ALL=(ALL) NOPASSWD: /usr/bin/tail, /bin/ls, /usr/bin/df, /usr/bin/ps, /usr/bin/htop
EOF
chmod 0440 /etc/sudoers.d/telegram_bot

echo "Deployment complete! Please set up your .env file with:"
echo "TELEGRAM_TOKEN=your_bot_token"
echo "ALLOWED_USERS=your_telegram_user_id"
echo "BOT_PASSWORD=your_secure_password" 