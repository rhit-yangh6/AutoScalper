# How to Get Your Discord User Token

## Method 1: Browser Developer Tools (Easiest)

### Desktop Browser (Chrome/Firefox/Edge)

1. Open Discord in your web browser (discord.com/app)
2. Log in to your account
3. Press `F12` to open Developer Tools
4. Go to the **Network** tab
5. Press `F5` to refresh the page
6. In the filter box, type: `api`
7. Click on any request to `discord.com/api`
8. Look in the **Request Headers** section
9. Find the `authorization:` header
10. Copy the value - this is your token

### Example:
```
authorization: MTA1ODc2NzM5ODIxNjc5ODI1OQ.GZrLmD.dQw4w9WgXcQ_example_token_here
```

## Method 2: Discord Desktop App

### Windows/Mac/Linux

1. Open Discord Desktop App
2. Press `Ctrl+Shift+I` (Windows/Linux) or `Cmd+Option+I` (Mac)
3. Go to **Console** tab
4. Paste this code and press Enter:

```javascript
(webpackChunkdiscord_app.push([[''],{},e=>{m=[];for(let c in e.c)m.push(e.c[c])}]),m).find(m=>m?.exports?.default?.getToken!==void 0).exports.default.getToken()
```

5. Your token will be displayed in quotes
6. Copy it (without the quotes)

## Method 3: Manual Network Inspection

1. Open Discord (web or desktop with DevTools)
2. Open Developer Tools (`F12` or `Ctrl+Shift+I`)
3. Go to **Application** tab (Chrome) or **Storage** tab (Firefox)
4. Expand **Local Storage** → `https://discord.com`
5. Look for a key that contains `token`
6. Copy the value

## Important Security Notes

⚠️ **NEVER share your Discord token with anyone!**

- Your token gives full access to your Discord account
- Anyone with your token can read your messages, send messages as you, etc.
- If your token is leaked, change your Discord password immediately (this invalidates the token)

⚠️ **Using user tokens for automation**

- Discord's Terms of Service technically prohibit self-bots (user token automation)
- This is for your **personal use only** to monitor your own trading channels
- Use at your own risk
- Don't spam or abuse Discord's API

## Storing Your Token Securely

### In your `.env` file:

```bash
DISCORD_USER_TOKEN=your_token_here
```

### Never commit your token to Git!

The `.gitignore` file already excludes `.env`, but double-check:

```bash
# Make sure .env is in .gitignore
echo ".env" >> .gitignore
```

## Troubleshooting

### "Invalid Token" Error
- Your token may have expired
- Change your Discord password and get a new token
- Make sure you copied the entire token (no extra spaces)

### "Missing Access" Error
- Verify you're in the Discord server/channel you're trying to monitor
- Check that the channel ID is correct
- Ensure you have permission to read messages in that channel

### Token Getting Invalidated
- Discord may detect automation and invalidate your token
- If this happens frequently, consider:
  - Using a bot token instead (requires setting up a bot)
  - Reducing API request frequency
  - Only monitoring specific channels/users

## Channel IDs

To get channel IDs:

1. Enable Developer Mode in Discord:
   - Settings → Advanced → Developer Mode → ON
2. Right-click any channel
3. Click "Copy ID"
4. Add to your `.env`:

```bash
DISCORD_CHANNEL_IDS=123456789,987654321
```

## Finding Username

To monitor specific users, you need their exact username:

1. Right-click on their message
2. Click "Copy Username" or "Copy ID"
3. Add to your `.env`:

```bash
DISCORD_MONITORED_USERS=trader1,trader2
```

## Example `.env` Configuration

```bash
# Your Discord user token (from steps above)
DISCORD_USER_TOKEN=MTA1ODc2NzM5ODIxNjc5ODI1OQ.GZrLmD.example

# Channel IDs to monitor (comma-separated)
DISCORD_CHANNEL_IDS=123456789012345678,987654321098765432

# Only monitor these users (optional, leave empty to monitor all)
DISCORD_MONITORED_USERS=ProTrader,OptionsGuru
```

## Rate Limits

Discord has rate limits for user accounts:

- Reading messages: ~50 requests per second
- The listener is passive (only receives messages), so rate limits are rarely hit
- If you get rate limited, the client will automatically wait and retry
