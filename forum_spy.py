from bs4 import BeautifulSoup
import discord
import json
import os
import time
import urllib.request


# # # # #
# Config variables
# # # # #

webhook_url = os.getenv('FORUM_SPY_DISCORD_WEBHOOK_URL')
if not webhook_url:
    print('ERROR: Environment variable FORUM_SPY_DISCORD_WEBHOOK_URL must be set!')
    exit()

DISCORD_WEBHOOK = discord.Webhook.from_url(webhook_url, adapter=discord.RequestsWebhookAdapter())
DISCORD_NO_MENTIONS = discord.AllowedMentions(everyone=False, users=False, roles=False)

FORUM_ROOT = 'https://forum.starmen.net'
FORUM_SPY_AJAX = FORUM_ROOT + '/forum/spy.ajax'
FORUM_SPY_REQUEST_HEADERS = {
    'Accept': '*/*',
    'Referer': 'https://forum.starmen.net/forum/spy',
    'User-Agent': 'discord-forum-spy-bot',
}
FORUM_PREVIEW_LENGTH = 250
FORUM_COLOR_EVEN = int(0x010b17)
FORUM_COLOR_ODD = int(0x001228)

# What to display when we can't fit a quote?
SNIP_TEXT = "*[...]*"
# What to display when we cut off some text?
TRUNCATE_TEXT = "..."
# Minimum length of a quote before we 'snip for length'?
MIN_QUOTE_LENGTH = 5


# # # # #
# Helper functions
# # # # #

def _get_username(user_profile):
    '''
    Requests the user profile and parses the name out of it (used for members with avatars).
    If the request fails, just default to the URL string.
    '''
    try:
        profile_request = urllib.request.Request(user_profile, headers=FORUM_SPY_REQUEST_HEADERS)
        with urllib.request.urlopen(profile_request) as f:
            data = f.read()
    except urllib.error.HTTPError as err:
        print(f'While querying {user_profile}, {err.code}: {err.reason}')
        return user_profile.split('/')[-1]

    soup = BeautifulSoup(data, 'html.parser')
    member = soup.find('a', {'class': 'member'})
    return member.string

def _convert_formatting(content, max_length):
    # Handle blockquotes and spoiler blocks

    # Blockquotes: recursively formats inner quote content the same way
    # We want to only show quotes if we have enough room after truncation
    # (i.e. we don't want to have the preview be just quotes.)
    # So we see how much space should be devoted to non-quote text and
    # then divide up remaining space among quotes which will get shortened.
    # (unless the remaining size per quote is very short or zero in which
    #  case we'll just replace the quote with '[...]')

    # Determine how much non-quote text is here
    def rec_textlength(node):
        text_length = 0
        for child in node.children:
            # Skip children that are blockquotes
            if child.name and child.name == 'blockquote':
                continue
            # Count length of string nodes
            elif child.string:
                if child.string != "\n":
                    text_length += len(child.string)
            # Add non-string children's length recursively
            elif child is not node:
                text_length += rec_textlength(child)
        return text_length

    text_length = rec_textlength(content)

    # If we have any blockquotes, we want to format/truncate them recursively
    blockquotes = content.find_all('blockquote', recursive=False)

    if blockquotes:
        # Find how much space can be devoted to each quote -- divide any remaining
        # space among them evenly
        remaining_length = (max_length - text_length) // len(blockquotes)
        for quote in blockquotes:
            quote_by = quote.find('div', {'class': 'citey'})
            quote_content = quote.find('div', {'class': 'quotey'})
            if remaining_length > MIN_QUOTE_LENGTH:
                # Recursively format inner quote text
                # (base case is no quotes in which case this loop doesn't run)
                _convert_formatting(quote_content, remaining_length)
                markdown_quote = "\n".join(("> " + line) for line in quote_content.get_text().split("\n"))
            else:
                markdown_quote = f'> {SNIP_TEXT}'

            # if quote has a cite, add it
            if quote_by is not None:
                markdown_quote = f'> **{quote_by.get_text()}**\n' + markdown_quote

            # If multiple quotes next to each other, add a separating line
            next_elem = quote.find_next_sibling()
            if next_elem and next_elem.name and next_elem.name == 'blockquote':
                markdown_quote += "\n"

            quote.clear()
            quote.insert(0, markdown_quote)

    def rec_truncate(node, deficit):
        # Recursive function to truncate *non-quoted* text.
        # 'deficit' is how much we have to cut off. But we
        # want to avoid slicing quotes in half when truncating,
        # so we want to remove them wholesale if we run into
        # them rather than just cutting the result of get_text()
        # at the very end. Hence the semi-convoluted logic here.

        # We iterate over the children of the node in reverse
        # so we start cutting from the end
        for child in reversed(list(node.children)):
            if child.name and child.name == 'blockquote':
                # Since we still have a deficit (i.e. we're still
                # looping, so we still want to be cutting stuff off
                # from the end), just remove the quote wholesale since
                # it's going to be after the '...' in the post
                child.clear()
            elif child.string:
                if len(child.string) < deficit:
                    # Remove the whole child and reduce the deficit
                    # by its length.
                    deficit -= len(child.string)
                    child.string.replace_with("")
                else:
                    # We reduced the deficit enough! Should fit
                    # under the character limit now.
                    child.string.replace_with(child.string[:-deficit] + TRUNCATE_TEXT)
                    deficit = 0
                    break
            else:
                # It's some kind of weird compound tag
                deficit = rec_truncate(child, deficit)
                if deficit <= 0: break

        return deficit

    if text_length > max_length:
        rec_truncate(content, text_length - max_length)

    # Block spoilers stripped from preview
    block_spoilers = content.find_all('div', {'class': 'spoiler_container'})
    for spoiler in block_spoilers:
        spoiler.clear()

    # Spoilerize inline spoilers
    inline_spoilers = content.find_all('span', {'class': 'inline_spoiler'})
    for spoiler in inline_spoilers:
        # Drop the red spoiler title if there is one
        if spoiler.span:
            spoiler.span.clear()
        new_spoiler = f'||{spoiler.get_text()}||'
        spoiler.replace_with(new_spoiler)

