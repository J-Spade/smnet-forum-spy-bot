# smnet-forum-spy-bot

Requires Python 3.6+ and the following dependencies:
* beautifulsoup4
* discord.py
* requests

In order to work, the `FORUM_SPY_DISCORD_WEBHOOK_URL` environment variable must be set to the **#forum-spy** webhook URL (see the Discord channel settings).

To run the bot, simply run the `forum_spy.py` script.


## Testing framework

The test framework, `test_spy.py`, can be used to validate local changes to the message parser or embed format. By adding specific forum posts to a local test set, you can test your changes without having to wait for a new post containing a particular type of formatting, and without manually downloading or copy/pasting HTML into a python interpreter.

Pass `-h` or `--help` to the test framework for information on how to use it.