from typing import Protocol

# TODO this is how to define high performance interfaces (since actually extending an ABC / class reduces python member lookup perf, so you want to have raw classes that all implement the same surface without the class derivation).
#  Make sure to use __slots__ for highest performance.


# 1. Define the "duck" interface
class Quacker(Protocol):
    def quack(self) -> str:
        pass


# 2. Independent class (no inheritance from Quacker)
class Duck:
    def quack(self) -> str:
        return "Quack!"


# 3. Another independent class
class Person:
    def quack(self) -> str:
        return "I'm quacking like a duck!"
