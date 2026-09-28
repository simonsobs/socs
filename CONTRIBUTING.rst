====================
Contributing to SOCS
====================

Branches
--------

socs has a single ``main`` branch Feature branches should be based off of the
latest ``main``, and pull requests should be made into ``main``.

Pull Requests
-------------

If you are an SO collaborator you may have push access, in which case you can
push your feature branch, then open a pull request, selecting the ``main``
branch as the base branch. (This is the default branch, so it should be
automatically selected for you.)

If you are not an SO collaborator, or otherwise do not have push access, we
still welcome your pull request! You will have to fork the repository and
submit a PR from there. See the `GitHub documentation
<https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/creating-a-pull-request-from-a-fork>`_
for details on how to do so.

PR Template
```````````
When you open a PR, a template will automatically populate the text field. Please
fill out all sections of the template.

Force Pushes
````````````
Please refrain from force pushing a rebase onto a branch after marking your PR
ready for review, unless requested to do so by a maintainer. Doing so makes it
difficult for the reviewers to follow changes you have made in response to the
review.

AI Usage
````````
Use of AI tools is allowed under the Simons Observatory `AI Governance
Policy`_, provided the usage is disclosed. Before submitting a PR with AI
generated code, please make sure to read the AI policy and follow the
guidelines within.

As a way of marking which Agents were developed with and without AI assistance,
the Agent reference pages should contain one of two badges:

.. image:: https://img.shields.io/badge/AI-assisted-orange
   :alt: Agent written with AI assistance

::

    .. image:: https://img.shields.io/badge/AI-assisted-orange
       :alt: Agent written with AI assistance

.. image:: https://img.shields.io/badge/AI-free-green
   :alt: Agent written without AI assistance

::

    .. image:: https://img.shields.io/badge/AI-free-green
       :alt: Agent written without AI assistance

You must also include the following comment at the top of every source file
that was generated using AI::

    # Code developed with AI assistance.

Most agents in this repo pre-date AI tools, and so contain AI free code, to the
best of the maintainer's knowledge.

.. _AI Governance Policy: https://simonsobservatory.org/wp-content/uploads/2026/08/Digital_Assets_Policy_20260811.pdf

Development Guide
-----------------

Contributors should follow the recommendations made in the `SO Developer Guide`_.

.. _SO Developer Guide: https://simonsobs-dev-guide.readthedocs.io/en/latest/

pre-commit
``````````
As a way to enforce development guide recommendations we have configured
`pre-commit`_.  While not required (yet), it is highly recommended you use this
tool when contributing to socs. It will save both you and the reviewers time
when submitting pull requests.

You should set this up before making and committing your changes. To do so make
sure the ``pre-commit`` package is installed (it is in ``requirements.txt``)::

    $ python -m pip install -r requirements.txt

Then run::

    $ pre-commit install

This will install the configured git hooks and any dependencies. Now, whenever
you commit the hooks will run. If there are issues you will see them in the
output. This may automatically make changes to your staged files.  These
changes will be unstaged and need to be reviewed (typically with a ``git diff``),
restaged, and recommitted. For example, if you have trailing
whitespace on a line, pre-commit will prevent the commit and remove the
whitespace. You will then stage the new changes with another ``git add <file>``
and then re-run the commit. Here is the expected git output for this example:

.. code-block::

    $ vim demo.py
    $ git status
    On branch koopman/test-pre-commit
    Changes not staged for commit:
      (use "git add <file>..." to update what will be committed)
      (use "git restore <file>..." to discard changes in working directory)
        modified:   demo.py

    no changes added to commit (use "git add" and/or "git commit -a")
    $ git add demo.py
    $ git commit
    Check python ast.........................................................Passed
    Fix End of Files.........................................................Passed
    Trim Trailing Whitespace.................................................Failed
    - hook id: trailing-whitespace
    - exit code: 1
    - files were modified by this hook

    Fixing demo/demo.py

    $ git status
    On branch koopman/test-pre-commit
    Changes to be committed:
      (use "git restore --staged <file>..." to unstage)
        modified:   demo.py

    Changes not staged for commit:
      (use "git add <file>..." to update what will be committed)
      (use "git restore <file>..." to discard changes in working directory)
        modified:   demo.py
    $ git add -u
    $ git commit

.. _pre-commit: https://pre-commit.com/

For Repo Maintainers
--------------------

The following sections are only relevant for repo maintainers.

Releases
````````

    **Note:** Releases will be issued by core maintainers of SOCS.

If you are trying to issue a release of SOCS you should follow these steps:

1. Test the release properly builds and publishes with a pre-release. You can
   do so by pushing a tag matching ``v0.*.*a*``, ``v0.*.*b*``, or
   ``v0.*.*rc*``.
2. If no new commits are made following a pre-release, remove the pre-release
   tag. Multiple tags may prevent the official release from publishing properly.
3. Use the GitHub releases interface to draft a new release, creating a new tag
   targeting the ``main`` branch.
4. Write the release notes. Make use of the "Generate release notes" feature.
   It is helpful to organize these into sections as done in past releases. Be
   sure to highlight any breaking changes and include instructions for any
   actions users must take when updating.
