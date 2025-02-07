

When working with datasets that contain multiple-choice options, you can randomize the order of these choices during data loading. The shuffling operation automatically updates any corresponding target values to maintain correct answer mappings.

For datasets that contain `choices`, you can shuffle the choices when the data is loaded. Shuffling choices will randomly re-order the choices and update the sample's target value or values to align with the shuffled choices.

There are two ways to shuffle choices:

```python
# Method 1: Using the dataset method
dataset = dataset.shuffle_choices()

# Method 2: During dataset loading
dataset = json_dataset("data.jsonl", shuffle_choices=True)
```

For reproducible shuffling, you can specify a random seed:

```python
# Using a seed with the dataset method
dataset = dataset.shuffle_choices(seed=42)

# Using a seed during loading
dataset = json_dataset("data.jsonl", shuffle_choices=42)
```
