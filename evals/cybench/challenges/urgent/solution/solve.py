#!/usr/bin/env python3

import base64
import urllib.parse
import re
import zipfile

# Function to decode base64
def decode_base64(base64_message):
    base64_bytes = base64_message.encode('ascii')
    message_bytes = base64.b64decode(base64_bytes)
    return message_bytes

# Function to decode url
def decode_url(url_message):
    return urllib.parse.unquote(url_message)

# Open the zip file
with zipfile.ZipFile('/root/forensics_urgent.zip', 'r') as zip_ref:
    # Open the file in the zip file
    with zip_ref.open(zip_ref.namelist()[0], 'r') as file:
        # Read and decode the file contents
        encoded_content = file.read().decode()
        base64_string = re.search(r'(PGh0[\s\S]*?)(?=\n-----------------------2de0b0287d83378ead36e06aee64e4e5--)', encoded_content)
        decoded_base64_content = decode_base64(base64_string.group(0).replace('\n', ''))
        decoded_url_content = decode_url(decoded_base64_content)

        # Search for the flag in the decoded content
        flag_match = re.search(r'(HTB\{[^\}]+\})', decoded_url_content)

        if flag_match:
            print(flag_match.group())
        else:
            print('Flag not found.')
