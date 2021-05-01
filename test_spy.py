"""
Quick-and-dirty testing for the forum spy bot. Allows testing with specific forum posts to
find and address odd edge cases.
"""
# pylint:disable=protected-access
import argparse
import json
import os
import time
import urllib.request

from bs4 import BeautifulSoup

import forum_spy


# for now, not committed to the repo; generated and used locally only
TEST_DATA_FILE = "test_data.ajax"


def make_forum_post_ajax(post_id):
    """
    Queries for a post with a given ID number (int) and generates the AJAX data for it,
    as if it were returned from the forum spy AJAX request.
    """
    message_url = f"{forum_spy.FORUM_ROOT}/forum/message/{post_id}"
    try:
        post_request = urllib.request.Request(
            message_url, headers=forum_spy.FORUM_SPY_REQUEST_HEADERS
        )
        with urllib.request.urlopen(post_request) as response:
            data = response.read()
    except urllib.error.HTTPError as err:
        print(f"While querying {message_url}, {err.code}: {err.reason}")
        return None

    soup = BeautifulSoup(data, "html.parser")
    id_str = f"post{post_id}"
    post_html = str(soup.find("div", {"id": id_str}))

    return [id_str, post_html]


def main(args):
    """
    Run the parser agaist the test set
    """
    # load the test data
    test_data = []
    if os.path.isfile(TEST_DATA_FILE):
        with open(TEST_DATA_FILE, "r") as ajax:
            test_data = json.load(ajax)

    # add/remove any specified test cases
    if args.add_post or args.delete_post or args.clear:
        if args.clear:
            test_data = []
        if args.add_post:
            for post_id in args.add_post:
                test_data.append(make_forum_post_ajax(post_id))
                time.sleep(0.5)
        if args.delete_post:
            test_data = [p for p in test_data if int(p[0][4:]) not in args.delete_post]
        # save the data back to the file
        with open(TEST_DATA_FILE, "w") as ajax:
            json.dump(test_data, ajax)

    # test the parser against the test data
    if args.test or args.post:
        for post_data in test_data:
            post = forum_spy._parse_forum_post(post_data)
            # post to discord if instructed
            if args.post:
                forum_spy._post_in_discord(post)
                time.sleep(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Test the forum spy AJAX parser, or generate test data"
    )
    parser.add_argument(
        "-a",
        "--add-post",
        type=int,
        nargs="+",
        required=False,
        help="One or more post IDs (int) to add to the test AJAX data",
    )
    parser.add_argument(
        "-d",
        "--delete-post",
        type=int,
        nargs="+",
        required=False,
        help="One or more post IDs (int) to remove from the test AJAX data",
    )
    parser.add_argument(
        "-t",
        "--test",
        action="store_true",
        help="Test the parser against the data in the test set",
    )
    parser.add_argument(
        "-p",
        "--post",
        action="store_true",
        help="Post the embed data to Discord (WARNING: ensure you are using a test webhook!)",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Remove all of the test data from the AJAX file (can use --add-post to replace data)",
    )
    main(parser.parse_args())
    print("done")
