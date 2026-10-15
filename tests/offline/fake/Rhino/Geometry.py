import math
class Point3d(object):
    def __init__(self, x=0.0, y=0.0, z=0.0):
        if isinstance(x, Point3d): x, y, z = x.X, x.Y, x.Z
        self.X, self.Y, self.Z = float(x), float(y), float(z)
    def __add__(self, v): return Point3d(self.X + v.X, self.Y + v.Y, self.Z + v.Z)
    def __sub__(self, o):
        if isinstance(o, Vector3d) and not isinstance(o, Point3d): return Point3d(self.X - o.X, self.Y - o.Y, self.Z - o.Z)
        return Vector3d(self.X - o.X, self.Y - o.Y, self.Z - o.Z)
    def DistanceTo(self, o): return math.sqrt((self.X-o.X)**2+(self.Y-o.Y)**2+(self.Z-o.Z)**2)
    def __repr__(self): return "P(%.4f, %.4f, %.4f)" % (self.X, self.Y, self.Z)
class Vector3d(object):
    def __init__(self, x=0.0, y=0.0, z=0.0): self.X, self.Y, self.Z = float(x), float(y), float(z)
    def __mul__(self, o):
        if isinstance(o, Vector3d): return self.X*o.X + self.Y*o.Y + self.Z*o.Z
        return Vector3d(self.X*o, self.Y*o, self.Z*o)
    __rmul__ = __mul__
    def __neg__(self): return Vector3d(-self.X, -self.Y, -self.Z)
    def __add__(self, o): return Vector3d(self.X+o.X, self.Y+o.Y, self.Z+o.Z)
    @property
    def Length(self): return math.sqrt(self*self)
    def Unitize(self):
        L = self.Length; self.X/=L; self.Y/=L; self.Z/=L; return True
    @staticmethod
    def CrossProduct(a, b): return Vector3d(a.Y*b.Z-a.Z*b.Y, a.Z*b.X-a.X*b.Z, a.X*b.Y-a.Y*b.X)
    @staticmethod
    def VectorAngle(a, b): return math.acos(max(-1, min(1, (a*b)/(a.Length*b.Length))))
Vector3d.ZAxis = Vector3d(0, 0, 1); Vector3d.XAxis = Vector3d(1, 0, 0); Vector3d.YAxis = Vector3d(0, 1, 0)
class Interval(object):
    def __init__(self, a, b): self.T0, self.T1 = a, b
    @property
    def Mid(self): return 0.5*(self.T0+self.T1)
class BoundingBox(object):
    def __init__(self, pts):
        self.Min = Point3d(min(p.X for p in pts), min(p.Y for p in pts), min(p.Z for p in pts))
        self.Max = Point3d(max(p.X for p in pts), max(p.Y for p in pts), max(p.Z for p in pts))
class CurveOrientation(object): CounterClockwise = 1; Clockwise = -1
class Continuity(object): G1_continuous = 1
class PolylineCurve(object):
    """Polyline curve parameterized by length."""
    def __init__(self, pts): self.P = [Point3d(p) for p in pts]
    def _segs(self):
        out, s = [], 0.0
        for a, b in zip(self.P, self.P[1:]):
            L = a.DistanceTo(b); out.append((s, a, b, L)); s += L
        return out
    @property
    def Domain(self): return Interval(0.0, self.GetLength())
    @property
    def IsClosed(self): return len(self.P) > 2 and self.P[0].DistanceTo(self.P[-1]) < 1e-9
    def GetLength(self, iv=None):
        L = sum(s[3] for s in self._segs())
        return L if iv is None else iv.T1 - iv.T0
    def PointAt(self, t):
        for s, a, b, L in self._segs():
            if t <= s + L + 1e-12 or (s, a, b, L) == self._segs()[-1]:
                f = (t - s) / L
                return Point3d(a.X + (b.X-a.X)*f, a.Y + (b.Y-a.Y)*f, a.Z + (b.Z-a.Z)*f)
    def TangentAt(self, t):
        segs = self._segs()
        for s, a, b, L in segs:
            if t < s + L - 1e-12 or (s, a, b, L) == segs[-1]:
                v = Vector3d(b.X-a.X, b.Y-a.Y, b.Z-a.Z); v.Unitize(); return v
    @property
    def PointAtStart(self): return Point3d(self.P[0])
    @property
    def PointAtEnd(self): return Point3d(self.P[-1])
    @property
    def TangentAtStart(self): return self.TangentAt(0.0)
    @property
    def TangentAtEnd(self): return self.TangentAt(self.GetLength())
    def ClosestPoint(self, p):
        best = None
        for s, a, b, L in self._segs():
            v = Vector3d(b.X-a.X, b.Y-a.Y, 0); f = ((p.X-a.X)*v.X + (p.Y-a.Y)*v.Y)/(L*L)
            f = max(0.0, min(1.0, f)); q = Point3d(a.X+(b.X-a.X)*f, a.Y+(b.Y-a.Y)*f, a.Z)
            d = math.hypot(q.X-p.X, q.Y-p.Y)
            if best is None or d < best[0]: best = (d, s + f*L)
        return True, best[1]
    def DuplicateCurve(self): return PolylineCurve(self.P)
    def Reverse(self): self.P.reverse(); return True
    def GetBoundingBox(self, acc): return BoundingBox(self.P)
    def ClosedCurveOrientation(self, z):
        a = sum(p.X*q.Y - q.X*p.Y for p, q in zip(self.P, self.P[1:]))
        return CurveOrientation.CounterClockwise if a > 0 else CurveOrientation.Clockwise
    def TryGetPolyline(self): return True, list(self.P)
