from typing import Literal

# this is duplicated in _computer.py
# changes should be synchronized!
Action = Literal[
    "key",
    "hold_key",
    "type",
    "cursor_position",
    "mouse_move",
    "left_mouse_down",
    "left_mouse_up",
    "left_click",
    "left_click_drag",
    "right_click",
    "middle_click",
    "back_click",
    "forward_click",
    "double_click",
    "triple_click",
    "scroll",
    "wait",
    "screenshot",
]
