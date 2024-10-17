#!/usr/bin/env python3
from __future__ import annotations

import re

from pwn import args
from pwn import context
from pwn import log
from pwn import remote
from pwn import u64

FLAG_REGEX = re.compile(r"gctf{.*}")


def main() -> int:
    HOST = "localhost"
    PORT = 1337

    if args["HOST"]:
        HOST = args["HOST"]
    if args["PORT"]:
        PORT = args["PORT"]

    rem_con = remote(HOST, PORT)

    # derive the key
    context.update(arch='amd64', endian='big')
    key = hex(((0x5443474D489DFDD3 + 12345678) ^ u64(b'HACKERS!')) >> 5)
    
    rem_con.recvuntil(b"Please input your key")
    rem_con.sendline(key.encode())

    output = rem_con.recvuntil("}").decode()
    flag = FLAG_REGEX.findall(output)

    if flag:
        log.success(f"Flag: {flag[0]}")
    else:
        log.error("Flag not found")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