def LineCurve(a, b): return PolylineCurve([a, b])
class Plane(object): pass
class _Any(object):
    def __init__(self, *a, **k): pass
    def __getattr__(self, n): return _Any()
    def __call__(self, *a, **k): return _Any()
def __getattr__(name): return _Any

class CurveEnd(object): Start = 0; End = 1; Both = 2
class CurveExtensionStyle(object): Line = 0
class CurveOffsetCornerStyle(object): Sharp = 0

def _off_poly(pts, d, closed):
    # offset to the LEFT by d (2D)
    n = len(pts) - (1 if closed else 0)
    P = pts[:n]
    lines = []
    segs = [(P[i], P[(i + 1) % n]) for i in range(n if closed else n - 1)]
    for a, b in segs:
        dx, dy = b.X - a.X, b.Y - a.Y; L = math.hypot(dx, dy); ex, ey = dx / L, dy / L
        lines.append(((a.X - ey * d, a.Y + ex * d), (ex, ey)))
    def meet(l1, l2):
        (p, u), (q, v) = l1, l2
        c = u[0] * v[1] - u[1] * v[0]
        if abs(c) < 1e-12: return q
        s = ((q[0] - p[0]) * v[1] - (q[1] - p[1]) * v[0]) / c
        return (p[0] + u[0] * s, p[1] + u[1] * s)
    z = pts[0].Z
    out = []
    if closed:
        for i in range(n):
            x, y = meet(lines[i - 1], lines[i]); out.append(Point3d(x, y, z))
        out.append(Point3d(out[0]))
    else:
        out.append(Point3d(lines[0][0][0], lines[0][0][1], z))
        for i in range(1, len(lines)):
            x, y = meet(lines[i - 1], lines[i]); out.append(Point3d(x, y, z))
        (p, u) = lines[-1]; b = segs[-1][1]; a = segs[-1][0]
        L = math.hypot(b.X - a.X, b.Y - a.Y)
        out.append(Point3d(p[0] + u[0] * L, p[1] + u[1] * L, z))
    return out

def _offset(self, plane, dist, tol, style):
    return [PolylineCurve(_off_poly(self.P, -dist, self.IsClosed))]
PolylineCurve.Offset = _offset

def _extend(self, end, e, style):
    P = [Point3d(p) for p in self.P]
    if end in (CurveEnd.End, CurveEnd.Both):
        t = self.TangentAtEnd; P[-1] = P[-1] + t * e
    if end in (CurveEnd.Start, CurveEnd.Both):
        t = self.TangentAtStart; P[0] = P[0] + (-t) * e
    return PolylineCurve(P)
PolylineCurve.Extend = _extend
def _lp(self, s): return True, s
PolylineCurve.LengthParameter = _lp
def _trim(self, iv, b=None):
    if b is not None: iv = Interval(iv, b)
    pts = [self.PointAt(iv.T0)]
    for s, a, bb, L in self._segs():
        if iv.T0 + 1e-12 < s < iv.T1 - 1e-12: pts.append(Point3d(a))
    pts.append(self.PointAt(iv.T1))
    return PolylineCurve(pts)
PolylineCurve.Trim = _trim

class Transform(object):
    def __init__(self, m=None): self.m = m or [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]
    def __mul__(self, o): return Transform([[sum(self.m[i][k]*o.m[k][j] for k in range(4)) for j in range(4)] for i in range(4)])
    @staticmethod
    def Translation(x, y, z): return Transform([[1,0,0,x],[0,1,0,y],[0,0,1,z],[0,0,0,1]])
    @staticmethod
    def PlaneToPlane(a, b):
        # map a's frame to b's frame: world = b.o + X_b*u + ...; u = local coords in a
        def to_world(p):  # plane -> matrix from local to world
            return [[p.XAxis.X, p.YAxis.X, p.ZAxis.X, p.Origin.X],[p.XAxis.Y, p.YAxis.Y, p.ZAxis.Y, p.Origin.Y],[p.XAxis.Z, p.YAxis.Z, p.ZAxis.Z, p.Origin.Z],[0,0,0,1]]
        def inv(p):
            R = [[p.XAxis.X, p.XAxis.Y, p.XAxis.Z],[p.YAxis.X, p.YAxis.Y, p.YAxis.Z],[p.ZAxis.X, p.ZAxis.Y, p.ZAxis.Z]]
            o = p.Origin; t = [-(R[i][0]*o.X + R[i][1]*o.Y + R[i][2]*o.Z) for i in range(3)]
            return [R[0]+[t[0]], R[1]+[t[1]], R[2]+[t[2]], [0,0,0,1]]
        return Transform(to_world(b)) * Transform(inv(a))
def _ptx(self, xf):
    m = xf.m; x, y, z = self.X, self.Y, self.Z
    self.X, self.Y, self.Z = m[0][0]*x+m[0][1]*y+m[0][2]*z+m[0][3], m[1][0]*x+m[1][1]*y+m[1][2]*z+m[1][3], m[2][0]*x+m[2][1]*y+m[2][2]*z+m[2][3]
    return True
Point3d.Transform = _ptx
class Plane(object):
    def __init__(self, o=None, x=None, y=None):
        self.Origin = Point3d(o) if o is not None else Point3d()
        if y is None and x is not None:   # origin + normal
            self.ZAxis = x; self.XAxis = Vector3d(1,0,0); self.YAxis = Vector3d(0,1,0); return
        self.XAxis = x or Vector3d(1,0,0); self.YAxis = y or Vector3d(0,1,0)
        self.ZAxis = Vector3d.CrossProduct(self.XAxis, self.YAxis)
Plane.WorldXY = Plane()
class Polyline(list):
    @property
    def Count(self): return len(self)
PolylineCurve.TryGetPolyline = lambda self: (True, Polyline(Point3d(p) for p in self.P))
