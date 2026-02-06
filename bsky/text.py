import re

mapping = {
    0x2018: "'",
    0x2019: "'",
    0x201C: '"',
    0x201D: '"',
    0x2026: '...',
    }

def clean_text(text):
    chars = list(text)
    for i in range(len(chars)):
        o = ord(chars[i])
        if o > 0x7f:
            if o in mapping:
                chars[i] = mapping[o]
            elif 0x2000 <= o <= 0x200B:
                chars[i] = ' '
            elif 0x2010 <= o <= 0x2015:
                chars[i] = '-'
            else:
                chars[i] = '?'

    return "".join(chars)
