#!/bin/bash

apt-get update -qq && apt-get -y install -qq cmake protobuf-compiler

pip install -qq pwntools==4.11.0 jwcrypto==1.5.6 PyJWT==2.9.0
