import os
import sys
import json
import time
import requests
import argparse
import logging
from typing import Dict, Any, Optional
from pathlib import Path

# Constants
CONFIG_DIR = Path.home() / ".config" / "heimdall"
CONFIG_FILE = CONFIG_DIR / "config.json"
DISCORD_API_BASE = "https://discord.com/api/v10"

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("heimdall")

def load_or_create_config() -> Dict[str, str]:
    """Loads config or creates a template if not exists."""
    if not CONFIG_DIR.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    
    if not CONFIG_FILE.exists():
        template = {
            "discord_token": "YOUR_BOT_TOKEN_HERE",
            "channel_id": "YOUR_CHANNEL_ID_HERE"
        }
        with open(CONFIG_FILE, "w") as f:
            json.dump(template, f, indent=4)
        logger.error(f"Configuration file not found. Created template at {CONFIG_FILE}.")
        logger.error("Please edit the file with your Discord Bot Token and Channel ID.")
        sys.exit(1)
    
    try:
        with open(CONFIG_FILE, "r") as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse config file: {e}")
        sys.exit(1)
    
    if config.get("discord_token") == "YOUR_BOT_TOKEN_HERE":
        logger.error(f"Please update {CONFIG_FILE} with valid credentials.")
        sys.exit(1)
        
    return config

def get_headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json"
    }

def send_notification(config: Dict[str, str], project_name: str, question: str) -> str:
    """Sends an embed to Discord and returns the message ID."""
    url = f"{DISCORD_API_BASE}/channels/{config['channel_id']}/messages"
    
    embed = {
        "title": f"🚨 Action Required: {project_name}",
        "description": question,
        "color": 15158332, # Orange/Red
        "footer": {
            "text": "Reply to this message to confirm."
        }
    }
    
    payload = {
        "embeds": [embed]
    }
    
    try:
        response = requests.post(url, headers=get_headers(config['discord_token']), json=payload)
        response.raise_for_status()
        message_id = response.json()['id']
        logger.info(f"Notification sent. Message ID: {message_id}")
        return message_id
    except requests.exceptions.RequestException as e:
        logger.error(f"Error sending notification: {e}")
        sys.exit(1)

def react_to_message(config: Dict[str, str], message_id: str, emoji: str = "%E2%9C%85") -> None:
    """Reacts to a message to acknowledge receipt."""
    url = f"{DISCORD_API_BASE}/channels/{config['channel_id']}/messages/{message_id}/reactions/{emoji}/@me"
    try:
        requests.put(url, headers=get_headers(config['discord_token']))
    except requests.exceptions.RequestException:
        pass # Non-critical

def wait_for_reply(config: Dict[str, str], prompt_message_id: str) -> str:
    """Polls for a reply to the prompt message."""
    url = f"{DISCORD_API_BASE}/channels/{config['channel_id']}/messages"
    
    logger.info(f"Waiting for user reply on Discord channel {config['channel_id']}...")
    
    while True:
        try:
            # Poll for messages after the prompt
            params = {"after": prompt_message_id}
            response = requests.get(url, headers=get_headers(config['discord_token']), params=params)
            
            if response.status_code == 200:
                messages = response.json()
                for msg in messages:
                    # Check if it's a human message (not a bot)
                    if not msg.get("author", {}).get("bot", False):
                        # Ideally we check referenced_message, but for now we accept any subsequent message
                        # to allow for simpler interaction flow
                        reply_content = msg.get("content", "").strip()
                        reply_id = msg.get("id")
                        
                        # Acknowledge
                        react_to_message(config, reply_id)
                        
                        return reply_content

            elif response.status_code == 429:
                # Rate limited
                retry_after = response.json().get("retry_after", 3)
                logger.warning(f"Rate limited. Retrying after {retry_after}s...")
                time.sleep(retry_after)
                continue
                
        except requests.exceptions.RequestException as e:
            # Network error, keep trying
            logger.error(f"Network error: {e}. Retrying...")
            time.sleep(5)
            continue
            
        time.sleep(3)

def main() -> None:
    parser = argparse.ArgumentParser(description="Heimdall - Human-in-the-Loop Blocking Gateway")
    parser.add_argument("question", help="The question/ask for the user")
    args = parser.parse_args()
    
    try:
        config = load_or_create_config()
        project_name = os.path.basename(os.getcwd())
        
        # Send
        message_id = send_notification(config, project_name, args.question)
        
        # Wait
        reply = wait_for_reply(config, message_id)
        
        # Output result to stdout (for capturing by calling process)
        print(f"USER_CONFIRMED: {reply}")
        
    except KeyboardInterrupt:
        logger.info("\nOperation cancelled by user.")
        sys.exit(130)
    except Exception as e:
        logger.exception(f"An detailed error occurred: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
