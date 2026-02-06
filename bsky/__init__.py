APP_DIR = "/bsky"

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

from ramfs import mkramfs
from usermessage import user_message
from text import clean_text

from atprototools import Session


mkramfs(1024 * 1024)

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

bloot_bounds =      rect( 5, 70, 310, 144)
avatar_bounds =     rect( 5,  5,  60, 60)
name_bounds =       rect(75, 35, 240, 25)
like_bounds =       rect(48, 214, 30, 26)
like_num_bounds =   rect(81, 214, 50, 21)
repost_bounds =     rect(145, 214, 30, 26)
repost_num_bounds = rect(178, 214, 50, 21)
has_image_bounds =  rect(243, 214, 30, 26)

image_bounds =      rect( 5, 70, 310, 190)

# Low res until connected
badge.mode(LORES)
screen.antialias = OFF

bloot_idx = 0


def display_png(uri, bounds, temp=False, fixed_scale=False):
    if temp:
        FILENAME = 'temp.png'
    else:
        FILENAME = uri.split('/')[-1]
    PATHNAME = '/ramfs/' + FILENAME
    
    if FILENAME not in os.listdir('/ramfs'):
        badge.set_caselights(1)
        resp = requests.get(uri)
        with open(PATHNAME, "wb") as f:
            f.write(resp.content)
    
    png = image.load(PATHNAME)
    
    if fixed_scale:
        bounds_ratio = bounds.h / bounds.w
        png_ratio = png.height / png.width
        if png_ratio > bounds_ratio:
            # png taller than required bounds
            bounds.w = bounds.h * (bounds_ratio / png_ratio)
        elif png_ratio < bounds_ratio:
            bounds.h = bounds.w * (png_ratio / bounds_ratio)
    
    screen.blit(png, bounds)
    badge.set_caselights(0)
    

def display_avatar(uri, bounds):
    if uri.endswith("@jpeg"):
        uri = uri[:-4] + 'png'
    
    if not 'img/avatar/plain' in uri or not uri.endswith("@png"):
        return
    
    uri = uri.replace("img/avatar/plain", "img/avatar_thumbnail/plain")
    display_png(uri, bounds)
    
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
    
    if uri.endswith('@jpeg'):
        uri = uri[:-4] + 'png'
    
    if not uri.endswith("@png"):
        print("Invalid image: " + uri)
        return
    
    display_user(bloot)
    
    display_png(uri, image_bounds, True, True)


def has_image(bloot):
    return ('embed' in bloot['post'] and
            (('media' in bloot['post']['embed'] and
              'images' in bloot['post']['embed']['media']) or
             'images' in bloot['post']['embed']))

def update_display(bloots):
    screen.pen = color.black
    screen.clear()
    screen.pen = color.white
    
    bloot = bloots[bloot_idx]
    
    display_user(bloot)
    
    bloot_text = bloot['post']['record']['text']
    screen.font = font_sans
    text.draw(screen, clean_text(bloot_text), bloot_bounds, size=18)
    
    if 'likeCount' in bloot['post']:
        if 'viewer' in bloot['post'] and 'like' in bloot['post']['viewer']:
            screen.blit(icons.sprite(0, 1), like_bounds)
        else:
            screen.blit(icons.sprite(0, 1), like_bounds)
        text.draw(screen, str(bloot['post']['likeCount']), like_num_bounds, size=16)
    if 'repostCount' in bloot['post']:
        if 'viewer' in bloot['post'] and 'repost' in bloot['post']['viewer']:
            screen.blit(icons.sprite(1, 1), repost_bounds)
        else:
            screen.blit(icons.sprite(1, 1), repost_bounds)
        text.draw(screen, str(bloot['post']['repostCount']), repost_num_bounds, size=16)
    if has_image(bloot):
        screen.blit(icons.sprite(2, 0), has_image_bounds)
    

def display_skyline():
    global last_update_time, session, bloot_idx, root_bloots, bsky_state
    
    fetch_bloots = time.time() - last_update_time >= UPDATE_INTERVAL
    
    display_update = fetch_bloots
    if badge.pressed(BUTTON_UP):
        if bloot_idx > 0: bloot_idx -= 1
        else: fetch_bloots = True
        display_update = True
    if badge.pressed(BUTTON_DOWN):
        bloot_idx += 1
        display_update = True
    if badge.pressed(BUTTON_C) and has_image(root_bloots[bloot_idx]):
        display_image(root_bloots[bloot_idx])
        bsky_state = BskyState.DisplayImage
    
    if fetch_bloots:
        bloot_idx = 0
        num_bloots = 20
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
            root_bloots.append(bloot)
            bloot_cids.append(bloot['post']['cid'])
    
    
    if display_update:
        bloot_idx = min(bloot_idx, len(root_bloots) - 1)
            
        update_display(root_bloots)
        last_update_time = time.time()


def update():
    global session, bsky_state

    if bsky_state == BskyState.Running:
        display_skyline()

    elif bsky_state == BskyState.ConnectBsky:
        session = Session(secrets.BSKY_USERNAME, secrets.BSKY_PASSWORD)
        bsky_state = BskyState.Running
        badge.default_clear(None)
        badge.mode(HIRES)
        screen.antialias = image.X4
        screen.pen = color.black
        screen.clear()        

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
            update_display(root_bloots)


# Standalone support for Thonny debugging
#if __name__ == "__main__":
#    run(update)

