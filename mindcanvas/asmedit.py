"""Assembly editor model (the logic behind MCAssemblyEditor; no UI here).

Edits a COPY of a library assembly: its layer stack (walls, floors, roofs: name, component,
material, thickness, core, options) and every other setting as JSON (curtain walls have no
layers: everything is settings). `save_as` writes it to library/assemblies/zz_user_assemblies.json
(library assemblies are never overwritten); `apply` gives selected assemblies of the same kind
the saved assembly.
"""

import copy
import json

from . import components, engine, meta, stack, units

COMPONENTS_BY_KIND = {
    "wall": None,                                      # every registered wall component
    "floor": ["solid", "membrane", "void", "joists", "deck"],
    "roof": ["solid", "membrane", "void", "rafters", "joists", "shingles"],
}


class EditError(Exception):
    pass


class AssemblyModel(object):
    def __init__(self, lib, name):
        self.lib = lib
        self.load(name)

    def load(self, name):
        self.source = name
        self.data = copy.deepcopy(self.lib.assembly(name))
        self.kind = self.data.get("kind", "wall")
        self.dirty = False

    # -- layers -----------------------------------------------------------------------------
    @property
    def has_layers(self):
        return isinstance(self.data.get("layers"), list)

    @property
    def layers(self):
        return self.data.get("layers") or []

    def resolved(self, i):
        return self.lib.resolve_layer(self.layers[i])

    def rows(self):
        """Display strings, one per layer (exterior / top first)."""
        return [stack.describe(self.resolved(i), i) for i in range(len(self.layers))]

    def components(self):
        allowed = COMPONENTS_BY_KIND.get(self.kind)
        names = sorted(components.REGISTRY) if allowed is None else allowed
        used = set(self.resolved(i).get("component", "solid") for i in range(len(self.layers)))
        return sorted(set(names) | used)

    def materials(self):
        return sorted(self.lib.data["materials"])

    def field(self, i, key):
        spec = self.resolved(i)
        if key == "thickness":
            return units.format_inches(units.parse_length(spec.get("thickness", 0)), 64).strip('"')
        if key == "core":
            return bool(spec.get("core"))
        if key == "options":
            return json.dumps(spec.get("options", {}), indent=1, sort_keys=True)
        if key == "name":
            return spec.get("name") or spec.get("material") or ""
        return spec.get(key) or ""

    def _set(self, i, spec):
        self.data["layers"][i] = spec
        self.dirty = True

    def _explicit(self, i):
        """The layer spec with its preset expanded (so edits never change a shared preset)."""
        return copy.deepcopy(self.resolved(i))

    def set_field(self, i, key, value):
        spec = self._explicit(i)
        if key == "thickness":
            t = units.parse_length(value)
            if t <= 0 and spec.get("component") != "void":
                raise EditError("Thickness must be positive.")
            spec["thickness"] = units.format_inches(t, 64)
            spec.get("options", {}).pop("stud", None)
        elif key == "core":
            if value:
                for j, other in enumerate(self.layers):
                    if j != i and other.get("core"):
                        o = copy.deepcopy(other)
                        o.pop("core", None)
                        self.data["layers"][j] = o
                spec["core"] = True
            else:
                spec.pop("core", None)
        elif key == "options":
            try:
                opts = json.loads(value) if value.strip() else {}
            except ValueError as ex:
                raise EditError("Options are not valid JSON: {}".format(ex))
            if not isinstance(opts, dict):
                raise EditError("Options must be a JSON object {...}.")
            spec["options"] = opts
            if not opts:
                spec.pop("options")
        elif key in ("name", "material", "component"):
            if not value:
                if key == "material":
                    spec.pop("material", None)
                else:
                    raise EditError("{} cannot be empty.".format(key.capitalize()))
            else:
                spec[key] = value
        else:
            raise EditError("Unknown field '{}'.".format(key))
        self._set(i, spec)

    def add(self, i=None, spec=None):
        """Insert a layer before i (None = interior / bottom end). Returns its index."""
        spec = spec or {"name": "New Layer", "component": "solid", "material": "Gypsum Board", "thickness": "1/2"}
        i = len(self.layers) if i is None else i
        self.data["layers"] = stack.insert(self.layers, i, spec)
        self.dirty = True
        return i

    def duplicate(self, i):
        spec = self._explicit(i)
        spec.pop("core", None)
        return self.add(i + 1, spec)

    def remove(self, i):
        self.data["layers"] = stack.remove(self.layers, i)
        self.dirty = True

    def move(self, i, step):
        self.data["layers"] = stack.move(self.layers, i, step)
        self.dirty = True
        return max(0, min(len(self.layers) - 1, i + step))

    def mirror(self):
        self.data["layers"] = stack.mirror(self.layers)
        self.dirty = True

    def total(self):
        t = 0.0
        for i in range(len(self.layers)):
            try:
                t += units.parse_length(self.resolved(i).get("thickness", 0))
            except ValueError:
                pass
        return t

    # -- the other settings -------------------------------------------------------------------
    def settings_json(self):
        rest = dict((k, v) for k, v in self.data.items() if k != "layers")
        return json.dumps(rest, indent=1, sort_keys=True)

    def set_settings_json(self, text):
        try:
            rest = json.loads(text)
        except ValueError as ex:
            raise EditError("Settings are not valid JSON: {}".format(ex))
        if not isinstance(rest, dict):
            raise EditError("Settings must be a JSON object {...}.")
        if rest.get("kind", self.kind) != self.kind:
            raise EditError("The kind of an assembly cannot change ({} -> {}).".format(self.kind, rest.get("kind")))
        rest["kind"] = self.kind
        if self.has_layers:
            rest["layers"] = self.layers
        self.data = rest
        self.dirty = True

    # -- checks, save, apply -------------------------------------------------------------------
    def problems(self):
        out = []
        if self.has_layers:
            if not self.layers:
                out.append("The assembly has no layers.")
            cores = [i for i in range(len(self.layers)) if self.resolved(i).get("core")]
            if self.kind == "wall" and len(cores) != 1:
                out.append("A wall needs exactly one core layer (has {}).".format(len(cores)))
            for i in range(len(self.layers)):
                s = self.resolved(i)
                c = s.get("component", "solid")
                if c not in components.REGISTRY and self.kind == "wall":
                    out.append("Layer {}: unknown component '{}'.".format(i + 1, c))
                m = s.get("material")
                if m and m not in self.lib.data["materials"]:
                    out.append("Layer {}: material '{}' is not in the library.".format(i + 1, m))
                try:
                    units.parse_length(s.get("thickness", 0))
                except ValueError:
                    out.append("Layer {}: bad thickness '{}'.".format(i + 1, s.get("thickness")))
        return out

    def save_as(self, name):
        name = (name or "").strip()
        if not name:
            raise EditError("Give the assembly a name.")
        if name in self.lib.data["assemblies"] and not self.lib.is_user_entry("assemblies", name):
            raise EditError("'{}' is a library assembly; choose another name.".format(name))
        bad = [p for p in self.problems() if "not in the library" not in p]
        if bad:
            raise EditError(bad[0])
        d = copy.deepcopy(self.data)
        if self.source != name:
            d["based_on"] = self.data.get("based_on") or self.source
        path = self.lib.save_assembly(name, d)
        self.source = name
        self.dirty = False
        return path

    def apply(self, doc, drivers):
        """Give drivers of this kind the (saved) assembly (a per-wall stack is dropped); returns
        their BuildResults."""
        if self.dirty:
            raise EditError("Save the assembly first.")
        out = []
        for d in drivers:
            if meta.get(d, meta.TYPE) != self.kind:
                continue
            out.append(engine.set_assembly(doc, d, self.source, self.lib))
        return out
