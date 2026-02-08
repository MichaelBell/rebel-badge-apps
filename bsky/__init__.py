APP_DIR = "/bsky"
TMP_DIR = "/tmp/bsky/"

import sys
import os
import wifi
import secrets
import time
import ntptime
import requests

# Standalone bootstrap for finding app assets
os.chdir(APP_DIR)

font_bold = font.load("osansb.af")
font_sans = font.load("osans.af")
icons = SpriteSheet("icons30b.png", 3, 2)

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

bsky_state = BskyState.ConnectWiFi
session = None

UPDATE_INTERVAL = 60
last_update_time = 0

bloot_bounds =      rect( 5, 68, 310, 146)
avatar_bounds =     rect( 5,  5,  60, 60)
name_bounds =       rect(75, 35, 240, 25)
like_bounds =       rect(47, 214, 30, 26)
like_num_bounds =   rect(80, 214, 50, 21)
repost_bounds =     rect(145, 214, 30, 26)
repost_num_bounds = rect(178, 214, 50, 21)
has_image_bounds =  rect(243, 214, 30, 26)

image_bounds =      rect( 5, 68, 310, 170)

# Low res until connected
badge.mode(LORES)
screen.antialias = OFF

bloot_idx = 0


def get_tmp_free():
    stat = os.statvfs('/tmp')
    return stat[0] * stat[4]

# Remove 10 least recently used files
def clean_tmp():
    files = []
    for file in os.listdir('/tmp'):
        files = (file, os.stat('/tmp/' + file)[7])
    
    files.sort(key=lambda f: f[1])
    for f in files[:10]:
        os.remove('/tmp/' + file)

def display_uri(uri, bounds, temp=False, scale_to_height=False):
    # Make a copy of bounds so we don't modify the incoming value
    bounds = rect(bounds.x, bounds.y, bounds.w, bounds.h)
    
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
            bounds.x += (bounds.w - img.width) / 2
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
    
def display_user(bloot):
    screen.font = font_bold
    
    if 'author' in bloot['post']:
        if 'avatar' in bloot['post']['author']:
            display_avatar(bloot['post']['author']['avatar'], avatar_bounds)

        display_name = clean_text(bloot['post']['author']['displayName'])
        if display_name == '':
            display_name = '@' + bloot['post']['author']['handle']
            screen.font = font_sans
        text.draw(screen, display_name, name_bounds, size=21)
        
    
    
def display_image(bloot):
    print("Render image")
    
    if 'media' in bloot['post']['embed']:
        uri = bloot['post']['embed']['media']['images'][0]['thumb']
    else:
        uri = bloot['post']['embed']['images'][0]['thumb']

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


def has_image(bloot):
    return ('embed' in bloot['post'] and
            (('media' in bloot['post']['embed'] and
              'images' in bloot['post']['embed']['media']) or
             'images' in bloot['post']['embed']))

def update_display():
    global bloot_idx, last_update_time
    
    bloot_idx = min(bloot_idx, len(root_bloots) - 1)
    
    bloot = root_bloots[bloot_idx]
    
    last_update_time = time.time()
    
    bloot_text = clean_text(bloot['post']['record']['text'])
    
    if len(bloot_text) == 0 and has_image(bloot):
        display_image(bloot)
        return
    
    screen.pen = color.black
    screen.clear()
    screen.pen = color.white
    
    display_user(bloot)
    
    screen.font = font_sans
    text.draw(screen, bloot_text, bloot_bounds, size=18)
    
    if 'likeCount' in bloot['post']:
        if 'viewer' in bloot['post'] and 'like' in bloot['post']['viewer']:
            screen.blit(icons.sprite(0, 0), like_bounds)
        else:
            screen.blit(icons.sprite(0, 1), like_bounds)
        text.draw(screen, str(bloot['post']['likeCount']), like_num_bounds, size=16)
    if 'repostCount' in bloot['post']:
        if 'viewer' in bloot['post'] and 'repost' in bloot['post']['viewer']:
            screen.blit(icons.sprite(1, 0), repost_bounds)
        else:
            screen.blit(icons.sprite(1, 1), repost_bounds)
        text.draw(screen, str(bloot['post']['repostCount']), repost_num_bounds, size=16)
    if has_image(bloot):
        screen.blit(icons.sprite(2, 0), has_image_bounds)
    

def fetch_bloots(cur_cid = None):
    global session, bloot_idx, root_bloots
    
    bloot_idx = 0
    num_bloots = 25
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
    for bloot in skyline:
        if 'record' not in bloot['post']: continue
        if 'reply' in bloot['post']['record']: continue
        if bloot['post']['cid'] in bloot_cids: continue
        
        if bloot['post']['cid'] == cur_cid:
            bloot_idx = len(root_bloots)
        
        root_bloots.append(bloot)
        bloot_cids.append(bloot['post']['cid'])
            

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

    # Disabled because tends to run out of RAM
    if badge.pressed(BUTTON_C) and has_image(root_bloots[bloot_idx]):
        display_image(root_bloots[bloot_idx])
        bsky_state = BskyState.DisplayImage
        
    cid = None
    if badge.pressed(BUTTON_A):
        cid = root_bloots[bloot_idx]['post']['cid']
        session.like(cid, root_bloots[bloot_idx]['post']['uri'])
        need_fetch = True
        need_display_update = True
    if badge.pressed(BUTTON_B):
        cid = root_bloots[bloot_idx]['post']['cid']
        session.rebloot(cid, root_bloots[bloot_idx]['post']['uri'])
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

    elif bsky_state == BskyState.DisplayImage:
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

