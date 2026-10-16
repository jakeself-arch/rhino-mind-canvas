"""Assembly editor model (the logic behind MCAssemblyEditor; no UI here).

Edits a COPY of a library assembly: its layer stack (walls, floors, roofs: name, component,
material, thickness, core, options) and every other setting as JSON (curtain walls have no
layers: everything is settings). `save_as` writes it to library/assemblies/zz_user_assemblies.json
(library assemblies are never overwritten); `apply` gives selected assemblies of the same kind
the saved assembly.

Phase 12 (visual editor) adds: the edited stack (`stack_key`: "layers", or a roof's attic
"ceiling"), `move_to`, the thickness the engine will build (`thickness_in`: framing follows its
member), member sizes + snapping for drags (`member_sizes`, `snap`, `set_thickness_in`), and typed
per-key options / settings (`option_fields`, `set_option`, `setting_fields`, `set_setting`, the
advanced JSON of the dict / list keys; schemas in asmfields.py).
"""

import copy
import json

from . import asmfields, components, engine, meta, stack, units

COMPONENTS_BY_KIND = {
    "wall": None,                                      # every registered wall component
    "floor": ["solid", "membrane", "void", "joists", "deck"],
    "roof": ["solid", "membrane", "void", "rafters", "joists", "shingles"],
}


STACKS = {"roof": ["layers", "ceiling"]}
STACK_LABELS = {"layers": "Layers", "ceiling": "Attic ceiling"}
SNAP_IN = 1.0 / 16
FINE_IN = 1.0 / 64


class EditError(Exception):
    pass


def _same(ftype, old, new):
    """A typed field's new value equals the stored one (lengths by value: 10' == 120 == 10'-0")."""
    if ftype == "length":
        try:
            return abs(units.parse_length(old) - units.parse_length(new)) < 1e-9
        except (ValueError, TypeError):
            pass
    return old == new and type(old) == type(new)


