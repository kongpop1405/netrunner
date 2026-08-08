import argparse

import pytest

from tools import run_sendlife_loop as rsl


def test_episode_list_parses_csv():
    assert rsl._episode_list("1,2,3,4,5,6") == [1, 2, 3, 4, 5, 6]


def test_episode_list_strips_whitespace():
    assert rsl._episode_list(" 2, 4 ,6") == [2, 4, 6]


def test_episode_list_rejects_empty():
    with pytest.raises(argparse.ArgumentTypeError):
        rsl._episode_list("")


def test_episode_list_rejects_non_int():
    with pytest.raises(argparse.ArgumentTypeError):
        rsl._episode_list("1,two,3")


def test_default_order_is_episodes_1_through_6():
    ap = argparse.ArgumentParser()
    ap.add_argument("--order", type=rsl._episode_list, default=[1, 2, 3, 4, 5, 6])
    assert ap.parse_args([]).order == [1, 2, 3, 4, 5, 6]


def test_custom_order_overrides_default():
    ap = argparse.ArgumentParser()
    ap.add_argument("--order", type=rsl._episode_list, default=[1, 2, 3, 4, 5, 6])
    assert ap.parse_args(["--order", "3,1"]).order == [3, 1]
