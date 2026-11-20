# SPDX-License-Identifier: GPL-3.0-or-later
# Quick Product Studio - one-click product photography setup for Blender.

bl_info = {
    "name": "Quick Product Studio",
    "author": "Neil Sawhney",
    "version": (1, 0, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > Product Studio, Object menu",
    "description": "Cyclorama backdrop, key/rim/fill lights and camera sized to the selection",
    "category": "Lighting",
}

import math
import bpy
import bmesh
from mathutils import Vector

COLL = "Product Studio"


def world_bbox(objs, depsgraph):
    mn = Vector((1e30,) * 3)
    mx = Vector((-1e30,) * 3)
    found = False
    for o in objs:
        ev = o.evaluated_get(depsgraph)
        for c in ev.bound_box:
            p = ev.matrix_world @ Vector(c)
            mn = Vector(map(min, mn, p))
            mx = Vector(map(max, mx, p))
            found = True
    return (mn, mx) if found else (None, None)


def clear_previous(scene):
    coll = bpy.data.collections.get(COLL)
    if coll is None:
        coll = bpy.data.collections.new(COLL)
    for o in list(coll.objects):
        data = o.data
        bpy.data.objects.remove(o, do_unlink=True)
        if data is not None and data.users == 0:
            if isinstance(data, bpy.types.Mesh):
                bpy.data.meshes.remove(data)
            elif isinstance(data, bpy.types.Light):
                bpy.data.lights.remove(data)
            elif isinstance(data, bpy.types.Camera):
                bpy.data.cameras.remove(data)
    if coll.name not in scene.collection.children:
        scene.collection.children.link(coll)
    return coll


def make_backdrop(coll, center, floor_z, D, color, gloss=0.1):
    W = 40.0 * D          # width (X)
    front = 15.0 * D      # floor extent toward the camera (-Y)
    back = 3.0 * D       # distance from center to start of curve (+Y)
    r = 4.0 * D          # sweep radius
    H = 20.0 * D          # wall height above floor
    prof = []
    for i in range(9):
        prof.append((-front + i * (front + back) / 8.0, 0.0))
    n = 24
    for i in range(1, n + 1):
        a = (math.pi / 2) * i / n
        prof.append((back + r * math.sin(a), r * (1 - math.cos(a))))
    for i in range(1, 13):
        prof.append((back + r, r + (H - r) * i / 12.0))
    me = bpy.data.meshes.new("PS_Backdrop")
    bm = bmesh.new()
    cols = 24
    grid = []
    for (y, z) in prof:
        row = []
        for j in range(cols + 1):
            x = -W / 2 + W * j / cols
            row.append(bm.verts.new((center.x + x, center.y + y, floor_z + z)))
        grid.append(row)
    for a in range(len(grid) - 1):
        for j in range(cols):
            bm.faces.new((grid[a][j], grid[a][j + 1], grid[a + 1][j + 1], grid[a + 1][j]))
    bm.normal_update()
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True
    # make normals face up/forward (toward the object)
    if me.polygons[0].normal.z < 0:
        bm = bmesh.new(); bm.from_mesh(me)
        bmesh.ops.reverse_faces(bm, faces=bm.faces[:]); bm.to_mesh(me); bm.free()
    ob = bpy.data.objects.new("PS_Backdrop", me)
    coll.objects.link(ob)
    mat = bpy.data.materials.get("PS_Backdrop_Mat") or bpy.data.materials.new("PS_Backdrop_Mat")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (*color, 1.0)
        bsdf.inputs["Roughness"].default_value = 1.0 - gloss
    me.materials.append(mat)
    return ob


def make_area(coll, name, loc, target, power, sx, sy, shape="RECTANGLE"):
    ld = bpy.data.lights.new(name, "AREA")
    ld.shape = shape
    ld.size = sx
    ld.size_y = sy
    ld.energy = power
    ob = bpy.data.objects.new(name, ld)
    ob.visible_camera = False  # never show the emitter itself in frame
    ob.location = loc
    coll.objects.link(ob)
    c = ob.constraints.new("TRACK_TO")
    c.target = target
    c.track_axis = "TRACK_NEGATIVE_Z"
    c.up_axis = "UP_Y"
    return ob


def sph(center, dist, az_deg, el_deg):
    az, el = math.radians(az_deg), math.radians(el_deg)
    # az 0 = in front of the object (-Y), positive = to the right (+X)
    return center + Vector((math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el))) * dist


