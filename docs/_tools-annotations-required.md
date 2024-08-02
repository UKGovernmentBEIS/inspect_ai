Note that we provide type annotations for both arguments:

``` python
async def execute(x: int, y: int)
```

Further, we provide descriptions for each parameter in the documention comment:

```python
Args:
    x: First number to add.
    y: Second number to add.
```

Type annotations and descriptions are *required* for tool declarations so that the model can be informed which types to pass back to the tool function and what the purpose of each parameter is.
