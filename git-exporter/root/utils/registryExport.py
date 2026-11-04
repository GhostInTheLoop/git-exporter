#!/usr/bin/env python3
"""Export a minimal, non-sensitive view of the Home Assistant registries.

Usage: registryExport.py <storage-dir> <output-dir>

Reads core.entity_registry, core.device_registry and core.area_registry and writes
entities.yaml, devices.yaml and areas.yaml containing ONLY an allow-list of fields.
This is enough to resolve the opaque ids that device-based automations use
(device_id / entity registry id) to real entity ids, names and areas.

Deliberately NOT exported: unique_id, identifiers, connections (MAC addresses),
serial numbers, firmware versions, config entry ids, and any other field.
"""
import json
import os
import sys

import yaml

ENTITY_FIELDS = ("id", "entity_id", "device_id", "platform", "name", "original_name", "area_id", "disabled_by")
DEVICE_FIELDS = ("id", "name", "name_by_user", "manufacturer", "model", "area_id", "disabled_by")
AREA_FIELDS = ("id", "name")


def load(storage_dir, name):
    path = os.path.join(storage_dir, name)
    if not os.path.isfile(path):
        print(f"registryExport: {name} not found, skipping", file=sys.stderr)
        return None
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle).get("data", {})


def pick(items, fields, sort_key):
    rows = [{f: item.get(f) for f in fields if item.get(f) is not None} for item in items or []]
    return sorted(rows, key=lambda r: str(r.get(sort_key, "")))


def dump(rows, path):
    with open(path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(rows, handle, default_flow_style=False, sort_keys=False, allow_unicode=True)


def main(storage_dir, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    entities = load(storage_dir, "core.entity_registry")
    devices = load(storage_dir, "core.device_registry")
    areas = load(storage_dir, "core.area_registry")
    if entities is not None:
        dump(pick(entities.get("entities"), ENTITY_FIELDS, "entity_id"), os.path.join(out_dir, "entities.yaml"))
    if devices is not None:
        dump(pick(devices.get("devices"), DEVICE_FIELDS, "id"), os.path.join(out_dir, "devices.yaml"))
    if areas is not None:
        dump(pick(areas.get("areas"), AREA_FIELDS, "id"), os.path.join(out_dir, "areas.yaml"))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