class PS_OT_build(bpy.types.Operator):
    bl_idname = "object.quick_product_studio"
    bl_label = "Build Product Studio"
    bl_description = "Create backdrop, lights and camera around the selected objects (replaces a previous setup)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        props = scene.quick_product_studio
        coll_existing = bpy.data.collections.get(COLL)
        ours = set(coll_existing.objects) if coll_existing else set()
        sel = [o for o in context.selected_objects if o not in ours and o.type in
               {"MESH", "CURVE", "SURFACE", "META", "FONT", "EMPTY", "CURVES", "POINTCLOUD", "VOLUME"}]
        if not sel:
            self.report({"ERROR"}, "Select the object(s) to photograph")
            return {"CANCELLED"}
        mn, mx = world_bbox(sel, context.evaluated_depsgraph_get())
        if mn is None:
            self.report({"ERROR"}, "Selection has no bounds")
            return {"CANCELLED"}
        names = [o.name for o in sel]
        center = (mn + mx) / 2
        dims = mx - mn
        D = max(max(dims), 1e-5)
        R = dims.length / 2  # bounding sphere radius
        coll = clear_previous(scene)

        tgt = bpy.data.objects.new("PS_Target", None)
        tgt.empty_display_size = D * 0.2
        tgt.location = center
        coll.objects.link(tgt)

        backdrop = make_backdrop(coll, center, mn.z, D, tuple(props.backdrop_color), props.backdrop_gloss)
        # Light linking: rim lights skip the backdrop, so they only draw edge highlights on the
        # product and never cast their hard single-sided terminator line across the floor.
        excl = bpy.data.collections.get("PS_Rim_Receivers") or bpy.data.collections.new("PS_Rim_Receivers")
        for o in list(excl.objects):
            excl.objects.unlink(o)
        excl.objects.link(backdrop)

        m = props.intensity
        P = D * D  # power scales with area so irradiance is size independent
        make_area(coll, "PS_Key", sph(center, 2.2 * D, -45, 40), tgt, 22 * P * m, 1.4 * D, 1.4 * D)
        make_area(coll, "PS_Fill", sph(center, 2.5 * D, 55, 15), tgt, 6 * P * m, 2.0 * D, 2.0 * D)
        rims = []
        if props.rim_side in {"BOTH", "LEFT"}:
            rims.append(make_area(coll, "PS_Rim_L", sph(center, 2.0 * D, -120, 20), tgt, 250 * P * m, 0.15 * D, 1.2 * D))
        if props.rim_side in {"BOTH", "RIGHT"}:
            rims.append(make_area(coll, "PS_Rim_R", sph(center, 2.0 * D, 125, 22), tgt, 250 * P * m, 0.15 * D, 1.2 * D))
        for r_ob in rims:
            try:
                r_ob.light_linking.receiver_collection = excl
                for child in excl.collection_objects:
                    child.light_linking.link_state = "EXCLUDE"
            except AttributeError:
                pass
        make_area(coll, "PS_Top", sph(center, 2.0 * D, 0, 88), tgt, 12 * P * m, 2.0 * D, 0.6 * D)

        # Geometry check: every light's full emitter rectangle must sit above the floor and
        # in front of the back wall with clearance, otherwise the backdrop clips the emitter.
        context.view_layer.update()
        floor_z = mn.z + 0.1 * D
        wall_y = center.y + 7.0 * D - 0.2 * D
        for lo in [o for o in coll.objects if o.type == "LIGHT"]:
            for _ in range(50):
                hx, hy = lo.data.size / 2, lo.data.size_y / 2
                pts = [lo.matrix_world @ Vector((sx * hx, sy * hy, 0)) for sx in (-1, 1) for sy in (-1, 1)]
                low = min(p.z for p in pts)
                far = max(p.y for p in pts)
                if low >= floor_z and far <= wall_y:
                    break
                if low < floor_z:
                    lo.location.z += (floor_z - low) + 0.02 * D
                if far > wall_y:
                    lo.location.y -= (far - wall_y) + 0.02 * D
                context.view_layer.update()

        # camera
        cd = bpy.data.cameras.new("PS_Camera")
        cd.lens = 85.0
        cd.sensor_width = 36.0
        cd.sensor_fit = "AUTO"
        rx, ry = scene.render.resolution_x, scene.render.resolution_y
        half_w = math.atan(18.0 / 85.0)
        half_min = half_w if rx <= ry else math.atan(math.tan(half_w) * ry / rx)
        dist = R * 1.25 / math.sin(half_min)
        cd.clip_start = max(dist * 0.01, 1e-5)
        cd.clip_end = dist * 50 + 20 * D
        cam = bpy.data.objects.new("PS_Camera", cd)
        cam.location = sph(center, dist, -28, 22)
        coll.objects.link(cam)
        c = cam.constraints.new("TRACK_TO")
        c.target = tgt
        c.track_axis = "TRACK_NEGATIVE_Z"
        c.up_axis = "UP_Y"
        scene.camera = cam

        # render settings
        scene.render.engine = "CYCLES"
        try:
            scene.view_settings.view_transform = "AgX"
            scene.view_settings.look = "AgX - Medium High Contrast"
        except TypeError:
            pass
        # Never touch an existing world (e.g. the user's HDRI). Only create one if none exists.
        if scene.world is None:
            w = bpy.data.worlds.new("PS_World")
            w.use_nodes = True
            bg = w.node_tree.nodes.get("Background")
            if bg:
                bg.inputs["Color"].default_value = (0.5, 0.5, 0.5, 1)
                bg.inputs["Strength"].default_value = 0.08
            scene.world = w

        context.view_layer.update()
        for o in coll.objects:
            o.select_set(False)
        self.report({"INFO"}, f"Product studio built for {len(names)} object(s), size {D*1000:.1f} mm")
        return {"FINISHED"}


