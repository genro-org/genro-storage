Contributing
============

Thank you for your interest in contributing to genro-storage!

Development Setup
-----------------

Clone the repository:

.. code-block:: bash

    git clone https://github.com/genropy/genro-storage.git
    cd genro-storage

Install development dependencies:

.. code-block:: bash

    pip install -e ".[dev]"

Running Tests
-------------

Run the test suite:

.. code-block:: bash

    pytest

Run tests with coverage:

.. code-block:: bash

    pytest --cov=genro_storage --cov-report=html

Code Style
----------

We use black for code formatting:

.. code-block:: bash

    black src/ tests/

Type checking with mypy:

.. code-block:: bash

    mypy src/

Pull Request Process
--------------------

1. Fork the repository
2. Create a topic branch off ``main``, prefixed with the commit type
   (``feat/``, ``fix/``, ``docs/``, ``chore/``)
3. Make your changes
4. Add tests for new features
5. Ensure all tests pass
6. Run code formatters
7. Submit a pull request against ``main``

``main`` is the only long-lived branch. See
`WORKFLOW.md <https://github.com/genropy/genro-storage/blob/main/.github/WORKFLOW.md>`_
for the full branching and release process.

Guidelines
----------

- Write clear commit messages
- Add tests for new features
- Update documentation as needed
- Follow existing code style
- Keep pull requests focused

Reporting Issues
----------------

Report bugs and request features on GitHub Issues.

Include:
- Clear description
- Steps to reproduce
- Expected vs actual behavior
- Environment details

License
-------

By contributing, you agree that your contributions will be licensed under the Apache License 2.0.
