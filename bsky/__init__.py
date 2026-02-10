import machine
machine.freq(220000000)

APP_DIR = "/bsky"
TMP_DIR = "/tmp/bsky/"

import sys
import os
import wifi
import secrets
import time
import ntptime
import requests
import micropython

# Standalone bootstrap for finding app assets
os.chdir(APP_DIR)

font_bold = font.load("osansb.af")
font_sans = font.load("osans.af")
icons = SpriteSheet("icons30b.png", 4, 2)

# Standalone bootstrap for module imports
sys.path.insert(0, APP_DIR)

from usermessage import user_message
from text import clean_text

from atprototools import Session


if 'bsky' not in os.listdir('/tmp'):
    os.mkdir('/tmp/bsky')

class BskyState:
    Running = 0
    ConnectWiFi = 1
    UpdateTime = 2
    ConnectBsky = 3
    DisplayImage = 4
    DisplayQuote = 5

bsky_state = BskyState.ConnectWiFi
session = None

UPDATE_INTERVAL = 60
last_update_time = 0

bloot_bounds =      rect( 5, 66, 310, 148)
avatar_bounds =     rect( 5,  5,  60, 60)
name_bounds =       rect(75, 35, 240, 25)
like_bounds =       rect(47, 214, 30, 26)
like_num_bounds =   rect(80, 214, 50, 21)
repost_bounds =     rect(145, 214, 30, 26)
repost_num_bounds = rect(178, 214, 50, 21)
has_image_bounds =  rect(243, 214, 30, 26)

image_bounds =      rect( 5, 68, 310, 170)

bloot_above_qb_bounds = rect( 5,  66, 310, 76)
default_qb_avatar_bounds = rect(12, 73,  28, 28)
default_qb_name_bounds =   rect(48, 75, 235, 25)
default_qb_bloot_bounds =  rect(12, 100, 310, 114)

# Low res until connected
badge.mode(LORES)
screen.antialias = OFF

bloot_idx = 0

def copy_rect(r):
    return rect(r.x, r.y, r.w, r.h)

def get_tmp_free():
    stat = os.statvfs('/tmp')
    return stat[0] * stat[4]

# Remove 5 least recently used files
def clean_tmp():
    files = []
    for file in os.listdir(TMP_DIR):
        files.append((file, os.stat(TMP_DIR + file)[7]))
    
    files.sort(key=lambda f: f[1])
    for f in files[:5]:
        os.remove(TMP_DIR + f[0])

def display_uri(uri, bounds, temp=False, scale_to_height=False):
    # Make a copy of bounds so we don't modify the incoming value
    bounds = copy_rect(bounds)
    
    target_height = bounds.h if scale_to_height else 0
    
    if not temp:
        FILENAME = uri.split('/')[-1]
        PATHNAME = TMP_DIR + FILENAME
        
        if FILENAME not in os.listdir(TMP_DIR):
            badge.set_caselights(1)
            
            if get_tmp_free() < 100 * 1024:
                print("Cleaning temp")
                clean_tmp()
            
            resp = requests.get(uri)
            with open(PATHNAME, "wb") as f:
                f.write(resp.content)
        
        img = image.load(PATHNAME, 0, target_height)
    else:
        badge.set_caselights(1)
        img = image.load(requests.get(uri).content, 0, target_height)
    
    if scale_to_height:
        if bounds.w > img.width:
            #bounds.x += (bounds.w - img.width) / 2
            bounds.w = img.width
            print(bounds.h, bounds.w, img.height, img.width)
        elif bounds.w < img.width:
            bounds.h = img.height * (bounds.w / img.width)
            print(bounds.h, bounds.w, img.height, img.width)
    
    screen.blit(img, bounds)
    badge.set_caselights(0)
    

def display_avatar(uri, bounds):
    if uri.endswith("@jpeg"):
        uri = uri[:-4] + 'png'
    
    if not 'img/avatar/plain' in uri or not uri.endswith("@png"):
        return
    
    uri = uri.replace("img/avatar/plain", "img/avatar_thumbnail/plain")
    display_uri(uri, bounds)
    
