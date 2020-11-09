#!/usr/bin/env python3
from datetime import datetime
from http import cookiejar
import json
import os
import re
import requests
import shutil
import tempfile
import traceback
import yaml
try:
    from yaml import CLoader as Loader, CDumper as Dumper
except ImportError:
    from yaml import Loader, Dumper

class WeverseUrls:
    info = 'https://weversewebapi.weverse.io/wapi/v1/communities/info'
    artistTab = 'https://weversewebapi.weverse.io/wapi/v1/communities/{}/posts/artistTab'
    toFans = 'https://weversewebapi.weverse.io/wapi/v1/stream/community/{}/toFans?pageSize=100&from={}'
    post = 'https://weversewebapi.weverse.io/wapi/v1/communities/{}/posts/{}'

config = {}

def dwexit(code):
    if 'keepOpen' not in config or config['keepOpen']:
        input(f'Press Enter to exit')
    exit(code)


def download_post(post, artist_id, post_type, combine_categories=False):
    with tempfile.TemporaryDirectory() as temp_dir:
        if combine_categories:
            post_type = ''
        post_id = post['id']
        user = post['communityUser']['profileNickname']
        user_image_url = post['communityUser']['profileImgPath']
        body = post['body']
        dt = datetime.strptime(post['createdAt'], '%Y-%m-%dT%H:%M:%S%z')
        ts = dt.timestamp()
        date_str = dt.strftime("%y%m%d")
        ts_str = str(dt)
        filename_prefix = f'{date_str}_{post_id}_{user}'
        dir_path = os.path.join(config['downloadPath'], post_type, filename_prefix)

        # check if already downloaded
        if os.path.exists(dir_path):
            return
        
        print(f'Downloading {filename_prefix}')

        # download photos
        if 'photos' in post:
            for i,photo in enumerate(post['photos']):
                # get photo extension
                match = re.match(r'.*\.(?P<ext>.+)$', photo['orgImgUrl'])
                ext = match.group('ext')

                # download photo
                photo_path = os.path.join(temp_dir, f'{filename_prefix}_img{i:02d}.{ext}') 
                download_media(photo['orgImgUrl'], photo_path)

        # download videos
        if 'attachedVideos' in post:
            r = s.get(WeverseUrls.post.format(artist_id, post_id))
            post_detail = r.json()
            for i,video in enumerate(post_detail['attachedVideos']):
                # get video extension
                match = re.match(r'.*\.(?P<ext>.+)$', video['videoUrl'])
                ext = match.group('ext')

                # download video
                video_path = os.path.join(temp_dir, f'{filename_prefix}_vid{i:02d}.{ext}') 
                download_media(video['videoUrl'], video_path)


        # write content txt
        content_path = os.path.join(temp_dir, f'{filename_prefix}_content.txt')
        write_content(content_path, post_id, user, body, ts_str, ts)

        os.utime(temp_dir, (ts, ts))

        # atomically copy to destination
        path = os.path.join(config['downloadPath'], post_type)
        shutil.move(temp_dir, path)
        temp_dir2 = os.path.join(path, os.path.basename(temp_dir))
        os.rename(temp_dir2, dir_path)


def download_media(url, path, ts=None):
    r = requests.get(url)
    if not r.ok:
        raise Exception("Could not download image")
    with open(path, 'wb') as f:
        f.write(r.content)
        if ts is not None:
            os.utime(path, (ts, ts))


def write_content(path, post_id, user, body, ts_str, ts):
    with open(path, 'w', encoding='utf-8') as f:
        print(f'https://weverse.io/{config["artist"].lower()}/artist/{post_id}', file=f)
        print(f'{user} ({ts_str}):', file=f)
        print(f'{body}', file=f)
    os.utime(path, (ts, ts))

def main():
    global config
    global s

    # read config
    with open('config.yml', 'r') as f:
        config = yaml.load(f, Loader=Loader)
    if 'combineCategories' in config and config['combineCategories']:
        combine_categories = True
        os.makedirs(config['downloadPath'], exist_ok=True)
    else:
        combine_categories = False
        artist_path = os.path.join(config['downloadPath'], 'artist')
        moments_path = os.path.join(config['downloadPath'], 'moments')
        os.makedirs(artist_path, exist_ok=True)
        os.makedirs(moments_path, exist_ok=True)

    # load cookies file
    cj = cookiejar.MozillaCookieJar(config['cookiesFile'])
    cj.load()

    s = requests.session()

    # set cookie
    s.cookies = cj

    # set header
    for cookie in cj:
        if cookie.name == 'we_access_token':
            s.headers.update({'Authorization': f'Bearer {cookie.value}'})
            break;

    # get artist id
    print('Fetching artist id...')
    r = s.get(WeverseUrls.info)
    for community in r.json()['communities']:
        if config['artist'].lower() == community['name'].lower():
            artist_id = community['id']


    download_kwargs = {
        'combine_categories': combine_categories,
    }

    # get posts
    print('Downloading posts...')
    r = s.get(WeverseUrls.artistTab.format(artist_id))
    posts = r.json()['posts']
    # download posts
    for post in posts:
        download_post(post, artist_id, 'artist', **download_kwargs)

    # get moments
    print('Downloading moments...')
    last_id = ''
    while True:
        r = s.get(WeverseUrls.toFans.format(artist_id, last_id))
        moments = r.json()['posts']
        ended = r.json()['isEnded']
        # download moments
        for moment in moments:
            download_post(moment, artist_id, 'moments', **download_kwargs)

        if ended:
            break

        last_id = r.json()['lastId']


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        traceback.print_exc()
        dwexit(1)
    print('Download complete')
    dwexit(0)
