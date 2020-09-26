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

FORUM_ROOT = 'https://forum.starmen.net'
FORUM_SPY_AJAX = FORUM_ROOT + '/forum/spy.ajax'
FORUM_SPY_REQUEST_HEADERS = {
    'Accept': '*/*',
    'Referer': 'https://forum.starmen.net/forum/spy',
    'User-Agent': 'discord-forum-spy-bot',
}
FORUM_PREVIEW_LENGTH = 250

# # # # #
# Helper functions
# # # # #

def _get_username(user_profile):
    '''
    Requests the user profile and parses the name out of it.
    We do this because users with avatars, which don't all have alt-text, and because the user
    profile URL may have been adjusted from the actual username (e.g. "J_Spade" -> "J-Spade").
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

    # Body: message content, signature
    body = soup.find('div', {'class': 'post-body'})
    content = body.find('div', {'class': 'message-content'})
    # TODO: handle things like quotes, spoilers, formatting
    text = ''.join(content.strings)[:FORUM_PREVIEW_LENGTH].strip()

    # Footer: date, thumb score, utils (quote, report, permalink)
    footer = soup.find('div', {'class': 'post-footer'})
    post_date = footer.p.find('span', {'class': 'changeabletime'})['title']
    
    utils = footer.find('ul', {'class': 'utils'})
    permalink = utils.find('li', {'class': 'permalink'})
    url = FORUM_ROOT + permalink.a['href']

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
        # Alternate forum post colors (even: 68375; odd:4648)
        'color': (68375 if int(post['id'][-1]) % 2 == 0 else 4648),
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
            DISCORD_WEBHOOK.send(embed=discord.Embed.from_dict(embed_data))
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