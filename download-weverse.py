#!/usr/bin/env python3
from datetime import datetime
from functools import partial
from http import cookiejar
from multiprocessing import Pool
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
    artistTab = 'https://weversewebapi.weverse.io/wapi/v1/communities/{}/posts/artistTab?pageSize={}&from={}'
    mediaTab = 'https://weversewebapi.weverse.io/wapi/v1/stream/community/{}/mediaTab?pageSize={}&from={}'
    toFans = 'https://weversewebapi.weverse.io/wapi/v1/stream/community/{}/toFans?pageSize={}&from={}'
    post = 'https://weversewebapi.weverse.io/wapi/v1/communities/{}/posts/{}'
    videoDash = 'https://cdn-media.weverse.io/video{}/DASH.mpd'

config = {}

def init_session(config):
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

    return s


def dwexit(code):
    if 'keepOpen' not in config or config['keepOpen']:
        input(f'Press Enter to exit')
    exit(code)


def download_post(artist_id, download_dir, config, post):
    with tempfile.TemporaryDirectory() as temp_dir:
        post_id = post['id']
        user = post['communityUser']['profileNickname']
        user_image_url = post['communityUser']['profileImgPath']
        body = post.get('body', '')
        dt = datetime.strptime(post['createdAt'], '%Y-%m-%dT%H:%M:%S%z')
        ts = dt.timestamp()
        date_str = dt.strftime("%y%m%d")
        ts_str = str(dt)
        filename_prefix = f'{date_str}_{post_id}_{user}'
        dir_path = os.path.join(download_dir, filename_prefix)

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
            url = WeverseUrls.post.format(artist_id, post_id)
            print(f'GET {url}')
            s = init_session(config)
            r = s.get(url)
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
        write_content(content_path, post_id, user, body, ts_str, ts, config)

        os.utime(temp_dir, (ts, ts))

        # atomically copy to destination
        path = download_dir
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


def write_content(path, post_id, user, body, ts_str, ts, config):
    with open(path, 'w', encoding='utf-8') as f:
        print(f'https://weverse.io/{config["artist"].lower()}/artist/{post_id}', file=f)
        print(f'{user} ({ts_str}):', file=f)
        print(f'{body}', file=f)
    os.utime(path, (ts, ts))


def download_videos(artist_id, config, media):
    if media['type'].lower() != 'video':
        return
    if 'extVideoPath' in media:
        return
    media_id = media['id']
    vid_id = media['video']['id']
    title = media['title']
    dt = datetime.strptime(media['createdAt'], '%Y-%m-%dT%H:%M:%S%z')
    ts = dt.timestamp()
    date_str = dt.strftime("%y%m%d")
    ts_str = str(dt)
    filename = f'{date_str}_{media_id}_{title}.mp4'

    dir_path = config['videosDownloadPath']
    if os.path.exists(os.path.join(dir_path, filename)):
        return

    # download video via youtube-dl
    import youtube_dl
    print(f'Downloading {filename}')
    ydl_opts = {
        'outtmpl': os.path.join(dir_path, filename),
        'cookiefile': config['cookiesFile'],
    }
    with youtube_dl.YoutubeDL(ydl_opts) as ydl:
        ydl.download([WeverseUrls.videoDash.format(vid_id)])


def main():
    # read config
    with open('config.yml', 'r') as f:
        config = yaml.load(f, Loader=Loader)
    num_processes = int(config.get('numProcesses', None))

    s = init_session(config)

    # get artist id
    print('Fetching artist id...')
    print(f'GET {WeverseUrls.info}')
    r = s.get(WeverseUrls.info)
    for community in r.json()['communities']:
        if config['artist'].lower() == community['name'].lower():
            artist_id = community['id']

    # get posts
    artist_path = config['artistDownloadPath']
    os.makedirs(artist_path, exist_ok=True)
    print('Downloading posts...')
    last_id = ''
    posts_remain = config.get('recentArtist', None)
    while True:
        if posts_remain is not None:
            url = WeverseUrls.artistTab.format(artist_id, posts_remain, last_id)
        else:
            url = WeverseUrls.artistTab.format(artist_id, 100, last_id)
        print(f'GET {url}')
        r = s.get(url)
        posts = r.json()['posts']
        if posts_remain is not None:
            posts_remain -= len(posts)
        ended = r.json()['isEnded']
        # download posts
        func = partial(download_post, artist_id, artist_path, config)
        with Pool(num_processes) as pool:
            pool.map(func, posts)
        if ended or (posts_remain is not None and posts_remain <= 0):
            break
        last_id = r.json()['lastId']

    # get moments
    moments_path = config['momentsDownloadPath']
    os.makedirs(moments_path, exist_ok=True)
    print('Downloading moments...')
    last_id = ''
    moments_remain = config.get('recentMoments', None)
    while True:
        if moments_remain is not None:
            url = WeverseUrls.toFans.format(artist_id, moments_remain, last_id)
        else:
            url = WeverseUrls.toFans.format(artist_id, 100, last_id)
        print(f'GET {url}')
        r = s.get(url)
        moments = r.json()['posts']
        if moments_remain is not None:
            moments_remain -= len(moments)
        ended = r.json()['isEnded']
        # download moments
        func = partial(download_post, artist_id, moments_path, config)
        with Pool(num_processes) as pool:
            pool.map(func, moments)
        if ended or (moments_remain is not None and moments_remain <= 0):
            break
        last_id = r.json()['lastId']

    # get videos
    if config.get('downloadVideos', False):
        videos_path = os.path.join(config['videosDownloadPath'])
        os.makedirs(videos_path, exist_ok=True)
        print('Downloading videos...')
        last_id = ''
        videos_remain = config.get('recentVideos', None)
        while True:
            if videos_remain is not None:
                url = WeverseUrls.mediaTab.format(artist_id, videos_remain, last_id)
            else:
                url = WeverseUrls.mediaTab.format(artist_id, 100, last_id)
            print(f'GET {url}')
            r = s.get(url)
            videos = r.json()['medias']
            if videos_remain is not None:
                videos_remain -= len(videos)
            ended = r.json()['isEnded']
            # download videos
            func = partial(download_videos, artist_id, config)
            with Pool(num_processes) as pool:
                pool.map(func, videos)
            if ended or (videos_remain is not None and videos_remain <= 0):
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
