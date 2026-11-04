#!/usr/bin/env python3
"""Print every scalar value of a secrets.yaml file, one per line.

Used as a git-secrets provider: the output lines are matched as literal strings,
so any of these values appearing in an exported file blocks the commit.
Values shorter than 4 characters are skipped to avoid constant false positives.
"""
import sys

import yaml


def scalars(node):
    if isinstance(node, dict):
        for value in node.values():
            yield from scalars(value)
    elif isinstance(node, list):
        for value in node:
            yield from scalars(value)
    elif node is not None and not isinstance(node, bool):
        yield str(node)


def main(path):
    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    for value in scalars(data):
        for line in value.splitlines():
            line = line.strip()
            if len(line) >= 4:
                print(line)


if __name__ == "__main__":
    main(sys.argv[1])
