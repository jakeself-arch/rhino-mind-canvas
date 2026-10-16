"""Assembly library: merges every JSON file under library/<section>/.

Sections:
    materials   name -> {color, render, section, print}
    profiles    name -> {type, ...dimensions}
    framing     name -> framing-system rules (wood, metal, ...)
    assemblies  name -> {kind, layers: [...], ...}
    layers      name -> reusable layer preset; assembly layers may say
                {"preset": "<name>", ...overrides}
    styles      name -> drawing style (phase 3)
    openings    name -> window / door type (phase 4, see mindcanvas/openings)
    entourage   name -> line-drawn figure (phase 8, see mindcanvas/entourage)

Adding content never requires code: drop a new .json file into the right
folder. Keys starting with "_" (e.g. "_comment") are ignored. Later files
override earlier ones (alphabetical), so a "zz_my_overrides.json" wins.
"""

import json
import os

SECTIONS = ("materials", "profiles", "framing", "assemblies", "layers", "styles", "openings", "entourage")
USER_ASSEMBLIES = "zz_user_assemblies.json"
USER_FILE = "zz_user_{}.json"      # e.g. library/profiles/zz_user_profiles.json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIBRARY_DIR = os.path.join(ROOT, "library")

DEFAULT_MATERIAL = {
    "color": [160, 160, 160],
    "section": {"fill": "white", "boundary_weight": 1.0},
}


class LibraryError(Exception):
    pass


class Library(object):
    def __init__(self, directory=LIBRARY_DIR):
        self.directory = directory
        self.data = dict((s, {}) for s in SECTIONS)
        self.sources = {}
        self.warnings = []
        self._stamp = None
        self.load()

    # -- loading ---------------------------------------------------------
    def _files(self):
        out = []
        for section in SECTIONS:
            folder = os.path.join(self.directory, section)
            if not os.path.isdir(folder):
                continue
            for name in sorted(os.listdir(folder)):
                if name.lower().endswith(".json"):
                    out.append((section, os.path.join(folder, name)))
        return out

    def _current_stamp(self):
        return tuple((p, os.path.getmtime(p)) for _, p in self._files())

    def load(self):
        self.data = dict((s, {}) for s in SECTIONS)
        self.sources = {}
        self.warnings = []
        for section, path in self._files():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = json.load(f)
            except ValueError as e:
                raise LibraryError("Invalid JSON in {}: {}".format(path, e))
            for key, value in content.items():
                if key.startswith("_"):
                    continue
                self.data[section][key] = value
                self.sources[(section, key)] = path
        self._stamp = self._current_stamp()

    def refresh(self):
        """Reload if any library file was added, removed or edited."""
        if self._current_stamp() != self._stamp:
            self.load()
        return self

    # -- accessors -------------------------------------------------------
    def material(self, name):
        if name is None:
            return None
        m = self.data["materials"].get(name)
        if m is None:
            msg = "Material '{}' not in library; using a default gray.".format(name)
            if msg not in self.warnings:
                self.warnings.append(msg)
            return dict(DEFAULT_MATERIAL)
        return m

    def profile(self, name):
        p = self.data["profiles"].get(name)
        if p is None:
            raise LibraryError("Profile '{}' not found in library/profiles".format(name))
        return p

    def framing_system(self, name):
        f = self.data["framing"].get(name)
        if f is None:
            raise LibraryError("Framing system '{}' not found in library/framing".format(name))
        return f

    def assembly(self, name):
        a = self.data["assemblies"].get(name)
        if a is None:
            raise LibraryError("Assembly '{}' not found in library/assemblies".format(name))
        return a

    def assemblies(self, kind=None):
        names = [n for n, a in self.data["assemblies"].items()
                 if kind is None or a.get("kind") == kind]
        return sorted(names)

    def layer_preset(self, name):
        p = self.data["layers"].get(name)
        if p is None:
            raise LibraryError("Layer preset '{}' not found in library/layers".format(name))
        return p

    def resolve_layer(self, spec):
        """Expand {"preset": name, ...} into a full layer spec (spec keys win,
        options are merged)."""
        if "preset" not in spec:
            return spec
        base = self.layer_preset(spec["preset"])
        out = dict(base)
        out.setdefault("name", spec["preset"])
        for k, v in spec.items():
            if k == "preset":
                continue
            if k == "options":
                merged = dict(base.get("options", {}))
                merged.update(v)
                out[k] = merged
            else:
                out[k] = v
        return out

    def save_entry(self, section, name, definition, filename=None):
        """Write one entry to library/<section>/<filename> (default zz_user_<section>.json),
        keeping the file's other entries. Returns the path."""
        if section not in SECTIONS:
            raise LibraryError("Unknown library section '{}'".format(section))
        folder = os.path.join(self.directory, section)
        if not os.path.isdir(folder):
            os.makedirs(folder)
        path = os.path.join(folder, filename or USER_FILE.format(section))
        content = {}
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                content = json.load(f)
        content[name] = definition
        with open(path, "w", encoding="utf-8") as f:
            json.dump(content, f, indent=2)
        self.load()
        return path

    def remove_entry(self, section, name, filename=None):
        """Delete an entry from a user file (never from the shipped files). Returns True if found."""
        path = os.path.join(self.directory, section, filename or USER_FILE.format(section))
        if not os.path.exists(path):
            return False
        with open(path, "r", encoding="utf-8") as f:
            content = json.load(f)
        if name not in content:
            return False
        del content[name]
        if content:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(content, f, indent=2)
        else:
            os.remove(path)
        self.load()
        return True

    def is_user_entry(self, section, name):
        src = self.sources.get((section, name), "")
        return os.path.basename(src).startswith("zz_")

    def save_assembly(self, name, definition):
        """Write an assembly to library/assemblies/zz_user_assemblies.json."""
        return self.save_entry("assemblies", name, definition, USER_ASSEMBLIES)

    def style(self, name):
        return self.data["styles"].get(name)


_LIBRARY = None


def get(force_reload=False):
    """Shared library instance, reloaded automatically when files change."""
    global _LIBRARY
    if _LIBRARY is None or force_reload:
        _LIBRARY = Library()
    else:
        _LIBRARY.refresh()
    return _LIBRARY
