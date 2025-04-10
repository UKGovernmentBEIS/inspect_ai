
If you don't have a custom Dockerfile, you can alternatively use the pre-built `aisiuk/inspect-tool-support` image:

``` {.yaml filename="compose.yaml"}
services:
  default:
    image: aisiuk/inspect-tool-support
    init: true
```

