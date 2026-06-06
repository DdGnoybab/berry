"""Python 常用特性演示."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import wraps
from typing import Any


# 1. Dataclass - 数据类
@dataclass
class User:
    name: str
    age: int
    tags: list[str] = field(default_factory=list)

    def greet(self) -> str:
        return f"你好，我是 {self.name}，今年 {self.age} 岁"


# 2. 装饰器
def log_call(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        print(f"调用: {func.__name__}")
        return func(*args, **kwargs)
    return wrapper


# 3. 类型注解 + 装饰器
@log_call
def add(a: int, b: int) -> int:
    return a + b


# 4. 生成器
def fibonacci(n: int):
    a, b = 0, 1
    for _ in range(n):
        yield a
        a, b = b, a + b


# 5. 列表推导 + 字典推导
def demo_comprehension():
    squares = [x**2 for x in range(10)]
    even_odd = {x: "偶" if x % 2 == 0 else "奇" for x in range(5)}
    return squares, even_odd


# 6. 模式匹配 (Python 3.10+)
def describe(value: Any) -> str:
    match value:
        case int():
            return f"整数: {value}"
        case str():
            return f"字符串: {value}"
        case list():
            return f"列表，长度 {len(value)}"
        case _:
            return f"其他类型: {type(value).__name__}"


# 7. 异步上下文管理器
class AsyncResource:
    async def __aenter__(self):
        print("获取资源")
        return self

    async def __aexit__(self, *args):
        print("释放资源")

    async def use(self):
        print("使用资源")


# 8. Protocol (结构化子类型)
class Drawable:
    def draw(self) -> str:
        ...


@dataclass
class Circle:
    radius: float

    def draw(self) -> str:
        return f"画圆，半径 {self.radius}"


@dataclass
class Square:
    side: float

    def draw(self) -> str:
        return f"画正方形，边长 {self.side}"


def render(shape: Drawable) -> str:
    return shape.draw()


# === 运行演示 ===
if __name__ == "__main__":
    # Dataclass
    user = User("张三", 25, ["开发者", "Python"])
    print(user.greet())

    # 装饰器
    result = add(3, 5)
    print(f"3 + 5 = {result}")

    # 生成器
    fib = list(fibonacci(10))
    print(f"斐波那契: {fib}")

    # 推导式
    squares, even_odd = demo_comprehension()
    print(f"平方: {squares[:5]}...")
    print(f"奇偶: {even_odd}")

    # 模式匹配
    print(describe(42))
    print(describe("hello"))
    print(describe([1, 2, 3]))

    # Protocol
    shapes: list[Drawable] = [Circle(5), Square(3)]
    for s in shapes:
        print(render(s))
