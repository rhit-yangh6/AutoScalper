# Quick Token Extraction Guide

## Method 1: Browser (Easiest - 30 seconds)

1. **Open Discord in Chrome/Firefox**
   - Go to: https://discord.com/app
   - Log in to your account

2. **Open Developer Tools**
   - Press `F12` (or `Cmd+Option+I` on Mac)

3. **Go to Console Tab**

4. **Paste this code and press Enter:**

```javascript
(webpackChunkdiscord_app.push([[''],{},e=>{m=[];for(let c in e.c)m.push(e.c[c])}]),m).find(m=>m?.exports?.default?.getToken!==void 0).exports.default.getToken()
```

5. **Copy the output** (it will be in quotes)
   - Remove the quotes when copying
   - Example: If you see `"abc123xyz"`, copy just `abc123xyz`

6. **Update your `.env` file:**
   ```bash
   DISCORD_USER_TOKEN=your_new_token_here
   ```

## Method 2: Network Tab (Alternative)

1. Open Discord in browser: https://discord.com/app
2. Press `F12` → **Network** tab
3. Press `F5` to refresh the page
4. Filter for "api" in the search box
5. Click any request to `discord.com/api`
6. Look at **Request Headers**
7. Find `authorization:` header
8. Copy the value (without "authorization:")

## Method 3: Local Storage

1. Open Discord in browser
2. Press `F12` → **Application** tab (Chrome) or **Storage** tab (Firefox)
3. Expand **Local Storage** → `https://discord.com`
4. Look for a key containing `token`
5. Copy the value

## Verify Your Token

Test if your token works:

```python
import requests

token = "paste_your_token_here"

headers = {
    "Authorization": token
}

response = requests.get("https://discord.com/api/v9/users/@me", headers=headers)

if response.status_code == 200:
    user = response.json()
    print(f"✓ Token works! Logged in as: {user['username']}#{user['discriminator']}")
else:
    print(f"✗ Token invalid: {response.status_code}")
    print(response.text)
```

## Common Issues

### "Token starts with a number"
✓ This is normal for user tokens. Bot tokens start with "Bot " or "MTk4NjIy..."

### "Token has dots (.)"
✓ This is correct. User tokens have 3 parts separated by dots

### "Token is very long"
✓ Normal. Tokens are ~60-80 characters

### Still not working?
1. Try logging out and back in to Discord
2. Clear browser cache
3. Try a different browser
4. Change your Discord password (this generates new tokens)

## Security Reminder

⚠️ **Never share your token!**
- Gives full access to your Discord account
- Can read all messages, send messages as you
- If leaked, change your Discord password immediately
