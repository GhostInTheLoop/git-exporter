#!/usr/bin/env python3
"""Convert JSON file(s) to YAML.

Usage: jsonToYaml.py <file-or-dir> [dotted.path] [--redact]

  dotted.path  only convert this part of the JSON document
  --redact     replace values of keys that look like credentials
"""
import json
import os
import re
import sys

import yaml

SENSITIVE_KEY = re.compile(
    r"pass(word|wd)?|token|secret|api[_-]?key|private[_-]?key|credential|auth|cert|salt|psk",
    re.IGNORECASE,
)


def get_path(data, path):
    for part in path.split("."):
        if isinstance(data, dict) and part in data:
            data = data[part]
        else:
            return None
    return data


def redact(value):
    if isinstance(value, dict):
        return {
            k: ("<redacted>" if SENSITIVE_KEY.search(str(k)) and not isinstance(v, dict) else redact(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def convert_file(file, path, do_redact):
    yaml_file_name = os.path.splitext(file)[0] + ".yaml"
    with open(file, "r", encoding="utf-8") as infile:
        data = json.load(infile)
    if path is not None:
        data = get_path(data, path)
    if do_redact:
        data = redact(data)
    with open(yaml_file_name, "w", encoding="utf-8") as outfile:
        yaml.safe_dump(data, outfile, default_flow_style=False)


def main(argv):
    do_redact = "--redact" in argv
    args = [a for a in argv[1:] if a != "--redact"]
    if not args:
        sys.exit(__doc__)
    target = args[0]
    path = args[1] if len(args) > 1 and args[1] else None

    if os.path.isfile(target):
        convert_file(target, path, do_redact)
    else:
        for name in sorted(os.listdir(target)):
            if name.endswith(".json"):
                convert_file(os.path.join(target, name), path, do_redact)


if __name__ == "__main__":
    main(sys.argv)