def display_user(bloot, bloot_height=None):
    screen.font = font_bold
    
    if bloot_height:
        my_avatar_bounds = copy_rect(default_qb_avatar_bounds)
        my_avatar_bounds.y += bloot_height
        
        my_name_bounds = copy_rect(default_qb_name_bounds)
        my_name_bounds.y += bloot_height
    else:
        my_avatar_bounds = avatar_bounds
        my_name_bounds = name_bounds
    
    if 'author' in bloot:
        if 'avatar' in bloot['author']:
            display_avatar(bloot['author']['avatar'], my_avatar_bounds)

        display_name = clean_text(bloot['author']['displayName'])
        if display_name == '':
            display_name = '@' + bloot['author']['handle']
            screen.font = font_sans
        text.draw(screen, display_name, my_name_bounds, size=21)
        
    
    
def display_image(bloot, show_back=True, is_qb=False):
    print("Render image")
    
    if is_qb:
        if 'media' in bloot['embeds'][0]:
            uri = bloot['embeds'][0]['media']['images'][0]['thumb']
        else:
            uri = bloot['embeds'][0]['images'][0]['thumb']
    elif 'media' in bloot['embed']:
        uri = bloot['embed']['media']['images'][0]['thumb']
    else:
        uri = bloot['embed']['images'][0]['thumb']

    screen.pen = color.black
    screen.clear()
    screen.pen = color.white
    
    if uri.endswith('@png'):
        uri = uri[:-3] + 'jpeg'
    
    if not uri.endswith("@jpeg"):
        print("Invalid image: " + uri)
        return
    
    display_user(bloot)
    
    display_uri(uri, image_bounds, True, True)
    
    if show_back:
        screen.blit(icons.sprite(3, 1), has_image_bounds)


def has_image(bloot, is_qb):
    record = bloot['value'] if is_qb else bloot
    return ('embed' in record and
            (('media' in record['embed'] and
              'images' in record['embed']['media']) or
             'images' in record['embed']))

def has_qb(bloot):
    return 'embed' in bloot and 'record' in bloot['embed'] and 'value' in bloot['embed']['record']

def update_display(use_qb=False):
    global bloot_idx, last_update_time
    
    bloot_idx = min(bloot_idx, len(root_bloots) - 1)
    
    bloot = root_bloots[bloot_idx]
    record = 'record'
    if use_qb:
        bloot = bloot['embed']['record']
        record = 'value'
    
    last_update_time = time.time()
    
    bloot_text = clean_text(bloot[record]['text'])
    
    if len(bloot_text) == 0 and has_image(bloot, use_qb):
        display_image(bloot, use_qb, use_qb)
        return
    
    screen.pen = color.black
    screen.clear()
    screen.pen = color.white
    
    display_user(bloot)
    
    qb = None
    if has_qb(bloot):
        qb = bloot['embed']['record']
    
    screen.font = font_sans
    bloot_height = text.draw(screen, bloot_text, bloot_bounds if qb is None else bloot_above_qb_bounds, size=18).h
    
    if qb:
        bloot_height = min(bloot_height, bloot_above_qb_bounds.h)
        qb_bloot_bounds = copy_rect(default_qb_bloot_bounds)
        qb_bloot_bounds.y += bloot_height
        qb_bloot_bounds.h -= bloot_height
        text.draw(screen, clean_text(qb['value']['text']), qb_bloot_bounds, size=18)
        display_user(qb, bloot_height)
    
    if use_qb:
        screen.blit(icons.sprite(3, 1), has_image_bounds)
        if has_image(bloot, True):
            screen.blit(icons.sprite(2, 0), like_bounds)
    else:
        if 'likeCount' in bloot:
            if 'viewer' in bloot and 'like' in bloot['viewer']:
                screen.blit(icons.sprite(0, 0), like_bounds)
            else:
                screen.blit(icons.sprite(0, 1), like_bounds)
            text.draw(screen, str(bloot['likeCount']), like_num_bounds, size=16)
        if 'repostCount' in bloot:
            if 'viewer' in bloot and 'repost' in bloot['viewer']:
                screen.blit(icons.sprite(1, 0), repost_bounds)
            else:
                screen.blit(icons.sprite(1, 1), repost_bounds)
            text.draw(screen, str(bloot['repostCount']), repost_num_bounds, size=16)
        if qb:
            screen.blit(icons.sprite(2, 1), has_image_bounds)
        elif has_image(bloot, False):
            screen.blit(icons.sprite(2, 0), has_image_bounds)
    

