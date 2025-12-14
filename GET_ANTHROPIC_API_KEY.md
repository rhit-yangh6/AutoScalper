# How to Get Your Anthropic API Key

## Step-by-Step Guide

### 1. Create an Anthropic Account

1. Go to https://console.anthropic.com/
2. Click "Sign Up" or "Get Started"
3. Sign up with:
   - Email and password, OR
   - Google account, OR
   - GitHub account

### 2. Verify Your Email

1. Check your email inbox
2. Click the verification link from Anthropic
3. Complete email verification

### 3. Set Up Billing

**Important**: You need to add a payment method to use the API.

1. Log in to https://console.anthropic.com/
2. Click on "Settings" (gear icon) or your profile
3. Go to "Billing" section
4. Click "Add Payment Method"
5. Enter your credit card details
6. Optionally set a monthly spending limit (recommended for safety)

**Pricing** (as of 2024):
- Claude 3.5 Sonnet: ~$3 per million input tokens, $15 per million output tokens
- For this trading bot, expect $0.01-0.05 per message parsed
- Starting with $10-20 credit should be plenty for testing

### 4. Get Your API Key

1. Go to https://console.anthropic.com/settings/keys
2. Click "Create Key" or "+ Create API Key"
3. Give it a name (e.g., "AutoScalper Trading Bot")
4. Click "Create Key"
5. **Copy the key immediately** - you won't be able to see it again!

Your key will look like:
```
sk-ant-api03-abc123xyz...
```

### 5. Add to Your `.env` File

```bash
ANTHROPIC_API_KEY=sk-ant-api03-your_actual_key_here
```

### 6. Verify It Works

Test with this Python script:

```python
import anthropic
import os
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

message = client.messages.create(
    model="claude-3-5-sonnet-20241022",
    max_tokens=100,
    messages=[
        {"role": "user", "content": "Say hello!"}
    ]
)

print(message.content[0].text)
```

If it prints "Hello!" or similar, your API key is working!

## Alternative: Use API Credits

Anthropic occasionally offers free API credits for new users:

1. Check https://console.anthropic.com/settings/billing
2. Look for any promotional credits
3. Some hackathons and programs offer Claude API credits

## Security Best Practices

### ✅ DO:
- Store in `.env` file (never commit to Git)
- Use different keys for development and production
- Set spending limits in the Console
- Rotate keys periodically
- Monitor usage regularly

### ❌ DON'T:
- Commit API keys to Git
- Share keys publicly
- Hardcode keys in source code
- Use the same key across multiple projects
- Ignore billing alerts

## Cost Management

### Set Spending Limits

1. Go to https://console.anthropic.com/settings/billing
2. Set a monthly spending limit (e.g., $50/month)
3. Enable email alerts for spending

### Monitor Usage

1. Go to https://console.anthropic.com/settings/usage
2. Check daily/monthly usage
3. Review cost per request

### Expected Costs for AutoScalper

Assuming:
- 50 Discord messages per day
- Each message = ~500 input tokens + 200 output tokens
- Using Claude 3.5 Sonnet

**Daily cost**:
- Input: 50 × 500 tokens × $3/1M = $0.075
- Output: 50 × 200 tokens × $15/1M = $0.15
- **Total: ~$0.23/day or ~$7/month**

This is very affordable for automated trading!

## Troubleshooting

### "Authentication Error" or "Invalid API Key"
- Double-check you copied the entire key
- Make sure there are no extra spaces
- Verify `.env` file is in the correct directory
- Try creating a new key

### "Insufficient Credits" or "Payment Required"
- Add a payment method in Console → Billing
- Check your spending limit isn't set to $0
- Verify your credit card is valid

### "Rate Limit Exceeded"
- Default rate limits: 50 requests/minute for Sonnet
- This is plenty for trading bot (1-2 messages/minute typical)
- If exceeded, wait a minute and retry
- Consider upgrading tier if needed

### Key Not Working After Creation
- Keys can take a few seconds to activate
- Try waiting 30 seconds
- Refresh your browser and check the key is listed
- Create a new key if issue persists

## Getting Help

- **Anthropic Support**: support@anthropic.com
- **Console**: https://console.anthropic.com/
- **Documentation**: https://docs.anthropic.com/
- **API Status**: https://status.anthropic.com/

## Free Alternatives (Not Recommended)

If you want to test without Anthropic:

1. **OpenAI GPT-4** - Modify `src/llm_parser/parser.py` to use OpenAI
2. **Local LLMs** - Much less reliable for structured parsing
3. **Other providers** - Most lack the JSON mode needed for parsing

**Recommendation**: Anthropic Claude is best for this use case due to:
- Excellent structured output (JSON)
- High accuracy on parsing tasks
- Reliable low-temperature behavior
- Good safety characteristics

The ~$7/month cost is negligible compared to trading capital.

## Example `.env` with Anthropic Key

```bash
# Anthropic API
ANTHROPIC_API_KEY=sk-ant-api03-abc123xyz...

# Discord
DISCORD_USER_TOKEN=MTA1ODc2...
DISCORD_CHANNEL_IDS=123456789
DISCORD_MONITORED_USERS=trader1

# IBKR
IBKR_HOST=127.0.0.1
IBKR_PORT=7497
IBKR_CLIENT_ID=1

# Risk
ACCOUNT_BALANCE=10000
RISK_PER_TRADE_PERCENT=0.5
DAILY_MAX_LOSS_PERCENT=2.0
MAX_CONTRACTS=1
PAPER_MODE=true
```

## Quick Start Checklist

- [ ] Created Anthropic account
- [ ] Verified email
- [ ] Added payment method
- [ ] Created API key
- [ ] Copied key to `.env` file
- [ ] Tested with example script
- [ ] Set spending limit ($50/month recommended)
- [ ] Ready to run AutoScalper!

---

**Total Time**: 5-10 minutes
**Total Cost**: ~$7/month for typical usage
