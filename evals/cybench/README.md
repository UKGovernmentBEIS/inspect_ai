
To run all challenges:
```sh
inspect eval task.py --model openai/gpt-4o
```

To run a subset of challenges
```sh
inspect eval task.py --model openai/gpt-4o -T challenges=avatar,chunky
```

To override the default values of the task, you can use the `-T` flag.
For example, to change the number of attempts and the maximum number of messages:
```sh
inspect eval task.py --model openai/gpt-4o -T max_attempts=2 -T max_messages=75
```

## TODO:
- Document `files` "merging" behaviour
- Document that images will be available from a public registry but the source is
  included for reference (and some files are copied into the container at runtime).
