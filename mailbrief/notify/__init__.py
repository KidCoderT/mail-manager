from mailbrief.notify import telegram

# Add a channel: write send_<channel>(target, text) and register it here.
ADAPTERS = {"telegram": telegram.send}
