# Secure Telegram Shell Bot

A simple and secure bot for executing shell commands via Telegram.

## Security Notice
This bot provides remote shell access. Use with caution and implement proper security measures:
1. Create a dedicated Linux user with restricted permissions
2. Use strong passwords and keep credentials secure
3. Enable only trusted Telegram users
4. Regularly audit command logs

## Complete Setup Instructions

### 1. Create Telegram Bot
1. Message @BotFather on Telegram
2. Send `/newbot` command
3. Choose a name (e.g., "My Server Shell")
4. Choose a username (must end in 'bot')
5. Save the API token you receive

### 2. Get Your Telegram User ID
1. Message @userinfobot on Telegram
2. Save the ID number it sends you

### 3. Server Deployment
1. Copy all files to your server:
   ```bash
   scp -r ./* user@your-server:/tmp/telegramShell/
   ```

2. SSH into your server:
   ```bash
   ssh user@your-server
   ```

3. Run the deployment script:
   ```bash
   cd /tmp/telegramShell
   sudo chmod +x deploy.sh
   sudo ./deploy.sh
   ```

4. Create and edit the .env file:
   ```bash
   sudo -u telegram_bot nano /home/telegram_bot/telegramShell/.env
   ```
   Add these lines:
   ```
   TELEGRAM_TOKEN=your_bot_token
   ALLOWED_USERS=your_telegram_user_id
   BOT_PASSWORD=your_secure_password
   ```

5. Restart the service:
   ```bash
   sudo systemctl restart telegram-shell-bot
   ```

### 4. Verify Installation
1. Check service status:
   ```bash
   sudo systemctl status telegram-shell-bot
   ```

2. View logs if needed:
   ```bash
   sudo journalctl -u telegram-shell-bot -f
   ```

## Usage
1. Start chat with bot: `/start`
2. Authenticate: `/auth your_password`
3. Type commands directly: `ls -la`
   - Or with slash prefix: `/ls -la`
4. Get help: `/help`

### Tips for Efficient Usage
1. Open multiple chat windows with the bot
2. Dedicate one window for log monitoring:
   ```
   tail -f /path/to/logfile
   ```
3. Use other windows for running commands
4. Press Ctrl+C in Telegram to stop viewing output

### Common Commands
- List files: `ls -la`
- Monitor log: `tail -f /var/log/syslog`
- System info: `htop`
- Check disk space: `df -h`
- Process list: `ps aux`

### Troubleshooting
1. Check service status:
   ```bash
   sudo systemctl status telegram-shell-bot
   ```
2. View logs:
   ```bash
   sudo journalctl -u telegram-shell-bot -f
   ```
3. Check permissions:
   ```bash
   ls -la /home/telegram_bot/telegramShell/
   sudo -l -U telegram_bot
   ``` 