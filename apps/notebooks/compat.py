"""
Python 3.14 compatibility shim for Django 5.1's template Context.__copy__.

Django's BaseContext.__copy__ (django/template/context.py) does
`duplicate = copy(super())` to get a shallow copy of `self` while bypassing
this override - a copy.copy() call on a bound `super` proxy object. That
idiom breaks under Python 3.14 ("AttributeError: 'super' object has no
attribute 'dicts' and no __dict__ for setting new attributes").

This isn't just a test-only problem: it's Django's own Context class, used
any time something copies a template Context (most visibly, django.test.Client
copies the Context on every render to populate response.context - meaning
EVERY test that renders a template is affected, in every app, regardless of
which test module Django happens to import first). So this is applied once
at app startup (see NotebooksConfig.ready()) rather than only within a
particular test package.

Restores the same shallow-copy semantics Django intended, without going
through the super() proxy. Scoped to Python 3.14+ only. Remove once Django
ships an upstream fix.
"""
import sys


def apply():
    if sys.version_info < (3, 14):
        return

    from django.template.context import BaseContext

    def _py314_safe_copy(self):
        cls = self.__class__
        duplicate = cls.__new__(cls)
        duplicate.__dict__.update(self.__dict__)
        duplicate.dicts = self.dicts[:]
        return duplicate

    BaseContext.__copy__ = _py314_safe_copy
