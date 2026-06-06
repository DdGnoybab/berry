"""Pytest 功能演示."""

from __future__ import annotations

import pytest


# 1. 基础断言
def test_basic_assert():
    assert 1 + 1 == 2
    assert "hello".upper() == "HELLO"
    assert [1, 2, 3][-1] == 3


# 2. 异常测试
def test_exception():
    with pytest.raises(ZeroDivisionError):
        1 / 0


# 3. 参数化测试
@pytest.mark.parametrize(
    ("input", "expected"),
    [
        (1, 1),
        (2, 4),
        (3, 9),
        (4, 16),
    ],
)
def test_square(input: int, expected: int):
    assert input**2 == expected


# 4. Fixture（测试前置/后置）
@pytest.fixture
def sample_list():
    return [3, 1, 4, 1, 5, 9]


def test_fixture_usage(sample_list: list[int]):
    assert sorted(sample_list) == [1, 1, 3, 4, 5, 9]
    assert len(sample_list) == 6


# 5. 类组织
class TestStringMethods:
    def test_split(self):
        assert "hello world".split() == ["hello", "world"]

    def test_strip(self):
        assert "  foo  ".strip() == "foo"

    def test_replace(self):
        assert "hello".replace("e", "a") == "hallo"


# 6. 跳过与标记
@pytest.mark.skip(reason="演示跳过")
def test_skipped():
    assert False


@pytest.mark.xfail(reason="预期失败")
def test_expected_fail():
    assert 1 == 2