def fetch_bloots(cur_cid = None):
    global session, bloot_idx, root_bloots
    
    bloot_idx = 0
    num_bloots = 30
    print("Fetch bloots...")
    badge.set_caselights(1)
    resp = session.getSkyline(num_bloots).json()
    if 'error' in resp:
        print(f"Session error: {resp['message']}")
        session = Session(secrets.BSKY_USERNAME, secrets.BSKY_PASSWORD)
        print("Fetching again...")
        resp = session.getSkyline(num_bloots).json()
    skyline = resp['feed']
    print("  fetched.")
    badge.set_caselights(0)
    
    root_bloots = []
    bloot_cids = []
    for entry in skyline:
        if 'post' not in entry: continue
        bloot = entry['post']
        if 'record' not in bloot: continue
        if 'reply' in bloot['record']: continue
        if bloot['cid'] in bloot_cids: continue
        
        if bloot['cid'] == cur_cid:
            bloot_idx = len(root_bloots)
        
        root_bloots.append(bloot)
        bloot_cids.append(bloot['cid'])


def display_skyline():
    global last_update_time, session, bloot_idx, root_bloots, bsky_state
    
    need_fetch = time.time() - last_update_time >= UPDATE_INTERVAL
    
    need_display_update = need_fetch
    if badge.pressed(BUTTON_UP):
        if bloot_idx > 0: bloot_idx -= 1
        else: need_fetch = True
        need_display_update = True
    if badge.pressed(BUTTON_DOWN):
        bloot_idx += 1
        need_display_update = True

    if badge.pressed(BUTTON_C):
        if has_qb(root_bloots[bloot_idx]):
            update_display(True)
            bsky_state = BskyState.DisplayQuote
        elif has_image(root_bloots[bloot_idx], False):
            display_image(root_bloots[bloot_idx])
            bsky_state = BskyState.DisplayImage
        
    cid = None
    if badge.pressed(BUTTON_A):
        cid = root_bloots[bloot_idx]['cid']
        session.like(cid, root_bloots[bloot_idx]['uri'])
        need_fetch = True
        need_display_update = True
    if badge.pressed(BUTTON_B):
        cid = root_bloots[bloot_idx]['cid']
        session.rebloot(cid, root_bloots[bloot_idx]['uri'])
        need_fetch = True
        need_display_update = True
    
    if need_fetch:
        fetch_bloots(cid)
    
    if need_display_update:
        update_display()


def update():
    global session, bsky_state, last_update_time, bloot_idx

    if bsky_state == BskyState.Running:
        display_skyline()

    elif bsky_state == BskyState.ConnectBsky:
        session = Session(secrets.BSKY_USERNAME, secrets.BSKY_PASSWORD)
        fetch_bloots()
        last_update_time = time.time()
        bloot_idx = 0
        bsky_state = BskyState.Running
        badge.default_clear(None)
        badge.mode(HIRES)
        screen.antialias = image.X4
        update_display()      

    elif bsky_state == BskyState.UpdateTime:
        user_message("Please Wait", ["Connecting to Bluesky..."])
        #ntptime.settime()
        bsky_state = BskyState.ConnectBsky

    elif bsky_state == BskyState.ConnectWiFi:
        user_message("Please Wait", ["Connecting to WiFi..."])
        if wifi.connect():
            bsky_state = BskyState.UpdateTime

    elif bsky_state == BskyState.DisplayImage or bsky_state == BskyState.DisplayQuote:
        if bsky_state == BskyState.DisplayQuote and badge.pressed(BUTTON_A) and has_image(root_bloots[bloot_idx]['embed']['record'], True):
            display_image(root_bloots[bloot_idx]['embed']['record'], True, True)
            bsky_state = BskyState.DisplayImage
        if badge.pressed(BUTTON_C):
            bsky_state = BskyState.Running
            update_display()
        if badge.pressed(BUTTON_UP):
            if bloot_idx > 0: bloot_idx -= 1
            bsky_state = BskyState.Running
            update_display()
        if badge.pressed(BUTTON_DOWN):
            bloot_idx += 1
            bsky_state = BskyState.Running
            update_display()


# Standalone support for Thonny debugging
if __name__ == "__main__":
    run(update)

