# Environment

The `kali-base` image in the `Dockerfile` is a container based on `kalilinux/kaling-rolling` with the
`kali-linux-headless` metapackage installed:

```
$ docker run --name kali-base --tty --interactive kalilinux/kali-rolling

# apt update
# apt full-upgrade -y
# apt install -y kali-linux-headless
...
# exit

$ docker commit kali-base
```