class PS_OT_remove(bpy.types.Operator):
    bl_idname = "object.quick_product_studio_remove"
    bl_label = "Remove Product Studio"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        coll = bpy.data.collections.get(COLL)
        if coll:
            clear_previous(context.scene)
            bpy.data.collections.remove(coll)
        ex = bpy.data.collections.get("PS_Rim_Receivers")
        if ex:
            bpy.data.collections.remove(ex)
        return {"FINISHED"}


def _update_backdrop(self, context):
    mat = bpy.data.materials.get("PS_Backdrop_Mat")
    if mat and mat.node_tree:
        b = mat.node_tree.nodes.get("Principled BSDF")
        if b:
            b.inputs["Base Color"].default_value = (*self.backdrop_color, 1.0)
            b.inputs["Roughness"].default_value = 1.0 - self.backdrop_gloss


class PS_Props(bpy.types.PropertyGroup):
    intensity: bpy.props.FloatProperty(name="Light Intensity", default=1.0, min=0.0, soft_max=5.0)
    backdrop_color: bpy.props.FloatVectorProperty(name="Backdrop", subtype="COLOR", size=3,
                                                  default=(0.18, 0.18, 0.18), min=0.0, max=1.0,
                                                  update=_update_backdrop)
    backdrop_gloss: bpy.props.FloatProperty(name="Backdrop Gloss", default=0.1, min=0.0, max=1.0,
                                            update=_update_backdrop)
    rim_side: bpy.props.EnumProperty(name="Rim Lights", default="BOTH", items=[
        ("BOTH", "Both", "Rim lights on both sides"),
        ("LEFT", "Left", "Left rim light only"),
        ("RIGHT", "Right", "Right rim light only")])


class PS_PT_panel(bpy.types.Panel):
    bl_label = "Quick Product Studio"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Product Studio"

    def draw(self, context):
        p = context.scene.quick_product_studio
        col = self.layout.column()
        col.prop(p, "intensity")
        col.prop(p, "backdrop_color")
        col.prop(p, "backdrop_gloss")
        col.prop(p, "rim_side")
        col.operator(PS_OT_build.bl_idname, icon="LIGHT_AREA")
        col.operator(PS_OT_remove.bl_idname, icon="TRASH")


def menu_func(self, context):
    self.layout.operator(PS_OT_build.bl_idname, icon="LIGHT_AREA")


classes = (PS_Props, PS_OT_build, PS_OT_remove, PS_PT_panel)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.quick_product_studio = bpy.props.PointerProperty(type=PS_Props)
    bpy.types.VIEW3D_MT_object.append(menu_func)


def unregister():
    bpy.types.VIEW3D_MT_object.remove(menu_func)
    del bpy.types.Scene.quick_product_studio
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
