import textwrap

from pavilion.utils.merge import add_to_module, new_module, render_imports, split


def dedent(text: str) -> str:
    return textwrap.dedent(text).lstrip("\n")


TOKEN = split(dedent('''
    import secrets


    def generate_token() -> str:
        return secrets.token_urlsafe()
'''))

HASH = split(dedent('''
    import hashlib


    def hash_token(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()
'''))


def test_split_separates_imports_from_definitions():
    snippet = split(dedent('''
        import logging
        from typing import Any, cast

        logger = logging.getLogger(__name__)


        # helper
        @decorator
        def f() -> Any:
            return cast(Any, 1)
    '''))

    assert snippet.imports == (
        ("logging", None, None), ("typing", "Any", None), ("typing", "cast", None)
    )
    assert [b.names for b in snippet.blocks] == [{"logger"}, {"f"}]
    assert snippet.blocks[1].text.startswith("# helper\n@decorator\ndef f()")
    assert [b.definition for b in snippet.blocks] == [False, True]


def test_render_imports_follows_isort():
    lines = render_imports([
        (".base", "Base", None),
        ("typing", "cast", None),
        ("sqlalchemy", "String", None),
        ("typing", "Any", None),
        ("os", None, None),
        ("datetime", "datetime", None),
        ("datetime", "UTC", None),
        ("numpy", None, "np"),
    ])

    assert lines == [
        "import os",
        "from datetime import UTC, datetime",
        "from typing import Any, cast",
        "",
        "import numpy as np",
        "from sqlalchemy import String",
        "",
        "from .base import Base",
    ]


def test_new_module_merges_snippets():
    assert new_module("Tokens.", [TOKEN, HASH]) == dedent('''
        """Tokens."""

        import hashlib
        import secrets


        def generate_token() -> str:
            return secrets.token_urlsafe()


        def hash_token(token: str) -> str:
            return hashlib.sha256(token.encode()).hexdigest()
    ''')


def test_new_module_one_blank_line_before_non_definitions():
    snippet = split("import logging\n\nlogger = logging.getLogger(__name__)\n")

    assert new_module("Log.", [snippet]) == (
        '"""Log."""\n\nimport logging\n\nlogger = logging.getLogger(__name__)\n'
    )


def test_new_module_skips_repeated_definitions():
    module = new_module("Doc.", [TOKEN, TOKEN])

    assert module.count("def generate_token") == 1


def test_add_to_module_merges_imports_and_appends():
    module = new_module("Tokens.", [TOKEN])

    assert add_to_module(module, HASH) == new_module("Tokens.", [TOKEN, HASH])


def test_add_to_module_extends_an_existing_from_import():
    module = dedent('''
        """Doc."""

        from typing import Any


        def a() -> Any: ...
    ''')
    snippet = split("from typing import cast\n\n\ndef b():\n    return cast(int, 1)\n")

    result = add_to_module(module, snippet)

    assert "from typing import Any, cast\n" in result
    assert result.endswith("def a() -> Any: ...\n\n\ndef b():\n    return cast(int, 1)\n")


def test_add_to_module_keeps_existing_helpers_and_user_code():
    module = dedent('''
        """Doc."""

        import logging

        logger = logging.getLogger("custom")


        def mine() -> None:
            logger.info("user code")
    ''')
    snippet = split(
        "import logging\n\nlogger = logging.getLogger(__name__)\n\n\ndef new() -> None: ...\n"
    )

    result = add_to_module(module, snippet)

    assert result.count("logger =") == 1
    assert 'logging.getLogger("custom")' in result
    assert "def mine()" in result and "def new()" in result
    compile(result, "module.py", "exec")


def test_add_to_module_replaces_only_the_named_definition():
    module = dedent('''
        """Doc."""

        import secrets


        # keep me
        def generate_token() -> str:
            return "old"


        def other() -> int:
            return 1
    ''')

    result = add_to_module(module, TOKEN, replace=frozenset({"generate_token"}))

    assert "secrets.token_urlsafe()" in result and '"old"' not in result
    assert "# keep me" in result
    assert result.endswith("def other() -> int:\n    return 1\n")


def test_add_to_module_does_not_drop_comments_between_imports():
    module = dedent('''
        """Doc."""

        import secrets  # used below
        # third party
        import requests


        def get(): ...
    ''')

    result = add_to_module(module, HASH)

    assert "import secrets  # used below\n# third party\nimport requests\n" in result
    assert "import hashlib\n" in result
    compile(result, "module.py", "exec")


def test_add_to_module_without_imports_inserts_them_after_the_docstring():
    module = '"""Doc."""\n\n\ndef first(): ...\n'

    result = add_to_module(module, HASH)

    assert result.startswith('"""Doc."""\n\nimport hashlib\n\n\ndef first(): ...\n')
    compile(result, "module.py", "exec")