def _parse_forum_post(data):
    '''
    Pulls apart the AJAX data to find the bits of the forum post we want to display in
    the Discord embed.
    '''
    soup = BeautifulSoup(data[1], 'html.parser') # format is [postID, html]
    post_id = data[0]

    # Header: sprite, username, badges
    header = soup.find('div', {'class': 'post-header'})
    if header.h3.img:
        user_sprite = header.h3.img['src']  # grabs the avatar if there is one (keep?)
    else:
        user_sprite = None
    member = header.h3.a
    user_profile = FORUM_ROOT + member['href']
    if member.string:
        user_name = member.string
    else:
        user_name = _get_username(user_profile)

    # Footer: date, thumb score, utils (quote, report, permalink)
    footer = soup.find('div', {'class': 'post-footer'})
    post_date = footer.p.find('span', {'class': 'changeabletime'})['title']
    utils = footer.find('ul', {'class': 'utils'})
    permalink = utils.find('li', {'class': 'permalink'})
    url = FORUM_ROOT + permalink.a['href']

    # Body: message content, signature
    body = soup.find('div', {'class': 'post-body'})
    content = body.find('div', {'class': 'message-content'})

    _convert_formatting(content, FORUM_PREVIEW_LENGTH)

    # Convert to plaintext and strip extra whitespace.
    text = content.get_text().strip()

    # We may have just stripped away part of an inline spoiler, so fix that if needed
    # (should be an even number of '||' delimiters)
    if text.count('||') % 2 != 0:
        text += '||'

    if text == '':
        text = '_[post contains only images, quotes and/or spoilers]_'

    post = {
        'id': post_id,
        'user_sprite': user_sprite,
        'user_name': user_name,
        'user_profile': user_profile,
        'date': post_date,
        'url': url,
        'text': text,
    }
    return post

def _post_in_discord(post):
    '''
    Sends a webhook request to Discord, containing an embedded forum post.
    If an error occurs, will retry up to a total of 5 attempts before giving up.
    '''
    # See: https://discord.com/developers/docs/resources/channel#embed-object
    embed_data = {
        # Alternate forum post colors
        'color': (FORUM_COLOR_EVEN if int(post['id'][-1]) % 2 == 0 else FORUM_COLOR_ODD),
        'author': {
            'name': post['user_name'],
            'url': post['user_profile']
        },
        'thumbnail': {
            'url': post['user_sprite']
        },
        'description': f"{post['text']}\n\n{post['url']}"
    }

    print(f"Posting {post['id']} to Discord")
    for attempt in range(5):
        try:
            DISCORD_WEBHOOK.send(
                embed=discord.Embed.from_dict(embed_data),
                allowed_mentions=DISCORD_NO_MENTIONS
            )
            return
        except discord.HTTPException as err:
            print(f"{post['id']} attempt {attempt}, {err.status}: {err.text} (Discord code {err.code})")
            time.sleep(5)
    print(f"Failed to send {post['id']}")


# # # # # 
# Functionality
# # # # #

def forum_spy_loop():
    '''
    The main loop. Retrieves new forum posts every 15 seconds (same as forum spy).
    If there are any new posts, has them posted to the Discord channel.
    '''
    prev_post_ids = []
    while True:
        try:
            # Request the forum spy data
            spy_request = urllib.request.Request(FORUM_SPY_AJAX, headers=FORUM_SPY_REQUEST_HEADERS)
            with urllib.request.urlopen(spy_request) as f:
                data = json.load(f)
        except urllib.error.HTTPError as err:
            # If an HTTP error occurs, wait 30s and try again
            print(f'While querying forum spy, {err.code}: {err.reason}')
            time.sleep(30)
            continue

        if len(prev_post_ids):  # The first time, just populate the list of posts in the spy
            for postdata in data:
                if postdata[0] not in prev_post_ids:
                    try:
                        post = _parse_forum_post(postdata)
                    except Exception as e:
                        print(f"While parsing {postdata[0]}, encountered {str(e)}")
                        continue
                    _post_in_discord(post)
                    time.sleep(1)
        prev_post_ids = [d[0] for d in data]

        # Wait a while before looking for new posts again
        time.sleep(15)

if __name__ == '__main__':
    # usually we'd probably kick off a worker thread doing this, but we only really do one thing,
    # so we may as well just do it here.
    forum_spy_loop()
