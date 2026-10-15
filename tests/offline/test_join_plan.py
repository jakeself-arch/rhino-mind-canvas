"""Offline unit test of the 2D join rules (mindcanvas/joins/plan.py). python tests/offline/test_join_plan.py"""
import importlib.util, sys
spec = importlib.util.spec_from_file_location("plan", __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "..", "..", "mindcanvas", "joins", "plan.py"))
P = importlib.util.module_from_spec(spec); spec.loader.exec_module(P)

def close(a, b, e=1e-9): return abs(a - b) < e
def pclose(p, q, e=1e-9): return close(p[0], q[0], e) and close(p[1], q[1], e)

# Convex L: A along +x ending at origin, exterior +y; B from the corner down along -y? B ends at corner too.
# A: faces ext=1, cext=0.5, cint=-0.5, int=-0.75 (ref center-ish)
A = P.Side((0, 0), (1, 0), +1, 1.0, 0.5, -0.5, -0.75)
# B runs upward toward the corner (body at y<0), ends at origin, tangent +y; exterior must be +x -> n = left(t) = (-1,0) -> exterior -x. flip: B tangent +y gives n=-x.
# Make B's exterior +x: B drawn from corner downward? Use B starting at corner going -y: t=(0,-1), out=-1, n=left((0,-1))=(1,0) => exterior +x.
B = P.Side((0, 0), (0, -1), -1, 1.2, 0.6, -0.4, -0.6)
print("u", A.u, B.u, "sigma", P.corner_sides(A, B))
ca = P.l_cut(A, B, "wrap", True, "B")
cb = P.l_cut(B, A, "wrap", False, "A")
print(ca); print(cb)
# A ext face (y=1) should end at B ext face x=1.2
assert pclose(ca.point(1.0), (1.2, 1.0)), ca.point(1.0)
# A core primary extends to B's outer core face x=0.6 on both core faces
assert pclose(ca.point(0.5, True), (0.6, 0.5)) and pclose(ca.point(-0.5, False), (0.6, -0.5))
# A inner zone ends at miter through (B.cint=-0.4, A.cint=-0.5) and (B.int=-0.6, A.int=-0.75)
assert pclose(ca.point(-0.5, True), (-0.4, -0.5)), ca.point(-0.5, True)
assert pclose(ca.point(-0.75), (-0.6, -0.75))
# B core secondary stops at A.cint (y=-0.5): B's s along t=(0,-1); point at d=0.6 -> (0.6, -0.5)
assert pclose(cb.point(0.6, True), (0.6, -0.5)), cb.point(0.6, True)
# B ext face (x=1.2) ends at A ext y=1
assert pclose(cb.point(1.2), (1.2, 1.0))
print("caps A", ca.cap(1.0, -0.75))
print("ext A core", ca.ext(0.0), "reach", ca.reach(), cb.reach())
# miter / butt
m = P.l_cut(A, B, "miter", True); assert pclose(m.point(1.0), (1.2, 1.0)) and pclose(m.point(-0.75), (-0.6, -0.75))
b1 = P.l_cut(A, B, "butt", True); assert pclose(b1.point(-0.75), (1.2, -0.75))
b2 = P.l_cut(B, A, "butt", False); assert pclose(b2.point(1.2), (1.2, -0.75))
# detection
print("meet", P.l_meeting(A, B, 0.1))
# T: host H along x through origin, faces 0.3/0.2/-0.2/-0.3; joining wall J coming from below (body y<0), ends at y=-0.3, t=(0,1) out=+1, n=(-1,0)
H = P.Side((0, 0), (1, 0), 0, 0.3, 0.2, -0.2, -0.3)
J = P.Side((0, -0.3), (0, 1), +1, 0.25, 0.1, -0.1, -0.25)
print("tmeet", P.t_meeting(J, H, 0.05))
tc = P.t_cut(J, H, "core")
# core reaches host near core face y=-0.2, finishes stop at y=-0.3
assert pclose(tc.point(0.0), (0.0, -0.2)), tc.point(0.0)
assert pclose(tc.point(0.25), (-0.25, -0.3))
poly, rng = P.t_notch(J, H, 0.01); print("notch", poly, rng)
bk = P.t_backers(J, H); print([b.point(0.0, 0.1) for b in bk])
lb = P.l_backer(A, B, True, "wrap"); print("Lbacker", lb.point(0.0, 0.1))
assert pclose(lb.point(0.0, 0.1), (-0.4 - 0.05, 0.0))
print("style", P.resolve_style("auto", "miter", True), P.resolve_style("butt", "miter", False), P.resolve_style("none", "wrap", True))
print("OK")
# concave: A along +x ends at origin, exterior -y (flip): t=(1,0), n=(0,1) -> use faces negated: ext side must be -y
# emulate by A' with t=(1,0) and ext = -? Our Side requires ext>=..; flip by giving tangent (1,0) but treating exterior as +n=+y,
# so make B's body on +y side: B starts at corner going +y: t=(0,1), out=-1, n=(-1,0) exterior -x (inside the turn)
A2 = P.Side((0, 0), (1, 0), +1, 1.0, 0.5, -0.5, -0.75)
B2 = P.Side((0, 0), (0, 1), -1, 1.2, 0.6, -0.4, -0.6)
print("sig", P.corner_sides(A2, B2))
c1 = P.l_cut(A2, B2, "wrap", True); c2 = P.l_cut(B2, A2, "wrap", False)
print(c1.cap(1.0, -0.75)); print(c2.cap(1.2, -0.6))
