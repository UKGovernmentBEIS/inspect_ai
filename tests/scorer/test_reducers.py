from inspect_ai.scorer import Score, at_least, avg, best_of, majority, median

avg_reducer = avg()
median_reducer = median()
majority_reducer = majority()
best_reducer = best_of()
at_least_3_reducer = at_least(3)
at_least_4_reducer = at_least(4)
at_least_5_reducer = at_least(5, 3)


def test_simple_reducers() -> None:
    simple_scores = [
        Score(value=6),
        Score(value=2),
        Score(value=2),
        Score(value=3),
        Score(value=2),
        Score(value=3),
    ]
    assert avg_reducer(simple_scores).value == 3.0
    assert median_reducer(simple_scores).value == 2.5
    assert majority_reducer(simple_scores).value == 2.0
    assert best_reducer(simple_scores).value == 6.0
    assert at_least_3_reducer(simple_scores).value == 1
    assert at_least_4_reducer(simple_scores).value == 0


def test_list_reducers() -> None:
    list_scores = [
        Score(value=[1, 2]),
        Score(value=[4, 3]),
        Score(value=[3, 1]),
        Score(value=[1, 2]),
        Score(value=[1, 2]),
    ]
    assert avg_reducer(list_scores).value == [2, 2]
    assert median_reducer(list_scores).value == [1, 2]
    assert majority_reducer(list_scores).value == [1, 2]
    assert best_reducer(list_scores).value == [4, 3]
    assert at_least_3_reducer(list_scores).value == [1, 1]
    assert at_least_4_reducer(list_scores).value == [0, 0]


def test_dict_reducers() -> None:
    dict_scores = [
        Score(value={"coolness": 5, "spiciness": 1}),
        Score(value={"coolness": 4, "spiciness": 1}),
        Score(value={"coolness": 3, "spiciness": 1}),
        Score(value={"coolness": 2, "spiciness": 1}),
        Score(value={"coolness": 1, "spiciness": 21}),
    ]
    assert avg_reducer(dict_scores).value == {"coolness": 3, "spiciness": 5}
    assert median_reducer(dict_scores).value == {"coolness": 3, "spiciness": 1}
    assert majority_reducer(dict_scores).value == {"coolness": 5, "spiciness": 1}
    assert best_reducer(dict_scores).value == {"coolness": 5, "spiciness": 21}
    assert at_least_3_reducer(dict_scores).value == {"coolness": 1, "spiciness": 1}
    assert at_least_4_reducer(dict_scores).value == {"coolness": 1, "spiciness": 1}
    assert at_least_5_reducer(dict_scores).value == {"coolness": 0, "spiciness": 0}
