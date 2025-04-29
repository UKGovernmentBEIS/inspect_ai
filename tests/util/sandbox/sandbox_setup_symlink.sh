#!/usr/bin/env bash

# Base file
echo "hello world" > foo.txt

# Simple relative symlink from current dir
ln -s foo.txt link_simple

# Explicit “./” prefix
ln -s ./foo.txt link_dot_slash

# Create a nested directory and symlink via “..”
mkdir -p nested/inner
# from nested/, go up one level to find foo.txt
ln -s ../foo.txt nested/link_up_one
# from nested/inner/, go up two levels to find foo.txt
ln -s ../../foo.txt nested/inner/link_up_two

# Absolute symlink for comparison
ln -s "$(pwd)/foo.txt" link_absolute


# Simple relative symlink from current dir
ln -s missing missing_simple

# Explicit “./” prefix
ln -s ./missing missing_dot_slash

# from nested/, go up one level to find foo.txt
ln -s ../missing nested/missing_up_one
# from nested/inner/, go up two levels to find foo.txt
ln -s ../../missing nested/inner/missing_up_two

# Absolute symlink for comparison
ln -s "$(pwd)/missing" missing_absolute

