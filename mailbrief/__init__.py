class ConfigError(Exception):
    """A setting is missing or wrong (.env). Library code raises this, never SystemExit: a SystemExit in the chat
    listener's thread would end that thread silently. `main()` turns it into a one-line message."""
