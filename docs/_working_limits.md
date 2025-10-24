The `working_limit` differs from the `time_limit` in that it measures only the time spent working (as opposed to retrying in response to rate limits or waiting on other shared resources). Working time is computed based on total clock time minus time spent on (a) unsuccessful model generations (e.g. rate limited requests); and (b) waiting on shared resources (e.g. Docker containers or subprocess execution).

::: {.callout-note appearance="simple"}
In order to distinguish successful generate requests from rate limited and retried requests, Inspect installs hooks into the HTTP client of various model packages. This is not possible for some models (`azureai`) and in these cases the `working_time` will include any internal retries that the model client performs.
:::