class AssemblyModel(object):
    def __init__(self, lib, name):
        self.lib = lib
        self.load(name)

    def load(self, name):
        self.source = name
        self.data = copy.deepcopy(self.lib.assembly(name))
        self.kind = self.data.get("kind", "wall")
        self.stack_key = "layers"
        self.dirty = False

    # -- layers -----------------------------------------------------------------------------
    @property
    def has_layers(self):
        return isinstance(self.data.get("layers"), list)

    @property
    def layers(self):
        return self.data.get(self.stack_key) or []

    def stacks(self):
        """The layer stacks this assembly can edit ("layers"; roofs also "ceiling")."""
        return list(STACKS.get(self.kind, ["layers"])) if self.has_layers else []

    def set_stack(self, key):
        if key not in STACKS.get(self.kind, ["layers"]):
            raise EditError("A {} has no '{}' stack.".format(self.kind, key))
        self.stack_key = key
        if not isinstance(self.data.get(key), list):
            self.data[key] = []

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
        self.data[self.stack_key][i] = spec
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
                        self.data[self.stack_key][j] = o
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
        self.data[self.stack_key] = stack.insert(self.layers, i, spec)
        self.dirty = True
        return i

    def duplicate(self, i):
        spec = self._explicit(i)
        spec.pop("core", None)
        return self.add(i + 1, spec)

    def remove(self, i):
        if self.stack_key != "layers" and len(self.layers) == 1:
            self.data[self.stack_key] = []          # an empty attic ceiling = none
        else:
            self.data[self.stack_key] = stack.remove(self.layers, i)
        self.dirty = True

    def move_to(self, i, j):
        """Move layer i to position j (0 = exterior / top). Returns j."""
        n = len(self.layers)
        j = max(0, min(n - 1, j))
        if i == j or not 0 <= i < n:
            return i
        out = copy.deepcopy(self.layers)
        out.insert(j, out.pop(i))
        self.data[self.stack_key] = out
        self.dirty = True
        return j

    def move(self, i, step):
        self.data[self.stack_key] = stack.move(self.layers, i, step)
        self.dirty = True
        return max(0, min(len(self.layers) - 1, i + step))

    def mirror(self):
        self.data[self.stack_key] = stack.mirror(self.layers)
        self.dirty = True

    def total(self):
        t = 0.0
        for i in range(len(self.layers)):
            try:
                t += units.parse_length(self.resolved(i).get("thickness", 0))
            except ValueError:
                pass
        return t

    # -- what the engine builds: fitted thickness, member sizes, snapping (Phase 12) ------------
    def fitted(self, i):
        """Layer spec with the thickness the engine will use (framing follows its member)."""
        spec = self.resolved(i)
        try:
            if self.kind == "wall":
                from .kinds import wall as k
                return k.fitted_layer(self.lib, spec, i, {})
            if self.kind == "floor":
                from .kinds import floor as k
                return k.fitted_layer(self.lib, spec, i, {})
            if self.kind == "roof":
                from .kinds import roof as k
                comps = ("rafters",) if self.stack_key == "layers" else ("joists", "framing")
                return k._fitted(self.lib, spec, i, {}, comps)
        except Exception:
            pass
        return spec

    def thickness_in(self, i):
        try:
            return units.parse_length(self.fitted(i).get("thickness", 0))
        except ValueError:
            return 0.0

    def member_key(self, i):
        """The option naming the member of a framing layer ("stud" / "joist" / "rafter") or None."""
        c = self.resolved(i).get("component")
        if self.kind == "wall" and c == "framing":
            return "stud"
        if c == "rafters":
            return "rafter"
        if c in ("joists", "framing") and self.kind in ("floor", "roof"):
            return "joist"
        return None

    def member_sizes(self, i):
        """[(depth in inches, profile name)] a framing / joist / rafter layer snaps to (library
        members of its system, family and gauge), or None for a free layer."""
        spec = self.resolved(i)
        opts = spec.get("options") or {}
        key = self.member_key(i)
        if key is None:
            return None
        lib = self.lib
        out = []
        try:
            if key == "stud":
                if opts.get("fit", "stud") != "stud":
                    return None
                from .components import framing as fr
                sysd = lib.framing_system(opts.get("system") or fr.DEFAULT_SYSTEM)
                fam = sysd.get("stud_family")
                gauge = fr._gauge(opts.get("gauge", sysd.get("gauge"))) if sysd.get("type") == "metal" else None
                cands = fr._family(lib, fam, gauge) or fr._family(lib, fam)
                out = [(d, n) for d, n, p in cands]
            else:
                if opts.get("fit", "joist") != "joist":
                    return None
                from .floors import joists as jm
                _, sysd = jm.system(lib, opts.get("system"))
                metal = sysd.get("type") == "metal"
                member = opts.get("rafter") or opts.get("joist")
                p = lib.data["profiles"].get(member) if member else None
                fam = (p or {}).get("family") or sysd.get("family")
                gauge = opts.get("gauge") or (sysd.get("gauge") if metal else None)
                cands = (jm._family(lib, fam, int(gauge)) if metal and gauge else None) or jm._family(lib, fam)
                with_track = metal and self.kind == "floor"
                out = [(jm.member_depth(q, with_track), n) for d, n, q in cands]
        except Exception:
            return None
        seen, uniq = set(), []
        for d, n in sorted(out, key=lambda c: (c[0], c[1])):
            k = round(d, 4)
            if k not in seen:
                seen.add(k)
                uniq.append((d, n))
        return uniq or None

    def member(self, i):
        """(profile name, profile, metal?) the engine picks for a framing layer, or (None, None, False)."""
        key = self.member_key(i)
        if key is None:
            return None, None, False
        spec = self.fitted(i)
        opts = spec.get("options") or {}
        try:
            t = units.parse_length(spec.get("thickness", 0))
            if key == "stud":
                from .components import framing as fr
                sysd = self.lib.framing_system(opts.get("system") or fr.DEFAULT_SYSTEM)
                name, p, _ = fr.select_stud(self.lib, sysd, opts, t)
            else:
                from .floors import joists as jm
                _, sysd = jm.system(self.lib, opts.get("system"))
                g = opts.get("gauge")
                name, p, _ = jm.select_member(self.lib, sysd, opts.get("rafter") or opts.get("joist"), t,
                                              gauge=int(g) if g else None)
            return name, p, sysd.get("type") == "metal"
        except Exception:
            return None, None, False

    def snap(self, i, inches, fine=False):
        """(thickness, member name or None) for a dragged thickness: the nearest library member
        of a framing layer, else the nearest 1/16" (1/64" with fine, or below 1/16")."""
        sizes = self.member_sizes(i)
        if sizes:
            d, n = min(sizes, key=lambda c: (abs(c[0] - inches), c[0]))
            return d, n
        step = FINE_IN if (fine or inches < SNAP_IN - 1e-9) else SNAP_IN
        t = max(FINE_IN, round(inches / step) * step)
        return t, None

    def set_thickness_in(self, i, inches, member=None):
        """Set a layer's thickness (inches). A joist / rafter layer that names its member gets the
        snapped member too (a named member decides the thickness)."""
        key = self.member_key(i)
        opts = self.resolved(i).get("options") or {}
        pinned = key in ("joist", "rafter") and key in opts
        self.set_field(i, "thickness", units.format_inches(inches, 64))
        if member and pinned:
            self.set_option(i, key, member, "profile")

    # -- typed options (Phase 12) ------------------------------------------------------------
    def options(self, i):
        return copy.deepcopy(self.resolved(i).get("options") or {})

    def option_fields(self, i):
        spec = self.resolved(i)
        comp = spec.get("component", "solid")
        return asmfields.build_fields(self.lib, self.kind, comp, spec.get("options") or {},
                                      asmfields.layer_schema(self.kind, comp))

    @staticmethod
    def _field_type(fields, key, value):
        for f in fields:
            if f.key == key:
                return f.type
        return "bool" if isinstance(value, bool) else "text"

    def set_option(self, i, key, value, field_type=None):
        """Set one option from a widget value (text, a choice, a bool); "" / "(default)" / "(none)"
        removes it (the component's default applies). Returns True if it changed."""
        ftype = field_type or self._field_type(self.option_fields(i), key, value)
        try:
            v, unset = asmfields.parse_value(ftype, value)
        except ValueError as ex:
            raise EditError("{}: {}".format(key, ex))
        opts = self.options(i)
        if unset:
            if key not in opts:
                return False
            opts.pop(key)
        else:
            if key in opts and _same(ftype, opts[key], v):
                return False
            opts[key] = v
        if key in ("system", "gauge", "fit") and self.member_key(i) == "stud":
            opts.pop("stud", None)       # the stud follows the system / gauge again
        spec = self._explicit(i)
        if opts:
            spec["options"] = opts
        else:
            spec.pop("options", None)
        self._set(i, spec)
        return True

    def advanced_options(self, i):
        return asmfields.advanced(self.resolved(i).get("options") or {})

    def set_advanced_options(self, i, text):
        try:
            opts = asmfields.merge_advanced(self.resolved(i).get("options") or {}, text)
        except ValueError as ex:
            raise EditError(str(ex))
        spec = self._explicit(i)
        if opts:
            spec["options"] = opts
        else:
            spec.pop("options", None)
        if spec != self.resolved(i):
            self._set(i, spec)
            return True
        return False

    # -- typed settings (Phase 12) -------------------------------------------------------------
    def setting_fields(self):
        vals = dict((k, v) for k, v in self.data.items() if k not in asmfields.HIDDEN_SETTINGS)
        return asmfields.build_fields(self.lib, self.kind, None, vals, asmfields.SETTINGS.get(self.kind, []))

    def set_setting(self, key, value, field_type=None):
        if key in asmfields.HIDDEN_SETTINGS:
            raise EditError("'{}' cannot be set here.".format(key))
        ftype = field_type or self._field_type(self.setting_fields(), key, value)
        try:
            v, unset = asmfields.parse_value(ftype, value)
        except ValueError as ex:
            raise EditError("{}: {}".format(key, ex))
        if unset:
            if key not in self.data:
                return False
            self.data.pop(key)
        else:
            if key in self.data and _same(ftype, self.data[key], v):
                return False
            self.data[key] = v
        self.dirty = True
        return True

    def advanced_settings(self):
        return asmfields.advanced(self.data, asmfields.HIDDEN_SETTINGS)

    def set_advanced_settings(self, text):
        try:
            d = asmfields.merge_advanced(self.data, text, asmfields.HIDDEN_SETTINGS)
        except ValueError as ex:
            raise EditError(str(ex))
        d["kind"] = self.kind
        if d != self.data:
            self.data = d
            self.dirty = True
            return True
        return False

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
            rest["layers"] = self.data["layers"]
        if self.stack_key not in rest and self.stack_key != "layers":
            self.stack_key = "layers"
        self.data = rest
        self.dirty = True

    # -- checks, save, apply -------------------------------------------------------------------
    def problems(self):
        out = []
        if self.has_layers:
            main = [self.lib.resolve_layer(x) for x in self.data["layers"]]
            if not main:
                out.append("The assembly has no layers.")
            cores = [i for i, x in enumerate(main) if x.get("core")]
            if self.kind == "wall" and len(cores) != 1:
                out.append("A wall needs exactly one core layer (has {}).".format(len(cores)))
            if self.kind == "roof" and main and not any(x.get("component") == "rafters" for x in main):
                out.append("A roof needs a 'rafters' layer.")
            for key in self.stacks():
                where = "" if key == "layers" else STACK_LABELS.get(key, key) + " "
                for i, raw in enumerate(self.data.get(key) or []):
                    s = self.lib.resolve_layer(raw)
                    c = s.get("component", "solid")
                    if c not in components.REGISTRY and self.kind == "wall":
                        out.append("{}Layer {}: unknown component '{}'.".format(where, i + 1, c))
                    m = s.get("material")
                    if m and m not in self.lib.data["materials"]:
                        out.append("{}Layer {}: material '{}' is not in the library.".format(where, i + 1, m))
                    try:
                        units.parse_length(s.get("thickness", 0))
                    except ValueError:
                        out.append("{}Layer {}: bad thickness '{}'.".format(where, i + 1, s.get("thickness")))
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
